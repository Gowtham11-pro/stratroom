import os
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import get_db
from app.core.deps import require_role

router = APIRouter(prefix="/ml", tags=["ml"])


def _load_ml_models():
    _ml_scripts = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "scripts")
    if _ml_scripts not in sys.path:
        sys.path.insert(0, _ml_scripts)
    from inference_all import (
        predict_risk, predict_revenue, predict_attrition,
        predict_incidents, predict_budget_variance, run_full_forecast,
    )
    return predict_risk, predict_revenue, predict_attrition, predict_incidents, predict_budget_variance, run_full_forecast

ALLOWED_TABLES = {"risks", "incidents", "scorecards", "budget_lines", "tasks", "projects"}


class RiskPayload(BaseModel):
    inherent_likelihood: float
    inherent_impact: float
    days_open: float = 0
    vendor_concentration_pct: float = 0


class RevenuePayload(BaseModel):
    quarter: float = 4
    pipeline_spend: float = 100
    dt_progress: float = 50
    market_index: float = 1.0
    headcount: float = 150
    churn_rate: float = 0.05


class AttritionPayload(BaseModel):
    tenure_years: float = 3
    engagement_score: float = 70
    salary_ratio: float = 1.0
    manager_rating: float = 3.5
    promotion_years: float = 2
    workload_score: float = 5
    market_demand: float = 0.5


class IncidentPayload(BaseModel):
    active_risks: float = 10
    vendor_count: float = 15
    dt_progress: float = 50
    security_score: float = 75
    patch_latency_days: float = 10
    region_count: float = 3


class BudgetPayload(BaseModel):
    budget_planned: float = 100000
    year: float = 2026
    is_capital: float = 0
    dept_risk_score: float = 0.3
    inflation_rate: float = 0.04


@router.post("/risk")
async def ml_risk(payload: RiskPayload, ctx: dict = Depends(require_role("member"))):
    try:
        models = _load_ml_models()
        return {"prediction": models[0](payload.model_dump())}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Model not trained. Run train_all.py first.")
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")


@router.post("/revenue")
async def ml_revenue(payload: RevenuePayload, ctx: dict = Depends(require_role("member"))):
    try:
        models = _load_ml_models()
        return {"prediction": models[1](payload.model_dump())}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Model not trained. Run train_all.py first.")
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")


@router.post("/attrition")
async def ml_attrition(payload: AttritionPayload, ctx: dict = Depends(require_role("member"))):
    try:
        models = _load_ml_models()
        return {"prediction": models[2](payload.model_dump())}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Model not trained. Run train_all.py first.")
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")


@router.post("/incidents")
async def ml_incidents(payload: IncidentPayload, ctx: dict = Depends(require_role("member"))):
    try:
        models = _load_ml_models()
        return {"prediction": models[3](payload.model_dump())}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Model not trained. Run train_all.py first.")
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")


@router.post("/budget")
async def ml_budget(payload: BudgetPayload, ctx: dict = Depends(require_role("member"))):
    try:
        models = _load_ml_models()
        return {"prediction": models[4](payload.model_dump())}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Model not trained. Run train_all.py first.")
    except Exception:
        raise HTTPException(status_code=500, detail="Prediction failed")


@router.post("/forecast")
async def ml_full_forecast(
    db=Depends(get_db),
    ctx: dict = Depends(require_role("member")),
):
    try:
        user_id = ctx["user_id"]
        org_id = ctx["org_id"]

        org_data = {}
        table_map = {
            "risks": "risks",
            "incidents": "incidents",
            "scorecards": "scorecards",
            "budget_lines": "budgets",
            "tasks": "tasks",
            "projects": "projects",
        }
        for table, key in table_map.items():
            if table not in ALLOWED_TABLES:
                continue
            safe_table = table
            result = await db.execute(
                text(f"SELECT * FROM {safe_table} WHERE org_id = :oid LIMIT 50"),
                {"oid": org_id},
            )
            org_data[key] = [dict(r) for r in result.mappings().all()]

        models = _load_ml_models()
        return {"forecast": models[5](org_data)}
    except Exception:
        raise HTTPException(status_code=500, detail="Forecast failed")
