import os
import django
import numpy as np
from datetime import timedelta, datetime
from django.utils import timezone

# from ml.apply_models_to_record import apply_models_to_record

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog

# Clear existing data
EnergyLog.objects.all().delete()

# Simulation parameters
days = 90
entries_per_day = 24 # 60-minute intervals
start_time = datetime.now() - timedelta(days=days)
num_entries = days * entries_per_day

for i in range(num_entries):
    timestamp = start_time + timedelta(minutes=60 * i)

    # Simulated inverter data
    ac_output_voltage = np.random.normal(230, 5)
    dc_battery_voltage = np.random.normal(24, 1)
    dc_battery_current = np.random.normal(10, 2)
    load_power = abs(np.sin(i / 10.0) * 2500 + np.random.normal(0, 100))
    temperature = np.random.normal(35, 2)

    # Save to DB
    EnergyLog.objects.create(
        timestamp=timezone.make_aware(timestamp),
        ac_output_voltage=ac_output_voltage,
        dc_battery_voltage=dc_battery_voltage,
        dc_battery_current=dc_battery_current,
        load_power=load_power,
        temperature=temperature
    )
    # apply_models_to_record()

print(f"Simulated {num_entries} inverter logs.")