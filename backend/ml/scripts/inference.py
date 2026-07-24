import os
import joblib
import pandas as pd

# Features expected by the inference API (sent from predict.py)
API_FEATURES = ["inherent_likelihood", "inherent_impact", "days_open", "vendor_concentration_pct"]

# Full feature set that the trained model may expect (12 features)
ALL_KNOWN_FEATURES = [
    "inherent_likelihood", "inherent_impact", "days_open", "vendor_concentration_pct",
    "current_controls", "historical_incidents", "regulatory_exposure",
    "org_risk_tolerance", "mitigation_effectiveness", "time_sensitivity",
    "residual_likelihood", "residual_impact",
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "risk_model.joblib")

_model = None
_model_features = None


def _load_model():
    global _model, _model_features
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"No trained model at {MODEL_PATH}. Run `python train.py` inside the ml/scripts folder first."
            )
        _model = joblib.load(MODEL_PATH)
        # Detect feature count from the model's booster or pipeline
        try:
            _model_features = _model.n_features_in_
        except AttributeError:
            # Pipeline — check the last step
            try:
                _model_features = _model.steps[-1][1].n_features_in_
            except AttributeError:
                _model_features = len(API_FEATURES)
    return _model


def predict_risk_score(features: dict) -> float:
    for key in API_FEATURES:
        if key not in features:
            raise ValueError(f"Missing required feature: {key}")

    model = _load_model()

    # Build input with all features, filling unknown ones with 0
    row_dict = {k: features[k] for k in API_FEATURES}
    if _model_features and _model_features > len(API_FEATURES):
        for feat in ALL_KNOWN_FEATURES:
            if feat not in row_dict:
                row_dict[feat] = 0.0

    row = pd.DataFrame([row_dict])
    prediction = model.predict(row)[0]
    return round(float(prediction), 2)
