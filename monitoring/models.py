# monitoring/models.py - Updated SystemSettings model

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    USER_ROLES = [
        ('regular', 'Звичайний користувач'),
        ('manager', 'Менеджер'),
        ('admin', 'Системний адміністратор'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=USER_ROLES, default='regular')

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    @property
    def is_manager(self):
        """Check if a user has manager or higher permissions"""
        return self.role in ['manager', 'admin']

    @property
    def is_admin(self):
        """Check if a user has admin permissions"""
        return self.role == 'admin'


class SystemSettings(models.Model):
    # Backup settings
    backup_frequency_hours = models.IntegerField(default=24,
                                                 help_text="Частота створення резервних копій (годин)")
    backup_retention_days = models.IntegerField(default=30,
                                                help_text="Зберігати резервні копії (днів)")
    max_backups = models.IntegerField(default=20,
                                      help_text="Максимальна кількість резервних копій")

    # Data collection settings
    data_collection_interval = models.IntegerField(default=15,
                                                   help_text="Інтервал збору даних (хвилин)")

    # Energy system settings
    min_load_threshold = models.FloatField(default=500,
                                           help_text="Мінімальне допустиме навантаження (Вт)")
    max_load_threshold = models.FloatField(default=2000,
                                           help_text="Максимальне допустиме навантаження (Вт)")

    # Database settings
    max_energy_logs = models.IntegerField(default=5000,
                                          help_text="Максимальна кількість записів енергосистеми")

    # Last modified tracking
    last_modified = models.DateTimeField(auto_now=True)
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Налаштування системи (ост. зміна: {self.last_modified})"

    class Meta:
        verbose_name = "Налаштування системи"
        verbose_name_plural = "Налаштування системи"


class EnergyLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Час запису")

    # Simulated inverter metrics
    ac_output_voltage = models.FloatField(verbose_name="Вихідна напруга (В)")
    dc_battery_voltage = models.FloatField(verbose_name="Напруга батареї (В)")
    dc_battery_current = models.FloatField(verbose_name="Струм батареї (А)")
    load_power = models.FloatField(verbose_name="Навантаження (Вт)")
    temperature = models.FloatField(null=True, blank=True, verbose_name="Температура (°C)")

    # ML outputs
    predicted_load = models.FloatField(null=True, blank=True, verbose_name="Прогнозоване навантаження (Вт)")
    anomaly_score = models.FloatField(null=True, blank=True, verbose_name="Оцінка аномалії")
    is_anomaly = models.BooleanField(default=False, verbose_name="Аномалія")
    anomaly_reason = models.CharField(max_length=255, null=True, blank=True, verbose_name="Причина аномалії")

    # Backup system
    backup_triggered = models.BooleanField(default=False, verbose_name="Резервна копія")

    # New fields
    is_manual = models.BooleanField(default=False, verbose_name="Ручний запис")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="Створено користувачем")

    def __str__(self):
        return f"[{self.timestamp}] Навантаження: {self.load_power}Вт | Аномалія: {self.is_anomaly}"

    def get_anomaly_description(self):
        """Return human-readable anomaly interpretation based on score"""
        if self.anomaly_score is None:
            return "Не визначено"

        # IsolationForest returns negative scores for anomalies, with lower values being more anomalous
        if self.anomaly_score < -0.5:
            return "Висока ймовірність"
        elif self.anomaly_score < -0.3:
            return "Середня ймовірність"
        elif self.anomaly_score < -0.1:
            return "Низька ймовірність"
        else:
            return "Норма"

    def get_anomaly_score_explanation(self):
        """Provides an explanation of the anomaly score scale"""
        return "Оцінка аномалії від -1 до 1. Значення менше -0.1 вважаються аномаліями, де -1 - найбільш аномальне."

    class Meta:
        indexes = [
            models.Index(fields=['-timestamp']),  # Index for faster ordering by timestamp desc
        ]
        verbose_name = "Запис енергосистеми"
        verbose_name_plural = "Записи енергосистеми"


class BackupLog(models.Model):
    TRIGGER_CHOICES = [
        ('ANOMALY', 'Аномалія'),
        ('PREDICTION', 'Прогноз навантаження'),
        ('MANUAL', 'Ручне копіювання'),
        ('SCHEDULED', 'За розкладом'),
        ('UNKNOWN', 'Невідома причина'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Успіх'),
        ('FAILED', 'Помилка'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Час створення")
    backup_file = models.CharField(max_length=255, verbose_name="Файл")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Статус")
    size_kb = models.FloatField(default=0, verbose_name="Розмір (КБ)")
    trigger_reason = models.CharField(max_length=20, choices=TRIGGER_CHOICES, verbose_name="Причина")
    error_message = models.CharField(max_length=255, blank=True, null=True, verbose_name="Повідомлення про помилку")
    triggered_by = models.ManyToManyField(EnergyLog, blank=True, related_name='backups',
                                          verbose_name="Спричинено записами")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="Створено користувачем")

    def __str__(self):
        return f"Резервна копія {self.id} - {self.timestamp} - {self.get_status_display()}"

    class Meta:
        indexes = [
            models.Index(fields=['-timestamp']),  # Index for faster ordering by timestamp desc
        ]
        verbose_name = "Резервна копія"
        verbose_name_plural = "Резервні копії"
