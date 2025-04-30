# ml/simulate_data.py

import os
import django
import numpy as np
from datetime import datetime
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
from ml.apply_models_to_record import apply_models_to_record
from ml.backup_database import backup_database

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


def create_energy_reading(anomaly=False, abnormal_prediction=False, is_manual=False, user=None):
    """
    Create a new energy reading simulating data from an energy system

    Args:
        anomaly: Force anomalous data if True
        abnormal_prediction: Generate data causing abnormal prediction
        is_manual: Flag if this is a manually triggered reading
        user: User who created this reading (for manual readings)

    Returns:
        EnergyLog: The created record
    """
    if anomaly:
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
    elif abnormal_prediction:
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

    logger.info(
        f"Created energy log: {log.id} (Forced anomaly: {anomaly}, Abnormal prediction: {abnormal_prediction}, Manual: {is_manual})")
    return log


def simulate_and_process(is_manual=False, user_id=None):
    """
    Simulate a new reading, apply models, and backup if needed

    Args:
        is_manual: Flag if this is a manually triggered reading
        user_id: ID of the user who triggered the simulation

    Returns:
        tuple: (log, is_anomaly, is_prediction_abnormal, backup_performed, reason)
    """
    parser = argparse.ArgumentParser(description="Simulate energy system data")
    parser.add_argument("--anomaly", action="store_true", help="Force anomalous data")
    parser.add_argument("--abnormal-prediction", action="store_true", help="Generate data causing abnormal prediction")
    parser.add_argument("--force-backup", action="store_true", help="Force backup regardless of conditions")
    args = parser.parse_args()

    # Get system settings
    settings = get_system_settings()
    min_threshold = settings.min_load_threshold
    max_threshold = settings.max_load_threshold

    # Get the user if provided
    user = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning(f"User with ID {user_id} not found")

    # 1. Create new record
    log = create_energy_reading(args.anomaly, args.abnormal_prediction, is_manual, user)

    # 2. Apply ML models
    try:
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)

        # Reload the log to get updated values
        log.refresh_from_db()

        # 3. Check predicted load
        is_prediction_abnormal = (predicted_load is not None and
                                  (predicted_load < min_threshold or
                                   predicted_load > max_threshold))

        # 4. Determine backup reason
        reason = None
        if args.force_backup:
            reason = "MANUAL"
            logger.info("Manual backup requested via --force-backup flag")
        elif is_anomaly:
            reason = "ANOMALY"
        elif is_prediction_abnormal:
            reason = "PREDICTION"

        # 5. Backup if needed
        backup_performed = False

        if reason:
            # Only log message if we have a reason to backup
            if reason == "ANOMALY":
                logger.info(f"Anomaly detected (score: {anomaly_score}), triggering backup")
            elif reason == "PREDICTION":
                logger.info(f"Abnormal prediction detected ({predicted_load:.2f}W), triggering backup")
            elif reason == "MANUAL":
                logger.info(f"Manual backup requested")

            # Perform backup
            backup_performed = backup_database(log.id, force=(reason == "MANUAL"))
        else:
            logger.info(f"No issues detected (anomaly score: {anomaly_score}, prediction: {predicted_load:.2f}W)")

    except Exception as e:
        logger.error(f"Error processing log: {str(e)}")
        is_anomaly = False
        is_prediction_abnormal = False
        backup_performed = False
        reason = None

    return log, is_anomaly, is_prediction_abnormal, backup_performed, reason


if __name__ == "__main__":
    # Add command line arguments for manual flag and user ID
    parser = argparse.ArgumentParser(description="Simulate energy system data")
    parser.add_argument("--manual", action="store_true", help="Mark as manual entry")
    parser.add_argument("--user", type=int, help="User ID who created this entry")

    args = parser.parse_args()

    log, is_anomaly, is_prediction_abnormal, backup_performed, reason = simulate_and_process(
        is_manual=args.manual,
        user_id=args.user
    )

    print("\nSimulation summary:")
    print(f"- Created energy log ID: {log.id}")
    print(f"- Manual entry: {log.is_manual}")
    if log.created_by:
        print(f"- Created by: {log.created_by.username}")
    print(f"- Anomaly detected: {is_anomaly}")
    if log.is_anomaly and log.anomaly_reason:
        print(f"- Anomaly reason: {log.anomaly_reason}")
    if log.predicted_load is not None:
        print(f"- Predicted next load: {log.predicted_load:.2f}W")
        print(f"- Prediction abnormal: {is_prediction_abnormal}")
    else:
        print("- Predicted next load: None")
    print(f"- Backup performed: {backup_performed}")
    if backup_performed:
        print(f"- Backup reason: {reason}")