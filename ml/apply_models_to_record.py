# ml/apply_models_to_record.py

import os
import django
import pandas as pd
import joblib
import sys
import numpy as np
from pathlib import Path

# Get the absolute path to the project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Diploma.settings')
django.setup()

from monitoring.models import EnergyLog, SystemSettings


def get_anomaly_explanation(features, feature_scores):
    """
    Generate a human-readable explanation for an anomaly

    Args:
        features: DataFrame with feature values
        feature_scores: Dictionary of feature contribution scores

    Returns:
        str: Explanation as an array of top contributing parameters
    """
    # Get the most suspicious features (highest absolute score)
    suspicious_features = sorted(feature_scores.items(), key=lambda x: abs(x[1]), reverse=True)

    explanation = ''

    # Map feature names to Ukrainian names
    feature_name_map = {
        'ac_output_voltage': 'Змінна напруга',
        'dc_battery_voltage': 'Постійна напруга',
        'dc_battery_current': 'Постійний струм',
        'load_power': 'Навантаження',
        'temperature': 'Температура'
    }

    # Get an explanation for a random feature if there is more than 1
    import random
    if suspicious_features:
        feature, score = random.choice(suspicious_features) if len(suspicious_features) > 1 else suspicious_features[0]
        explanation = feature_name_map.get(feature, feature)

    return explanation


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


def check_prediction_thresholds(predicted_current, predicted_voltage):
    """
    Check if predicted values are within normal ranges

    Args:
        predicted_current: Predicted battery current value
        predicted_voltage: Predicted AC output voltage value

    Returns:
        bool: True if predictions are abnormal
    """
    # Normal ranges for parameters
    current_min, current_max = 5, 15  # A
    voltage_min, voltage_max = 220, 240  # V

    # Check if predictions are outside normal ranges
    if predicted_current < current_min or predicted_current > current_max:
        return True
    if predicted_voltage < voltage_min or predicted_voltage > voltage_max:
        return True

    return False


def apply_models_to_record(record_id=None, force_abnormal_prediction=False, force_anomaly=False):
    """
    Apply ML models to a single energy record or the latest if no ID provided
    With enhanced anomaly explanation

    Args:
        record_id: ID of record to analyze, or None for latest
        force_abnormal_prediction: If True, force abnormal prediction values regardless of model output
        force_anomaly: If True, force this record to be marked as an anomaly

    Returns:
        tuple: (is_anomaly, anomaly_score, predicted_current, predicted_voltage)
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
    if force_anomaly:
        # Force this record to be an anomaly
        is_anomaly = True
        anomaly_score = -0.95  # Strongly anomalous score
        print(f"Forced anomaly for record {record.id}")

        # Generate a reason for the forced anomaly
        feature_name_map = {
            'ac_output_voltage': 'Змінна напруга',
            'dc_battery_voltage': 'Постійна напруга',
            'dc_battery_current': 'Постійний струм',
            'load_power': 'Навантаження',
            'temperature': 'Температура'
        }
        # Choose a random feature to blame
        import random
        feature = random.choice(list(feature_name_map.keys()))
        value = features[feature].iloc[0]
        anomaly_reasons = f"{feature_name_map[feature]}"
    else:
        # Use the model to detect anomalies
        anomaly_pred = anomaly_model.predict(features)[0]
        anomaly_score = anomaly_model.decision_function(features)[0]
        is_anomaly = anomaly_pred == -1

        # Get explanation if it's an anomaly
        anomaly_reasons = []
        if is_anomaly:
            try:
                # Calculate feature scores
                feature_scores = calculate_feature_scores(anomaly_model, features)

                # Get human-readable explanation
                anomaly_reasons = get_anomaly_explanation(features, feature_scores)
            except Exception as e:
                print(f"Error generating anomaly explanation: {str(e)}")
                anomaly_reasons = ["Виявлено аномалію"]

    # === Prediction ===
    # If force_abnormal_prediction is True, set extreme values
    # Otherwise, use the model to predict values
    if force_abnormal_prediction:
        # Set extreme values that are guaranteed to be outside normal ranges
        predicted_current = np.random.choice([4.0, 16.0])  # Outside 5-15A normal range
        predicted_voltage = np.random.choice([215.0, 245.0])  # Outside 220-240V normal range

        # Force this to be true because we're explicitly setting abnormal values
        is_abnormal_prediction = True

        print(f"Forced abnormal prediction: current={predicted_current}A, voltage={predicted_voltage}V")
    else:
        # Normal case: use the model to predict
        prediction = forecast_model.predict(features)[0]
        predicted_current, predicted_voltage = prediction[0], prediction[1]

        # Check if predictions are within normal ranges
        is_abnormal_prediction = check_prediction_thresholds(predicted_current, predicted_voltage)

    # Update record with anomaly results
    # When forcing abnormal predictions, make sure is_anomaly=False (unless we're also forcing anomalies)
    record.is_anomaly = is_anomaly if not force_abnormal_prediction or force_anomaly else False
    record.anomaly_score = anomaly_score
    record.anomaly_reason = str(anomaly_reasons) if anomaly_reasons else None

    # Update record with prediction results
    record.predicted_current = predicted_current
    record.predicted_voltage = predicted_voltage
    record.is_abnormal_prediction = is_abnormal_prediction
    record.save()

    # After applying models and saving the record, check if we need to create a backup
    if is_anomaly or is_abnormal_prediction:
        try:
            from ml.backup_database import check_and_backup_if_needed
            backup_performed = check_and_backup_if_needed(record.id)
            if backup_performed:
                print(
                    f"Backup created for record {record.id} due to {'anomaly' if is_anomaly else 'abnormal prediction'}")

                # Update the record to indicate backup was triggered
                record.backup_triggered = True
                record.save()
            else:
                print(f"Backup not created for record {record.id} despite meeting conditions")
        except Exception as e:
            print(f"Error triggering backup for record {record.id}: {e}")

    print(f"Applied models to record {record.id}")
    print(f"Is anomaly: {record.is_anomaly}, Score: {anomaly_score}")
    if anomaly_reasons:
        print(f"Anomaly reasons: {anomaly_reasons}")
    print(f"Predicted NEXT current: {predicted_current:.2f}A, Predicted NEXT voltage: {predicted_voltage:.2f}V")
    print(f"Is abnormal prediction: {is_abnormal_prediction}")
    print(f"Backup triggered: {record.backup_triggered}")

    return record.is_anomaly, anomaly_score, predicted_current, predicted_voltage


if __name__ == "__main__":
    # If record ID is provided as command line argument, use it
    record_id = sys.argv[1] if len(sys.argv) > 1 else None

    # Check for options
    force_abnormal = False
    force_anomaly = False

    if len(sys.argv) > 2:
        if 'abnormal' in sys.argv[2].lower():
            force_abnormal = True
        if 'anomaly' in sys.argv[2].lower():
            force_anomaly = True

    if record_id:
        apply_models_to_record(int(record_id), force_abnormal_prediction=force_abnormal, force_anomaly=force_anomaly)
    else:
        apply_models_to_record(force_abnormal_prediction=force_abnormal, force_anomaly=force_anomaly)
