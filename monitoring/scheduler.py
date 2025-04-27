# monitoring/scheduler.py

import os
import subprocess
import psutil
import time
import datetime
import sys
import signal
from pathlib import Path
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from .models import UserProfile, EnergyLog, BackupLog


def find_scheduler_process():
    """Find the scheduler process if it's running"""
    # First, check for PID file
    BASE_DIR = Path(__file__).resolve().parent.parent
    pid_file = os.path.join(BASE_DIR, 'logs', 'scheduler.pid')

    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            # Check if process with this PID exists
            try:
                proc = psutil.Process(pid)
                # Verify it's actually our scheduler
                cmdline_str = ' '.join(proc.cmdline())
                if 'python' in cmdline_str.lower() and 'scheduled_tasks.py' in cmdline_str:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # PID file exists but process doesn't, clean up the file
                os.remove(pid_file)
        except:
            # Problems reading PID file, ignore and fall back to process search
            pass

    # Fall back to searching all processes
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
        'uptime': timezone.now() - timezone.make_aware(datetime.datetime.fromtimestamp(proc.create_time())),
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


def kill_scheduler_process(proc):
    """Kill a scheduler process with escalating force"""
    if not proc:
        return False

    pid = proc.pid
    success = False

    try:
        # First, try to terminate gracefully
        proc.terminate()

        # Wait up to 5 seconds for it to exit
        for i in range(50):
            if not proc.is_running():
                success = True
                break
            time.sleep(0.1)

        # If still running, send SIGINT (equivalent to Ctrl+C)
        if not success:
            os.kill(pid, signal.SIGINT)

            # Wait another 5 seconds
            for i in range(50):
                if not psutil.pid_exists(pid):
                    success = True
                    break
                time.sleep(0.1)

        # If still running, force kill
        if not success:
            proc.kill()
            success = True

        # Clean up PID file if it exists
        BASE_DIR = Path(__file__).resolve().parent.parent
        pid_file = os.path.join(BASE_DIR, 'logs', 'scheduler.pid')
        if os.path.exists(pid_file):
            os.remove(pid_file)

    except Exception as e:
        print(f"Error killing process: {e}")
        return False

    return success


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

    # Add operation counters for information
    scheduler_info['total_logs'] = EnergyLog.objects.count()
    scheduler_info['total_backups'] = BackupLog.objects.count()
    scheduler_info['total_anomalies'] = EnergyLog.objects.filter(is_anomaly=True).count()

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

        # Clear any existing PID file to prevent confusion
        pid_file = os.path.join(logs_dir, 'scheduler.pid')
        if os.path.exists(pid_file):
            os.remove(pid_file)

        # Start the process with minimal output and handling
        subprocess.Popen(
            [python_executable, script_path],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(BASE_DIR)  # Set working directory to project root
        )

        # Wait a moment and check if it started
        time.sleep(3)
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

        if kill_scheduler_process(proc):
            messages.success(request, f"Планувальник (PID {pid}) успішно зупинено")
        else:
            messages.warning(request,
                             f"Планувальник (PID {pid}) примусово зупинено, але можуть залишитися активні процеси")

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
            if not kill_scheduler_process(proc):
                messages.error(request, "Не вдалося зупинити поточний планувальник")
                return redirect('scheduler_status')
        except Exception as e:
            messages.error(request, f"Помилка зупинки планувальника: {str(e)}")
            return redirect('scheduler_status')

    # Wait a bit
    time.sleep(2)

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
        time.sleep(3)
        proc = find_scheduler_process()

        if proc:
            messages.success(request, f"Планувальник успішно перезапущено з PID {proc.pid}")
        else:
            messages.error(request, "Не вдалося перезапустити планувальник")

    except Exception as e:
        messages.error(request, f"Помилка запуску планувальника: {str(e)}")

    return redirect('scheduler_status')


@login_required
def run_maintenance(request):
    """Run maintenance tasks manually"""
    if request.method != 'POST':
        return redirect('scheduler_status')

    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для запуску обслуговування.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        python_executable = sys.executable

        # Run maintenance command
        result = subprocess.run(
            [python_executable, script_path, "maintenance"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR)
        )

        if result.returncode == 0:
            messages.success(request, "Задачі обслуговування виконано успішно.")
        else:
            messages.error(request, f"Помилка виконання обслуговування: {result.stderr}")

    except Exception as e:
        messages.error(request, f"Помилка запуску обслуговування: {str(e)}")

    return redirect('scheduler_status')


@login_required
def run_simulation_anomaly(request):
    """Run simulation with anomaly"""
    if request.method != 'POST':
        return redirect('scheduler_status')

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
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        python_executable = sys.executable

        # Run anomaly simulation
        result = subprocess.run(
            [python_executable, script_path, "anomaly"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR)
        )

        if result.returncode == 0:
            messages.success(request, "Симуляція аномалії виконана успішно.")
        else:
            messages.error(request, f"Помилка виконання симуляції аномалії: {result.stderr}")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції аномалії: {str(e)}")

    return redirect('scheduler_status')


@login_required
def run_simulation_abnormal_prediction(request):
    """Run simulation with abnormal prediction"""
    if request.method != 'POST':
        return redirect('scheduler_status')

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
        BASE_DIR = Path(__file__).resolve().parent.parent
        script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
        python_executable = sys.executable

        # Run abnormal prediction simulation
        result = subprocess.run(
            [python_executable, script_path, "abnormal_prediction"],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR)
        )

        if result.returncode == 0:
            messages.success(request, "Симуляція аномального прогнозу виконана успішно.")
        else:
            messages.error(request, f"Помилка виконання симуляції аномального прогнозу: {result.stderr}")

    except Exception as e:
        messages.error(request, f"Помилка запуску симуляції аномального прогнозу: {str(e)}")

    return redirect('scheduler_status')