# monitoring/system_settings.py

import os
import subprocess
import datetime
import sys
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from django import forms
from django.shortcuts import render, redirect
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import SystemSettings, UserProfile, EnergyLog, BackupLog
from ml.manage_scheduler import (find_scheduler_process, start_scheduler as start_sched, stop_scheduler as stop_sched,
                                 restart_scheduler as restart_sched)


class SystemSettingsForm(forms.ModelForm):
    """Form for updating system settings"""

    class Meta:
        model = SystemSettings
        fields = [
            'data_collection_interval',
            'backup_frequency_hours',
            'backup_retention_days',
            'max_backups',
            'min_load_threshold',
            'max_load_threshold',
            'max_energy_logs',
            'maintenance_time',
        ]
        widgets = {
            'data_collection_interval': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '60'}),
            'backup_frequency_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '168'}),
            'backup_retention_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '365'}),
            'max_backups': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '100'}),
            'min_load_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '5000'}),
            'max_load_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '5000'}),
            'max_energy_logs': forms.NumberInput(attrs={'class': 'form-control', 'min': '100', 'max': '50000'}),
            'maintenance_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }


def manager_required(view_function=None, *, redirect_url='dashboard', message=None):
    """
    Decorator to verify that a user has a manager role.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            try:
                profile = request.user.profile
                if not profile.is_manager:
                    error_msg = message or "У вас немає прав для виконання цієї дії."
                    messages.error(request, error_msg)
                    return redirect(redirect_url)
            except UserProfile.DoesNotExist:
                error_msg = "У вас немає профілю користувача."
                messages.error(request, error_msg)
                return redirect(redirect_url)

            return view_func(request, *args, **kwargs)

        return wrapped_view

    # This allows the decorator to be used with or without arguments
    if view_function:
        return decorator(view_function)
    return decorator

@login_required
@manager_required(message="У вас немає доступу до налаштувань планувальника.")
def system_settings(request):
    """View for managing system settings - manager role required"""

    # Get or create system settings (there should be only one)
    settings, created = SystemSettings.objects.get_or_create(pk=1)

    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            with transaction.atomic():
                # Update the settings
                settings_obj = form.save(commit=False)
                settings_obj.modified_by = request.user
                settings_obj.save()

                # Update constants in backup_database.py
                try:
                    from ml.backup_database import update_thresholds
                    update_thresholds(
                        settings_obj.min_load_threshold,
                        settings_obj.max_load_threshold
                    )
                    messages.success(request, "Налаштування планувальника успішно оновлено.")
                except Exception as e:
                    messages.warning(request,
                                     f"Налаштування збережено, але не вдалося оновити пороги навантаження: {str(e)}")

            return redirect('system_settings')
    else:
        form = SystemSettingsForm(instance=settings)

    return render(request, 'settings/system_settings.html', {
        'form': form,
        'settings': settings,
    })


def get_scheduler_info():
    """Get information about the scheduler process"""
    proc = find_scheduler_process()
    
    if not proc:
        return {
            'is_running': False,
            'pid': None,
            'started_at': None,
            'uptime': None,
            'memory_mb': None,
            'log_entries': [],
            'status': 'Зупинено',
        }

    info = {
        'is_running': True,
        'pid': proc.pid,
        'started_at': datetime.datetime.fromtimestamp(proc.create_time()),
        'uptime': timezone.now() - timezone.make_aware(datetime.datetime.fromtimestamp(proc.create_time())),
        'status': 'Активний',
    }

    try:
        mem = proc.memory_info()
        info['memory_mb'] = mem.rss / (1024 * 1024)
    except:
        info['memory_mb'] = None

    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        log_file = os.path.join(BASE_DIR, 'logs', 'scheduler.log')

        if os.path.exists(log_file):
            last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(log_file))
            info['log_last_modified'] = last_modified

            with open(log_file, 'r') as f:
                lines = f.readlines()
                info['log_entries'] = lines[-20:]
        else:
            info['log_entries'] = ["Файл журналу не знайдено"]
    except Exception as e:
        info['log_entries'] = [f"Помилка читання журналу: {str(e)}"]

    return info


@login_required
@manager_required(message="У вас немає доступу до налаштувань планувальника.")
def scheduler_status(request):
    """View for scheduler status"""
    scheduler_info = get_scheduler_info()

    scheduler_info['total_logs'] = EnergyLog.objects.count()
    scheduler_info['total_backups'] = BackupLog.objects.count()
    scheduler_info['total_anomalies'] = EnergyLog.objects.filter(is_anomaly=True).count()

    return render(request, 'settings/scheduler_status.html', {
        'scheduler': scheduler_info,
    })


@login_required
@manager_required(message="У вас немає прав для запуску планувальника.")
def start_scheduler(request):
    """Start the scheduler process"""
    if request.method != 'POST':
        return redirect('system_settings')

    start_sched()

    proc = find_scheduler_process()
    if proc:
        messages.success(request, f"Планувальник успішно запущено з PID {proc.pid}")
    else:
        messages.error(request, "Не вдалося запустити планувальник")

    return redirect('system_settings')


@login_required
@manager_required(message="У вас немає прав для зупинки планувальника.")
def stop_scheduler(request):
    """Stop the scheduler process"""
    if request.method != 'POST':
        return redirect('system_settings')

    proc = find_scheduler_process()
    if not proc:
        messages.info(request, "Планувальник не запущено")
        return redirect('system_settings')
    pid = proc.pid
    stop_sched()
    
    messages.success(request, f"Планувальник (PID {pid}) успішно зупинено")
    return redirect('system_settings')


@login_required
@manager_required(message="У вас немає прав для перезапуску планувальника.")
def restart_scheduler(request):
    """Restart the scheduler process """
    if request.method != 'POST':
        return redirect('system_settings')

    restart_sched()

    proc = find_scheduler_process()
    if proc:
        messages.success(request, f"Планувальник успішно перезапущено з PID {proc.pid}")
    else:
        messages.error(request, "Не вдалося перезапустити планувальник")

    return redirect('system_settings')


@login_required
@manager_required(message="У вас немає прав для перезапису бази даних.")
def run_maintenance(request):
    """Run maintenance tasks manually"""
    if request.method != 'POST':
        return redirect('system_settings')

    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        python_executable = sys.executable

        result = subprocess.run(
            [python_executable, script_path, "maintenance"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR)
        )

        if result.returncode == 0:
            messages.success(request, "Перезапис бази даних виконано успішно.")
        else:
            messages.error(request, f"Помилка перезапису бази даних: {result.stderr}")

    except Exception as e:
        messages.error(request, f"Помилка запуску перезапису бази даних: {str(e)}")

    return redirect('system_settings')
