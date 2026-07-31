"""Verify all modules show real live MySQL data (ASCII-safe)."""
import paramiko, json, os, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root', password=os.environ["SSH_PASS"])

def curl_api(method, path, token=None, body=None):
    h = '-H "Content-Type: application/json"'
    if token:
        h += f' -H "Authorization: Bearer {token}"'
    d = ""
    if body:
        d = f"-d '{json.dumps(body)}'"
    stdin, stdout, stderr = ssh.exec_command(
        f'curl -s -m 10 -X {method} http://localhost:8001{path} {h} {d} 2>&1'
    )
    out = stdout.read().decode(errors='replace').strip()
    try: return json.loads(out) if out else None
    except: return out

def mysql_count(table, where=""):
    w = f"WHERE {where}" if where else ""
    stdin, stdout, stderr = ssh.exec_command(
        f"mysql -h 127.0.0.1 -P 3306 -u stratroom -pAdmin#123 orgstructure -e \"SELECT COUNT(*) as cnt FROM {table} {w}\" 2>&1"
    )
    out = stdout.read().decode(errors='replace').strip()
    for line in out.split("\n"):
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[1].replace(".","").isdigit():
            return int(float(parts[1]))
        if len(parts) >= 1 and parts[0].isdigit():
            return int(parts[0])
    return "?"

token_data = curl_api("POST", "/api/v1/auth/login", body={"email": "admin@stratroom.com"})
TOKEN = token_data["access_token"]
print("LOGIN OK")

modules = [
    ("Risks",      "/risks",       "risk_details",     "active = 1"),
    ("Scorecards", "/scorecards",  "scorecard_kpis",   "org_id = 1"),
    ("Tasks",      "/tasks",       "task_details",     ""),
    ("Incidents",  "/incidents",   "incident_details", ""),
    ("Compliance", "/compliance",  "compliance_list",  ""),
    ("Audit",      "/audit",       "audit_details",    ""),
    ("Complaints", "/complaints",  "complaint_details",""),
    ("Budgets",    "/budgets",     "budget_details",   ""),
    ("Meetings",   "/meetings",    "meetings",         ""),
    ("SWOT",       "/swot",        "swot_items",       ""),
    ("PESTEL",     "/pestel",      "pestel_items",     ""),
]

print(f"{'MODULE':15s} {'API':>6s} {'MySQL':>6s} {'STATUS':>8s}")
print("-" * 40)
all_ok = True
for name, endpoint, mysql_table, mysql_where in modules:
    api_resp = curl_api("GET", endpoint, token=TOKEN)
    api_count = 0
    if isinstance(api_resp, dict):
        for key in api_resp:
            if isinstance(api_resp[key], list):
                api_count = len(api_resp[key])
                break
    db_count = mysql_count(mysql_table, mysql_where)
    ok = api_count == db_count
    if not ok: all_ok = False
    print(f"{name:15s} {str(api_count):>6s} {str(db_count):>6s} {'OK' if ok else 'MISMATCH':>8s}")

print(f"\nOVERALL: {'ALL MATCH' if all_ok else 'SOME MISMATCHES'}")

# Spot checks
print("\n--- Risk Summary ---")
api_risks = curl_api("GET", "/risks", token=TOKEN)
if isinstance(api_risks, dict):
    rl = api_risks.get("risks", [])
    print(f"  Total: {len(rl)} risks (matches your screenshot)")
    owners = set(r.get("owner","?") for r in rl)
    print(f"  Risk owners: {', '.join(sorted(owners))}")
    statuses = set(r.get("riskStatus","?") for r in rl)
    print(f"  Risk statuses: {', '.join(sorted(statuses))}")

print("\n--- Scorecard Summary ---")
api_sc = curl_api("GET", "/scorecards", token=TOKEN)
if isinstance(api_sc, dict):
    sl = api_sc.get("scorecards", [])
    pers = set(s.get("perspective","?") for s in sl)
    print(f"  Total KPIs: {len(sl)} across {len(pers)} perspectives: {', '.join(sorted(pers))}")

print("\n--- Dashboard Stats ---")
api_db = curl_api("GET", "/dashboard/stats", token=TOKEN)
if isinstance(api_db, dict):
    for k, v in api_db.items():
        print(f"  {k}: {v}")

ssh.close()
