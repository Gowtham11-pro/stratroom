import os
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.deps import require_role

_ml_scripts = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "scripts")
if _ml_scripts not in sys.path:
    sys.path.insert(0, _ml_scripts)
from inference import predict_risk_score  # noqa: E402

router = APIRouter(prefix="/predict", tags=["ml"])


class RiskFeatures(BaseModel):
    inherent_likelihood: float
    inherent_impact: float
    days_open: float
    vendor_concentration_pct: float


@router.post("/risk-score")
async def risk_score(payload: RiskFeatures, ctx: dict = Depends(require_role("member"))):
    try:
        score = predict_risk_score(payload.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="ML model not trained yet. Run train.py first.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"predicted_residual_score": score}
