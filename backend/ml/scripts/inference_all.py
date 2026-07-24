import os
import joblib
import pandas as pd
import numpy as np

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

_models = {}


def _load(name):
    if name not in _models:
        path = os.path.join(MODELS_DIR, f"{name}_model.joblib")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}. Run train_all.py first.")
        _models[name] = joblib.load(path)
    return _models[name]


# ── Risk ──
def predict_risk(features: dict) -> float:
    model = _load("risk")
    row = pd.DataFrame([{
        "inherent_likelihood": features["inherent_likelihood"],
        "inherent_impact": features["inherent_impact"],
        "days_open": features.get("days_open", 0),
        "vendor_concentration_pct": features.get("vendor_concentration_pct", 0),
    }])
    return round(float(model.predict(row)[0]), 2)


# ── Revenue ──
def predict_revenue(features: dict) -> dict:
    model = _load("revenue")
    row = pd.DataFrame([{
        "quarter": features.get("quarter", 4),
        "pipeline_spend": features.get("pipeline_spend", 100),
        "dt_progress": features.get("dt_progress", 50),
        "market_index": features.get("market_index", 1.0),
        "headcount": features.get("headcount", 150),
        "churn_rate": features.get("churn_rate", 0.05),
    }])
    pred = float(model.predict(row)[0])
    return {
        "predicted_revenue_pct": round(pred, 1),
        "confidence_low": round(pred - 4, 1),
        "confidence_high": round(pred + 4, 1),
        "status": "above_target" if pred >= 85 else "on_track" if pred >= 75 else "below_target",
    }


# ── Attrition ──
def predict_attrition(features: dict) -> dict:
    model = _load("attrition")
    row = pd.DataFrame([{
        "tenure_years": features.get("tenure_years", 3),
        "engagement_score": features.get("engagement_score", 70),
        "salary_ratio": features.get("salary_ratio", 1.0),
        "manager_rating": features.get("manager_rating", 3.5),
        "promotion_years": features.get("promotion_years", 2),
        "workload_score": features.get("workload_score", 5),
        "market_demand": features.get("market_demand", 0.5),
    }])
    proba = model.predict_proba(row)[0]
    attrition_prob = round(float(proba[1]) * 100, 1)
    return {
        "attrition_probability": attrition_prob,
        "risk_level": "critical" if attrition_prob >= 60 else "high" if attrition_prob >= 40 else "medium" if attrition_prob >= 20 else "low",
    }


# ── Incidents ──
def predict_incidents(features: dict) -> dict:
    model = _load("incident")
    row = pd.DataFrame([{
        "active_risks": features.get("active_risks", 10),
        "vendor_count": features.get("vendor_count", 15),
        "dt_progress": features.get("dt_progress", 50),
        "security_score": features.get("security_score", 75),
        "patch_latency_days": features.get("patch_latency_days", 10),
        "region_count": features.get("region_count", 3),
    }])
    pred = float(model.predict(row)[0])
    return {
        "predicted_incidents": round(pred, 1),
        "risk_level": "critical" if pred >= 8 else "high" if pred >= 5 else "medium" if pred >= 3 else "low",
    }


# ── Budget Variance ──
def predict_budget_variance(features: dict) -> dict:
    model = _load("budget")
    row = pd.DataFrame([{
        "budget_planned": features.get("budget_planned", 100000),
        "year": features.get("year", 2026),
        "is_capital": features.get("is_capital", 0),
        "dept_risk_score": features.get("dept_risk_score", 0.3),
        "inflation_rate": features.get("inflation_rate", 0.04),
    }])
    pred = float(model.predict(row)[0])
    return {
        "predicted_variance_pct": round(pred, 1),
        "status": "over_budget" if pred > 5 else "on_track" if pred > -2 else "under_budget",
    }


# ── Composite Forecast (all models at once) ──
def run_full_forecast(org_data: dict) -> dict:
    results = {}
    try:
        risks = org_data.get("risks", [])
        if risks:
            top = max(risks, key=lambda r: (r.get("residual_likelihood", 3) or 3) * (r.get("residual_impact", 3) or 3))
            results["risk"] = predict_risk({
                "inherent_likelihood": top.get("inherent_likelihood", 3),
                "inherent_impact": top.get("inherent_impact", 3),
                "days_open": 90,
                "vendor_concentration_pct": 67,
            })
    except Exception as e:
        results["risk"] = {"error": str(e)}

    try:
        results["revenue"] = predict_revenue({
            "quarter": 4, "pipeline_spend": 120, "dt_progress": 38,
            "market_index": 0.95, "headcount": 150, "churn_rate": 0.08,
        })
    except Exception as e:
        results["revenue"] = {"error": str(e)}

    try:
        results["attrition"] = predict_attrition({
            "tenure_years": 2.5, "engagement_score": 63, "salary_ratio": 0.95,
            "manager_rating": 3.2, "promotion_years": 3, "workload_score": 7, "market_demand": 0.7,
        })
    except Exception as e:
        results["attrition"] = {"error": str(e)}

    try:
        incidents = org_data.get("incidents", [])
        active = [i for i in incidents if i.get("status") in ("open", "in_progress")]
        results["incidents"] = predict_incidents({
            "active_risks": len(org_data.get("risks", [])),
            "vendor_count": 12, "dt_progress": 38, "security_score": 78,
            "patch_latency_days": 14, "region_count": 4,
        })
    except Exception as e:
        results["incidents"] = {"error": str(e)}

    try:
        results["budget"] = predict_budget_variance({
            "budget_planned": 200000, "year": 2026, "is_capital": 0,
            "dept_risk_score": 0.4, "inflation_rate": 0.04,
        })
    except Exception as e:
        results["budget"] = {"error": str(e)}

    return results
