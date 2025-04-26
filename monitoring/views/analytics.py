# monitoring/views/analytics.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Count, Avg, Max, Sum, Q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, ExtractHour
from datetime import timedelta
from django.utils import timezone

from ..models import EnergyLog, BackupLog


@login_required
def analytics(request):
    """Main analytics view with charts"""
    # Get a time period from query params, default to month
    period = request.GET.get('period', 'month')

    # Get date ranges for context
    now = timezone.now()
    if period == 'week':
        start_date = now - timedelta(days=7)
        period_display = "тиждень"
    elif period == 'year':
        start_date = now - timedelta(days=365)
        period_display = "рік"
    else:  # default to month
        start_date = now - timedelta(days=30)
        period_display = "місяць"

    # Get summary stats for the selected period
    logs_in_period = EnergyLog.objects.filter(timestamp__gte=start_date).count()
    anomalies_in_period = EnergyLog.objects.filter(timestamp__gte=start_date, is_anomaly=True).count()
    backups_in_period = BackupLog.objects.filter(timestamp__gte=start_date).count()
    successful_backups = BackupLog.objects.filter(timestamp__gte=start_date, status='SUCCESS').count()

    # Calculate percentages
    anomaly_percentage = 0
    backup_success_rate = 0

    if logs_in_period > 0:
        anomaly_percentage = (anomalies_in_period / logs_in_period) * 100

    if backups_in_period > 0:
        backup_success_rate = (successful_backups / backups_in_period) * 100

    # Calculate average load
    avg_load = EnergyLog.objects.filter(timestamp__gte=start_date).aggregate(avg=Avg('load_power'))['avg'] or 0

    # Calculate peak load
    peak_load = EnergyLog.objects.filter(timestamp__gte=start_date).aggregate(max=Max('load_power'))['max'] or 0

    # Get top anomaly reasons
    top_anomalies = EnergyLog.objects.filter(
        timestamp__gte=start_date,
        is_anomaly=True,
        anomaly_reason__isnull=False
    ).values('anomaly_reason').annotate(
        count=Count('anomaly_reason')
    ).order_by('-count')[:5]

    context = {
        'period': period,
        'period_display': period_display,
        'start_date': start_date,
        'end_date': now,
        'logs_count': logs_in_period,
        'anomalies_count': anomalies_in_period,
        'anomaly_percentage': anomaly_percentage,
        'backups_count': backups_in_period,
        'successful_backups': successful_backups,
        'backup_success_rate': backup_success_rate,
        'avg_load': avg_load,
        'peak_load': peak_load,
        'top_anomalies': top_anomalies,
    }

    return render(request, 'analytics/analytics.html', context)


@login_required
def load_trend_chart(request):
    """AJAX endpoint for load trend chart data"""
    # Get time period from query params, default to month
    period = request.GET.get('period', 'month')

    # Determine start date and truncation function based on period
    now = timezone.now()
    if period == 'week':
        start_date = now - timedelta(days=7)
        trunc_func = TruncDay
        date_format = '%d %b'
    elif period == 'year':
        start_date = now - timedelta(days=365)
        trunc_func = TruncMonth
        date_format = '%b %Y'
    else:  # default to month
        start_date = now - timedelta(days=30)
        trunc_func = TruncDay
        date_format = '%d %b'

    # Query for average and max load by day/week/month
    load_data = EnergyLog.objects.filter(
        timestamp__gte=start_date
    ).annotate(
        date=trunc_func('timestamp')
    ).values('date').annotate(
        avg_load=Avg('load_power'),
        max_load=Max('load_power')
    ).order_by('date')

    # Format data for chart
    labels = [item['date'].strftime(date_format) for item in load_data]
    avg_loads = [round(item['avg_load'], 2) if item['avg_load'] else 0 for item in load_data]
    max_loads = [round(item['max_load'], 2) if item['max_load'] else 0 for item in load_data]

    # Get average prediction accuracy
    prediction_data = EnergyLog.objects.filter(
        timestamp__gte=start_date,
        load_power__isnull=False,
        predicted_load__isnull=False
    ).annotate(
        date=trunc_func('timestamp')
    ).values('date').annotate(
        avg_predicted=Avg('predicted_load')
    ).order_by('date')

    predicted_loads = []
    for date in labels:
        # Find matching date in prediction data
        matching_prediction = next(
            (item for item in prediction_data if item['date'].strftime(date_format) == date),
            None
        )
        if matching_prediction and matching_prediction['avg_predicted']:
            predicted_loads.append(round(matching_prediction['avg_predicted'], 2))
        else:
            predicted_loads.append(None)

    return JsonResponse({
        'labels': labels,
        'datasets': [
            {
                'label': 'Середнє навантаження (Вт)',
                'data': avg_loads,
                'borderColor': 'rgba(75, 192, 192, 1)',
                'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                'fill': True,
                'tension': 0.4,
            },
            {
                'label': 'Максимальне навантаження (Вт)',
                'data': max_loads,
                'borderColor': 'rgba(255, 99, 132, 1)',
                'backgroundColor': 'rgba(255, 99, 132, 0.2)',
                'fill': False,
                'tension': 0.4,
            },
            {
                'label': 'Прогнозоване навантаження (Вт)',
                'data': predicted_loads,
                'borderColor': 'rgba(54, 162, 235, 1)',
                'backgroundColor': 'rgba(54, 162, 235, 0.2)',
                'borderDash': [5, 5],
                'fill': False,
            }
        ]
    })


@login_required
def anomalies_by_month_chart(request):
    """AJAX endpoint for anomalies by month chart data"""
    # Get last 12 months of data
    end_date = timezone.now()
    start_date = end_date - timedelta(days=365)

    # Get anomaly counts by month
    anomaly_data = EnergyLog.objects.filter(
        timestamp__gte=start_date
    ).annotate(
        month=TruncMonth('timestamp')
    ).values('month').annotate(
        total_logs=Count('id'),
        anomaly_count=Count('id', filter=Q(is_anomaly=True))
    ).order_by('month')

    # Format data for chart
    labels = [item['month'].strftime('%b %Y') for item in anomaly_data]
    anomaly_counts = [item['anomaly_count'] for item in anomaly_data]
    total_counts = [item['total_logs'] for item in anomaly_data]

    # Calculate anomaly rates
    anomaly_rates = [
        round((item['anomaly_count'] / item['total_logs']) * 100, 1)
        if item['total_logs'] > 0 else 0
        for item in anomaly_data
    ]

    return JsonResponse({
        'labels': labels,
        'datasets': [
            {
                'type': 'bar',
                'label': 'Всього записів',
                'data': total_counts,
                'backgroundColor': 'rgba(54, 162, 235, 0.5)',
                'order': 2
            },
            {
                'type': 'bar',
                'label': 'Кількість аномалій',
                'data': anomaly_counts,
                'backgroundColor': 'rgba(255, 99, 132, 0.5)',
                'order': 1
            },
            {
                'type': 'line',
                'label': 'Відсоток аномалій (%)',
                'data': anomaly_rates,
                'borderColor': 'rgba(255, 159, 64, 1)',
                'backgroundColor': 'rgba(255, 159, 64, 0.2)',
                'yAxisID': 'y1',
                'order': 0
            }
        ]
    })


@login_required
def backups_by_reason_chart(request):
    """AJAX endpoint for backups by reason chart data"""
    # Get time period from query params, default to month
    period = request.GET.get('period', 'month')

    # Determine start date based on period
    now = timezone.now()
    if period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'year':
        start_date = now - timedelta(days=365)
    else:  # default to month
        start_date = now - timedelta(days=30)

    # Get backup counts by reason
    backup_data = BackupLog.objects.filter(
        timestamp__gte=start_date
    ).values('trigger_reason').annotate(
        count=Count('id'),
        success_count=Count('id', filter=Q(status='SUCCESS')),
        failed_count=Count('id', filter=Q(status='FAILED')),
        total_size=Sum('size_kb', filter=Q(status='SUCCESS'))
    ).order_by('trigger_reason')

    # Format data for chart
    reason_map = {
        'ANOMALY': 'Аномалія',
        'PREDICTION': 'Прогноз',
        'MANUAL': 'Вручну',
        'SCHEDULED': 'За розкладом',
        'UNKNOWN': 'Невідомо'
    }

    labels = [reason_map.get(item['trigger_reason'], item['trigger_reason']) for item in backup_data]
    success_counts = [item['success_count'] for item in backup_data]
    failed_counts = [item['failed_count'] for item in backup_data]

    # Calculate total size in MB
    sizes = [round(item['total_size'] / 1024, 2) if item['total_size'] else 0 for item in backup_data]

    return JsonResponse({
        'labels': labels,
        'datasets': [
            {
                'label': 'Успішні резервні копії',
                'data': success_counts,
                'backgroundColor': 'rgba(75, 192, 192, 0.7)',
            },
            {
                'label': 'Невдалі резервні копії',
                'data': failed_counts,
                'backgroundColor': 'rgba(255, 99, 132, 0.7)',
            },
            {
                'type': 'line',
                'label': 'Загальний розмір (МБ)',
                'data': sizes,
                'borderColor': 'rgba(153, 102, 255, 1)',
                'backgroundColor': 'rgba(153, 102, 255, 0.2)',
                'yAxisID': 'y1',
            }
        ]
    })
