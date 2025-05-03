# monitoring/urls.py
from django.urls import path
from . import views
from . import system_settings
from .auth import (
    CustomLoginView, CustomLogoutView, RegisterView,
    UserManagementView, UserProfileEditView
)

urlpatterns = [
    # Authentication URLs
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),

    # User Management (admin only)
    path('users/', UserManagementView.as_view(), name='user_management'),
    path('users/<int:pk>/edit/', UserProfileEditView.as_view(), name='edit_user_profile'),

    # System Settings (manager and admin)
    path('settings/', views.system_settings, name='system_settings'),

    # Main Application URLs
    path('', views.dashboard, name='dashboard'),
    path('logs/', views.logs_list, name='logs_list'),
    path('logs/<int:pk>/', views.log_detail, name='log_detail'),
    path('backups/', views.backups_list, name='backups_list'),
    path('analytics/', views.analytics, name='analytics'),

    # HTMX partial endpoints
    path('partial/stats/', views.stats_partial, name='stats_partial'),
    path('partial/logs/', views.logs_partial, name='logs_partial'),
    path('partial/backups/', views.backups_partial, name='backups_partial'),
    path('scheduler_status', system_settings.scheduler_status, name='scheduler_status'),

    # HTMX action endpoints - simulations
    path('action/run-simulation/', views.run_normal_simulation, name='run_simulation'),
    path('action/run-simulation-anomaly/', views.run_anomaly_simulation, name='run_simulation_anomaly'),
    path('action/run-simulation-abnormal-prediction/', views.run_abnormal_prediction_simulation,
         name='run_simulation_abnormal_prediction'),

    # Backup management actions
    path('action/force-backup/', views.force_backup, name='force_backup'),
    path('backups/<int:backup_id>/restore/', views.restore_backup, name='restore_backup'),
    path('backups/<int:backup_id>/delete/', views.delete_backup, name='delete_backup'),

    # Scheduler management
    path('action/start-scheduler/', system_settings.start_scheduler, name='start_scheduler'),
    path('action/stop-scheduler/', system_settings.stop_scheduler, name='stop_scheduler'),
    path('action/restart-scheduler/', system_settings.restart_scheduler, name='restart_scheduler'),
    path('action/run-maintenance/', system_settings.run_maintenance, name='run_maintenance'),

    # HTMX chart endpoints for analytics
    path('charts/load-trend/', views.load_trend_chart, name='load_trend_chart'),
    path('charts/anomalies-by-month/', views.anomalies_by_month_chart, name='anomalies_by_month_chart'),
    path('charts/backups-by-reason/', views.backups_by_reason_chart, name='backups_by_reason_chart'),
]