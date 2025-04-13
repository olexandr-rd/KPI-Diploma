# ml/backup_database.py

import os
import django
import subprocess
from datetime import datetime
import logging

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from django.conf import settings
from monitoring.models import EnergyLog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('backup.log'), logging.StreamHandler()]
)
logger = logging.getLogger('backup')


def backup_database(record_id=None, force=False):
    """
    Create a backup of the PostgreSQL database if record is anomalous or forced

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

    # Check if backup needed
    if not force and not record.is_anomaly:
        logger.info(f"Record {record.id} is not anomalous, no backup needed")
        return False

    # Get database settings
    db_settings = settings.DATABASES['default']

    # Create backup directory if it doesn't exist
    backup_dir = 'backups'
    os.makedirs(backup_dir, exist_ok=True)

    # Create backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f"{backup_dir}/energy_data_{timestamp}.sql"

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
        logger.info(f"Starting database backup to {backup_file}")
        process = subprocess.Popen(
            cmd,
            env=dict(os.environ, PGPASSWORD=db_settings['PASSWORD']),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logger.info(f"Backup completed successfully: {backup_file}")

            # Mark record as backed up
            record.backup_triggered = True
            record.save()

            logger.info(f"Marked record {record.id} as backed up")
            return True
        else:
            error_msg = stderr.decode('utf-8')
            logger.error(f"Backup failed: {error_msg}")
            return False

    except Exception as e:
        logger.error(f"Exception during backup: {str(e)}")
        return False


if __name__ == "__main__":
    # Check latest record and backup if needed
    backup_database()