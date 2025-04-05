# ml/train_anomaly_model.py

import os
import django
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog

# Load data from DB
logs = EnergyLog.objects.all().values(
    'ac_output_voltage',
    'dc_battery_voltage',
    'dc_battery_current',
    'load_power',
    'temperature'
)
df = pd.DataFrame(list(logs))

# Train IsolationForest
features = df[['ac_output_voltage', 'dc_battery_voltage', 'dc_battery_current', 'load_power', 'temperature']]
model = IsolationForest(contamination=0.02, random_state=42)
model.fit(features)

# Save model
os.makedirs("model", exist_ok=True)
joblib.dump(model, "model/anomaly_model.pkl")

print("IsolationForest trained and saved to ml/model/anomaly_model.pkl")