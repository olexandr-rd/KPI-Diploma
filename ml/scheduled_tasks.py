# ml/scheduled_tasks.py - Updated version to fix race condition

import os
import django
import logging
import time
import schedule
import sys
import functools
from pathlib import Path
from datetime import datetime, timedelta
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


@prioritized_job_wrapper
def run_data_simulation():
    """Run the data simulation directly with proper connection handling"""
    logger.info("Running scheduled data simulation")

    try:
        # Import functions from simulate_data instead of reimplementing
        from ml.simulate_data import run_simulation_with_type

        # Run the simulation with proper error handling
        log_id, simulation_message = run_simulation_with_type(
            simulation_type=None,  # Normal simulation
            is_manual=False,  # Automated by scheduler
            user_id=None  # No user for automated tasks
        )

        if log_id:
            logger.info(f"Data simulation completed successfully. Log ID: {log_id}, {simulation_message}")

            # After simulation, check if we need to create a backup
            # This additional check helps ensure that backups are triggered when needed
            from ml.backup_database import check_and_backup_if_needed
            check_and_backup_if_needed(log_id)
        else:
            logger.error("Data simulation failed - no log ID returned")

    except django.db.utils.InterfaceError as e:
        # Handle the specific connection closed error
        logger.error(f"Database connection error during data simulation: {str(e)}")

        # Force close the connection to ensure it's re-established on next use
        from django.db import connection
        connection.close()

        # Could attempt a retry here if needed
        logger.info("Closed broken database connection. Next run will establish a fresh connection.")

    except Exception as e:
        logger.error(f"Exception during data simulation: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


@prioritized_job_wrapper
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


@prioritized_job_wrapper
def run_maintenance():
    """Run all maintenance tasks"""
    logger.info("Running maintenance tasks")

    # Rotate logs before other maintenance tasks
    rotate_logs()

    # Run database maintenance
    cleanup_old_backups()
    purge_old_energy_logs()

    logger.info("Maintenance tasks completed")


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
    try:
        # Get the maintenance time from settings
        if hasattr(settings, 'maintenance_time') and settings.maintenance_time:
            # Convert from settings time field to string
            maintenance_time = settings.maintenance_time.strftime("%H:%M")
            logger.info(f"Using maintenance time from settings: {maintenance_time}")
        else:
            maintenance_time = "00:00"  # Default
            logger.info(f"Using default maintenance time: {maintenance_time}")

        # Explicitly schedule maintenance at the specified time
        logger.info(f"Scheduling daily maintenance at {maintenance_time}")
        active_jobs['maintenance'] = schedule.every().day.at(maintenance_time).do(run_maintenance)
    except Exception as e:
        logger.error(f"Error scheduling maintenance: {e}")
        # Fallback to default time
        maintenance_time = "00:00"
        logger.info(f"Fallback: Scheduling daily maintenance at {maintenance_time}")
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
    """Run pending jobs without priority - run all that are due"""
    global job_running

    # If a job is already running, don't start another
    if job_running:
        logger.info(f"Job {job_running} is already running, deferring other jobs")
        return

    # Get all jobs that are due to run
    pending_jobs = []

    for job in schedule.jobs:
        if job.should_run:
            pending_jobs.append(job)

    # No jobs to run
    if not pending_jobs:
        return

    # Run all jobs that are due
    for job_to_run in pending_jobs:
        logger.info(f"Running job {job_to_run.job_func.__name__}")
        job_to_run.run()
        time.sleep(1)


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


if __name__ == "__main__":
    # Check if a command is provided
    if len(sys.argv) > 1 and sys.argv[1] == "maintenance":
        run_maintenance()
        sys.exit(0)

    # Otherwise start the regular scheduler
    start_scheduler()