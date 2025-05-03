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


# monitoring/views/logs.py

# Let's create a unified simulation function first
@login_required
def run_simulation_generic(request, simulation_type=None):
    """
    Generic function to run different types of simulations

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

    try:
        # Mark the simulation as manual and note who triggered it
        is_manual = True
        user_id = request.user.id

        # Pick the right simulation based on type
        if simulation_type == 'anomaly':
            from ml.scheduled_tasks import simulate_with_anomaly
            log_id = simulate_with_anomaly(is_manual=is_manual, user_id=user_id)
            message_text = "Симуляція аномалії"
        elif simulation_type == 'abnormal_prediction':
            from ml.scheduled_tasks import simulate_with_abnormal_prediction
            log_id = simulate_with_abnormal_prediction(is_manual=is_manual, user_id=user_id)
            message_text = "Симуляція аномального прогнозу"
        else:
            # Normal simulation (existing run_simulation logic)
            from ml.simulate_data import create_energy_reading
            from ml.apply_models_to_record import apply_models_to_record

            # Create a new energy reading (normal data)
            log = create_energy_reading(anomaly=False, abnormal_prediction=False,
                                        is_manual=is_manual, user=request.user)

            # Apply ML models to the new reading
            is_anomaly, anomaly_score, predicted_load = apply_models_to_record(log.id)
            log_id = log.id
            message_text = "Симуляція звичайних даних"

        if log_id:
            messages.success(request, f"{message_text} виконана успішно. ID запису: {log_id}")
        else:
            messages.error(request, f"Помилка виконання симуляції")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції: {str(e)}")

    # Check if the request was made with HTMX
    if request.headers.get('HX-Request'):
        # Get the latest logs and updated stats
        logs = EnergyLog.objects.all().order_by('-timestamp')[:15]
        stats = get_stats()

        context = {
            'logs': logs,
            'stats': stats,
        }

        # Render the response with the updated logs table and trigger the event
        response = render(request, 'logs/logs_table.html', context)
        response['HX-Trigger'] = 'statsUpdated'  # Trigger event for stats/cards update
        return response
    else:
        # For non-HTMX requests, redirect to logs list
        return redirect('logs_list')


# Update existing view functions to use the generic one
@login_required
def run_simulation(request):
    """Run data simulation with normal data"""
    return run_simulation_generic(request)


@login_required
def run_simulation_anomaly(request):
    """Run simulation with anomaly"""
    return run_simulation_generic(request, simulation_type='anomaly')


@login_required
def run_simulation_abnormal_prediction(request):
    """Run simulation with abnormal prediction"""
    return run_simulation_generic(request, simulation_type='abnormal_prediction')
