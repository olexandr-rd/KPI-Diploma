#!/usr/bin/env python
# ml/manage_scheduler.py

import os
import argparse
import psutil
import sys
import subprocess
import signal
import time


def find_scheduler_process():
    """Find the scheduler process if it's running"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and len(cmdline) > 1 and 'python' in cmdline[0].lower() and 'scheduled_tasks.py' in cmdline[1]:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None


def start_scheduler():
    """Start the scheduler if it's not already running"""
    proc = find_scheduler_process()
    if proc:
        print(f"Scheduler is already running with PID {proc.pid}")
        return

    print("Starting scheduler...")

    # Start the process in the background
    subprocess.Popen(
        ["python", "scheduled_tasks.py"],
        stdout=open("logs/scheduler.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )

    # Wait a moment and check if it started
    time.sleep(2)
    proc = find_scheduler_process()
    if proc:
        print(f"Scheduler started successfully with PID {proc.pid}")
    else:
        print("Failed to start scheduler. Check logs/scheduler.log for details")


def stop_scheduler():
    """Stop the scheduler if it's running"""
    proc = find_scheduler_process()
    if not proc:
        print("Scheduler is not running")
        return

    print(f"Stopping scheduler (PID {proc.pid})...")

    try:
        # Try to terminate gracefully first
        proc.terminate()

        # Wait up to 5 seconds for it to exit
        for i in range(50):
            if not proc.is_running():
                break
            time.sleep(0.1)

        # If still running, force kill
        if proc.is_running():
            print("Scheduler didn't terminate gracefully, forcing kill...")
            proc.kill()

        print("Scheduler stopped successfully")

    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        print(f"Error stopping scheduler: {e}")


def status_scheduler():
    """Check the status of the scheduler"""
    proc = find_scheduler_process()
    if proc:
        print(f"Scheduler is running with PID {proc.pid}")
        print(f"Started at: {time.ctime(proc.create_time())}")
        print(f"Running for: {time.time() - proc.create_time():.1f} seconds")

        # Try to get memory info
        try:
            mem = proc.memory_info()
            print(f"Memory usage: {mem.rss / (1024 * 1024):.2f} MB")
        except:
            pass
    else:
        print("Scheduler is not running")


def restart_scheduler():
    """Restart the scheduler"""
    stop_scheduler()
    time.sleep(1)
    start_scheduler()


def run_once():
    """Run the simulation and maintenance once without starting the scheduler"""
    print("Running data simulation once...")
    subprocess.run(["python", "ml/simulate_data.py"], check=True)

    print("\nRunning maintenance tasks once...")
    subprocess.run(["python", "-c", """
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()
from ml.scheduled_tasks import cleanup_old_backups, purge_old_energy_logs
cleanup_old_backups()
purge_old_energy_logs()
print('Maintenance completed')
"""], check=True)


def main():
    parser = argparse.ArgumentParser(description="Manage the energy monitoring scheduler")
    parser.add_argument("action", choices=["start", "stop", "restart", "status", "run-once"],
                        help="Action to perform")

    args = parser.parse_args()

    match args.action:
        case "start":
            start_scheduler()
        case "stop":
            stop_scheduler()
        case "restart":
            restart_scheduler()
        case "status":
            status_scheduler()
        case "run-once":
            run_once()
        case _:
            print("Invalid action. Please specify a valid action (start, stop, restart, status, run-once).")


if __name__ == "__main__":
    main()