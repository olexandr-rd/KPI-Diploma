# ml/apply_models_to_db.py

import os
import django
import pandas as pd
import numpy as np
import joblib

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog

# Load models
anomaly_model = joblib.load("model/anomaly_model.pkl")
forecast_model = joblib.load("model/forecast_model.pkl")

# Load latest N rows (sorted)
N = 100  # you can adjust this
logs = EnergyLog.objects.all().order_by('timestamp').values(
    'id',
    'ac_output_voltage',
    'dc_battery_voltage',
    'dc_battery_current',
    'load_power',
    'temperature'
)

df = pd.DataFrame(list(logs))

if df.empty or len(df) < 2:
    print("Not enough data to run predictions.")
    exit()

# === Forecasting ===
# Predict next load based on current row (t ➝ t+1)
forecast_features = df[['ac_output_voltage', 'dc_battery_voltage', 'dc_battery_current', 'load_power', 'temperature']]
forecast_preds = forecast_model.predict(forecast_features[:-1])  # last row can't be predicted

# Save forecast to current rows
for i, pred in enumerate(forecast_preds):
    EnergyLog.objects.filter(id=df.iloc[i].id).update(predicted_load=pred)

# === Anomaly Detection ===
# Use current values for anomaly detection
anomaly_features = df[['ac_output_voltage', 'dc_battery_voltage', 'dc_battery_current', 'load_power', 'temperature']]
anomaly_preds = anomaly_model.predict(anomaly_features)
anomaly_scores = anomaly_model.decision_function(anomaly_features)

# Save anomaly results to DB
for i, (pred, score) in enumerate(zip(anomaly_preds, anomaly_scores)):
    is_anomaly = pred == -1
    EnergyLog.objects.filter(id=df.iloc[i].id).update(
        is_anomaly=is_anomaly,
        anomaly_score=score
    )

print(f"Applied models to {len(df)} rows.")