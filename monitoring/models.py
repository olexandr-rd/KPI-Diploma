from django.db import models


class EnergyLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)

    # Simulated inverter metrics
    ac_output_voltage = models.FloatField()
    dc_battery_voltage = models.FloatField()
    dc_battery_current = models.FloatField()
    load_power = models.FloatField()
    temperature = models.FloatField(null=True, blank=True)

    # ML outputs
    predicted_load = models.FloatField(null=True, blank=True)
    anomaly_score = models.FloatField(null=True, blank=True)
    is_anomaly = models.BooleanField(default=False)

    # Backup system
    backup_triggered = models.BooleanField(default=False)

    def __str__(self):
        return f"[{self.timestamp}] Load: {self.load_power}W | Anomaly: {self.is_anomaly}"

    class Meta:
        indexes = [
            models.Index(fields=['-timestamp']),  # Index for faster ordering by timestamp desc
        ]


class BackupLog(models.Model):
    TRIGGER_CHOICES = [
        ('ANOMALY', 'Anomaly Detection'),
        ('PREDICTION', 'Load Prediction'),
        ('MANUAL', 'Manual Backup'),
        ('SCHEDULED', 'Scheduled Backup'),
        ('UNKNOWN', 'Unknown Reason'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    backup_file = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    size_kb = models.FloatField(default=0)
    trigger_reason = models.CharField(max_length=20, choices=TRIGGER_CHOICES)
    error_message = models.CharField(max_length=255, blank=True, null=True)
    triggered_by = models.ManyToManyField(EnergyLog, blank=True, related_name='backups')

    def __str__(self):
        return f"Backup {self.id} - {self.timestamp} - {self.status}"

    class Meta:
        indexes = [
            models.Index(fields=['-timestamp']),  # Index for faster ordering by timestamp desc
        ]