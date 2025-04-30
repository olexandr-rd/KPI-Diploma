# ml/apply_models_to_record.py

import os
import django
import pandas as pd
import numpy as np
import joblib
import sys
from pathlib import Path

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog, SystemSettings


def get_system_settings():
    """Get system settings for thresholds"""
    try:
        settings = SystemSettings.objects.first()
        if settings:
            return settings
    except Exception:
        pass

    # Default values if settings not found
    return type('obj', (object,), {
        'min_load_threshold': 500,
        'max_load_threshold': 2000,
    })


def get_anomaly_explanation(features, feature_scores):
    """
    Generate a human-readable explanation for an anomaly

    Args:
        features: DataFrame with feature values
        feature_scores: Dictionary of feature contribution scores

    Returns:
        str: Explanation of the anomaly
    """
    settings = get_system_settings()

    # Get the most suspicious features (highest absolute score)
    suspicious_features = sorted(feature_scores.items(), key=lambda x: abs(x[1]), reverse=True)

    explanations = []

    # Check each feature for potential issues
    for feature, score in suspicious_features[:2]:  # Top 2 contributing features
        if feature == 'ac_output_voltage':
            if features['ac_output_voltage'].values[0] < 210:
                explanations.append(f"Надто низька вихідна напруга")
            elif features['ac_output_voltage'].values[0] > 250:
                explanations.append(f"Надто висока вихідна напруга")

        elif feature == 'dc_battery_voltage':
            if features['dc_battery_voltage'].values[0] < 22:
                explanations.append(f"Критично низький заряд батареї")
            elif features['dc_battery_voltage'].values[0] > 28:
                explanations.append(f"Перевищення напруги батареї")

        elif feature == 'dc_battery_current':
            if features['dc_battery_current'].values[0] > 15:
                explanations.append(f"Високий струм батареї")
            elif features['dc_battery_current'].values[0] < 5:
                explanations.append(f"Низький струм батареї")

        elif feature == 'load_power':
            if features['load_power'].values[0] < settings.min_load_threshold:
                explanations.append(f"Критично низьке навантаження")
            elif features['load_power'].values[0] > settings.max_load_threshold:
                explanations.append(f"Перевантаження системи")

        elif feature == 'temperature':
            if features['temperature'].values[0] > 45:
                explanations.append(f"Перегрів системи")
            elif features['temperature'].values[0] < 10:
                explanations.append(f"Надто низька температура")

    # If no specific issues found, provide a general explanation
    if not explanations:
        top_feature = suspicious_features[0][0] if suspicious_features else None
        if top_feature:
            feature_name_map = {
                'ac_output_voltage': 'вихідна напруга',
                'dc_battery_voltage': 'напруга батареї',
                'dc_battery_current': 'струм батареї',
                'load_power': 'навантаження',
                'temperature': 'температура'
            }
            feature_name = feature_name_map.get(top_feature, top_feature)
            explanations.append(f"Нетипове значення параметра: {feature_name}")
        else:
            explanations.append("Незвичайна комбінація параметрів")

    return ", ".join(explanations)


def calculate_feature_scores(model, features):
    """
    Calculate the contribution of each feature to the anomaly score

    Args:
        model: Trained IsolationForest model
        features: DataFrame with feature values

    Returns:
        dict: Feature contribution scores
    """
    # Get feature importances
    feature_scores = {}

    # Simple approach: check each feature independently
    baseline_score = model.decision_function(features)[0]

    for feature in features.columns:
        # Create a copy with the feature set to its mean value
        modified_features = features.copy()
        modified_features[feature] = features[feature].mean()

        # Calculate new anomaly score
        new_score = model.decision_function(modified_features)[0]

        # The difference shows how much this feature contributes to the anomaly score
        feature_scores[feature] = baseline_score - new_score

    return feature_scores


def apply_models_to_record(record_id=None):
    """
    Apply ML models to a single energy record or the latest if no ID provided
    With enhanced anomaly explanation

    Args:
        record_id: ID of record to analyze, or None for latest

    Returns:
        tuple: (is_anomaly, anomaly_score, predicted_load)
    """
    # Load models
    model_dir = os.path.join(BASE_DIR, 'ml/model')
    os.makedirs(model_dir, exist_ok=True)

    anomaly_model_path = os.path.join(model_dir, 'anomaly_model.pkl')
    forecast_model_path = os.path.join(model_dir, 'forecast_model.pkl')

    # Check if models exist, if not print a helpful error
    missing_models = []
    if not os.path.exists(anomaly_model_path):
        missing_models.append('anomaly_model.pkl')
    if not os.path.exists(forecast_model_path):
        missing_models.append('forecast_model.pkl')

    if missing_models:
        error_msg = f"Missing models: {', '.join(missing_models)}. Please run the training scripts first."
        print(error_msg)
        raise FileNotFoundError(error_msg)

    # Load models
    anomaly_model = joblib.load(anomaly_model_path)
    forecast_model = joblib.load(forecast_model_path)

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

    # Get explanation if it's an anomaly
    anomaly_reason = None
    if is_anomaly:
        try:
            # Calculate feature scores
            feature_scores = calculate_feature_scores(anomaly_model, features)

            # Get human-readable explanation
            anomaly_reason = get_anomaly_explanation(features, feature_scores)
        except Exception as e:
            print(f"Error generating anomaly explanation: {str(e)}")
            anomaly_reason = "Виявлено аномалію"

    # Update record with anomaly results
    record.is_anomaly = is_anomaly
    record.anomaly_score = anomaly_score
    record.anomaly_reason = anomaly_reason
    record.save()

    # === Load Forecasting ===
    # For the current record, predict what the next load will be
    predicted_next_load = forecast_model.predict(features)[0]

    # Get the thresholds from system settings
    settings = get_system_settings()
    min_threshold = settings.min_load_threshold
    max_threshold = settings.max_load_threshold

    # Log the prediction and thresholds to debug
    print(f"Predicted next load: {predicted_next_load}, Thresholds: Min={min_threshold}, Max={max_threshold}")

    # Explicitly check if the prediction is outside thresholds
    is_prediction_abnormal = (predicted_next_load < min_threshold or predicted_next_load > max_threshold)
    if is_prediction_abnormal:
        print(f"ABNORMAL PREDICTION DETECTED: {predicted_next_load} is outside range [{min_threshold}-{max_threshold}]")

    # Update the current record with the prediction for the NEXT load
    record.predicted_load = predicted_next_load
    record.save()

    print(f"Applied models to record {record.id}")
    print(f"Is anomaly: {is_anomaly}, Score: {anomaly_score}, Predicted next load: {predicted_next_load}")
    if anomaly_reason:
        print(f"Anomaly reason: {anomaly_reason}")

    return is_anomaly, anomaly_score, predicted_next_load


if __name__ == "__main__":
    # If record ID is provided as command line argument, use it
    record_id = sys.argv[1] if len(sys.argv) > 1 else None

    if record_id:
        apply_models_to_record(int(record_id))
    else:
        apply_models_to_record()