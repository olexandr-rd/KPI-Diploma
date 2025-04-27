# ml/scheduled_tasks.py

import os
import django
import logging
import time
import schedule
import sys
from pathlib import Path
from django.utils import timezone
from monitoring.models import EnergyLog, BackupLog, SystemSettings

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

# Create a logs directory if it doesn't exist
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

# Store active jobs for management
active_jobs = {
    'data_simulation': None,
    'backup': None,
    'maintenance': None
}


def get_system_settings():
    """Get or create system settings"""
    try:
        settings, created = SystemSettings.objects.get_or_create(pk=1)
        return settings
    except Exception as e:
        logger.error(f"Error getting system settings: {str(e)}")
        # Return default values
        return type('obj', (object,), {
            'backup_frequency_hours': 24,
            'max_energy_logs': 5000,
            'max_backups': 20,
            'data_collection_interval': 15,
        })


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


def run_scheduled_backup():
    """Run daily scheduled backup"""
    logger.info("Running scheduled backup")

    try:
        from ml.backup_database import create_scheduled_backup

        backup_performed = create_scheduled_backup()
        if backup_performed:
            logger.info("Scheduled backup completed successfully")
        else:
            logger.error("Scheduled backup failed")

    except Exception as e:
        logger.error(f"Exception during scheduled backup: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def cleanup_old_backups():
    """Keep only the most recent backups according to settings"""
    logger.info("Cleaning up old backups")

    try:
        from ml.backup_database import cleanup_old_backups
        cleanup_old_backups()
        logger.info("Backup cleanup completed")

    except Exception as e:
        logger.error(f"Exception during backup cleanup: {str(e)}")


def purge_old_energy_logs():
    """Limit energy logs according to settings"""
    settings = get_system_settings()
    max_logs = settings.max_energy_logs

    logger.info(f"Purging old energy logs (keeping {max_logs} most recent)")

    try:
        # Count total logs
        total_logs = EnergyLog.objects.count()

        if total_logs > max_logs:
            # Calculate how many to delete
            logs_to_delete = total_logs - max_logs
            logger.info(f"Found {total_logs} logs, need to delete {logs_to_delete} old records")

            # Get the timestamp of the oldest log to keep
            oldest_to_keep = EnergyLog.objects.order_by('-timestamp')[max_logs - 1:max_logs].first()
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
    logger.info("Running maintenance tasks")
    cleanup_old_backups()
    purge_old_energy_logs()
    logger.info("Maintenance tasks completed")


def update_schedule():
    """Update the schedule based on system settings"""
    global active_jobs

    # Clear existing jobs
    schedule.clear()
    active_jobs = {key: None for key in active_jobs}

    # Get current settings
    settings = get_system_settings()

    # Schedule data simulation based on interval setting
    interval_minutes = settings.data_collection_interval
    logger.info(f"Setting data collection interval to {interval_minutes} minutes")
    active_jobs['data_simulation'] = schedule.every(interval_minutes).minutes.do(run_data_simulation)

    # Schedule daily backup based on settings
    backup_hours = settings.backup_frequency_hours
    if backup_hours <= 0:
        backup_hours = 24  # Default to daily if invalid

    logger.info(f"Setting backup frequency to {backup_hours} hours")
    active_jobs['backup'] = schedule.every(backup_hours).hours.do(run_scheduled_backup)

    # Schedule maintenance tasks once a day (at midnight)
    logger.info("Scheduling daily maintenance at midnight")
    active_jobs['maintenance'] = schedule.every().day.at("00:00").do(run_maintenance)

    # Log schedule
    log_schedule()


def log_schedule():
    """Log current schedule information"""
    logger.info("Current schedule:")
    for job in schedule.jobs:
        next_run = timezone.make_aware(job.next_run)
        if next_run:
            time_until = (next_run - timezone.now()).total_seconds() / 60
            logger.info(f"- Job {job.job_func.__name__} will run in {time_until:.1f} minutes")
        else:
            logger.info(f"- Job {job.job_func.__name__} has no next run time")


def start_scheduler():
    """Start the scheduler with all scheduled tasks"""
    logger.info(f"Starting scheduler from directory: {os.getcwd()}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"BASE_DIR: {BASE_DIR}")

    # Set up initial schedule
    update_schedule()

    # Run initial data simulation immediately
    logger.info("Running initial data simulation")
    run_data_simulation()

    # Run initial maintenance
    logger.info("Running initial maintenance")
    run_maintenance()

    # Create a flag file to indicate the scheduler is running
    with open(os.path.join(logs_dir, 'scheduler.pid'), 'w') as f:
        f.write(str(os.getpid()))

    # Keep the scheduler running
    logger.info("Entering scheduler loop")
    last_settings_check = time.time()
    settings_check_interval = 5 * 60  # Check settings every 5 minutes

    while True:
        n_jobs = len(schedule.jobs)
        logger.info(f"Checking scheduled jobs ({n_jobs} jobs in queue)")

        schedule.run_pending()

        # Sleep for a shorter interval to be more responsive
        time.sleep(30)

        # Periodically check if settings have changed (every 5 minutes)
        current_time = time.time()
        if current_time - last_settings_check > settings_check_interval:
            logger.info("Checking for settings changes...")
            update_schedule()
            last_settings_check = current_time

        # Periodically log schedule information (once every hour, on the hour)
        if timezone.now().minute < 1 and timezone.now().second < 30:
            log_schedule()


def simulate_with_anomaly():
    """Run data simulation with forced anomaly"""
    logger.info("Running simulation with forced anomaly")

    try:
        from ml.simulate_data import create_energy_reading
        from ml.apply_models_to_record import apply_models_to_record

        # Create anomalous data
        log = create_energy_reading(anomaly=True, abnormal_prediction=False)
        logger.info(f"Created anomalous energy log with ID: {log.id}")

        # Apply ML models
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

        # Ensure backup happens
        from ml.backup_database import backup_database
        backup_performed = backup_database(log.id)
        logger.info(f"Backup performed: {backup_performed}")

        return log.id
    except Exception as e:
        logger.error(f"Error in simulate_with_anomaly: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def simulate_with_abnormal_prediction():
    """Run data simulation with abnormal prediction"""
    logger.info("Running simulation with abnormal prediction")

    try:
        from ml.simulate_data import create_energy_reading
        from ml.apply_models_to_record import apply_models_to_record

        # Create data that will lead to abnormal prediction
        log = create_energy_reading(anomaly=False, abnormal_prediction=True)
        logger.info(f"Created log with abnormal prediction potential, ID: {log.id}")

        # Apply ML models
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

        # Check if prediction is abnormal and backup if needed
        from ml.backup_database import backup_database, PREDICTED_LOAD_MIN, PREDICTED_LOAD_MAX
        is_prediction_abnormal = (predicted_load is not None and
                                  (predicted_load < PREDICTED_LOAD_MIN or predicted_load > PREDICTED_LOAD_MAX))

        if is_prediction_abnormal:
            backup_performed = backup_database(log.id)
            logger.info(f"Abnormal prediction detected, backup performed: {backup_performed}")

        return log.id
    except Exception as e:
        logger.error(f"Error in simulate_with_abnormal_prediction: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


if __name__ == "__main__":
    # Check if a command is provided
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "anomaly":
            # Run simulation with anomaly and exit
            simulate_with_anomaly()
            sys.exit(0)
        elif command == "abnormal_prediction":
            # Run simulation with abnormal prediction and exit
            simulate_with_abnormal_prediction()
            sys.exit(0)
        elif command == "maintenance":
            # Run maintenance tasks and exit
            run_maintenance()
            sys.exit(0)

    # Otherwise start the regular scheduler
    start_scheduler()