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

    # Check if the request was made with HTMX
    if request.headers.get('HX-Request'):
        # Get the latest logs and updated stats
        logs = EnergyLog.objects.all().order_by('-timestamp')[:15]
        stats = {
            'total_logs': EnergyLog.objects.count(),
            'total_anomalies': EnergyLog.objects.filter(is_anomaly=True).count(),
            'total_manual': EnergyLog.objects.filter(is_manual=True).count(),
            'total_with_backup': EnergyLog.objects.filter(backup_triggered=True).count(),
        }

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


@login_required
def run_simulation_anomaly(request):
    """Run simulation with anomaly"""
    if request.method != 'POST':
        return redirect('logs_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для запуску симуляції аномалії.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    try:
        from ml.scheduled_tasks import simulate_with_anomaly
        log_id = simulate_with_anomaly(is_manual=True, user_id=request.user.id)

        if log_id:
            messages.success(request, f"Симуляція аномалії виконана успішно. ID запису: {log_id}")
        else:
            messages.error(request, "Помилка виконання симуляції аномалії")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції аномалії: {str(e)}")

    return redirect('logs_list')


@login_required
def run_simulation_abnormal_prediction(request):
    """Run simulation with abnormal prediction"""
    if request.method != 'POST':
        return redirect('logs_list')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для запуску симуляції аномального прогнозу.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    try:
        from ml.scheduled_tasks import simulate_with_abnormal_prediction
        log_id = simulate_with_abnormal_prediction(is_manual=True, user_id=request.user.id)

        if log_id:
            messages.success(request, f"Симуляція аномального прогнозу виконана успішно. ID запису: {log_id}")
        else:
            messages.error(request, "Помилка виконання симуляції аномального прогнозу")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції аномального прогнозу: {str(e)}")

    return redirect('logs_list')