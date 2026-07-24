"""Centralized registry for AI-callable tools.

Each tool represents an ML prediction model or utility that agents can invoke.
The registry maps tool names to metadata and callables, enabling agents to
discover and use tools without hard-coding imports.
"""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., Any]
    input_schema: dict = field(default_factory=dict)
    category: str = "ml_prediction"


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "category": t.category,
            }
            for t in self._tools.values()
        ]

    def call(self, name: str, **kwargs) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return tool.fn(**kwargs)


# Module-level singleton
registry = ToolRegistry()


def _register_ml_tools():
    import sys
    import os
    _ml_scripts = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ml", "scripts"))
    if _ml_scripts not in sys.path:
        sys.path.insert(0, _ml_scripts)

    from inference_all import (
        predict_risk,
        predict_revenue,
        predict_attrition,
        predict_incidents,
        predict_budget_variance,
        run_full_forecast,
    )

    registry.register(Tool(
        name="predict_risk",
        description="Predict residual risk score for a given risk item.",
        fn=predict_risk,
        input_schema={
            "type": "object",
            "properties": {
                "inherent_likelihood": {"type": "integer"},
                "inherent_impact": {"type": "integer"},
                "days_open": {"type": "integer", "default": 0},
                "vendor_concentration_pct": {"type": "number", "default": 0},
            },
            "required": ["inherent_likelihood", "inherent_impact"],
        },
        category="ml_prediction",
    ))

    registry.register(Tool(
        name="predict_revenue",
        description="Predict revenue attainment percentage for the next quarter.",
        fn=predict_revenue,
        input_schema={
            "type": "object",
            "properties": {
                "quarter": {"type": "integer", "default": 4},
                "pipeline_spend": {"type": "number", "default": 100},
                "dt_progress": {"type": "number", "default": 50},
                "market_index": {"type": "number", "default": 1.0},
                "headcount": {"type": "integer", "default": 150},
                "churn_rate": {"type": "number", "default": 0.05},
            },
        },
        category="ml_prediction",
    ))

    registry.register(Tool(
        name="predict_attrition",
        description="Predict employee attrition probability.",
        fn=predict_attrition,
        input_schema={
            "type": "object",
            "properties": {
                "tenure_years": {"type": "number", "default": 3},
                "engagement_score": {"type": "number", "default": 70},
                "salary_ratio": {"type": "number", "default": 1.0},
                "manager_rating": {"type": "number", "default": 3.5},
                "promotion_years": {"type": "number", "default": 2},
                "workload_score": {"type": "number", "default": 5},
                "market_demand": {"type": "number", "default": 0.5},
            },
        },
        category="ml_prediction",
    ))

    registry.register(Tool(
        name="predict_incidents",
        description="Predict number of security incidents in the next period.",
        fn=predict_incidents,
        input_schema={
            "type": "object",
            "properties": {
                "active_risks": {"type": "integer", "default": 10},
                "vendor_count": {"type": "integer", "default": 15},
                "dt_progress": {"type": "number", "default": 50},
                "security_score": {"type": "number", "default": 75},
                "patch_latency_days": {"type": "integer", "default": 10},
                "region_count": {"type": "integer", "default": 3},
            },
        },
        category="ml_prediction",
    ))

    registry.register(Tool(
        name="predict_budget_variance",
        description="Predict budget variance percentage.",
        fn=predict_budget_variance,
        input_schema={
            "type": "object",
            "properties": {
                "budget_planned": {"type": "number", "default": 100000},
                "year": {"type": "integer", "default": 2026},
                "is_capital": {"type": "integer", "default": 0},
                "dept_risk_score": {"type": "number", "default": 0.3},
                "inflation_rate": {"type": "number", "default": 0.04},
            },
        },
        category="ml_prediction",
    ))

    registry.register(Tool(
        name="run_full_forecast",
        description="Run all ML models at once for a composite forecast.",
        fn=run_full_forecast,
        input_schema={
            "type": "object",
            "properties": {
                "risks": {"type": "array", "items": {"type": "object"}},
                "incidents": {"type": "array", "items": {"type": "object"}},
            },
        },
        category="ml_prediction",
    ))


_register_ml_tools()
