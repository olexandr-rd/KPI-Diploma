# monitoring/views/backups.py
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from datetime import datetime, timedelta

from django.utils import timezone

from . import get_stats
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
def force_backup(request):
    """Force a manual backup without creating new data"""
    if request.method != 'POST':
        return redirect('backups_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для створення резервних копій.")
            return redirect('backups_list')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('backups_list')

    try:
        # Get the latest record
        latest_record = EnergyLog.objects.latest('timestamp')

        print(f"Forcing backup for latest record ID: {latest_record.id}")

        # Import backup function directly
        from ml.backup_database import backup_database

        # Force backup of the latest record with the current user
        backup_performed = backup_database(latest_record.id, force=True, user=request.user)

        if backup_performed:
            messages.success(request, "Резервну копію створено успішно")
        else:
            messages.error(request, "Не вдалося створити резервну копію")

    except Exception as e:
        messages.error(request, f"Помилка при створенні резервної копії: {str(e)}")

    # Check if the request was made with HTMX
    if request.headers.get('HX-Request'):
        # Get all backups for the updated view
        backups = BackupLog.objects.all().order_by('-timestamp')[:20]
        context = {
            'backups': backups,
        }

        # Return the updated backups table
        response = render(request, 'backups/backups_table.html', context)
        response['HX-Trigger'] = 'statsUpdated'  # Trigger stats update
        return response
    else:
        return redirect('backups_list')


# monitoring/views/backups.py (New functions)

@login_required
def restore_backup(request, backup_id):
    """Restore database from a backup"""
    if request.method != 'POST':
        return redirect('backups_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для відновлення резервних копій.")
            return redirect('backups_list')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('backups_list')

    try:
        # Get the backup
        backup = get_object_or_404(BackupLog, id=backup_id, status='SUCCESS')

        # Import restore function
        from ml.backup_database import restore_database

        # Perform restore
        success, message = restore_database(backup.backup_file, user=request.user)

        if success:
            messages.success(request, f"Базу даних успішно відновлено з резервної копії {backup.backup_file}")
        else:
            messages.error(request, f"Помилка відновлення: {message}")

    except Exception as e:
        messages.error(request, f"Помилка при відновленні бази даних: {str(e)}")

    # Return the updated backups table
    backups = BackupLog.objects.all().order_by('-timestamp')[:20]
    context = {
        'backups': backups,
    }

    # Return the updated view
    response = render(request, 'backups/backups_table.html', context)
    response['HX-Trigger'] = 'statsUpdated'  # Trigger stats update
    return response


@login_required
def delete_backup(request, backup_id):
    """Delete a backup file"""
    if request.method != 'POST':
        return redirect('backups_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для видалення резервних копій.")
            return redirect('backups_list')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('backups_list')

    try:
        # Get the backup
        backup = get_object_or_404(BackupLog, id=backup_id)

        # Import delete function
        from ml.backup_database import delete_backup_file

        # Delete the backup file
        success, message = delete_backup_file(backup.backup_file)

        if success:
            # Delete the database record
            backup.delete()
            messages.success(request, f"Резервну копію {backup.backup_file} успішно видалено")
        else:
            messages.error(request, f"Помилка видалення файлу: {message}")

    except Exception as e:
        messages.error(request, f"Помилка при видаленні резервної копії: {str(e)}")

    # Return the updated backups table
    backups = BackupLog.objects.all().order_by('-timestamp')[:20]
    context = {
        'backups': backups,
    }

    # Return the updated view
    response = render(request, 'backups/backups_table.html', context)
    response['HX-Trigger'] = 'statsUpdated'  # Trigger stats update
    return response
