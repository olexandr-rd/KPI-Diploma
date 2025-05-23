# monitoring/views/dashboard.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import psutil
from datetime import timedelta, datetime
from django.utils import timezone
from ..models import EnergyLog, BackupLog, SystemSettings


def get_stats():
    """Helper function to get system statistics"""
    # Get current time
    now = timezone.now()

    # Get settings
    settings = SystemSettings.objects.first() or SystemSettings()

    # Calculate statistics
    total_logs = EnergyLog.objects.count()
    anomaly_count = EnergyLog.objects.filter(is_anomaly=True).count()
    backup_success = BackupLog.objects.filter(status="SUCCESS").count()
    backup_failed = BackupLog.objects.filter(status="FAILED").count()

    # Calculate anomaly percentage
    anomaly_percentage = 0
    if total_logs > 0:
        anomaly_percentage = (anomaly_count / total_logs) * 100

    # Get all logs distribution by type
    manual_count = EnergyLog.objects.filter(is_manual=True).count()
    auto_count = total_logs - manual_count

    # Calculate storage used by backups
    storage_used = sum(b.size_kb for b in BackupLog.objects.filter(status="SUCCESS")) / 1024  # Convert to MB

    # Calculate the next scheduled data collection time
    data_collection_interval = settings.data_collection_interval if hasattr(settings,
                                                                            'data_collection_interval') else 15

    # Calculate next aligned data collection time
    minutes_since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 60
    next_interval = ((minutes_since_midnight // data_collection_interval) + 1) * data_collection_interval
    minutes_to_add = next_interval - minutes_since_midnight
    next_data_collection = now + timedelta(minutes=minutes_to_add)
    next_data_collection = next_data_collection.replace(second=0, microsecond=0)

    # Next maintenance at specified time - Convert to local timezone for display
    maintenance_time = settings.maintenance_time if hasattr(settings, 'maintenance_time') else now.replace(hour=0,
                                                                                                           minute=0,
                                                                                                           second=0,
                                                                                                           microsecond=0).time()

    # Create a timezone-aware datetime for today at the maintenance time in user's timezone
    local_now = timezone.localtime(now)
    next_maintenance = timezone.localtime(
        timezone.make_aware(datetime.combine(local_now.date(), maintenance_time))
    )

    # If that time is already past today, schedule for tomorrow
    if next_maintenance < local_now:
        next_maintenance += timedelta(days=1)

    backup_hours = settings.backup_frequency_hours
    if backup_hours <= 0:
        backup_hours = 24  # Default to daily

    # Convert hours to minutes for calculation
    backup_interval_minutes = backup_hours * 60

    # Get the current time in local timezone
    local_now = timezone.localtime(now)
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_since_midnight = (local_now - midnight).total_seconds() / 60
    next_backup_interval = ((minutes_since_midnight // backup_interval_minutes) + 1) * backup_interval_minutes
    next_backup = midnight + timedelta(minutes=next_backup_interval)

    # If the calculated time is in the past, add a day
    if next_backup < local_now:
        next_backup += timedelta(days=1)

    # Check if scheduler is running
    scheduler_active = False
    scheduler_status = "Неактивний"
    last_scheduler_check = timezone.localtime(now)  # Display in local timezone

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
        'anomaly_percentage': anomaly_percentage,
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
        'data_collection_interval': data_collection_interval,
        'maintenance_time': maintenance_time,
    }

    return stats


@login_required
def dashboard(request):
    """Main dashboard view"""
    # Get recent logs
    logs = EnergyLog.objects.all().order_by('-timestamp')[:15]

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
    logs = EnergyLog.objects.all().order_by('-timestamp')[:15]
    return render(request, 'dashboard/partials/logs_table.html', {'logs': logs})


@login_required
def backups_partial(request):
    """HTMX partial view for backup logs"""
    backups = BackupLog.objects.all().order_by('-timestamp')[:5]
    return render(request, 'dashboard/partials/backups_table.html', {'backups': backups})
