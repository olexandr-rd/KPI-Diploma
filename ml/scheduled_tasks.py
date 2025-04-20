# ml/scheduled_tasks.py

import os
import django
import logging
import time
import schedule
import subprocess
# import shutil
# from datetime import datetime, timedelta
from pathlib import Path

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog, BackupLog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('logs/scheduler.log'), logging.StreamHandler()]
)
logger = logging.getLogger('scheduler')

# Constants
MAX_BACKUPS = 20
MAX_ENERGY_LOGS = 5000


def run_data_simulation():
    """Run the data simulation script"""
    logger.info("Running scheduled data simulation")

    try:
        # Run the simulation script
        result = subprocess.run(
            ["python", "ml/simulate_data.py"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            logger.info("Data simulation completed successfully")
            logger.debug(f"Output: {result.stdout}")
        else:
            logger.error(f"Data simulation failed with exit code {result.returncode}")
            logger.error(f"Error: {result.stderr}")

    except Exception as e:
        logger.error(f"Exception during data simulation: {str(e)}")


def cleanup_old_backups():
    """Keep only the most recent MAX_BACKUPS backup files"""
    logger.info(f"Cleaning up old backups (keeping {MAX_BACKUPS} most recent)")

    try:
        backup_dir = Path("backups")

        # Ensure the backup directory exists
        if not backup_dir.exists():
            logger.info("No backup directory found, nothing to clean")
            return

        # Get all .sql backup files
        backup_files = list(backup_dir.glob("*.sql"))

        # Sort by modification time (newest first)
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # If we have more than MAX_BACKUPS, delete the older ones
        if len(backup_files) > MAX_BACKUPS:
            files_to_delete = backup_files[MAX_BACKUPS:]
            logger.info(f"Found {len(backup_files)} backups, deleting {len(files_to_delete)} old backups")

            for file_path in files_to_delete:
                try:
                    # Delete the file
                    file_path.unlink()
                    logger.info(f"Deleted old backup: {file_path.name}")

                    # Also delete the corresponding entry in the BackupLog if it exists
                    BackupLog.objects.filter(backup_file=file_path.name).delete()

                except Exception as e:
                    logger.error(f"Failed to delete backup {file_path}: {str(e)}")
        else:
            logger.info(f"Found {len(backup_files)} backups, no cleanup needed")

    except Exception as e:
        logger.error(f"Exception during backup cleanup: {str(e)}")


def purge_old_energy_logs():
    """Limit energy logs to MAX_ENERGY_LOGS most recent records"""
    logger.info(f"Purging old energy logs (keeping {MAX_ENERGY_LOGS} most recent)")

    try:
        # Count total logs
        total_logs = EnergyLog.objects.count()

        if total_logs > MAX_ENERGY_LOGS:
            # Calculate how many to delete
            logs_to_delete = total_logs - MAX_ENERGY_LOGS
            logger.info(f"Found {total_logs} logs, need to delete {logs_to_delete} old records")

            # Get the timestamp of the oldest log to keep
            oldest_to_keep = EnergyLog.objects.order_by('-timestamp')[MAX_ENERGY_LOGS - 1:MAX_ENERGY_LOGS].first()
            if oldest_to_keep:
                # Delete older logs
                deleted_count = EnergyLog.objects.filter(timestamp__lt=oldest_to_keep.timestamp).delete()[0]
                logger.info(f"Deleted {deleted_count} old energy logs")
        else:
            logger.info(f"Found {total_logs} logs, no purge needed")

    except Exception as e:
        logger.error(f"Exception during energy log purge: {str(e)}")


def run_maintenance():
    """Run all maintenance tasks"""
    cleanup_old_backups()
    purge_old_energy_logs()


def start_scheduler():
    """Start the scheduler with all scheduled tasks"""
    logger.info("Starting scheduler")

    # Schedule data simulation every 15 minutes
    schedule.every(15).minutes.do(run_data_simulation)
    logger.info("Scheduled data simulation every 15 minutes")

    # Schedule maintenance tasks once a day (at midnight)
    schedule.every().day.at("00:00").do(run_maintenance)
    logger.info("Scheduled daily maintenance at midnight")

    # Run initial maintenance
    logger.info("Running initial maintenance")
    run_maintenance()

    # Keep the scheduler running
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    start_scheduler()