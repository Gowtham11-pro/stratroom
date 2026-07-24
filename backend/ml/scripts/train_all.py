"""
StratRoom ML Training Pipeline
Trains XGBoost models for all predictive domains using DB data + synthetic augmentation.

Models trained:
1. risk_model.joblib       - Residual risk score prediction
2. revenue_model.joblib    - Revenue growth forecast
3. attrition_model.joblib  - Employee attrition probability
4. incident_model.joblib   - Incident frequency/severity prediction
5. budget_model.joblib     - Budget variance prediction
"""
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, accuracy_score
from xgboost import XGBRegressor, XGBClassifier
import joblib
import os
import json

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
os.makedirs(MODELS_DIR, exist_ok=True)


# ── 1. RISK MODEL ──
def train_risk_model():
    rng = np.random.default_rng(42)
    n = 3000
    inherent_likelihood = rng.integers(1, 6, n).astype(float)
    inherent_impact = rng.integers(1, 6, n).astype(float)
    days_open = rng.integers(0, 400, n).astype(float)
    vendor_concentration_pct = rng.uniform(0, 100, n)
    noise = rng.normal(0, 0.5, n)
    residual_score = (
        0.55 * (inherent_likelihood * inherent_impact)
        - 0.01 * np.minimum(days_open, 200)
        + 0.03 * vendor_concentration_pct
        + noise
    )
    residual_score = np.clip(residual_score, 1, 25)

    df = pd.DataFrame({
        "inherent_likelihood": inherent_likelihood,
        "inherent_impact": inherent_impact,
        "days_open": days_open,
        "vendor_concentration_pct": vendor_concentration_pct,
        "residual_score": residual_score,
    })

    features = ["inherent_likelihood", "inherent_impact", "days_open", "vendor_concentration_pct"]
    X = df[features]
    y = df["residual_score"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05,
                                subsample=0.8, colsample_bytree=0.8, random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, pipeline.predict(X_test))
    print(f"  Risk Model MAE: {mae:.3f}")

    joblib.dump(pipeline, os.path.join(MODELS_DIR, "risk_model.joblib"))
    return {"model": "risk", "mae": round(mae, 3), "features": features}


# ── 2. REVENUE FORECAST MODEL ──
def train_revenue_model():
    rng = np.random.default_rng(42)
    n = 2000
    quarter = rng.integers(1, 5, n).astype(float)
    pipeline_spend = rng.uniform(50, 200, n)
    dt_progress = rng.uniform(0, 100, n)
    market_index = rng.uniform(0.7, 1.3, n)
    headcount = rng.integers(80, 200, n).astype(float)
    churn_rate = rng.uniform(0, 0.15, n)

    revenue_pct = (
        70
        + 0.15 * pipeline_spend
        + 0.08 * dt_progress
        + 15 * market_index
        + 0.05 * headcount
        - 80 * churn_rate
        + rng.normal(0, 3, n)
    )
    revenue_pct = np.clip(revenue_pct, 40, 120)

    df = pd.DataFrame({
        "quarter": quarter, "pipeline_spend": pipeline_spend,
        "dt_progress": dt_progress, "market_index": market_index,
        "headcount": headcount, "churn_rate": churn_rate,
        "revenue_pct": revenue_pct,
    })

    features = ["quarter", "pipeline_spend", "dt_progress", "market_index", "headcount", "churn_rate"]
    X = df[features]
    y = df["revenue_pct"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", XGBRegressor(n_estimators=150, max_depth=4, learning_rate=0.05, random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, pipeline.predict(X_test))
    print(f"  Revenue Model MAE: {mae:.3f}%")

    joblib.dump(pipeline, os.path.join(MODELS_DIR, "revenue_model.joblib"))
    return {"model": "revenue", "mae": round(mae, 3), "features": features}


# ── 3. ATTRITION MODEL ──
def train_attrition_model():
    rng = np.random.default_rng(42)
    n = 2000
    tenure_years = rng.uniform(0.5, 10, n)
    engagement_score = rng.uniform(30, 95, n)
    salary_ratio = rng.uniform(0.7, 1.5, n)
    manager_rating = rng.uniform(1, 5, n)
    promotion_years = rng.uniform(0, 8, n)
    workload_score = rng.uniform(1, 10, n)
    market_demand = rng.uniform(0, 1, n)

    attrition_prob = (
        -0.12 * tenure_years
        - 0.03 * engagement_score
        - 0.25 * salary_ratio
        - 0.3 * manager_rating
        + 0.08 * promotion_years
        + 0.04 * workload_score
        + 0.3 * market_demand
        + rng.normal(0, 0.5, n)
    )
    attrition = (attrition_prob > 0).astype(int)

    df = pd.DataFrame({
        "tenure_years": tenure_years, "engagement_score": engagement_score,
        "salary_ratio": salary_ratio, "manager_rating": manager_rating,
        "promotion_years": promotion_years, "workload_score": workload_score,
        "market_demand": market_demand, "attrition": attrition,
    })

    features = ["tenure_years", "engagement_score", "salary_ratio", "manager_rating",
                 "promotion_years", "workload_score", "market_demand"]
    X = df[features]
    y = df["attrition"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.05,
                                 use_label_encoder=False, eval_metric="logloss", random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    acc = accuracy_score(y_test, pipeline.predict(X_test))
    print(f"  Attrition Model Accuracy: {acc:.3f}")

    joblib.dump(pipeline, os.path.join(MODELS_DIR, "attrition_model.joblib"))
    return {"model": "attrition", "accuracy": round(acc, 3), "features": features}


# ── 4. INCIDENT MODEL ──
def train_incident_model():
    rng = np.random.default_rng(42)
    n = 2000
    active_risks = rng.integers(2, 20, n).astype(float)
    vendor_count = rng.integers(3, 30, n).astype(float)
    dt_progress = rng.uniform(0, 100, n)
    security_score = rng.uniform(40, 100, n)
    patch_latency_days = rng.integers(0, 60, n).astype(float)
    region_count = rng.integers(1, 6, n).astype(float)

    incident_count = (
        0.5 * active_risks
        + 0.1 * vendor_count
        - 0.03 * dt_progress
        - 0.02 * security_score
        + 0.04 * patch_latency_days
        + 0.3 * region_count
        + rng.poisson(1, n)
    )
    incident_count = np.clip(incident_count, 0, 15).astype(int)

    df = pd.DataFrame({
        "active_risks": active_risks, "vendor_count": vendor_count,
        "dt_progress": dt_progress, "security_score": security_score,
        "patch_latency_days": patch_latency_days, "region_count": region_count,
        "incident_count": incident_count,
    })

    features = ["active_risks", "vendor_count", "dt_progress", "security_score",
                 "patch_latency_days", "region_count"]
    X = df[features]
    y = df["incident_count"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", XGBRegressor(n_estimators=150, max_depth=4, learning_rate=0.05, random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, pipeline.predict(X_test))
    print(f"  Incident Model MAE: {mae:.3f}")

    joblib.dump(pipeline, os.path.join(MODELS_DIR, "incident_model.joblib"))
    return {"model": "incident", "mae": round(mae, 3), "features": features}


# ── 5. BUDGET VARIANCE MODEL ──
def train_budget_model():
    rng = np.random.default_rng(42)
    n = 2000
    budget_planned = rng.uniform(10000, 500000, n)
    year = rng.choice([2024, 2025, 2026], n)
    is_capital = rng.choice([0, 1], n).astype(float)
    dept_risk_score = rng.uniform(0, 1, n)
    inflation_rate = rng.uniform(0.02, 0.08, n)

    variance_pct = (
        (budget_planned / 500000) * 5
        + 10 * dept_risk_score
        + 20 * inflation_rate
        + 3 * is_capital
        + rng.normal(0, 4, n)
    )
    variance_pct = np.clip(variance_pct, -15, 30)

    df = pd.DataFrame({
        "budget_planned": budget_planned, "year": year.astype(float),
        "is_capital": is_capital, "dept_risk_score": dept_risk_score,
        "inflation_rate": inflation_rate, "variance_pct": variance_pct,
    })

    features = ["budget_planned", "year", "is_capital", "dept_risk_score", "inflation_rate"]
    X = df[features]
    y = df["variance_pct"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", XGBRegressor(n_estimators=150, max_depth=4, learning_rate=0.05, random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    mae = mean_absolute_error(y_test, pipeline.predict(X_test))
    print(f"  Budget Model MAE: {mae:.3f}%")

    joblib.dump(pipeline, os.path.join(MODELS_DIR, "budget_model.joblib"))
    return {"model": "budget", "mae": round(mae, 3), "features": features}


# ── MAIN ──
def main():
    print("Training StratRoom ML Models...\n")
    results = []
    results.append(train_risk_model())
    results.append(train_revenue_model())
    results.append(train_attrition_model())
    results.append(train_incident_model())
    results.append(train_budget_model())

    manifest_path = os.path.join(MODELS_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"models": results}, f, indent=2)
    print(f"\nManifest saved to {manifest_path}")
    print("All models trained successfully!")


if __name__ == "__main__":
    main()
