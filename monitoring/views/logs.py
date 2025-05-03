# monitoring/views/logs.py
from django.contrib import messages
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q

from . import get_stats
from ..models import EnergyLog, SystemSettings, UserProfile


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

    context = {
        'page_obj': page_obj,
        'total_logs': total_logs,
        'total_anomalies': total_anomalies,
        'total_manual': total_manual,
        'total_with_backup': total_with_backup,
        'search_query': search_query,
        'is_anomaly': is_anomaly,
        'is_manual': is_manual,
        'has_backup': has_backup,
    }

    if request.headers.get('HX-Request'):
        template_name = 'logs/logs_table.html'
    else:
        template_name = 'logs/logs_list.html'

    return render(request, template_name, context)


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


@login_required
def run_simulation(request, simulation_type=None):
    """
    Run data simulation with optional simulation type

    Args:
        simulation_type: None for normal, 'anomaly' for anomalous data,
                         'abnormal_prediction' for abnormal prediction
    """
    if request.method != 'POST':
        return redirect('logs_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для запуску симуляції.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Import the simulation function
    from ml.simulate_data import run_simulation_with_type

    # Set parameters for simulation
    is_manual = True
    user_id = request.user.id

    try:
        # Run the simulation
        log_id, simulation_message = run_simulation_with_type(
            simulation_type=simulation_type,
            is_manual=is_manual,
            user_id=user_id
        )

        if log_id:
            messages.success(request, f"{simulation_message} виконана успішно. ID запису: {log_id}")
        else:
            messages.error(request, f"Помилка виконання симуляції")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції: {str(e)}")

    # Get the current filters from the request
    search_query = request.GET.get('q', '')
    is_anomaly = request.GET.get('anomaly', '')
    is_manual = request.GET.get('manual', '')
    has_backup = request.GET.get('backup', '')
    page = request.GET.get('page', '1')

    # Build the filter query
    filter_params = {}
    if search_query:
        filter_params['q'] = search_query
    if is_anomaly:
        filter_params['anomaly'] = is_anomaly
    if is_manual:
        filter_params['manual'] = is_manual
    if has_backup:
        filter_params['backup'] = has_backup
    if page != '1':
        filter_params['page'] = page

    # Check if the request was made with HTMX
    if request.headers.get('HX-Request'):
        # Forward to the logs_list view to get updated data with filters
        return logs_list(request)
    else:
        # Redirect to the logs list with any filters preserved
        return redirect('logs_list')


# Specialized views that call the generic one
@login_required
def run_normal_simulation(request):
    """Run normal data simulation"""
    return run_simulation(request, simulation_type=None)


@login_required
def run_anomaly_simulation(request):
    """Run anomaly data simulation"""
    return run_simulation(request, simulation_type='anomaly')


@login_required
def run_abnormal_prediction_simulation(request):
    """Run abnormal prediction simulation"""
    return run_simulation(request, simulation_type='abnormal_prediction')