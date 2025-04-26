# monitoring/urls.py
from django.urls import path
from . import views
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
    path('scheduler/', views.scheduler_status, name='scheduler_status'),

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

    # HTMX action endpoints
    path('action/run-simulation/', views.run_simulation, name='run_simulation'),
    path('action/force-backup/', views.force_backup, name='force_backup'),
    path('action/start-scheduler/', views.start_scheduler, name='start_scheduler'),
    path('action/stop-scheduler/', views.stop_scheduler, name='stop_scheduler'),
    path('action/restart-scheduler/', views.restart_scheduler, name='restart_scheduler'),

    # HTMX chart endpoints for analytics
    path('charts/load-trend/', views.load_trend_chart, name='load_trend_chart'),
    path('charts/anomalies-by-month/', views.anomalies_by_month_chart, name='anomalies_by_month_chart'),
    path('charts/backups-by-reason/', views.backups_by_reason_chart, name='backups_by_reason_chart'),
]