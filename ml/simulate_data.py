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

from monitoring.models import EnergyLog, SystemSettings
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


def get_system_settings():
    """Get system settings for thresholds"""
    try:
        settings = SystemSettings.objects.first()
        if settings:
            return settings
    except Exception:
        pass

    # Default values if settings not found
    return type('obj', (object,), {
        'min_load_threshold': 500,
        'max_load_threshold': 2000,
    })


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
        load_power = np.random.choice([
            np.random.normal(3500, 300),  # Overload
            np.random.normal(10, 5)  # Almost no load
        ])
        temperature = np.random.normal(55, 5)  # High temperature
    elif simulation_type == 'abnormal_prediction':
        # Create data that will lead to abnormal prediction but not trigger anomaly detector
        # These values should be within "normal" ranges but in combinations that lead to
        # extreme predicted values in the next step
        ac_output_voltage = np.random.normal(230, 2)  # Normal voltage
        dc_battery_voltage = np.random.normal(24, 0.3)  # Normal battery
        dc_battery_current = np.random.normal(10, 0.5)  # Normal current

        # The key factor - we want to create a trend that will lead to prediction outside normal range
        # But not so extreme that it triggers anomaly detection
        load_power = np.random.normal(1800, 50)  # High but not anomalous load

        temperature = np.random.normal(38, 1)  # Slightly high temperature
    else:
        # Create normal data
        ac_output_voltage = np.random.normal(230, 3)
        dc_battery_voltage = np.random.normal(24, 0.5)
        dc_battery_current = np.random.normal(10, 1)
        load_power = np.random.normal(1250, 150)  # Middle of normal range
        temperature = np.random.normal(35, 1)

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
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)

        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

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
        if log.predicted_load is not None:
            print(f"- Predicted next load: {log.predicted_load:.2f}W")
        else:
            print("- Predicted next load: None")
        print(f"- Backup triggered: {log.backup_triggered}")
        if log.backup_triggered:
            backups = log.backups.all()
            if backups:
                backup = backups.first()
                print(f"- Backup reason: {backup.trigger_reason}")
                print(f"- Backup created by: {backup.created_by.username if backup.created_by else 'System'}")
