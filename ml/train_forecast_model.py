import os
import django
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestRegressor

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog

# Load data
logs = EnergyLog.objects.all().order_by('timestamp').values(
    'timestamp',
    'ac_output_voltage',
    'dc_battery_voltage',
    'dc_battery_current',
    'load_power',
    'temperature'
)
df = pd.DataFrame(list(logs))

# Sort & reset index
df = df.sort_values('timestamp').reset_index(drop=True)

# Feature engineering
# Predict load_power at t+1 using values at t
df['load_power_next'] = df['load_power'].shift(-1)

# Drop last row (no target available)
df = df.dropna()

features = df[['ac_output_voltage', 'dc_battery_voltage', 'dc_battery_current', 'load_power', 'temperature']]
target = df['load_power_next']

# Train model
model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(features, target)

# Save model
os.makedirs("model", exist_ok=True)
joblib.dump(model, "model/forecast_model.pkl")

print("RandomForestRegressor trained and saved to ml/model/forecast_model.pkl")