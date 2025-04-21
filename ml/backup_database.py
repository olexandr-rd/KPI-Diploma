# ml/backup_database.py

import os
import django
import subprocess
from datetime import datetime
import logging
from pathlib import Path

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure logs directory exists
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Ensure backups directory exists
backups_dir = os.path.join(BASE_DIR, 'backups')
os.makedirs(backups_dir, exist_ok=True)

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from django.conf import settings
from monitoring.models import EnergyLog, BackupLog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'backup.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('backup')

# Define threshold for predicted load
PREDICTED_LOAD_MIN = 500  # Minimum acceptable predicted load
PREDICTED_LOAD_MAX = 2000  # Maximum acceptable predicted load


def backup_database(record_id=None, force=False):
    """
    Create a backup of the PostgreSQL database if:
    1. Record is anomalous OR
    2. Predicted load is outside normal range OR
    3. Force parameter is True

    Args:
        record_id: ID of record to check, or None for latest
        force: Force backup regardless of anomaly status

    Returns:
        bool: True if backup was performed
    """
    # Get the record to check
    if record_id:
        record = EnergyLog.objects.get(id=record_id)
    else:
        record = EnergyLog.objects.latest('timestamp')

    # Determine backup reason
    trigger_reason = None

    # Check all conditions that might trigger a backup
    is_anomalous = record.is_anomaly
    predicted_load_abnormal = False

    if record.predicted_load is not None:
        if record.predicted_load < PREDICTED_LOAD_MIN or record.predicted_load > PREDICTED_LOAD_MAX:
            predicted_load_abnormal = True
            logger.info(
                f"Predicted load {record.predicted_load:.2f}W is outside normal range ({PREDICTED_LOAD_MIN}-{PREDICTED_LOAD_MAX}W)")

    # Determine trigger reason in clear priority order
    if force:
        trigger_reason = "MANUAL"
        logger.info("Manual backup requested via force flag")
    elif is_anomalous:
        trigger_reason = "ANOMALY"
    elif predicted_load_abnormal:
        trigger_reason = "PREDICTION"

    # If no reason to backup, exit
    if trigger_reason is None:
        logger.info(
            f"Record {record.id} does not need backup (anomaly={is_anomalous}, pred_load_abnormal={predicted_load_abnormal})")
        return False

    # Get database settings
    db_settings = settings.DATABASES['default']

    # Create backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(backups_dir, f"energy_data_{timestamp}.sql")

    try:
        # PostgreSQL dump command
        cmd = [
            'pg_dump',
            '-h', db_settings['HOST'],
            '-p', db_settings['PORT'],
            '-U', db_settings['USER'],
            '-d', db_settings['NAME'],
            '-f', backup_file
        ]

        # Execute backup
        logger.info(f"Starting database backup to {backup_file} (reason: {trigger_reason})")
        process = subprocess.Popen(
            cmd,
            env=dict(os.environ, PGPASSWORD=db_settings['PASSWORD']),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logger.info(f"Backup completed successfully: {backup_file}")

            # Get file size in KB
            file_size_kb = os.path.getsize(backup_file) / 1024

            # Create backup log entry
            backup_log = BackupLog.objects.create(
                backup_file=os.path.basename(backup_file),
                status="SUCCESS",
                size_kb=file_size_kb,
                trigger_reason=trigger_reason or "UNKNOWN"
            )

            # Associate backup with the triggering record
            backup_log.triggered_by.add(record)

            # Mark record as backed up
            record.backup_triggered = True
            record.save()

            logger.info(f"Marked record {record.id} as backed up")
            return True
        else:
            error_msg = stderr.decode('utf-8')
            logger.error(f"Backup failed: {error_msg}")

            # Create failed backup log entry
            backup_log = BackupLog.objects.create(
                backup_file=os.path.basename(backup_file),
                status="FAILED",
                size_kb=0,
                trigger_reason=trigger_reason or "UNKNOWN",
                error_message=error_msg[:255]  # Truncate if needed
            )

            # Associate backup with the triggering record
            backup_log.triggered_by.add(record)

            return False

    except Exception as e:
        logger.error(f"Exception during backup: {str(e)}")

        # Create failed backup log entry
        try:
            backup_log = BackupLog.objects.create(
                backup_file=os.path.basename(backup_file),
                status="FAILED",
                size_kb=0,
                trigger_reason=trigger_reason or "UNKNOWN",
                error_message=str(e)[:255]  # Truncate if needed
            )

            # Associate backup with the triggering record
            backup_log.triggered_by.add(record)
        except Exception as inner_e:
            logger.error(f"Failed to log backup failure: {str(inner_e)}")

        return False


if __name__ == "__main__":
    # Check latest record and backup if needed
    backup_database()