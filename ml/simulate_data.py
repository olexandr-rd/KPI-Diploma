# ml/simulate_data.py

import os
import django
import numpy as np
import logging
import argparse
from pathlib import Path

from django.utils import timezone

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure the logs directory exists
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog
from django.contrib.auth.models import User

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'simulation.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('simulation')


def create_energy_reading(simulation_type=None, is_manual=False, user=None):
    """
    Create a new energy reading simulating data from an energy system

    Args:
        simulation_type: Type of simulation - None for normal, 'anomaly' for anomalous data,
                         'abnormal_prediction' for abnormal prediction data
        is_manual: Flag if this is a manually triggered reading
        user: User who created this reading (for manual readings)

    Returns:
        EnergyLog: The created record
    """
    if simulation_type == 'anomaly':
        # Create clearly anomalous data
        ac_output_voltage = np.random.choice([
            np.random.normal(150, 10),  # Low voltage
            np.random.normal(280, 10)  # High voltage
        ])
        dc_battery_voltage = np.random.choice([
            np.random.normal(18, 1),  # Low battery
            np.random.normal(30, 2)  # High battery
        ])
        dc_battery_current = np.random.normal(10, 8)  # Unstable current
        load_power = np.random.normal(1250, 150)  # Normal power range
        temperature = np.random.normal(55, 5)  # High battery temperature
    elif simulation_type == 'abnormal_prediction':

        # Create a scenario that's near normal but will push the prediction out of bounds
        scenario = np.random.choice(['low_current', 'high_current', 'low_voltage', 'high_voltage'])

        if scenario == 'low_current':
            # This should predict a very low battery current (below 5A)
            ac_output_voltage = np.random.normal(229, 1)  # Near lower end of normal voltage
            dc_battery_voltage = np.random.normal(23.5, 0.2)  # Lower battery voltage
            dc_battery_current = np.random.normal(5.5, 0.3)  # Near lower end of normal current
            load_power = np.random.normal(800, 50)  # Low load tends to correlate with low current
            temperature = np.random.normal(37, 1)  # Slightly above normal temp
        elif scenario == 'high_current':
            # This should predict a very high battery current (above 15A)
            ac_output_voltage = np.random.normal(231, 1)  # Near upper end of normal voltage
            dc_battery_voltage = np.random.normal(24.5, 0.2)  # Higher battery voltage
            dc_battery_current = np.random.normal(14.5, 0.3)  # Near upper end of normal current
            load_power = np.random.normal(1800, 50)  # High load tends to correlate with high current
            temperature = np.random.normal(38, 1)  # Higher temperature
        elif scenario == 'low_voltage':
            # This should predict a very low AC voltage (below 220V)
            ac_output_voltage = np.random.normal(221, 1)  # Near lower end of normal voltage
            dc_battery_voltage = np.random.normal(23.8, 0.2)  # Lower battery voltage
            dc_battery_current = np.random.normal(9, 0.5)  # Normal current
            load_power = np.random.normal(1000, 100)  # Normal load
            temperature = np.random.normal(36, 1)  # Normal temperature
        else:  # high_voltage
            # This should predict a very high AC voltage (above 240V)
            ac_output_voltage = np.random.normal(239, 1)  # Near upper end of normal voltage
            dc_battery_voltage = np.random.normal(24.2, 0.2)  # Higher battery voltage
            dc_battery_current = np.random.normal(11, 0.5)  # Normal current
            load_power = np.random.normal(1500, 100)  # Normal load
            temperature = np.random.normal(39, 1)  # Slightly higher temperature
    else:
        # Create normal data
        ac_output_voltage = np.random.normal(230, 3)
        dc_battery_voltage = np.random.normal(24, 0.5)
        dc_battery_current = np.random.normal(10, 1)
        load_power = np.random.normal(1250, 150)  # Normal power range
        temperature = np.random.normal(35, 1)  # Normal battery temperature

    # Save to DB
    log = EnergyLog.objects.create(
        timestamp=timezone.now(),
        ac_output_voltage=ac_output_voltage,
        dc_battery_voltage=dc_battery_voltage,
        dc_battery_current=dc_battery_current,
        load_power=load_power,
        temperature=temperature,
        is_manual=is_manual,
        created_by=user
    )

    logger.info(f"Created energy log: {log.id} (Type: {simulation_type or 'normal'}, Manual: {is_manual})")
    return log


def run_simulation_with_type(simulation_type=None, is_manual=False, user_id=None):
    """
    Unified simulation function that handles all simulation types

    Args:
        simulation_type: Type of simulation - None for normal, 'anomaly' for anomalous data,
                        'abnormal_prediction' for abnormal prediction data
        is_manual: Flag if this is a manually triggered reading
        user_id: ID of the user who triggered the simulation

    Returns:
        tuple: (log_id, simulation_message)
    """
    logger.info(f"Running simulation with type: {simulation_type or 'normal'}")

    # Get the user if provided
    user = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning(f"User with ID {user_id} not found")

    try:
        # 1. Create a new energy reading based on simulation type
        log = create_energy_reading(simulation_type=simulation_type, is_manual=is_manual, user=user)
        logger.info(f"Created new energy log with ID: {log.id}")

        # 2. Apply ML models to the new reading
        from ml.apply_models_to_record import apply_models_to_record
        is_anomaly, anomaly_score, predicted_current, predicted_voltage = apply_models_to_record(log.id)

        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}")
        logger.info(f"Predicted current: {predicted_current:.2f}A, Predicted voltage: {predicted_voltage:.2f}V")

        # 3. Determine the simulation message for the user
        match simulation_type:
            case 'anomaly':
                simulation_message = "Симуляція аномалії"
            case 'abnormal_prediction':
                simulation_message = "Симуляція аномального прогнозу"
            case _:
                simulation_message = "Симуляція звичайних даних"

        return log.id, simulation_message

    except Exception as e:
        logger.error(f"Error during simulation: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None, "Помилка симуляції"


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Simulate energy system data")
    parser.add_argument("--type", choices=[None, 'normal', 'anomaly', 'abnormal_prediction'],
                        default=None, help="Type of simulation data to generate")
    parser.add_argument("--manual", action="store_true", help="Mark as manual entry")
    parser.add_argument("--user", type=int, help="User ID who created this entry")

    args = parser.parse_args()

    # Map 'normal' to None for function call
    sim_type = None if args.type == 'normal' else args.type

    # Run the simulation
    log_id, message = run_simulation_with_type(
        simulation_type=sim_type,
        is_manual=args.manual,
        user_id=args.user
    )

    print("\nSimulation summary:")
    print(f"- {message}")
    print(f"- Created energy log ID: {log_id}")

    # Get the updated log to show results
    if log_id:
        log = EnergyLog.objects.get(id=log_id)
        print(f"- Manual entry: {log.is_manual}")
        if log.created_by:
            print(f"- Created by: {log.created_by.username}")
        print(f"- Anomaly detected: {log.is_anomaly}")
        if log.is_anomaly and log.anomaly_reason:
            print(f"- Anomaly reason: {log.anomaly_reason}")
        if log.predicted_current is not None and log.predicted_voltage is not None:
            print(f"- Predicted next current: {log.predicted_current:.2f}A")
            print(f"- Predicted next voltage: {log.predicted_voltage:.2f}V")
            print(f"- Is abnormal prediction: {log.is_abnormal_prediction}")
        else:
            print("- Predicted values: None")
        print(f"- Backup triggered: {log.backup_triggered}")
        if log.backup_triggered:
            backups = log.backups.all()
            if backups:
                backup = backups.first()
                print(f"- Backup reason: {backup.trigger_reason}")
                print(f"- Backup created by: {backup.created_by.username if backup.created_by else 'System'}")