# monitoring/views/dashboard.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import os
import psutil
import datetime
from pathlib import Path

from ..models import EnergyLog, BackupLog, SystemSettings, UserProfile


def get_stats():
    """Helper function to get system statistics"""
    # Get current time
    now = datetime.datetime.now()

    # Get settings
    settings = SystemSettings.objects.first() or SystemSettings()

    # Calculate statistics
    total_logs = EnergyLog.objects.count()
    anomaly_count = EnergyLog.objects.filter(is_anomaly=True).count()
    backup_success = BackupLog.objects.filter(status="SUCCESS").count()
    backup_failed = BackupLog.objects.filter(status="FAILED").count()

    # Get recent logs distribution
    recent_logs = EnergyLog.objects.all().order_by('-timestamp')[:1000]
    manual_count = recent_logs.filter(is_manual=True).count()
    auto_count = recent_logs.count() - manual_count

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

    # Next scheduled backup
    backup_hours = settings.backup_frequency_hours
    if backup_hours <= 0:
        backup_hours = 24  # Default to daily

    # Find the last backup first
    last_backup = BackupLog.objects.filter(
        trigger_reason='SCHEDULED',
        status='SUCCESS'
    ).order_by('-timestamp').first()

    if last_backup:
        # Calculate next scheduled backup time
        next_backup = last_backup.timestamp + datetime.timedelta(hours=backup_hours)
    else:
        # If no previous scheduled backup, use current time + backup_hours
        next_backup = now + datetime.timedelta(hours=backup_hours)

    # Check if scheduler is running
    scheduler_active = False
    scheduler_status = "Неактивний"
    last_scheduler_check = now

    # Get the absolute path to the project directory
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

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
        'next_backup': next_backup,
        'next_maintenance': next_maintenance,
        'backup_frequency_hours': backup_hours,
        'max_logs_kept': settings.max_energy_logs,
        'max_backups_kept': settings.max_backups,
        'retention_days': settings.backup_retention_days,
        'scheduler_active': scheduler_active,
        'scheduler_status': scheduler_status,
        'last_scheduler_check': last_scheduler_check,
        'manual_count': manual_count,
        'auto_count': auto_count,
    }

    return stats


@login_required
def dashboard(request):
    """Main dashboard view"""
    # Get recent logs
    logs = EnergyLog.objects.all().order_by('-timestamp')[:10]

    # Get recent backup logs
    backups = BackupLog.objects.all().order_by('-timestamp')[:5]

    # Get statistics
    stats = get_stats()

    # Get recent anomalies
    recent_anomalies = EnergyLog.objects.filter(is_anomaly=True).order_by('-timestamp')[:5]

    return render(request, 'dashboard/dashboard.html', {
        'logs': logs,
        'backups': backups,
        'stats': stats,
        'recent_anomalies': recent_anomalies,
    })


@login_required
def stats_partial(request):
    """HTMX partial view for statistics"""
    stats = get_stats()
    return render(request, 'dashboard/partials/stats.html', {'stats': stats})


@login_required
def logs_partial(request):
    """HTMX partial view for energy logs"""
    logs = EnergyLog.objects.all().order_by('-timestamp')[:10]
    return render(request, 'dashboard/partials/logs_table.html', {'logs': logs})


@login_required
def backups_partial(request):
    """HTMX partial view for backup logs"""
    backups = BackupLog.objects.all().order_by('-timestamp')[:5]
    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})


@login_required
def run_simulation(request):
    """Run data simulation with model application"""
    if request.method == 'POST':
        try:
            # Run the simulation directly instead of using subprocess
            from ml.simulate_data import create_energy_reading, apply_models_to_record

            # Flag as manual and record the user who triggered it
            is_manual = True
            user = request.user

            # 1. Create a new energy reading (normal data)
            log = create_energy_reading(anomaly=False, abnormal_prediction=False,
                                        is_manual=is_manual, user=user)
            print(f"Created new energy log with ID: {log.id}")

            # 2. Apply ML models to the new reading
            is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)

            print(f"Applied models to record {log.id}")
            print(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_load}")

            # 3. Check if backup is needed based on anomaly or prediction
            settings = SystemSettings.objects.first() or {
                'min_load_threshold': 500,
                'max_load_threshold': 2000,
            }

            if is_anomaly or (predicted_load is not None and
                              (predicted_load < settings.min_load_threshold or
                               predicted_load > settings.max_load_threshold)):
                from ml.backup_database import backup_database
                backup_performed = backup_database(log.id)
                if backup_performed:
                    print("Automatic backup performed")

        except Exception as e:
            print(f"Error running simulation: {e}")

    # Return updated logs
    logs = EnergyLog.objects.all().order_by('-timestamp')[:10]
    return render(request, 'dashboard/partials/logs_table.html', {'logs': logs})


@login_required
def force_backup(request):
    """Force a manual backup without creating new data"""
    if request.method == 'POST':
        try:
            from django.contrib import messages
            # Check if user has manager or admin role
            try:
                profile = request.user.profile
                if not profile.is_manager:
                    messages.error(request, "У вас немає прав для створення резервних копій.")
                    backups = BackupLog.objects.all().order_by('-timestamp')[:5]
                    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})
            except UserProfile.DoesNotExist:
                messages.error(request, "У вас немає профілю користувача.")
                backups = BackupLog.objects.all().order_by('-timestamp')[:5]
                return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})

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
    backups = BackupLog.objects.all().order_by('-timestamp')[:5]
    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})