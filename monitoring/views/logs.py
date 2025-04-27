# monitoring/views/logs.py

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q

from ..models import EnergyLog


@login_required
def logs_list(request):
    """Full list of energy logs with filtering and pagination"""
    # Get filter parameters
    search_query = request.GET.get('q', '')
    is_anomaly = request.GET.get('anomaly', '')
    is_manual = request.GET.get('manual', '')
    has_backup = request.GET.get('backup', '')

    # Start with all logs
    logs = EnergyLog.objects.all()

    # Apply filters
    if search_query:
        logs = logs.filter(
            Q(anomaly_reason__icontains=search_query) |
            Q(created_by__username__icontains=search_query) |
            Q(created_by__first_name__icontains=search_query) |
            Q(created_by__last_name__icontains=search_query)
        )

    if is_anomaly == 'yes':
        logs = logs.filter(is_anomaly=True)
    elif is_anomaly == 'no':
        logs = logs.filter(is_anomaly=False)

    if is_manual == 'yes':
        logs = logs.filter(is_manual=True)
    elif is_manual == 'no':
        logs = logs.filter(is_manual=False)

    if has_backup == 'yes':
        logs = logs.filter(backup_triggered=True)
    elif has_backup == 'no':
        logs = logs.filter(backup_triggered=False)

    # Order by timestamp (newest first)
    logs = logs.order_by('-timestamp')

    # Paginate results
    paginator = Paginator(logs, 50)  # 50 logs per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Count totals for summary
    total_logs = EnergyLog.objects.count()
    total_anomalies = EnergyLog.objects.filter(is_anomaly=True).count()
    total_manual = EnergyLog.objects.filter(is_manual=True).count()
    total_with_backup = EnergyLog.objects.filter(backup_triggered=True).count()

    return render(request, 'logs/logs_list.html', {
        'page_obj': page_obj,
        'total_logs': total_logs,
        'total_anomalies': total_anomalies,
        'total_manual': total_manual,
        'total_with_backup': total_with_backup,
        'search_query': search_query,
        'is_anomaly': is_anomaly,
        'is_manual': is_manual,
        'has_backup': has_backup,
    })


@login_required
def log_detail(request, pk):
    """Detailed view of a single energy log"""
    log = get_object_or_404(EnergyLog, pk=pk)

    # Get related backups
    backups = log.backups.all()

    # Get the previous and next logs for navigation
    prev_log = EnergyLog.objects.filter(timestamp__lt=log.timestamp).order_by('-timestamp').first()
    next_log = EnergyLog.objects.filter(timestamp__gt=log.timestamp).order_by('timestamp').first()

    return render(request, 'logs/log_detail.html', {
        'log': log,
        'backups': backups,
        'prev_log': prev_log,
        'next_log': next_log,
    })



