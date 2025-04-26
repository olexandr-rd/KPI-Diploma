# monitoring/scheduler.py

import os
import subprocess
import psutil
import time
import datetime
import sys
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from .models import UserProfile


def find_scheduler_process():
    """Find the scheduler process if it's running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Get full command line as string to perform more flexible matching
            if proc.info.get('cmdline'):
                cmdline_str = ' '.join(proc.info['cmdline'])
                if 'python' in cmdline_str.lower() and 'scheduled_tasks.py' in cmdline_str:
                    return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None


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

    # Get basic process info
    info = {
        'is_running': True,
        'pid': proc.pid,
        'started_at': datetime.datetime.fromtimestamp(proc.create_time()),
        'uptime': timezone.now() - datetime.datetime.fromtimestamp(proc.create_time()),
        'status': 'Активний',
    }

    # Try to get memory info
    try:
        mem = proc.memory_info()
        info['memory_mb'] = mem.rss / (1024 * 1024)
    except:
        info['memory_mb'] = None

    # Check a log file
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        log_file = os.path.join(BASE_DIR, 'logs', 'scheduler.log')

        if os.path.exists(log_file):
            last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(log_file))
            info['log_last_modified'] = last_modified

            # Get last few lines of log
            with open(log_file, 'r') as f:
                lines = f.readlines()
                info['log_entries'] = lines[-20:]  # Last 20 lines
        else:
            info['log_entries'] = ["Файл журналу не знайдено"]
    except Exception as e:
        info['log_entries'] = [f"Помилка читання журналу: {str(e)}"]

    return info


@login_required
def scheduler_status(request):
    """View for managing scheduler process - manager role required"""
    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для управління планувальником.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Get scheduler info
    scheduler_info = get_scheduler_info()

    return render(request, 'settings/scheduler_status.html', {
        'scheduler': scheduler_info,
    })


@login_required
def start_scheduler(request):
    """Start the scheduler process - manager role required"""
    if request.method != 'POST':
        return redirect('scheduler_status')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для запуску планувальника.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Check if already running
    proc = find_scheduler_process()
    if proc:
        messages.info(request, f"Планувальник вже запущено з PID {proc.pid}")
        return redirect('scheduler_status')

    # Start the scheduler
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        log_file = os.path.join(BASE_DIR, 'logs', 'scheduler.log')

        # Ensure logs directory exists
        logs_dir = os.path.dirname(log_file)
        os.makedirs(logs_dir, exist_ok=True)

        # Use the same Python executable running this Django app
        python_executable = sys.executable

        subprocess.Popen(
            [python_executable, script_path],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(BASE_DIR)  # Set working directory to project root
        )

        # Wait a moment and check if it started
        time.sleep(2)
        proc = find_scheduler_process()

        if proc:
            messages.success(request, f"Планувальник успішно запущено з PID {proc.pid}")
        else:
            messages.error(request, "Не вдалося запустити планувальник")

    except Exception as e:
        messages.error(request, f"Помилка запуску планувальника: {str(e)}")

    return redirect('scheduler_status')


@login_required
def stop_scheduler(request):
    """Stop the scheduler process - manager role required"""
    if request.method != 'POST':
        return redirect('scheduler_status')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для зупинки планувальника.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Find scheduler process
    proc = find_scheduler_process()
    if not proc:
        messages.info(request, "Планувальник не запущено")
        return redirect('scheduler_status')

    # Stop the scheduler
    try:
        pid = proc.pid

        # Try to terminate gracefully first
        proc.terminate()

        # Wait up to 5 seconds for it to exit
        for i in range(50):
            if not proc.is_running():
                break
            time.sleep(0.1)

        # If still running, force kill
        if proc.is_running():
            proc.kill()
            messages.warning(request, f"Планувальник (PID {pid}) примусово зупинено")
        else:
            messages.success(request, f"Планувальник (PID {pid}) успішно зупинено")

    except Exception as e:
        messages.error(request, f"Помилка зупинки планувальника: {str(e)}")

    return redirect('scheduler_status')


@login_required
def restart_scheduler(request):
    """Restart the scheduler process - manager role required"""
    if request.method != 'POST':
        return redirect('scheduler_status')

    # Check if a user has a manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для перезапуску планувальника.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Stop first
    proc = find_scheduler_process()
    if proc:
        try:
            pid = proc.pid

            # Try to terminate gracefully
            proc.terminate()

            # Wait for it to exit
            for i in range(50):
                if not proc.is_running():
                    break
                time.sleep(0.1)

            # If still running, force kill
            if proc.is_running():
                proc.kill()
        except Exception as e:
            messages.error(request, f"Помилка зупинки планувальника: {str(e)}")
            return redirect('scheduler_status')

    # Wait a bit
    time.sleep(1)

    # Start again
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        log_file = os.path.join(BASE_DIR, 'logs', 'scheduler.log')

        # Use the same Python executable that's running this Django app
        python_executable = sys.executable

        subprocess.Popen(
            [python_executable, script_path],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(BASE_DIR)  # Set working directory to project root
        )

        # Wait a moment and check if it started
        time.sleep(2)
        proc = find_scheduler_process()

        if proc:
            messages.success(request, f"Планувальник успішно перезапущено з PID {proc.pid}")
        else:
            messages.error(request, "Не вдалося перезапустити планувальник")

    except Exception as e:
        messages.error(request, f"Помилка запуску планувальника: {str(e)}")

    return redirect('scheduler_status')
