# monitoring/views/backups.py
from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from datetime import datetime, timedelta

from django.utils import timezone

from ..models import BackupLog, UserProfile, SystemSettings, EnergyLog


@login_required
def backups_list(request):
    """Full list of backup logs with filtering and pagination"""
    # Get filter parameters
    search_query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    reason = request.GET.get('reason', '')
    period = request.GET.get('period', '')

    # Start with all backups
    backups = BackupLog.objects.all()

    # Apply filters
    if search_query:
        backups = backups.filter(
            Q(backup_file__icontains=search_query) |
            Q(error_message__icontains=search_query) |
            Q(created_by__username__icontains=search_query) |
            Q(created_by__first_name__icontains=search_query) |
            Q(created_by__last_name__icontains=search_query)
        )

    if status == 'success':
        backups = backups.filter(status='SUCCESS')
    elif status == 'failed':
        backups = backups.filter(status='FAILED')

    if reason:
        backups = backups.filter(trigger_reason=reason)

    # Time filters
    now = timezone.now()
    if period == 'day':
        start_date = now - timedelta(days=1)
        backups = backups.filter(timestamp__gte=start_date)
    elif period == 'week':
        start_date = now - timedelta(days=7)
        backups = backups.filter(timestamp__gte=start_date)
    elif period == 'month':
        start_date = now - timedelta(days=30)
        backups = backups.filter(timestamp__gte=start_date)

    # Order by timestamp (newest first)
    backups = backups.order_by('-timestamp')

    # Paginate results
    paginator = Paginator(backups, 20)  # 20 backups per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Get counts for summary
    total_backups = BackupLog.objects.count()
    successful_backups = BackupLog.objects.filter(status='SUCCESS').count()
    failed_backups = BackupLog.objects.filter(status='FAILED').count()

    # Get reason distribution
    reasons = BackupLog.objects.values('trigger_reason').distinct()

    return render(request, 'backups/backups_list.html', {
        'page_obj': page_obj,
        'total_backups': total_backups,
        'successful_backups': successful_backups,
        'failed_backups': failed_backups,
        'search_query': search_query,
        'status': status,
        'reason': reason,
        'period': period,
        'reasons': reasons,
    })


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