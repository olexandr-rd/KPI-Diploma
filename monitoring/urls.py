from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # HTMX partial endpoints
    path('stats/', views.stats_partial, name='stats_partial'),
    path('logs/', views.logs_partial, name='logs_partial'),
    path('backups/', views.backups_partial, name='backups_partial'),

    # HTMX action endpoints
    path('run-simulation/', views.run_simulation, name='run_simulation'),
    path('force-backup/', views.force_backup, name='force_backup'),
]