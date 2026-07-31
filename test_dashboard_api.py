import paramiko, json, os, sys

sys.stdout.reconfigure(encoding='utf-8')  # Allow emoji output

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root', password=os.environ['SSH_PASS'])

def run(script: str):
    stdin, stdout, stderr = ssh.exec_command("docker exec -i stratroom_api python3")
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    err = stderr.read().decode()
    if err.strip():
        print("STDERR:", err[:300])
    return out.strip()

# Login + fetch dashboard stats
script = """
import sys; sys.path.insert(0, '/app/backend')
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# Login first
login = client.post("/auth/login", json={"email": "admin@stratroom.com", "password": "changeme"})
if login.status_code != 200:
    print("LOGIN FAILED:", login.status_code, login.text)
    sys.exit(1)

token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# Fetch dashboard stats
resp = client.get("/dashboard/stats", headers=headers)
if resp.status_code != 200:
    print("DASHBOARD FAILED:", resp.status_code, resp.text)
    sys.exit(1)

data = resp.json()

# Print all card fields
print("=== CARD 1: KPI Health ===")
print(f"  on_track={data.get('kpi_health_on_track')}, at_risk={data.get('kpi_health_at_risk')}, critical={data.get('kpi_health_critical')}")
p = data.get('kpi_health_perspectives', {})
for name, pd in p.items():
    print(f"  Perspective '{name}': {pd}")

print()
print("=== CARD 2: Projects ===")
print(f"  total_initiatives={data.get('total_initiatives')}, projects_ontrack={data.get('projects_ontrack')}, projects_offtrack={data.get('projects_offtrack')}")
print(f"  portfolio_budget={data.get('portfolio_budget')}, avg_progress={data.get('avg_progress')}")

print()
print("=== CARD 3: Risk Register ===")
print(f"  total_risks={data.get('total_risks')}, critical={data.get('critical_risks')}, high={data.get('high_risks')}, medium={data.get('medium_risks')}, low={data.get('low_risks')}")
print(f"  avg_inherent_heat={data.get('avg_inherent_heat')}")

print()
print("=== CARD 4: Audit (FIXED - was showing P1 incidents) ===")
print(f"  audit_total={data.get('audit_total')}, audit_open={data.get('audit_open')}, audit_completion_pct={data.get('audit_completion_pct')}")

print()
print("=== CARD 5: Compliance ===")
print(f"  compliance_pct={data.get('compliance_pct')}, compliance_total={data.get('compliance_total')}, compliance_gaps={data.get('compliance_gaps')}")

print()
print("=== CARD 6: Tasks ===")
print(f"  total_tasks={data.get('total_tasks')}, overdue={data.get('overdue_tasks')}, completed={data.get('completed_tasks')}, completion_pct={data.get('task_completion_pct')}")

print()
print("=== CARD 7: Incidents ===")
print(f"  total_incidents={data.get('total_incidents')}, open={data.get('open_incidents')}, p1_open={data.get('p1_open')}")

print()
print("=== CARD 8: Budgets ===")
print(f"  budget_variance={data.get('budget_variance')}, budget_planned={data.get('budget_planned')}, utilisation={data.get('budget_utilisation')}%")

print()
print("=== CARD 9: Meetings (FIXED - was showing scorecards) ===")
print(f"  total_meetings={data.get('total_meetings')}")

print()
print("=== CARD 10: Strategic Health (FIXED - was duplicating compliance) ===")
print(f"  strategic_health={data.get('strategic_health')}, risk_resilience={data.get('risk_resilience')}, active_org_members={data.get('active_org_members')}")

print()
print("=== Backward Compat Fields ===")
print(f"  total_scorecards={data.get('total_scorecards')}, rbac_role={data.get('rbac_role')}")

# Verify
bugs = []
if data.get('audit_total') is None and data.get('audit_open') is None:
    bugs.append("Card 4 (Audit) has no data")
if data.get('total_meetings') is None:
    bugs.append("Card 9 (Meetings) has no data")
if data.get('strategic_health') is None:
    bugs.append("Card 10 (Strategic Health) has no data")

if bugs:
    print()
    print("BUGS FOUND:", bugs)
else:
    print()
    print("ALL CARDS HAVE VALID DATA")
"""

result = run(script)
print(result)
ssh.close()
