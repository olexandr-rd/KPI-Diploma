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
        logger.info(f"Found {len(backup_files)} backup files")

        # Remove files older than retention_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        old_files = []

        for file_path in backup_files:
            try:
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_mtime < cutoff_date:
                    old_files.append(file_path)
            except Exception as e:
                logger.error(f"Error checking file {file_path}: {e}")

        # Delete old files
        logger.info(f"Found {len(old_files)} files older than {retention_days} days")
        for file_path in old_files:
            try:
                logger.info(f"Deleting old backup: {file_path.name}")
                file_path.unlink()
                # Also delete from database
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

            logger.info(f"Need to delete {len(files_to_delete)} files to respect max_backups limit of {max_backups}")

            # Delete the files
            for file_path in files_to_delete:
                try:
                    logger.info(f"Deleting backup (exceeding max count): {file_path.name}")
                    file_path.unlink()
                    # Also delete from database
                    BackupLog.objects.filter(backup_file=file_path.name).delete()
                    logger.info(f"Deleted old backup exceeding count limit: {file_path.name}")
                except Exception as e:
                    logger.error(f"Failed to delete backup {file_path}: {str(e)}")

    except Exception as e:
        logger.error(f"Exception during backup cleanup: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def create_scheduled_backup():
    """Create a scheduled backup without requiring an anomaly"""
    logger.info("Creating scheduled backup")

    try:
        return backup_database(record_id=None, reason="SCHEDULED")

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
        record_id: ID of record to check, or None for no association
        force: Force backup regardless of anomaly status
        reason: Optional specific reason for backup
        user: User who initiated the backup

    Returns:
        bool: True if backup was performed
    """
    # Load system settings
    settings = load_system_settings()

    # Determine backup reason
    trigger_reason = reason

    record = None
    if record_id:
        # Get the record to check if ID was provided
        record = EnergyLog.objects.get(id=record_id)

        # Check all conditions that might trigger a backup
        is_anomalous = record.is_anomaly
        predicted_load_abnormal = False

        # Get current thresholds from settings
        min_threshold = settings.min_load_threshold
        max_threshold = settings.max_load_threshold

        # Check the prediction
        if record.predicted_load is not None:
            if record.predicted_load < min_threshold or record.predicted_load > max_threshold:
                predicted_load_abnormal = True
                logger.info(
                    f"Predicted load {record.predicted_load:.2f}W is outside normal range ({min_threshold}-{max_threshold}W)")

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

        # If no reason to back up and not forced, exit
        if trigger_reason is None and not force:
            logger.info(
                f"Record {record.id} does not need backup (anomaly={is_anomalous}, pred_load_abnormal={predicted_load_abnormal})")
            return False
    else:
        # No record provided, must have force or reason
        if force:
            trigger_reason = "MANUAL"
            logger.info("Manual backup requested without record association")
        elif reason:
            # Use the provided reason
            logger.info(f"Backup requested with reason {reason} without record association")
        else:
            # No record, no force, no reason - exit
            logger.info("No record, force, or reason provided for backup")
            return False

    # Get database settings from Django settings, not from the SystemSettings model
    from django.conf import settings as django_settings
    db_settings = django_settings.DATABASES['default']

    # Create backup filename with timestamp
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(backups_dir, f"energy_data_{timestamp}.sql")
    backup_filename = os.path.basename(backup_file)

    # Check if a backup log with this filename already exists (prevent duplicates)
    existing_backup = BackupLog.objects.filter(backup_file=backup_filename).first()
    if existing_backup:
        logger.warning(f"Backup log for {backup_filename} already exists (ID: {existing_backup.id})")

        # If it's successful, just return True to indicate backup was done
        if existing_backup.status == "SUCCESS":
            # Just ensure the record is associated with this backup if provided
            if record and record not in existing_backup.triggered_by.all():
                existing_backup.triggered_by.add(record)
                # Mark record as backed up if not already
                if not record.backup_triggered:
                    record.backup_triggered = True
                    record.save()
                    logger.info(f"Associated record {record.id} with existing backup {existing_backup.id}")
            return True
        else:
            # If previous attempt failed, we'll try again and update the record
            logger.info(f"Previous backup attempt failed, retrying...")

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

            # If we have an existing record that failed, update it instead of creating a new one
            if existing_backup and existing_backup.status != "SUCCESS":
                existing_backup.status = "SUCCESS"
                existing_backup.size_kb = file_size_kb
                existing_backup.error_message = None
                existing_backup.save()
                backup_log = existing_backup
                logger.info(f"Updated existing backup log {existing_backup.id} to SUCCESS")
            else:
                # Create new backup log entry
                backup_log = BackupLog.objects.create(
                    backup_file=backup_filename,
                    status="SUCCESS",
                    size_kb=file_size_kb,
                    trigger_reason=trigger_reason or "UNKNOWN",
                    created_by=user,
                )
                logger.info(f"Created new backup log with ID {backup_log.id}")

            # Associate backup with the triggering record if provided
            if record:
                backup_log.triggered_by.add(record)

                # Mark record as backed up
                record.backup_triggered = True
                record.save()

                logger.info(f"Marked record {record.id} as backed up")

            return True
        else:
            error_msg = stderr.decode('utf-8')
            logger.error(f"Backup failed: {error_msg}")

            # If we have an existing record, update it instead of creating a new one
            if existing_backup:
                existing_backup.status = "FAILED"
                existing_backup.error_message = error_msg[:255]  # Truncate if needed
                existing_backup.save()
                backup_log = existing_backup
                logger.info(f"Updated existing backup log {existing_backup.id} to FAILED")
            else:
                # Create failed backup log entry
                backup_log = BackupLog.objects.create(
                    backup_file=backup_filename,
                    status="FAILED",
                    size_kb=0,
                    trigger_reason=trigger_reason or "UNKNOWN",
                    error_message=error_msg[:255],  # Truncate if needed
                    created_by=user
                )
                logger.info(f"Created new FAILED backup log with ID {backup_log.id}")

            # Associate backup with the triggering record if provided
            if record:
                backup_log.triggered_by.add(record)

            return False

    except Exception as e:
        logger.error(f"Exception during backup: {str(e)}")

        # Update existing record if available
        if existing_backup:
            existing_backup.status = "FAILED"
            existing_backup.error_message = str(e)[:255]  # Truncate if needed
            existing_backup.save()
            logger.info(f"Updated existing backup log {existing_backup.id} to FAILED")
        else:
            # Create failed backup log entry
            try:
                backup_log = BackupLog.objects.create(
                    backup_file=backup_filename,
                    status="FAILED",
                    size_kb=0,
                    trigger_reason=trigger_reason or "UNKNOWN",
                    error_message=str(e)[:255],  # Truncate if needed
                    created_by=user
                )
                # Associate backup with the triggering record if provided
                if record:
                    backup_log.triggered_by.add(record)
                logger.info(f"Created new FAILED backup log with ID {backup_log.id}")
            except Exception as inner_e:
                logger.error(f"Failed to log backup failure: {str(inner_e)}")

        return False


# ml/backup_database.py (restore_database function)

def restore_database(backup_filename, user=None):
    """
    Restore only the energy logs from a backup file

    Args:
        backup_filename: Name of the backup file
        user: User who initiated the restore

    Returns:
        tuple: (success, message)
    """
    from django.conf import settings
    import tempfile
    import re

    logger.info(f"Attempting to restore energy logs from {backup_filename}")

    backup_file = os.path.join(backups_dir, backup_filename)

    # Check if the file exists
    if not os.path.exists(backup_file):
        error_msg = f"Файл резервної копії не знайдено: {backup_filename}"
        logger.error(error_msg)
        return False, error_msg

    # Get database settings
    db_settings = settings.DATABASES['default']

    try:
        # Create a temporary file to hold only the energy logs data
        with tempfile.NamedTemporaryFile(suffix='.sql', mode='w', delete=False) as temp_file:
            temp_path = temp_file.name

            # Read the original backup file
            with open(backup_file, 'r') as original_file:
                content = original_file.read()

            # Extract only the energy logs table data and schema
            # Define patterns to match the energy logs table SQL statements
            table_pattern = r'CREATE TABLE public\.monitoring_energylog[\s\S]*?;\s*\n'
            sequence_pattern = r'CREATE SEQUENCE public\.monitoring_energylog_id_seq[\s\S]*?;\s*\n'
            data_pattern = r'COPY public\.monitoring_energylog[\s\S]*?\\.\s*\n'
            index_pattern = r'CREATE INDEX[\s\S]*?monitoring_energylog[\s\S]*?;\s*\n'

            # Find all relevant sections
            table_match = re.search(table_pattern, content)
            sequence_match = re.search(sequence_pattern, content)
            data_match = re.search(data_pattern, content)
            index_matches = re.finditer(index_pattern, content)

            # Start with statements to drop existing table
            temp_file.write('-- Generated restore script for monitoring_energylog\n')
            temp_file.write('BEGIN;\n')
            temp_file.write('DROP TABLE IF EXISTS public.monitoring_energylog CASCADE;\n')

            # Write the relevant sections to the temp file
            if sequence_match:
                temp_file.write(sequence_match.group(0))

            if table_match:
                temp_file.write(table_match.group(0))

            # Write any relevant indexes
            for match in index_matches:
                temp_file.write(match.group(0))

            # Write the data
            if data_match:
                temp_file.write(data_match.group(0))

            temp_file.write('COMMIT;\n')

        # Now restore from the temporary file
        restore_cmd = [
            'psql',
            '-h', db_settings['HOST'],
            '-p', db_settings['PORT'],
            '-U', db_settings['USER'],
            '-d', db_settings['NAME'],
            '-f', temp_path
        ]

        logger.info(f"Restoring energy logs from temporary file {temp_path}")
        restore_process = subprocess.Popen(
            restore_cmd,
            env=dict(os.environ, PGPASSWORD=db_settings['PASSWORD']),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        restore_stdout, restore_stderr = restore_process.communicate()

        # Clean up the temporary file
        try:
            os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"Failed to delete temporary file {temp_path}: {e}")

        if restore_process.returncode != 0:
            error_msg = f"Failed to restore energy logs: {restore_stderr.decode('utf-8')}"
            logger.error(error_msg)
            return False, error_msg

        # Log the restoration
        restoration_log = BackupLog.objects.create(
            backup_file=f"restored_from_{backup_filename}",
            status="SUCCESS",
            size_kb=0,  # No actual file created
            trigger_reason="MANUAL",
            error_message=None,
            created_by=user
        )

        logger.info("Energy logs restored successfully")
        return True, "Energy logs restored successfully"

    except Exception as e:
        error_msg = f"Exception during database restore: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return False, error_msg


def delete_backup_file(backup_filename):
    """
    Delete a backup file

    Args:
        backup_filename: Name of the backup file

    Returns:
        tuple: (success, message)
    """
    backup_file = os.path.join(backups_dir, backup_filename)

    logger.info(f"Attempting to delete backup file: {backup_file}")

    # Check if the file exists
    if not os.path.exists(backup_file):
        error_msg = f"Файл резервної копії не знайдено: {backup_filename}"
        logger.error(error_msg)
        return False, error_msg

    try:
        # Delete the file
        os.remove(backup_file)
        logger.info(f"Backup file deleted: {backup_file}")
        return True, "Backup file deleted successfully"
    except Exception as e:
        error_msg = f"Error deleting backup file: {str(e)}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return False, error_msg


if __name__ == "__main__":
    # If a specific reason is provided as a command line argument, use it
    if len(sys.argv) > 1 and sys.argv[1] == "scheduled":
        create_scheduled_backup()
    else:
        # Check the latest record and backup if needed
        backup_database()