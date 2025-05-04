# monitoring/views/__init__.py

# Import all views to make them available through the views package
from .analytics import *
from .backups import *
from .dashboard import *
from .logs import *
from monitoring.system_settings import (
    system_settings, start_scheduler, stop_scheduler, restart_scheduler
)
