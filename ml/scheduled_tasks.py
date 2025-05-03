# ml/scheduled_tasks.py

import os
import django
import logging
import time
import schedule
import sys
import functools
from pathlib import Path
from django.utils import timezone

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog, BackupLog, SystemSettings

# Create a logs directory if it doesn't exist
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Configure logging
logger = logging.getLogger('scheduler')
# Clear any existing handlers to prevent duplication
if logger.handlers:
    logger.handlers = []

logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Add file handler
file_handler = logging.FileHandler(os.path.join(logs_dir, 'scheduler.log'))
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Add console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Prevent propagation to root logger to avoid duplicated logs
logger.propagate = False

# Store active jobs for management
active_jobs = {
    'data_simulation': None,
    'backup': None,
    'maintenance': None
}

# Global job queue with priorities
job_priorities = {
    'run_data_simulation': 1,  # Highest priority
    'run_scheduled_backup': 2,
    'run_maintenance': 3  # Lowest priority
}

# Track if a job is currently running
job_running = None


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


def prioritized_job_wrapper(func):
    """Decorator to handle job prioritization"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global job_running

        # Get the name of the current function
        func_name = func.__name__

        # Log that we're starting this job
        logger.info(f"Starting job: {func_name}")

        # Set the currently running job
        job_running = func_name

        try:
            # Run the actual job function
            result = func(*args, **kwargs)
            logger.info(f"Completed job: {func_name}")
            return result
        except Exception as e:
            logger.error(f"Error in job {func_name}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
        finally:
            # Clear the running job marker
            job_running = None

    return wrapper


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


def rotate_logs():
    """Keep logs from growing too large by rotating them"""
    logger.info("Rotating log files")

    try:
        # Rotate scheduler log
        scheduler_log = os.path.join(logs_dir, 'scheduler.log')
        if os.path.exists(scheduler_log):
            # Check file size in MB
            size_mb = os.path.getsize(scheduler_log) / (1024 * 1024)

            if size_mb > 5:  # Rotate if larger than 5MB
                # Backup the current log
                timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
                backup_log = os.path.join(logs_dir, f'scheduler_{timestamp}.log')

                # Move current log to backup
                os.rename(scheduler_log, backup_log)

                # Create a new empty log file
                with open(scheduler_log, 'w') as f:
                    f.write(f"Log rotated at {timezone.now()} - Previous log saved as {os.path.basename(backup_log)}\n")

                logger.info(f"Rotated scheduler log (was {size_mb:.2f}MB)")

                # Delete older log files (keep last 5)
                old_logs = sorted([f for f in os.listdir(logs_dir) if f.startswith('scheduler_')], reverse=True)
                if len(old_logs) > 5:
                    for old_log in old_logs[5:]:
                        try:
                            os.remove(os.path.join(logs_dir, old_log))
                            logger.info(f"Deleted old log file: {old_log}")
                        except Exception as e:
                            logger.error(f"Error deleting old log {old_log}: {e}")

    except Exception as e:
        logger.error(f"Error during log rotation: {e}")


def run_maintenance():
    """Run all maintenance tasks"""
    logger.info("Running maintenance tasks")

    # Rotate logs before other maintenance tasks
    rotate_logs()

    # Run database maintenance
    cleanup_old_backups()
    purge_old_energy_logs()

    logger.info("Maintenance tasks completed")


# Apply the wrapper to the job functions
run_data_simulation = prioritized_job_wrapper(run_data_simulation)
run_scheduled_backup = prioritized_job_wrapper(run_scheduled_backup)
run_maintenance = prioritized_job_wrapper(run_maintenance)


def get_aligned_schedule_times(interval_minutes):
    """
    Generate aligned schedule times for a given interval

    For example, if interval is 15 minutes, this generates: 00:00, 00:15, 00:30, 00:45, 01:00, etc.
    """
    times = []
    current_minutes = 0

    while current_minutes < 24 * 60:  # 24 hours in minutes
        hour = current_minutes // 60
        minute = current_minutes % 60
        times.append(f"{hour:02d}:{minute:02d}")
        current_minutes += interval_minutes

    return times


def get_next_aligned_time(interval_minutes):
    """Get the next aligned time for a given interval"""
    now = timezone.now()

    # Calculate minutes since midnight
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_since_midnight = int((now - midnight).total_seconds() / 60)

    # Find the next aligned time
    next_minutes = ((minutes_since_midnight // interval_minutes) + 1) * interval_minutes

    # Format as "HH:MM"
    next_hour = (next_minutes // 60) % 24  # Ensure it wraps around for next day
    next_minute = next_minutes % 60

    return f"{next_hour:02d}:{next_minute:02d}"


def update_schedule():
    """Update the schedule based on system settings"""
    global active_jobs

    # Clear existing jobs
    schedule.clear()
    active_jobs = {key: None for key in active_jobs}

    # Get current settings
    settings = get_system_settings()

    # ===== DATA COLLECTION SCHEDULING =====
    interval_minutes = settings.data_collection_interval
    if interval_minutes <= 0:
        interval_minutes = 15  # Default to 15 minutes if invalid

    # Generate all aligned times for the day
    data_collection_times = get_aligned_schedule_times(interval_minutes)

    logger.info(f"Setting data collection interval to {interval_minutes} minutes")
    logger.info(
        f"Data collection will run at: {', '.join(data_collection_times[:4])}... (every {interval_minutes} min)")

    # Schedule data collection at each aligned time
    for time_str in data_collection_times:
        schedule.every().day.at(time_str).do(run_data_simulation)

    next_run_time = get_next_aligned_time(interval_minutes)
    logger.info(f"Next data collection at: {next_run_time}")

    # ===== BACKUP SCHEDULING =====
    backup_hours = settings.backup_frequency_hours
    if backup_hours <= 0:
        backup_hours = 24  # Default to daily if invalid

    backup_interval_minutes = backup_hours * 60
    backup_times = get_aligned_schedule_times(backup_interval_minutes)

    logger.info(f"Setting backup frequency to {backup_hours} hours")
    logger.info(f"Backups will run at: {', '.join(backup_times[:4])}...")

    # Schedule backups at each aligned time
    for time_str in backup_times:
        schedule.every().day.at(time_str).do(run_scheduled_backup)

    next_backup_time = get_next_aligned_time(backup_interval_minutes)
    logger.info(f"Next backup at: {next_backup_time}")

    # ===== MAINTENANCE SCHEDULING =====
    maintenance_time = "00:00"  # Default
    try:
        # Get the maintenance time from settings
        if hasattr(settings, 'maintenance_time') and settings.maintenance_time:
            # Get time in the correct timezone
            local_time = timezone.localtime(timezone.now())
            settings_time = settings.maintenance_time

            # Format as "HH:MM" in correct timezone
            maintenance_time = f"{settings_time.hour:02d}:{settings_time.minute:02d}"

            logger.info(f"Using maintenance time from settings: {maintenance_time}")
    except Exception as e:
        logger.error(f"Error getting maintenance time: {e}")

    logger.info(f"Scheduling daily maintenance at {maintenance_time}")
    active_jobs['maintenance'] = schedule.every().day.at(maintenance_time).do(run_maintenance)

    # Log schedule
    log_schedule()


def log_schedule():
    """Log current schedule information"""
    logger.info("Current schedule:")

    # Check if we have jobs scheduled
    if not schedule.jobs:
        logger.warning("No jobs are currently scheduled!")
        return

    # Log all scheduled jobs
    for job in schedule.jobs:
        job_name = job.job_func.__name__

        # Get next run time
        next_run = job.next_run
        if next_run:
            # Convert to timezone-aware time
            if timezone.is_naive(next_run):
                next_run = timezone.make_aware(next_run)

            now = timezone.now()
            time_until = (next_run - now).total_seconds() / 60

            # Format as human-readable
            next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S")

            logger.info(f"- Job {job_name} will run at {next_run_str} ({time_until:.1f} minutes from now)")
        else:
            logger.warning(f"- Job {job_name} has no next run time set!")


def run_pending_jobs():
    """Run pending jobs with priority handling"""
    global job_running

    # If a job is already running, don't start another
    if job_running:
        logger.info(f"Job {job_running} is already running, deferring other jobs")
        return

    # Get all jobs that are due to run
    pending_jobs = []

    for job in schedule.jobs:
        if job.should_run:
            # Add to pending list with priority
            priority = job_priorities.get(job.job_func.__name__, 99)  # Default to low priority
            pending_jobs.append((priority, job))

    # No jobs to run
    if not pending_jobs:
        return

    # Sort by priority (lower number = higher priority)
    pending_jobs.sort(key=lambda x: x[0])

    # Run only the highest priority job
    _, job_to_run = pending_jobs[0]

    # Run the job
    logger.info(
        f"Running job {job_to_run.job_func.__name__} (priority {job_priorities.get(job_to_run.job_func.__name__, 99)})")
    job_to_run.run()

    # Update the job's next run time
    schedule.jobs = [job for job in schedule.jobs if job != job_to_run]
    schedule.jobs.append(job_to_run)


def start_scheduler():
    """Start the scheduler with all scheduled tasks"""
    logger.info(f"Starting scheduler from directory: {os.getcwd()}")
    logger.info(f"Python executable: {sys.executable}")
    logger.info(f"BASE_DIR: {BASE_DIR}")

    # Set up initial schedule
    update_schedule()

    # Create a flag file to indicate the scheduler is running
    with open(os.path.join(logs_dir, 'scheduler.pid'), 'w') as f:
        f.write(str(os.getpid()))

    # Keep the scheduler running
    logger.info("Entering scheduler loop")
    last_settings_check = time.time()
    settings_check_interval = 5 * 60  # Check settings every 5 minutes

    while True:
        try:
            n_jobs = len(schedule.jobs)
            if n_jobs > 0:
                logger.info(f"Checking scheduled jobs ({n_jobs} jobs in queue)")
                # Use our custom function instead of schedule.run_pending()
                run_pending_jobs()
            else:
                logger.warning("No scheduled jobs found! Re-configuring schedule...")
                update_schedule()

            # Sleep for a shorter interval to be more responsive
            time.sleep(30)

            # Periodically check if settings have changed (every 5 minutes)
            current_time = time.time()
            if current_time - last_settings_check > settings_check_interval:
                logger.info("Checking for settings changes...")
                update_schedule()
                last_settings_check = current_time
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Sleep briefly before continuing
            time.sleep(5)


# ml/scheduled_tasks.py (Update simulation functions)

def simulate_with_anomaly(is_manual=False, user_id=None):
    """Run simulation with forced anomaly"""
    logger.info("Running simulation with forced anomaly")

    try:
        from ml.simulate_data import create_energy_reading
        from ml.apply_models_to_record import apply_models_to_record

        # Get user if provided
        user = None
        if user_id:
            try:
                from django.contrib.auth.models import User
                user = User.objects.get(id=user_id)
            except Exception as e:
                logger.warning(f"Error getting user: {e}")

        # Create anomalous data
        log = create_energy_reading(anomaly=True, abnormal_prediction=False, is_manual=is_manual, user=user)
        logger.info(f"Created anomalous energy log with ID: {log.id}")

        # Apply ML models
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

        # Let system decide if backup is needed
        # System will use ANOMALY reason automatically if an anomaly is detected

        return log.id
    except Exception as e:
        logger.error(f"Error in simulate_with_anomaly: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def simulate_with_abnormal_prediction(is_manual=False, user_id=None):
    """Run simulation with abnormal prediction"""
    logger.info("Running simulation with abnormal prediction")

    try:
        from ml.simulate_data import create_energy_reading
        from ml.apply_models_to_record import apply_models_to_record

        # Get user if provided
        user = None
        if user_id:
            try:
                from django.contrib.auth.models import User
                user = User.objects.get(id=user_id)
            except Exception as e:
                logger.warning(f"Error getting user: {e}")

        # Create data that will lead to abnormal prediction, marking as manual if specified
        log = create_energy_reading(anomaly=False, abnormal_prediction=True, is_manual=is_manual, user=user)
        logger.info(f"Created log with abnormal prediction potential, ID: {log.id}")

        # Apply ML models
        is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
        logger.info(f"Applied models to record {log.id}")
        logger.info(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

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