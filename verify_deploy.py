"""Post-deploy acceptance checks for the generic scorecard UI integration.

Run AFTER deploying backend/app/routers/scorecards.py + frontend/31may_index.html:

    python verify_deploy.py
    python verify_deploy.py http://10.0.0.5:8088   # custom base URL
"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://103.191.132.36:8088"
passed, failed = 0, 0


def call(path, token=None):
    req = urllib.request.Request(BASE.rstrip("/") + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def login():
    req = urllib.request.Request(
        BASE.rstrip("/") + "/api/v1/auth/login",
        data=json.dumps({"email": "admin@stratroom.com"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())["access_token"]


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def get_persp_ids(d):
    return [p["tab"] for p in d["perspectives"]]


print(f"Base URL: {BASE}")
token = login()
print("login OK")

print("\n== 1. Default SKL scorecard ==")
d = call("/scorecards/balanced", token)
check("name == SKL Group Scorecard", d.get("scorecard_name") == "SKL Group Scorecard", d.get("scorecard_name"))
check("overall_score == 102.1", abs(d.get("overall_score", -1) - 102.1) < 0.05, d.get("overall_score"))
check("6 perspectives", d.get("total_perspectives") == 6, d.get("total_perspectives"))
check("54 KPIs", d.get("total_kpis") == 54, d.get("total_kpis"))
check("SKL tab keys intact", set(get_persp_ids(d)) == {"financial", "customer", "ops", "projects", "esg", "people"}, get_persp_ids(d))

print("\n== 2. Board (3202) ==")
d = call("/scorecards/balanced?scorecard_id=3202", token)
tabs = get_persp_ids(d)
check("4 perspectives", d.get("total_perspectives") == 4, d.get("total_perspectives"))
check("26 KPIs", d.get("total_kpis") == 26, d.get("total_kpis"))
check(
    "slug tabs correct",
    set(tabs) == {"governance_and_oversight", "financial_performance", "esg_and_sustainability", "strategic_direction"},
    tabs,
)
check("perspective weights 25.0", all(p["weight"] == 25.0 for p in d["perspectives"]), [p["weight"] for p in d["perspectives"]])
objs = [o for p in d["perspectives"] for o in p["objectives"]]
check("objective weights 33.33", objs and all(abs(o["weight"] - 33.33) < 0.01 for o in objs), sorted({o["weight"] for o in objs}))
scores = [k["score"] for p in d["perspectives"] for o in p["objectives"] for k in o["kpis"]]
check("zero scores present & finite", any(s == 0.0 for s in scores) and all(isinstance(s, float) for s in scores))
statuses = {k["status"] for p in d["perspectives"] for o in p["objectives"] for k in o["kpis"]}
check("0-scores map to critical status", "critical" in statuses, statuses)

print("\n== 3. Group Finance (3210) ==")
d = call("/scorecards/balanced?scorecard_id=3210", token)
check("3 perspectives", d.get("total_perspectives") == 3, d.get("total_perspectives"))
check("19 KPIs", d.get("total_kpis") == 19, d.get("total_kpis"))
check(
    "slug tabs correct",
    set(get_persp_ids(d)) == {"financial_performance", "liquidity_and_capital", "financial_reporting"},
    get_persp_ids(d),
)
check("weights 33.33", all(p["weight"] == 33.33 for p in d["perspectives"]), [p["weight"] for p in d["perspectives"]])
all_scores = [k["score"] for p in d["perspectives"] for o in p["objectives"] for k in o["kpis"]]
check("all actuals missing -> 0.0 scores", len(all_scores) == 19 and all(s == 0.0 for s in all_scores))

print("\n== 4. /scorecards/list (dropdown source) ==")
d = call("/scorecards/list", token)
items = d.get("scorecards", [])
check("list non-empty", len(items) > 0, f"{len(items)} items")
names = [i.get("name") or "" for i in items]
check("Board entry present", any("Board" in n for n in names), names[:6])
check("Group Finance entry present", any("Finance" in n or "finance" in n for n in names), names[:6])
check("entries carry id+name+perspective_count", all(i.get("id") and i.get("name") and "perspective_count" in i for i in items))

anchor_board = next((i["id"] for i in items if "Board" in (i.get("name") or "")), None)
if anchor_board:
    d = call(f"/scorecards/balanced?scorecard_id={anchor_board}", token)
    check(f"MIN(id) anchor {anchor_board} resolves Board card", d.get("scorecard_name") == "Board of Directors Scorecard", d.get("scorecard_name"))

print("\n================================")
print(f"RESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
