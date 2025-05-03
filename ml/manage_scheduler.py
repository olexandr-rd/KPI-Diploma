# ml/manage_scheduler.py

import os
import argparse
import psutil
import sys
import subprocess
import time
from pathlib import Path

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure logs directory exists
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)


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


def start_scheduler():
    """Start the scheduler if it's not already running"""
    proc = find_scheduler_process()
    if proc:
        print(f"Scheduler is already running with PID {proc.pid}")
        return

    print("Starting scheduler...")

    # Use absolute paths
    script_path = os.path.join(BASE_DIR, 'ml', 'scheduled_tasks.py')
    python_executable = sys.executable
    log_file = os.path.join(logs_dir, 'scheduler.log')

    print(f"Running: {python_executable} {script_path}")
    print(f"Logging to: {log_file}")

    # Start the process in the background
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

        # Check log file
        log_file = os.path.join(logs_dir, 'scheduler.log')
        if os.path.exists(log_file):
            last_modified = time.ctime(os.path.getmtime(log_file))
            print(f"Log file last modified: {last_modified}")

            # Show last few lines of log
            print("\nLast 5 log entries:")
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-5:]:
                        print(f"  {line.strip()}")
            except Exception as e:
                print(f"Error reading log file: {e}")
        else:
            print(f"Log file not found: {log_file}")
    else:
        print("Scheduler is not running")


def restart_scheduler():
    """Restart the scheduler"""
    stop_scheduler()
    time.sleep(1)
    start_scheduler()


def main():
    parser = argparse.ArgumentParser(description="Manage the energy monitoring scheduler")
    parser.add_argument("action", choices=["start", "stop", "restart", "status"],
                        help="Action to perform")

    match parser.parse_args():
        case "start":
            start_scheduler()
        case "stop":
            stop_scheduler()
        case "restart":
            restart_scheduler()
        case "status":
            status_scheduler()
        case _:
            print("Invalid action. Please specify a valid action (start, stop, restart, status).")


if __name__ == "__main__":
    main()