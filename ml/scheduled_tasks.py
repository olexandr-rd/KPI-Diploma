# ml/scheduled_tasks.py

import os
import django
import logging
import time
import schedule
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog, BackupLog

# Create logs directory if it doesn't exist
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'scheduler.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('scheduler')

# Constants
MAX_BACKUPS = 20
MAX_ENERGY_LOGS = 5000


def run_data_simulation():
    """Run the data simulation directly"""
    logger.info("Running scheduled data simulation")

    try:
        # Import needed functions directly
        from ml.simulate_data import create_energy_reading
        from ml.apply_models_to_record import apply_models_to_record
        from ml.backup_database import backup_database, PREDICTED_LOAD_MIN, PREDICTED_LOAD_MAX

        # 1. Create a new energy reading
        log = create_energy_reading(anomaly=False, abnormal_prediction=False)
        logger.info(f"Created new energy log with ID: {log.id}")

        # 2. Apply ML models
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

        # 3. Check if backup is needed
        if is_anomaly:
            logger.info(f"Anomaly detected (score: {anomaly_score}), triggering backup")
            backup_performed = backup_database(log.id)
            if backup_performed:
                logger.info("Backup completed successfully")
            else:
                logger.info("Backup failed")
        elif predicted_load is not None and (
                predicted_load < PREDICTED_LOAD_MIN or predicted_load > PREDICTED_LOAD_MAX):
            logger.info(f"Abnormal prediction detected ({predicted_load:.2f}W), triggering backup")
            backup_performed = backup_database(log.id)
            if backup_performed:
                logger.info("Backup completed successfully")
            else:
                logger.info("Backup failed")
        else:
            logger.info(f"No issues detected - no backup needed")

    except Exception as e:
        logger.error(f"Exception during data simulation: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def cleanup_old_backups():
    """Keep only the most recent MAX_BACKUPS backup files"""
    logger.info(f"Cleaning up old backups (keeping {MAX_BACKUPS} most recent)")

    try:
        backup_dir = Path(os.path.join(BASE_DIR, "backups"))

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
    logger.info(f"Starting scheduler from directory: {os.getcwd()}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"BASE_DIR: {BASE_DIR}")

    # Run initial data simulation immediately
    logger.info("Running initial data simulation")
    run_data_simulation()

    # Run initial maintenance
    logger.info("Running initial maintenance")
    run_maintenance()

    # Schedule data simulation every 15 minutes
    logger.info("Scheduling data simulation every 15 minutes")
    schedule.every(15).minutes.do(run_data_simulation)

    # Schedule maintenance tasks once a day (at midnight)
    logger.info("Scheduling daily maintenance at midnight")
    schedule.every().day.at("00:00").do(run_maintenance)

    # Log initial schedule information
    logger.info("Current schedule:")
    for job in schedule.jobs:
        next_run = job.next_run
        if next_run:
            time_until = (next_run - datetime.now()).total_seconds() / 60
            logger.info(f"- Job {job.job_func.__name__} will run in {time_until:.1f} minutes")
        else:
            logger.info(f"- Job {job.job_func.__name__} has no next run time")

    # Keep the scheduler running
    logger.info("Entering scheduler loop")
    while True:
        n_jobs = len(schedule.jobs)
        logger.info(f"Checking scheduled jobs ({n_jobs} jobs in queue)")

        schedule.run_pending()

        # Sleep for 60 seconds to reduce excessive logging, but still reasonable for 15-minute schedule
        time.sleep(60)

        # Periodically log schedule information (once every 5 minutes)
        if datetime.now().minute % 5 == 0 and datetime.now().second < 2:
            logger.info("Periodic schedule check:")
            for job in schedule.jobs:
                next_run = job.next_run
                if next_run:
                    time_until = (next_run - datetime.now()).total_seconds() / 60
                    logger.info(f"- Job {job.job_func.__name__} will run in {time_until:.1f} minutes")
                else:
                    logger.info(f"- Job {job.job_func.__name__} has no next run time")


if __name__ == "__main__":
    start_scheduler()