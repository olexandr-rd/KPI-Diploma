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