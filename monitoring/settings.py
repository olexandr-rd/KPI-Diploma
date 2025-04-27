# monitoring/settings.py

from django import forms
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from .models import SystemSettings, UserProfile


class SystemSettingsForm(forms.ModelForm):
    """Form for updating system settings"""

    class Meta:
        model = SystemSettings
        fields = [
            'data_collection_interval',
            'backup_frequency_hours',
            'backup_retention_days',
            'max_backups',
            'min_load_threshold',
            'max_load_threshold',
            'max_energy_logs'
        ]
        widgets = {
            'data_collection_interval': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '60'}),
            'backup_frequency_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '168'}),
            'backup_retention_days': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '365'}),
            'max_backups': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '100'}),
            'min_load_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '5000'}),
            'max_load_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '5000'}),
            'max_energy_logs': forms.NumberInput(attrs={'class': 'form-control', 'min': '100', 'max': '50000'}),
        }


@login_required
def system_settings(request):
    """View for managing system settings - manager role required"""
    # Check if user has manager or admin role
    try:
        profile = request.user.profile
        if not profile.is_manager:
            messages.error(request, "У вас немає прав для доступу до налаштувань системи.")
            return redirect('dashboard')
    except UserProfile.DoesNotExist:
        messages.error(request, "У вас немає профілю користувача.")
        return redirect('dashboard')

    # Get or create system settings (there should be only one)
    settings, created = SystemSettings.objects.get_or_create(pk=1)

    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            with transaction.atomic():
                # Update the settings
                settings_obj = form.save(commit=False)
                settings_obj.modified_by = request.user
                settings_obj.save()

                # Update constants in backup_database.py
                try:
                    from ml.backup_database import update_thresholds
                    update_thresholds(
                        settings_obj.min_load_threshold,
                        settings_obj.max_load_threshold
                    )
                    messages.success(request, "Налаштування системи успішно оновлено.")
                except Exception as e:
                    messages.warning(request,
                                     f"Налаштування збережено, але не вдалося оновити пороги навантаження: {str(e)}")

            return redirect('system_settings')
    else:
        form = SystemSettingsForm(instance=settings)

    return render(request, 'settings/system_settings.html', {
        'form': form,
        'settings': settings,
    })
