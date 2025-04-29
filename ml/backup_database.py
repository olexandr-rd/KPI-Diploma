# ml/backup_database.py

import os
import django
import subprocess
from datetime import datetime, timedelta
import logging
from pathlib import Path
import sys
from django.utils import timezone

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
from monitoring.models import EnergyLog, BackupLog, SystemSettings

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

# Default threshold for predicted load
PREDICTED_LOAD_MIN = 500  # Minimum acceptable predicted load
PREDICTED_LOAD_MAX = 2000  # Maximum acceptable predicted load


def update_thresholds(min_load, max_load):
    """Update the threshold values for predicted load"""
    global PREDICTED_LOAD_MIN, PREDICTED_LOAD_MAX
    PREDICTED_LOAD_MIN = min_load
    PREDICTED_LOAD_MAX = max_load
    logger.info(f"Updated load thresholds: Min={min_load}W, Max={max_load}W")


def load_system_settings():
    """Load threshold values from system settings"""
    try:
        settings = SystemSettings.objects.first()
        if settings:
            update_thresholds(settings.min_load_threshold, settings.max_load_threshold)
            logger.info("Loaded threshold values from system settings")
            return settings
    except Exception as e:
        logger.error(f"Error loading system settings: {str(e)}")

    return None


def cleanup_old_backups():
    """
    Clean up old backups based on both count limit and age
    """
    settings = load_system_settings()
    if not settings:
        logger.warning("No system settings found, using defaults")
        max_backups = 20
        retention_days = 30
    else:
        max_backups = settings.max_backups
        retention_days = settings.backup_retention_days

    logger.info(f"Cleaning up old backups (keeping {max_backups} files, {retention_days} days retention)")

    try:
        # Get all backup files
        backup_files = list(Path(backups_dir).glob("*.sql"))

        # Remove files older than retention_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        old_files = []

        for file_path in backup_files:
            file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if file_mtime < cutoff_date:
                old_files.append(file_path)

        # Delete old files
        for file_path in old_files:
            try:
                file_path.unlink()
                BackupLog.objects.filter(backup_file=file_path.name).delete()
                logger.info(f"Deleted old backup older than {retention_days} days: {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to delete old backup {file_path}: {str(e)}")

        # Now check if we still have too many files and remove the oldest ones
        backup_files = list(Path(backups_dir).glob("*.sql"))
        if len(backup_files) > max_backups:
            # Sort by modification time (oldest first)
            backup_files.sort(key=lambda x: x.stat().st_mtime)

            # Select files to delete
            files_to_delete = backup_files[:(len(backup_files) - max_backups)]

            # Delete the files
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    BackupLog.objects.filter(backup_file=file_path.name).delete()
                    logger.info(f"Deleted old backup exceeding count limit: {file_path.name}")
                except Exception as e:
                    logger.error(f"Failed to delete backup {file_path}: {str(e)}")

    except Exception as e:
        logger.error(f"Exception during backup cleanup: {str(e)}")


def create_scheduled_backup():
    """Create a scheduled backup without requiring an anomaly"""
    logger.info("Creating scheduled backup")

    try:
        # Get the latest record
        latest_record = EnergyLog.objects.latest('timestamp')

        # Force backup
        return backup_database(latest_record.id, reason="SCHEDULED")

    except Exception as e:
        logger.error(f"Error creating scheduled backup: {str(e)}")
        return False


def backup_database(record_id=None, force=False, reason=None, user=None):
    """
    Create a backup of the PostgreSQL database if:
    1. Record is anomalous OR
    2. Predicted load is outside normal range OR
    3. Force parameter is True OR
    4. Specific reason is provided

    Args:
        record_id: ID of record to check, or None for latest
        force: Force backup regardless of anomaly status
        reason: Optional specific reason for backup

    Returns:
        bool: True if backup was performed
    """
    # Load system settings

    # Get the record to check
    if record_id:
        record = EnergyLog.objects.get(id=record_id)
    else:
        record = EnergyLog.objects.latest('timestamp')

    # Determine backup reason
    trigger_reason = reason

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
    elif reason:
        # Use the provided reason (already set)
        pass
    elif is_anomalous:
        trigger_reason = "ANOMALY"
    elif predicted_load_abnormal:
        trigger_reason = "PREDICTION"

    # If no reason to back up, exit
    if trigger_reason is None:
        logger.info(
            f"Record {record.id} does not need backup (anomaly={is_anomalous}, pred_load_abnormal={predicted_load_abnormal})")
        return False

    # Get database settings from Django settings, not from the SystemSettings model
    from django.conf import settings as django_settings
    db_settings = django_settings.DATABASES['default']

    # Create backup filename with timestamp
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
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
                trigger_reason=trigger_reason or "UNKNOWN",
                created_by = user,
            )

            # Associate backup with the triggering record
            backup_log.triggered_by.add(record)

            # Mark record as backed up
            record.backup_triggered = True
            record.save()

            logger.info(f"Marked record {record.id} as backed up")

            # Cleanup after successful backup
            cleanup_old_backups()

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
                error_message=error_msg[:255],  # Truncate if needed
                created_by=user
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
                error_message=str(e)[:255],  # Truncate if needed
                created_by=user
            )

            # Associate backup with the triggering record
            backup_log.triggered_by.add(record)
        except Exception as inner_e:
            logger.error(f"Failed to log backup failure: {str(inner_e)}")

        return False


if __name__ == "__main__":
    # If a specific reason is provided as a command line argument, use it
    if len(sys.argv) > 1 and sys.argv[1] == "scheduled":
        create_scheduled_backup()
    else:
        # Check the latest record and backup if needed
        backup_database()