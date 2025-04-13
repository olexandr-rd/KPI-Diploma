# ml/apply_models_to_record.py

import os
import django
import pandas as pd
import joblib
import sys

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog


def apply_models_to_record(record_id=None):
    """
    Apply ML models to a single energy record or the latest if no ID provided

    Args:
        record_id: ID of record to analyze, or None for latest

    Returns:
        tuple: (is_anomaly, anomaly_score, predicted_load)
    """
    # Load models
    anomaly_model = joblib.load("model/anomaly_model.pkl")
    forecast_model = joblib.load("model/forecast_model.pkl")

    # Get the record to analyze
    if record_id:
        record = EnergyLog.objects.get(id=record_id)
    else:
        record = EnergyLog.objects.latest('timestamp')

    # Create DataFrame with feature columns matching model expectations
    features = pd.DataFrame({
        'ac_output_voltage': [record.ac_output_voltage],
        'dc_battery_voltage': [record.dc_battery_voltage],
        'dc_battery_current': [record.dc_battery_current],
        'load_power': [record.load_power],
        'temperature': [record.temperature]
    })

    # === Anomaly Detection ===
    anomaly_pred = anomaly_model.predict(features)[0]
    anomaly_score = anomaly_model.decision_function(features)[0]
    is_anomaly = anomaly_pred == -1

    # Update record with anomaly results
    record.is_anomaly = is_anomaly
    record.anomaly_score = anomaly_score
    record.save()

    # === Load Forecasting ===
    # For forecasting, we'll need previous records to predict the next one
    # Get the previous record to use for forecasting the next load
    prev_records = EnergyLog.objects.filter(timestamp__lt=record.timestamp).order_by('-timestamp')[:1]

    # If we have a previous record, we can predict the next load
    predicted_load = None
    if prev_records.exists():
        prev_record = prev_records.first()
        prev_features = pd.DataFrame({
            'ac_output_voltage': [prev_record.ac_output_voltage],
            'dc_battery_voltage': [prev_record.dc_battery_voltage],
            'dc_battery_current': [prev_record.dc_battery_current],
            'load_power': [prev_record.load_power],
            'temperature': [prev_record.temperature]
        })

        # Predict load for the current record
        predicted_load = forecast_model.predict(prev_features)[0]

        # Update the current record with the prediction
        record.predicted_load = predicted_load
        record.save()

    print(f"Applied models to record {record.id}")
    print(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted load: {predicted_load}")

    return is_anomaly, anomaly_score, predicted_load


if __name__ == "__main__":
    # If record ID is provided as command line argument, use it
    record_id = sys.argv[1] if len(sys.argv) > 1 else None

    if record_id:
        apply_models_to_record(int(record_id))
    else:
        apply_models_to_record()