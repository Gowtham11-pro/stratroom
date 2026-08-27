"""
Scorecard Scoring Test Suite — evaluate_formula + weighted rollups

Self-contained offline tests (no database / Docker required). Covers:
  - Style A safe AST expression evaluation ("(Actual/Target)*100")
  - Style B aggregate formulas ("avg[KPI Name]") against a fake bridge
  - Injection resistance of the AST whitelist
  - Weight normalization (_effective_weight) and weighted rollups (_weighted_avg)

Usage:  python test_scorecard_scoring.py
"""
import asyncio
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

from app.routers.scorecards import (  # noqa: E402
    FormulaEvaluationError,
    _effective_weight,
    _eval_expression,
    _weighted_avg,
    evaluate_formula,
)

passed = 0
failed = 0
results = []


def run_test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        results.append(("PASS", name, ""))
    except Exception as e:
        failed += 1
        results.append(("FAIL", name, f"{type(e).__name__}: {e}"))


def run(coro):
    return asyncio.run(coro)


def expect_raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    except Exception as e:
        raise AssertionError(f"expected {exc_type.__name__}, got {type(e).__name__}: {e}")
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


# ── Fake DB for Style-B tests ─────────────────────────────────────
def make_fake_db(org_row=None, ref_rows=None, okd_rows=None):
    """Async callable mimicking bridge._mysql(sql, params) -> list[dict]."""
    calls = []

    async def fake_db(sql, params=(), one=False):
        calls.append((" ".join(sql.split()).lower(), tuple(params)))
        s = " ".join(sql.split()).lower()
        if s.startswith("select org_id from kpi"):
            return [org_row] if org_row else []
        if "lower(trim(kpi_name))" in s:
            return ref_rows or []
        if "from org_kpi_details" in s:
            return okd_rows or []
        return []

    fake_db.calls = calls
    return fake_db


# ── 1. Style A — real production reference values ─────────────────
def test_style_a_real_reference():
    # KPI "Revenue growth rate" (db_id 35983): actual=12.4 target=15 -> 82.67
    assert _eval_expression("(Actual/Target)*100", 12.4, 15) == 82.67

def test_style_a_case_insensitive_names():
    assert _eval_expression("(actual/TARGET)*100", 12.4, 15) == 82.67

def test_style_a_operator_coverage():
    assert _eval_expression("(Actual + Target) / 2", 12.4, 15) == 13.7
    assert _eval_expression("Actual**2 - Target", 12.4, 15) == 138.76
    assert _eval_expression("-Actual + Target", 12.4, 15) == 2.6
    assert _eval_expression("Target % Actual", 12.4, 15) == 2.6
    assert _eval_expression("Target // Actual", 12.4, 15) == 1.0
    assert _eval_expression("+Actual", 12.4, 15) == 12.4

def test_style_a_division_by_zero():
    expect_raises(FormulaEvaluationError, lambda: _eval_expression("Actual/Target", 5, 0))

def test_injection_blocked():
    for bad in [
        "__import__('os').getcwd()",
        "Actual.__class__",
        "[1, 2, 3]",
        "lambda: 1",
        "'hello'",
        "foo",
        "Actual if Target else 1",
        "(lambda a: a)(Actual)",
        "{1: 2}",
        "Actual; Target",
    ]:
        expect_raises(FormulaEvaluationError, lambda b=bad: _eval_expression(b, 12.4, 15))


# ── 2. evaluate_formula dispatch ──────────────────────────────────
def test_empty_formula_falls_back_to_default():
    assert run(evaluate_formula("", 12.4, 15)) == 82.67
    assert run(evaluate_formula(None, 12.4, 15)) == 82.67
    assert run(evaluate_formula("   ", 12.4, 15)) == 82.67

def test_default_zero_target_returns_zero():
    assert run(evaluate_formula(None, 5, 0)) == 0.0
    assert run(evaluate_formula("", "0", 0)) == 0.0

def test_style_a_via_evaluate_formula_no_db_calls():
    db = make_fake_db()
    result = run(evaluate_formula("(Actual/Target)*100", 12.4, 15, kpi_id=35983, db=db))
    assert result == 82.67
    assert db.calls == [], "Style A must not touch the database"

def test_style_b_avg_computes_mean_of_actuals():
    db = make_fake_db(
        org_row={"org_id": 4},
        ref_rows=[{"id": 999, "start_date": None, "end_date": None}],
        okd_rows=[{"mtd_actual": 10}, {"mtd_actual": 20}, {"mtd_actual": 30}],
    )
    result = run(evaluate_formula("avg[Revenue growth rate]", 0, 0, kpi_id=35983, db=db))
    assert result == 20.0

def test_style_b_unknown_kpi_name_raises():
    db = make_fake_db(org_row={"org_id": 4}, ref_rows=[], okd_rows=[{"mtd_actual": 1}])
    try:
        run(evaluate_formula("avg[Nonexistent KPI]", 0, 0, kpi_id=35983, db=db))
    except FormulaEvaluationError as e:
        assert "Nonexistent KPI" in str(e)
        return
    raise AssertionError("expected FormulaEvaluationError for unknown KPI name")

def test_style_b_no_actuals_raises():
    db = make_fake_db(
        org_row={"org_id": 4},
        ref_rows=[{"id": 999, "start_date": None, "end_date": None}],
        okd_rows=[],
    )
    expect_raises(FormulaEvaluationError,
                  lambda: run(evaluate_formula("avg[Revenue growth rate]", 0, 0, kpi_id=35983, db=db)))

def test_style_b_missing_caller_kpi_surfaces_error():
    # Caller KPI id unknown -> org lookup empty -> referenced name can't resolve
    db = make_fake_db(org_row=None, ref_rows=[], okd_rows=[])
    expect_raises(FormulaEvaluationError,
                  lambda: run(evaluate_formula("avg[Whatever]", 0, 0, kpi_id=0, db=db)))

def test_style_b_date_range_filter_applied():
    db = make_fake_db(
        org_row={"org_id": 4},
        ref_rows=[{"id": 999, "start_date": "2026-01-01", "end_date": "2026-12-31"}],
        okd_rows=[{"mtd_actual": 50}],
    )
    result = run(evaluate_formula("avg[Net revenue]", 0, 0, kpi_id=35983, db=db))
    assert result == 50.0
    actuals_sql, actuals_params = db.calls[-1]
    assert "real_date_from >=" in actuals_sql
    assert ("2026-01-01", "2026-12-31") == actuals_params[-2:]

def test_style_b_null_actuals_skipped():
    db = make_fake_db(
        org_row={"org_id": 4},
        ref_rows=[{"id": 999, "start_date": None, "end_date": None}],
        okd_rows=[{"mtd_actual": None}, {"mtd_actual": 8}, {"mtd_actual": None}],
    )
    assert run(evaluate_formula("avg[X]", 0, 0, kpi_id=1, db=db)) == 8.0


# ── 3. Weight semantics ───────────────────────────────────────────
def test_effective_weight_normalization():
    assert _effective_weight(None) == 1.0          # missing -> neutral 1.0
    assert _effective_weight("") == 1.0            # blank -> 1.0
    assert _effective_weight("   ") == 1.0         # whitespace -> 1.0
    assert _effective_weight("abc") == 1.0         # garbage -> 1.0
    assert _effective_weight("5") == 5.0           # numeric string honored
    assert _effective_weight(2.5) == 2.5
    assert _effective_weight(0) == 0.0             # explicit zero -> excluded
    assert _effective_weight(-3) == 0.0            # negative -> excluded

def test_weight_proof_unequal_weights_differ_from_simple_avg():
    scores_weights = [(80, 5), (90, 10), (70, 15)]
    weighted = _weighted_avg(scores_weights)
    simple = round(sum(s for s, _ in scores_weights) / len(scores_weights), 2)
    # Hand-calc: (80*5 + 90*10 + 70*15) / 30 = 2350 / 30 = 78.33
    assert weighted == 78.33
    assert simple == 80.0
    assert weighted != simple, "weights must change the result"

def test_equal_weights_reproduce_simple_average():
    pairs = [(80, 5), (90, 5), (70, 5)]
    assert _weighted_avg(pairs) == 80.0

def test_missing_weights_default_to_one():
    assert _weighted_avg([(80, None), (90, "")]) == 85.0

def test_explicit_zero_weight_excluded():
    assert _weighted_avg([(80, 0), (90, 10)]) == 90.0

def test_all_zero_total_weight_returns_none():
    assert _weighted_avg([(80, 0), (90, -1)]) is None

def test_empty_pairs_return_none():
    assert _weighted_avg([]) is None


# ── 4. Balanced scorecard — dual-scope behavior ───────────────────
def _install_balanced_fake_bridge(anchor=None, siblings=None, objectives=None,
                                  kpis=None, skl_kpis=None, okd=None):
    """Patch bridge._mysql with a dispatcher over the balanced-endpoint SQL shapes.

    Dispatch keys are normalized (whitespace-collapsed, lowercased) substrings:
      anchor     -> "from score_card where id = %s"
      siblings   -> "from score_card where page_id = %s"
      legacy wts -> "from score_card where org_id"
      objectives -> "from objectives where score_card_id in"
      gen kpis   -> "from kpi where objective_id in"
      skl kpis   -> "from kpi where kpi_id like 'skl-k%"
      actuals    -> "from org_kpi_details"
    """
    from app.services.java_bridge import bridge

    async def fake_db(sql, params=(), one=False):
        s = " ".join(sql.split()).lower()
        if s.startswith("select org_id from kpi"):
            return []
        if "from score_card where id = %s" in s:
            return [anchor] if anchor else []
        if "from score_card where page_id = %s" in s:
            return siblings or []
        if "from score_card where org_id" in s:
            return []
        if "from objectives where score_card_id in" in s:
            return objectives or []
        if "from kpi where objective_id in" in s:
            return kpis or []
        if "from kpi where kpi_id like 'skl-k%" in s:
            return skl_kpis or []
        if "from org_kpi_details" in s:
            return okd or []
        return []

    orig = bridge._mysql
    bridge._mysql = fake_db
    return orig, bridge


BOARD_SIBLINGS = [
    {"id": 3201, "score_name": None, "page_id": 3075,
     "score_card_val": '{"name": "Governance and Oversight", "perspectiveType": "Governance", "weight": "25.0", "description": "NA"}'},
    {"id": 3202, "score_name": "Board of Directors Scorecard", "page_id": 3075,
     "score_card_val": '{"name": "Financial Performance", "perspectiveType": "Financial Performance", "weight": "25.0", "description": "Board level KPIs"}'},
    {"id": 3203, "score_name": "Board of Directors Scorecard", "page_id": 3075,
     "score_card_val": '{"name": "ESG and Sustainability", "weight": "25.0"}'},
    {"id": 3204, "score_name": "Board of Directors Scorecard", "page_id": 3075,
     "score_card_val": '{"name": "Strategic Direction", "weight": "25.0"}'},
]
BOARD_OBJECTIVES = [
    {"id": 1, "score_card_id": 3201,
     "objectives_val": '{"objectiveId": "1", "name": "Board Effectiveness", "weight": "33.33"}'},
    {"id": 2, "score_card_id": 3201,
     "objectives_val": '{"objectiveId": "2", "name": "Risk Oversight", "weight": "33.33"}'},
]
BOARD_KPIS = [
    {"id": 34781, "kpi_id": "34781", "kpi_name": "Board Meeting Attendance Rate",
     "objective_id": 1,
     "kpi_value": '{"actual": "36.9", "target": "46.9", "weight": "50.0", '
                  '"thresholdFormula": "(Actual/Target)*100", "dataType": "Number", '
                  '"optioncolor1": "60", "optioncolor2": "80"}'},
    {"id": 34785, "kpi_id": "BOARD.1.2.1", "kpi_name": "Risk Committee Review Completion Rate",
     "objective_id": 2,
     "kpi_value": '{"actual": "90", "target": "100", "weight": "50.0", '
                  '"thresholdFormula": "(Actual/Target)*100"}'},
]


def _board_fixture():
    return dict(
        anchor=BOARD_SIBLINGS[1],
        siblings=BOARD_SIBLINGS,
        objectives=BOARD_OBJECTIVES,
        kpis=BOARD_KPIS,
    )


def test_balanced_generic_full_chain_board_routing():
    """FK chain resolves real data: perspectives from sibling blobs, KPIs routed
    via kpi.objective_id -> objectives.score_card_id."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(**_board_fixture())
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=3202, ctx={}))
    finally:
        bridge._mysql = orig

    assert data["scorecard_name"] == "Board of Directors Scorecard"
    assert data["scorecard_description"] == "Board level KPIs"
    assert "data_scope_warning" not in data
    # 4 sibling perspective rows, ordered by id ASC (empty-named 3201 first)
    assert len(data["perspectives"]) == 4
    names = [p["name"] for p in data["perspectives"]]
    assert names == ["Governance and Oversight", "Financial Performance",
                     "ESG and Sustainability", "Strategic Direction"]
    assert [p["id"] for p in data["perspectives"]] == ["SC-3201", "SC-3202", "SC-3203", "SC-3204"]
    assert [p["tab"] for p in data["perspectives"]] == [
        "governance_and_oversight", "financial_performance",
        "esg_and_sustainability", "strategic_direction"]
    # Objective names come from the objectives table blobs
    gov = data["perspectives"][0]
    assert [o["name"] for o in gov["objectives"]] == ["Board Effectiveness", "Risk Oversight"]
    # KPI 34781 routed into Governance (obj 1 -> score_card 3201), NOT Financial
    gov_kpi_ids = [k["db_id"] for o in gov["objectives"] for k in o["kpis"]]
    assert gov_kpi_ids == [34781, 34785]
    fin = data["perspectives"][1]
    assert all(len(o["kpis"]) == 0 for o in fin["objectives"]) or not fin["objectives"]
    # Formula engine scored the routed KPI: 36.9/46.9*100 = 78.68;
    # below its amber threshold (80) -> at-risk
    k = gov["objectives"][0]["kpis"][0]
    assert k["score"] == 78.68
    assert k["status"] == "at-risk"


def test_balanced_generic_board_scores_and_weights():
    """Weighted rollups flow through: KPI weights -> objective -> perspective -> overall."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(**_board_fixture())
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=3202, ctx={}))
    finally:
        bridge._mysql = orig

    gov = data["perspectives"][0]
    # Objectives at 33.33 each; scores 78.68 and 90 -> weighted avg
    assert gov["objectives"][0]["weight"] == 33.33
    assert gov["objectives"][0]["score"] == 78.68
    assert gov["objectives"][1]["score"] == 90.0
    # Perspective: (78.68*33.33 + 90*33.33)/66.66 = 84.34
    assert gov["score"] == 84.34
    assert gov["weight"] == 25.0
    # Empty perspectives score 0.0; overall over ALL four at 25 each:
    # (84.34 + 0 + 0 + 0) / 4 = 21.09
    assert data["overall_score"] == 21.09
    assert data["total_kpis"] == 2


GROUP_FINANCE_SIBLINGS = [
    {"id": 3210, "score_name": "Group Finance Scorecard", "page_id": 3077,
     "score_card_val": '{"name": "Financial Stewardship", "weight": "25.0", "description": "Finance corporate card"}'},
    {"id": 3211, "score_name": "Group Finance Scorecard", "page_id": 3077,
     "score_card_val": '{"name": "Budget Discipline", "weight": "25.0"}'},
    {"id": 3212, "score_name": "Group Finance Scorecard", "page_id": 3077,
     "score_card_val": '{"name": "Revenue Assurance", "weight": "50.0"}'},
]
GROUP_FINANCE_OBJECTIVES = [
    {"id": 101, "score_card_id": 3210,
     "objectives_val": '{"name": "Cash Flow", "weight": "50"}'},
    {"id": 102, "score_card_id": 3210,
     "objectives_val": '{"name": "Cost Control", "weight": "50"}'},
    {"id": 103, "score_card_id": 3211,
     "objectives_val": '{"name": "Budget Adherence", "weight": ""}'},
]
GROUP_FINANCE_KPIS = [
    {"id": 9001, "kpi_id": "FIN-K01", "kpi_name": "Operating Cash Ratio",
     "objective_id": 101,
     "kpi_value": '{"actual": "80", "target": "100", "weight": "60", '
                  '"thresholdFormula": "(Actual/Target)*100"}'},
    {"id": 9002, "kpi_id": "FIN-K02", "kpi_name": "Overhead Variance",
     "objective_id": 102,
     "kpi_value": '{"actual": "70", "target": "100", "weight": "40", '
                  '"thresholdFormula": "(Actual/Target)*100"}'},
    {"id": 9003, "kpi_id": "FIN-K03", "kpi_name": "Collection Effectiveness",
     "objective_id": 103,
     "kpi_value": '{"actual": "55", "target": "50", "weight": "10", '
                  '"thresholdFormula": "(Actual/Target)*100"}'},
    # Zero-weight KPI must be excluded from its parent rollup entirely
    {"id": 9004, "kpi_id": "FIN-K04", "kpi_name": "Unweighted Noise",
     "objective_id": 101,
     "kpi_value": '{"actual": "999", "target": "1", "weight": "0", '
                  '"thresholdFormula": "(Actual/Target)*100"}'},
]


def test_balanced_generic_group_finance_weighted_rollup():
    """Real business scorecard shape: unequal perspective weights (25/25/50),
    objective weights from the objectives table, zero-weight KPI excluded.
    Hand-computed expectations:
      P3210: obj CashFlow=[(80,w60),(99999,w0)->excl] = 80; obj CostControl = 70
             -> (80*50 + 70*50)/100 = 75.0
      P3211: obj BudgetAdherence(w "") = 110.0 -> 110.0
      P3212: no objectives -> 0.0
      overall = (75*25 + 110*25 + 0*50)/100 = 46.25
    """
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(
        anchor=GROUP_FINANCE_SIBLINGS[0], siblings=GROUP_FINANCE_SIBLINGS,
        objectives=GROUP_FINANCE_OBJECTIVES, kpis=GROUP_FINANCE_KPIS,
    )
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=3210, ctx={}))
    finally:
        bridge._mysql = orig

    assert data["scorecard_name"] == "Group Finance Scorecard"
    assert data["total_kpis"] == 4  # zero-weight KPI still listed, just not counted in scores
    p = data["perspectives"]
    assert [x["name"] for x in p] == ["Financial Stewardship", "Budget Discipline", "Revenue Assurance"]
    assert [x["weight"] for x in p] == [25.0, 25.0, 50.0]
    assert p[0]["score"] == 75.0
    assert p[0]["objectives"][0]["kpis"][0]["score"] == 80.0  # noise KPI did not drag it up
    assert p[1]["objectives"][0]["weight"] == 1.0  # blank objective weight -> neutral 1.0
    assert p[1]["score"] == 110.0
    assert p[2]["score"] == 0.0
    assert data["overall_score"] == 46.25


def test_balanced_generic_title_falls_back_to_named_sibling():
    """Anchor row 3201 carries an empty score_name; title must come from a
    named page_id sibling, not fall back to a placeholder."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(**_board_fixture())
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=3201, ctx={}))
    finally:
        bridge._mysql = orig
    assert data["scorecard_name"] == "Board of Directors Scorecard"
    assert len(data["perspectives"]) == 4


def test_balanced_generic_scorecard_not_found():
    """Unknown scorecard_id -> explicit error shape, never SKL data."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(anchor=None)
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=99999, ctx={}))
    finally:
        bridge._mysql = orig
    assert data.get("error") == "scorecard_id 99999 not found"
    assert data["perspectives"] == []
    assert data["overall_score"] == 0.0


def test_balanced_generic_perspective_filter_keeps_overall():
    """?perspective=<tab> filters display but NOT the overall score."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(**_board_fixture())
    try:
        unfiltered = run(sc_mod.get_balanced_scorecard(perspective=None, scorecard_id=3202, ctx={}))
        filtered = run(sc_mod.get_balanced_scorecard(
            perspective="governance_and_oversight", scorecard_id=3202, ctx={}))
    finally:
        bridge._mysql = orig
    assert unfiltered["overall_score"] == filtered["overall_score"] == 21.09
    assert filtered["total_perspectives"] == 1
    assert filtered["perspectives"][0]["tab"] == "governance_and_oversight"
    assert filtered["total_kpis"] == 2


SKL_FIXTURE_ROWS = [
    {"id": 35983, "kpi_name": "Revenue growth rate", "kpi_id": "SKL-K01",
     "objective_id": "SKL-O01", "kpi_value": '{"weight": "50"}',
     "start_date": None, "end_date": None},
    {"id": 35984, "kpi_name": "Absolute revenue", "kpi_id": "SKL-K02",
     "objective_id": "SKL-O01", "kpi_value": '{"weight": "50"}',
     "start_date": None, "end_date": None},
]


def test_balanced_default_skl_scope_unchanged():
    """No scorecard_id -> SKL reference dataset through the shared builder:
    reference perspectives, tab keys, and SKL_KPI_DEFAULTS actual/target."""
    from app.routers import scorecards as sc_mod

    orig, bridge = _install_balanced_fake_bridge(skl_kpis=SKL_FIXTURE_ROWS)
    try:
        data = run(sc_mod.get_balanced_scorecard(perspective=None, ctx={}))
    finally:
        bridge._mysql = orig

    assert data["scorecard_name"] == "SKL Group Scorecard"
    assert data["scorecard_description"].startswith("SKL Group")
    assert len(data["perspectives"]) == 6
    assert data["perspectives"][0]["name"] == "Financial Performance and Growth"
    assert data["perspectives"][0]["tab"] == "financial"
    assert data["perspectives"][0]["id"] == "SKL-P01"
    # Defaults applied (no okd rows): 12.4/15 -> 82.67 ; 1731260000/2000000000 -> 86.56
    kpis = data["perspectives"][0]["objectives"][0]["kpis"]
    assert [k["score"] for k in kpis] == [82.67, 86.56]
    assert kpis[0]["actual_raw"] == 12.4
    assert kpis[1]["currency"] == "USD"
    assert data["overall_score"] > 0


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        run_test(name, fn)

    print("=" * 64)
    print(f"Scorecard Scoring Test Suite — {passed} passed, {failed} failed")
    print("=" * 64)
    for status, name, err in results:
        marker = "[PASS]" if status == "PASS" else "[FAIL]"
        print(f"{marker} {name}" + (f"\n       {err}" if err else ""))
    print("=" * 64)
    sys.exit(1 if failed else 0)
