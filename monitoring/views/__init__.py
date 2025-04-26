# monitoring/views/__init__.py

# Import all views to make them available through the views package
from .dashboard import *
from .logs import *
from monitoring.settings import system_settings
from monitoring.scheduler import (
    scheduler_status, start_scheduler, stop_scheduler, restart_scheduler
)
from .analytics import analytics, load_trend_chart, anomalies_by_month_chart, backups_by_reason_chart