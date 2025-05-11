# ml/train_forecast_model.py

import os
import django
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.multioutput import MultiOutputRegressor

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
# Predict NEXT battery current and ac output voltage at t+1 using values at t
df['dc_battery_current_next'] = df['dc_battery_current'].shift(-1)
df['ac_output_voltage_next'] = df['ac_output_voltage'].shift(-1)

# Drop last row (no next values available)
df = df.dropna()

# Features: current values of all parameters
features = df[['ac_output_voltage', 'dc_battery_voltage', 'dc_battery_current',
               'load_power', 'temperature']]

# Targets: next battery current and AC output voltage
targets = df[['dc_battery_current_next', 'ac_output_voltage_next']]

# Train multi-output regression model
base_regressor = RandomForestRegressor(n_estimators=100, random_state=42)
model = MultiOutputRegressor(base_regressor)
model.fit(features, targets)

# Save model
os.makedirs("model", exist_ok=True)
joblib.dump(model, "model/forecast_model.pkl")

print("Multi-output RandomForest trained and saved to ml/model/forecast_model.pkl")
