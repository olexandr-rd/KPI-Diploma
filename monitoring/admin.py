# monitoring/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import EnergyLog, BackupLog, UserProfile, SystemSettings


# Define inline admin for UserProfile
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Профіль користувача'


# Define a new User admin
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'get_role', 'is_staff')

    def get_role(self, obj):
        try:
            return obj.profile.get_role_display()
        except UserProfile.DoesNotExist:
            return "Немає профілю"

    get_role.short_description = 'Роль'


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# Register other models
@admin.register(EnergyLog)
class EnergyLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'load_power', 'predicted_load', 'is_anomaly', 'is_manual', 'created_by')
    list_filter = ('is_anomaly', 'is_manual', 'backup_triggered')
    search_fields = ('anomaly_reason',)
    readonly_fields = ('timestamp',)


@admin.register(BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'backup_file', 'status', 'trigger_reason', 'size_kb', 'created_by')
    list_filter = ('status', 'trigger_reason')
    search_fields = ('backup_file', 'error_message')
    readonly_fields = ('timestamp',)


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'backup_frequency_hours', 'backup_retention_days', 'max_backups',
                    'min_load_threshold', 'max_load_threshold', 'last_modified', 'modified_by')
    readonly_fields = ('last_modified',)

    def has_add_permission(self, request):
        # Only allow one instance of system settings
        if SystemSettings.objects.exists():
            return False
        return super().has_add_permission(request)
