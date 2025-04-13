# ml/simulate_data.py

import os
import django
import numpy as np
from datetime import datetime
import logging
import argparse

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog
from ml.apply_models_to_record import apply_models_to_record
from ml.backup_database import backup_database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('simulation.log'), logging.StreamHandler()]
)
logger = logging.getLogger('simulation')


def create_energy_reading(anomaly=False):
    """
    Create a new energy reading simulating data from an energy system

    Args:
        anomaly: Force anomalous data if True

    Returns:
        EnergyLog: The created record
    """
    if anomaly:
        # Create anomalous data
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
    else:
        # Create normal data
        ac_output_voltage = np.random.normal(230, 3)
        dc_battery_voltage = np.random.normal(24, 0.5)
        dc_battery_current = np.random.normal(10, 1)
        load_power = np.random.normal(1000, 200)
        temperature = np.random.normal(35, 1)

    # Save to DB
    log = EnergyLog.objects.create(
        timestamp=datetime.now(),
        ac_output_voltage=ac_output_voltage,
        dc_battery_voltage=dc_battery_voltage,
        dc_battery_current=dc_battery_current,
        load_power=load_power,
        temperature=temperature
    )

    logger.info(f"Created energy log: {log.id} (Forced anomaly: {anomaly})")
    return log


def simulate_and_process():
    """
    Simulate a new reading, apply models, and backup if needed

    Returns:
        tuple: (log, is_anomaly, backup_performed)
    """
    parser = argparse.ArgumentParser(description="Simulate energy system data")
    parser.add_argument("--anomaly", action="store_true", help="Force anomalous data")
    args = parser.parse_args()

    # 1. Create new record
    log = create_energy_reading(args.anomaly)

    # 2. Apply ML models
    is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)

    # 3. Backup if anomaly detected
    if is_anomaly:
        logger.info(f"Anomaly detected (score: {anomaly_score}), triggering backup")
        backup_performed = backup_database(log.id)
    else:
        logger.info(f"No anomaly detected (score: {anomaly_score}), no backup needed")
        backup_performed = False

    return log, is_anomaly, backup_performed


if __name__ == "__main__":
    log, is_anomaly, backup_performed = simulate_and_process()

    print("\nSimulation summary:")
    print(f"- Created energy log ID: {log.id}")
    print(f"- Anomaly detected: {is_anomaly}")
    print(f"- Backup performed: {backup_performed}")