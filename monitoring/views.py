import os
import psutil
import datetime
from pathlib import Path
from django.shortcuts import render
from django.utils import timezone
from monitoring.models import EnergyLog, BackupLog

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Constants from scheduled_tasks.py
MAX_BACKUPS = 20
MAX_ENERGY_LOGS = 5000


def get_stats():
    """Helper function to get system statistics"""
    # Get current time
    now = timezone.now()

    # Calculate statistics
    total_logs = EnergyLog.objects.count()
    anomaly_count = EnergyLog.objects.filter(is_anomaly=True).count()
    backup_success = BackupLog.objects.filter(status="SUCCESS").count()
    backup_failed = BackupLog.objects.filter(status="FAILED").count()

    # Calculate storage used by backups
    storage_used = sum(b.size_kb for b in BackupLog.objects.filter(status="SUCCESS")) / 1024  # Convert to MB

    # Calculate next scheduled data collection time
    # First, get current time and round to nearest 15 min
    minutes_to_add = 15 - (now.minute % 15)
    next_data_collection = now + datetime.timedelta(minutes=minutes_to_add)
    next_data_collection = next_data_collection.replace(second=0, microsecond=0)

    # Next maintenance at midnight
    next_maintenance = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_maintenance <= now:
        next_maintenance += datetime.timedelta(days=1)

    # Check if scheduler is running
    scheduler_active = False
    scheduler_status = "Неактивний"
    last_scheduler_check = now

    # First check if scheduler.log exists and when it was last modified
    scheduler_log_path = Path(os.path.join(BASE_DIR, "logs", "scheduler.log"))
    if scheduler_log_path.exists():
        last_modified = datetime.datetime.fromtimestamp(scheduler_log_path.stat().st_mtime)
        # If log was modified in the last hour, consider scheduler active
        if (now - last_modified).total_seconds() < 3600:
            last_scheduler_check = last_modified
            scheduler_active = True
            scheduler_status = "Активний"

    # Double-check by looking for Python process running scheduled_tasks.py
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Get full command line as string to perform more flexible matching
                if proc.info.get('cmdline'):
                    cmdline_str = ' '.join(proc.info['cmdline'])
                    if 'python' in cmdline_str.lower() and 'scheduled_tasks.py' in cmdline_str:
                        scheduler_active = True
                        scheduler_status = "Активний"
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        # Log error but don't crash if process detection fails
        print(f"Error detecting scheduler process: {e}")

    # Prepare stats for template
    stats = {
        'total_logs': total_logs,
        'anomaly_count': anomaly_count,
        'backup_success': backup_success,
        'backup_failed': backup_failed,
        'storage_used': storage_used,
        'next_data_collection': next_data_collection,
        'next_maintenance': next_maintenance,
        'max_logs_kept': MAX_ENERGY_LOGS,
        'max_backups_kept': MAX_BACKUPS,
        'scheduler_active': scheduler_active,
        'scheduler_status': scheduler_status,
        'last_scheduler_check': last_scheduler_check
    }

    return stats


def dashboard(request):
    """Main dashboard view"""
    # Get recent logs
    logs = EnergyLog.objects.all().order_by('-timestamp')[:20]

    # Get backup logs
    backups = BackupLog.objects.all().order_by('-timestamp')

    # Get statistics
    stats = get_stats()

    return render(request, 'dashboard/dashboard.html', {
        'logs': logs,
        'backups': backups,
        'stats': stats
    })


def stats_partial(request):
    """HTMX partial view for statistics"""
    stats = get_stats()
    return render(request, 'dashboard/partials/stats.html', {'stats': stats})


def logs_partial(request):
    """HTMX partial view for energy logs"""
    logs = EnergyLog.objects.all().order_by('-timestamp')[:1000]
    return render(request, 'dashboard/partials/logs_table.html', {'logs': logs})


def backups_partial(request):
    """HTMX partial view for backup logs"""
    backups = BackupLog.objects.all().order_by('-timestamp')
    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})


def run_simulation(request):
    """Run data simulation with model application"""
    if request.method == 'POST':
        try:
            # Run the simulation directly instead of using subprocess
            from ml.simulate_data import create_energy_reading, apply_models_to_record

            # 1. Create a new energy reading (normal data)
            log = create_energy_reading(anomaly=False, abnormal_prediction=False)
            print(f"Created new energy log with ID: {log.id}")

            # 2. Apply ML models to the new reading
            is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)

            print(f"Applied models to record {log.id}")
            print(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

            # 3. Check if backup is needed based on anomaly or prediction
            if is_anomaly or (predicted_load is not None and
                              (predicted_load < 500 or predicted_load > 2000)):
                from ml.backup_database import backup_database
                backup_performed = backup_database(log.id)
                if backup_performed:
                    print("Automatic backup performed")

        except Exception as e:
            print(f"Error running simulation: {e}")

    # Return updated logs
    logs = EnergyLog.objects.all().order_by('-timestamp')[:1000]
    return render(request, 'dashboard/partials/logs_table.html', {'logs': logs})


def force_backup(request):
    """Force a manual backup without creating new data"""
    if request.method == 'POST':
        try:
            # Get the latest record
            latest_record = EnergyLog.objects.latest('timestamp')

            print(f"Forcing backup for latest record ID: {latest_record.id}")

            # Import backup function directly
            from ml.backup_database import backup_database

            # Force backup of the latest record
            backup_performed = backup_database(latest_record.id, force=True)

            if backup_performed:
                print("Backup completed successfully")
            else:
                print("Backup failed")

        except Exception as e:
            print(f"Error forcing backup: {e}")

    # Return updated backups
    backups = BackupLog.objects.all().order_by('-timestamp')
    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})