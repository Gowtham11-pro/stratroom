"""
Trains a small XGBoost regressor that predicts a residual risk score
from: inherent_likelihood, inherent_impact, days_open, vendor_concentration_pct.

Uses synthetic data so it runs immediately without needing a real dataset.
Replace `generate_synthetic_data()` with a real data-loading step later.
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error
from xgboost import XGBRegressor
import joblib
import os

FEATURES = ["inherent_likelihood", "inherent_impact", "days_open", "vendor_concentration_pct"]
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "risk_model.joblib")


def generate_synthetic_data(n=2000, seed=42):
    rng = np.random.default_rng(seed)
    inherent_likelihood = rng.integers(1, 6, n).astype(float)
    inherent_impact = rng.integers(1, 6, n).astype(float)
    days_open = rng.integers(0, 400, n).astype(float)
    vendor_concentration_pct = rng.uniform(0, 100, n)

    noise = rng.normal(0, 0.5, n)
    residual_score = (
        0.55 * (inherent_likelihood * inherent_impact)
        - 0.01 * np.minimum(days_open, 200)  # mitigations reduce risk over time, capped
        + 0.03 * vendor_concentration_pct
        + noise
    )
    residual_score = np.clip(residual_score, 1, 25)

    return pd.DataFrame(
        {
            "inherent_likelihood": inherent_likelihood,
            "inherent_impact": inherent_impact,
            "days_open": days_open,
            "vendor_concentration_pct": vendor_concentration_pct,
            "residual_score": residual_score,
        }
    )


def main():
    df = generate_synthetic_data()

    # Basic data validation before training
    assert df[FEATURES].isnull().sum().sum() == 0, "Found nulls in feature columns"
    assert (df["inherent_likelihood"].between(1, 5)).all(), "Likelihood out of range"
    assert (df["inherent_impact"].between(1, 5)).all(), "Impact out of range"

    X = df[FEATURES]
    y = df["residual_score"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                XGBRegressor(
                    n_estimators=200,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                ),
            ),
        ]
    )

    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    print(f"Validation MAE: {mae:.3f}")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()
