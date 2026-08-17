"""
Phase 2 RBAC â€” Local HTTP Verification

Verifies the three Manager-specified access scenarios end-to-end at the HTTP
layer (real FastAPI app + real auth + real routers):

  Scenario A. Lower-level member -> peer member's TASK    -> 403 "This task is not
             assigned to you; it is assigned to a different user."
  Scenario B. Lower-level member -> Manager's TASK/data  -> 403 "You don't have
             permission to access this data"
  Scenario C. Manager -> direct subordinate              -> 200 allowed

Two run modes:

  --offline   (default)  Runs the real app through Starlette TestClient with a
                         faked MySQL bridge. No database / server / Docker needed.
  --live      Requires a running FastAPI server + MySQL. Bootstraps the three
             users + hierarchy + records in MySQL, then verifies over HTTP.

Bootstrap accounts (offline and live modes use the same credentials):

  email / password / role / emp_id / parent_emp_id
  admin@rbac.local      / Passw0rd! / admin   / 900 / None
  manager@rbac.local    / Passw0rd! / manager / 901 / 900
  member@rbac.local     / Passw0rd! / member  / 902 / 901
  peer@rbac.local       / Passw0rd! / member  / 903 / 901   (a peer of member)

Usage:
  python test_rbac_local.py                    # offline
  python test_rbac_local.py --live             # live, MYSQL_*/BASE_URL env
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Bootstrap account + hierarchy definition
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ORG_ID = 1
DEPT_MANAGEMENT = 10
PASSWORD = "Passw0rd!"

ACCOUNTS = [
    # emp_id, parent_emp_id, dept_id, first, last, title, email, role
    (900, None, DEPT_MANAGEMENT, "Admin", "User", "Super User", "admin@rbac.local", "admin"),
    (901, 900, DEPT_MANAGEMENT, "Manager", "User", "Manager", "manager@rbac.local", "manager"),
    (902, 901, DEPT_MANAGEMENT, "Member", "User", "Analyst", "member@rbac.local", "member"),
    (903, 901, DEPT_MANAGEMENT, "Peer", "User", "Analyst", "peer@rbac.local", "member"),
]
EMP_BY_EMAIL = {email: emp_id for emp_id, _, _, _, _, _, email, _ in ACCOUNTS}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Offline in-memory "database"
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class FakeDB:
    """In-memory tables shaped like the MySQL schema the bridge reads."""

    def __init__(self):
        self.users = {}       # email -> {"hashed_password", "role", "org_id"}
        self.employees = []   # rows for /employeeDetailsList + hierarchy
        self.user_roles = {}  # email -> {"emp_id","designation","role","department","location","status"}
        self.tasks = {}       # id -> {"id","owner","assigned_user_id","task_value","title","status","priority"}
        self.risks = {}       # id -> {"id","owner","risk_name","status"}
        self.scorecards = {}  # id -> {"id","owner","assigned_user_id","perspective","kpi_name","target","actual","status"}

    # â”€â”€ seeding â”€â”€
    def seed_accounts(self):
        from app.core.security import hash_password

        for emp_id, parent, dept, first, last, title, email, role in ACCOUNTS:
            self.users[email.lower()] = {
                "hashed_password": hash_password(PASSWORD),
                "role": role,
                "org_id": ORG_ID,
            }
            self.employees.append({
                "emp_id": emp_id,
                "org_id": ORG_ID,
                "dept_id": dept,
                "first_name": first,
                "last_name": last,
                "title": title,
                "email_address": email,
                "status": "Active",
                "department": "Management",
                "location": "",
                "parent_emp_id": parent,
            })
            self.user_roles[email.lower()] = {
                "emp_id": emp_id,
                "designation": title,
                "role": role,
                "login_status": "Active",
                "department": "Management",
                "location": "",
                "status": "Active",
            }

    def seed_records(self):
        # Task owned by peer (903)  -> Scenario A target
        self.tasks[5001] = {"id": 5001, "owner": 903, "assigned_user_id": 903,
                            "title": "Peer task", "status": "pending", "priority": "Medium"}
        # Task owned by manager (901) -> Scenario B target
        self.tasks[5002] = {"id": 5002, "owner": 901, "assigned_user_id": 901,
                            "title": "Manager task", "status": "in_progress", "priority": "High"}
        # Task owned by member (902) -> Scenario C target
        self.tasks[5003] = {"id": 5003, "owner": 902, "assigned_user_id": 902,
                            "title": "Member task", "status": "pending", "priority": "Medium"}
        self.risks[6001] = {"id": 6001, "owner": 901, "risk_name": "Manager risk", "status": "open"}
        self.risks[6002] = {"id": 6002, "owner": 902, "risk_name": "Member risk", "status": "open"}
        self.scorecards[7001] = {"id": 7001, "owner": 901, "assigned_user_id": 901,
                                 "perspective": "Financial", "kpi_name": "Revenue", "target": 100, "actual": 80, "status": "on-track"}
        self.scorecards[7002] = {"id": 7002, "owner": 902, "assigned_user_id": 902,
                                 "perspective": "Customer", "kpi_name": "NPS", "target": 50, "actual": 45, "status": "at-risk"}

    def employee_by_email(self, email: str):
        for row in self.employees:
            if row["email_address"].lower() == email.lower():
                return row
        return None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Faked bridge (offline mode)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def install_fake_bridge(db: FakeDB):
    """Monkeypatch the singleton bridge so auth + routers + rbac read FakeDB.

    Dispatches on the same URL patterns / SQL shapes the real bridge uses.
    """
    from app.services import java_bridge

    bridge = java_bridge.bridge
    db_seeded = [db]

    async def fake_get(service, path, **kwargs):
        params = kwargs.get("params") or {}
        email = params.get("email")
        # â”€â”€ identity endpoints used by utils.resolve_* â”€â”€
        if path == "/findByUser":
            emp = db_seeded[0].employee_by_email(email or "")
            if emp:
                if service == bridge.user_service:
                    ur = db_seeded[0].user_roles.get((email or "").lower(), {})
                    return {
                        "empId": emp["emp_id"],
                        "designation": ur.get("designation", emp["title"]),
                        "role": ur.get("role", "member"),
                        "loginStatus": "Active",
                        "department": emp.get("department"),
                        "location": emp.get("location"),
                        "status": emp.get("status"),
                    }
                return [{
                    "emp_id": emp["emp_id"],
                    "org_id": emp["org_id"],
                    "first_name": emp["first_name"],
                    "last_name": emp["last_name"],
                    "title": emp["title"],
                    "email_address": emp["email_address"],
                    "status": emp["status"],
                    "department": emp.get("department"),
                    "location": emp.get("location"),
                }]
            return []
        if path == "/employeeDetailsList":
            return list(db_seeded[0].employees)
        # â”€â”€ task endpoints â”€â”€
        if path.startswith("/retrieveTaskList/"):
            return list(db_seeded[0].tasks.values())
        if path.startswith("/task/"):
            task_id = int(path.rsplit("/", 1)[1])
            task = db_seeded[0].tasks.get(task_id)
            return [task] if task else []
        # â”€â”€ risk endpoints â”€â”€
        if path.startswith("/riskList/"):
            return list(db_seeded[0].risks.values())
        if path.startswith("/risk/"):
            risk_id = int(path.rsplit("/", 1)[1])
            risk = db_seeded[0].risks.get(risk_id)
            return [risk] if risk else []
        # â”€â”€ scorecard endpoints â”€â”€
        if path.startswith("/scorecard/"):
            sc_id = int(path.rsplit("/", 1)[1])
            sc = db_seeded[0].scorecards.get(sc_id)
            return [sc] if sc else []
        raise java_bridge.JavaBridgeError(f"fake bridge: unhandled GET {path}")

    async def fake_mysql(sql, params=(), one=False):
        low = sql.lower()
        db_ = db_seeded[0]
        # login: hashed password lookup
        if "hashed_password from users" in low and "email" in low:
            email = (params[0] if params else "").lower()
            row = db_.users.get(email)
            if one:
                return row or None
            return [row] if row else []
        if "from users" in low and "email" in low:
            email = (params[0] if params else "").lower()
            u = db_.users.get(email, {})
            emp = db_.employee_by_email(email)
            row = {
                "id": (emp["emp_id"] if emp else 0),
                "org_id": u.get("org_id", ORG_ID),
                "role": u.get("role", "member"),
                "full_name": "",
                "email": email,
            }
            if one:
                return row
            return [row] if u else []
        # hierarchy / report tree
        if "parent_emp_id from employee_details" in low:
            return [{"emp_id": r["emp_id"], "org_id": r["org_id"], "parent_emp_id": r["parent_emp_id"]}
                    for r in db_.employees]
        # department members
        if "dept_id" in low and "from employee_details" in low:
            dept_id = params[0] if params else None
            return [{"emp_id": r["emp_id"]} for r in db_.employees if r["dept_id"] == dept_id]
        # title lookup (owner-is-manager)
        if "title from employee_details" in low:
            emp_id = params[0] if params else None
            for r in db_.employees:
                if r["emp_id"] == emp_id:
                    return [{"title": r["title"]}]
            return []
        # user_role_management fallback
        if "user_role_management" in low:
            email = (params[0] if params else "").lower()
            ur = db_.user_roles.get(email)
            if one:
                return ur or None
            return [ur] if ur else []
        # scorecard_kpis list
        if "scorecard_kpis" in low and "select" in low:
            rows = []
            seen = set()
            for sc in db_.scorecards.values():
                key = (sc["perspective"], sc["kpi_name"], sc["target"], sc["actual"], sc["status"])
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "id": sc["id"], "perspective": sc["perspective"], "kpi_name": sc["kpi_name"],
                    "target": sc["target"], "actual": sc["actual"], "owner": sc["owner"],
                    "status": sc["status"], "assigned_user_id": sc["assigned_user_id"],
                })
            if one:
                return rows[0] if rows else None
            return rows
        if "organizations" in low:
            return [{"id": ORG_ID}]
        return []

    async def fake_mysql_write(sql, params=()):
        return 1

    async def fake_post(service, path, **kwargs):
        data = kwargs.get("json") or {}
        db_ = db_seeded[0]
        if path == "/task":
            nid = 9000 + len(db_.tasks)
            db_.tasks[nid] = {
                "id": nid, "owner": data.get("owner"), "assigned_user_id": data.get("assignedUserId"),
                "title": data.get("title"), "status": data.get("status"), "priority": data.get("priority"),
            }
            return {"id": nid}
        if path == "/risk":
            nid = 9000 + len(db_.risks)
            db_.risks[nid] = {"id": nid, "owner": data.get("owner"), "risk_name": data.get("riskName"), "status": "open"}
            return {"id": nid}
        if path == "/scorecard":
            nid = 9000 + len(db_.scorecards)
            db_.scorecards[nid] = {
                "id": nid, "owner": data.get("owner"), "assigned_user_id": data.get("assignedUserId"),
                "perspective": data.get("perspective"), "kpi_name": data.get("kpiName"),
                "target": data.get("target"), "actual": data.get("actual"), "status": data.get("status"),
            }
            return {"id": nid}
        return {"id": 1}

    async def fake_put(service, path, **kwargs):
        return None

    async def fake_delete(service, path, **kwargs):
        return None

    bridge.get = fake_get
    bridge._mysql = fake_mysql
    bridge._mysql_write = fake_mysql_write
    bridge.post = fake_post
    bridge.put = fake_put
    bridge.delete = fake_delete


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Test harness
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class HttpVerifier:
    """HTTP client wrapper â€” works with both TestClient and real httpx client."""

    def __init__(self, base_url=None):
        self.base_url = base_url

    def post(self, path, json):
        raise NotImplementedError

    def get(self, path, headers=None):
        raise NotImplementedError


class OfflineHttp(HttpVerifier):
    def __init__(self, app):
        super().__init__()
        from starlette.testclient import TestClient

        self.client = TestClient(app)

    def post(self, path, json):
        return self.client.post(path, json=json)

    def get(self, path, headers=None):
        return self.client.get(path, headers=headers or {})


class LiveHttp(HttpVerifier):
    def __init__(self, base_url):
        super().__init__(base_url)
        import httpx

        self.client = httpx.Client(base_url=base_url, timeout=30)

    def post(self, path, json):
        return self.client.post(path, json=json)

    def get(self, path, headers=None):
        return self.client.get(path, headers=headers or {})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Live-mode MySQL bootstrap (idempotent)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def bootstrap_mysql_live():
    import pymysql
    from app.core.security import hash_password

    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "Admin#123"),
        database=os.environ.get("MYSQL_DATABASE", "orgstructure"),
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    cur = conn.cursor()

    def q(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchall()

    print("  Â· bootstrapping MySQL (orgstructure) ...")
    # ensure org
    q("INSERT IGNORE INTO organizations (id, name) VALUES (%s, %s)", (ORG_ID, "RBAC Test Org"))

    for emp_id, parent, dept, first, last, title, email, role in ACCOUNTS:
        # employee_details (idempotent upsert)
        cur.execute(
            "INSERT INTO employee_details (emp_id, org_id, dept_id, first_name, last_name, title, "
            "email_address, status, department, parent_emp_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'Active', 'Management', %s) "
            "ON DUPLICATE KEY UPDATE title=VALUES(title), parent_emp_id=VALUES(parent_emp_id), "
            "dept_id=VALUES(dept_id), email_address=VALUES(email_address)",
            (emp_id, ORG_ID, dept, first, last, title, email, parent),
        )
        # user (idempotent upsert)
        cur.execute(
            "INSERT INTO users (org_id, email, hashed_password, full_name, role) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE hashed_password=VALUES(hashed_password), role=VALUES(role), "
            "full_name=VALUES(full_name)",
            (ORG_ID, email, hash_password(PASSWORD), f"{first} {last}", role),
        )
        # user_role_management (optional; enables enterprise-role path)
        cur.execute(
            "INSERT INTO user_role_management (emp_id, email_address, designation, role, department, location, status) "
            "VALUES (%s, %s, %s, %s, 'Management', '', 'Active') "
            "ON DUPLICATE KEY UPDATE designation=VALUES(designation), role=VALUES(role)",
            (emp_id, email, title, role),
        )

    # tasks
    def upsert_task(tid, owner_emp, title, status, priority):
        import json

        tv = json.dumps({"title": title, "assignedUserId": owner_emp})
        cur.execute(
            "INSERT INTO task_details (ID, task_value, active, owner, created_time, updated_time, priority, status) "
            "VALUES (%s, %s, 1, %s, NOW(), NOW(), %s, %s) "
            "ON DUPLICATE KEY UPDATE task_value=VALUES(task_value), owner=VALUES(owner), "
            "priority=VALUES(priority), status=VALUES(status)",
            (tid, tv, owner_emp, priority, status),
        )

    upsert_task(5001, 903, "Peer task", "pending", "Medium")
    upsert_task(5002, 901, "Manager task", "in_progress", "High")
    upsert_task(5003, 902, "Member task", "pending", "Medium")

    # risks
    def upsert_risk(rid, owner_emp, name):
        import json

        rv = json.dumps({"riskName": name})
        cur.execute(
            "INSERT INTO risk_details (ID, risk_value, active, owner, created_time, updated_time, page_id, status) "
            "VALUES (%s, %s, 1, %s, NOW(), NOW(), %s, 'open') "
            "ON DUPLICATE KEY UPDATE risk_value=VALUES(risk_value), owner=VALUES(owner)",
            (rid, rv, owner_emp, rid),
        )

    upsert_risk(6001, 901, "Manager risk")
    upsert_risk(6002, 902, "Member risk")

    # scorecard_kpis
    def upsert_scorecard(sid, owner_emp, perspective, kpi, target, actual, status):
        cur.execute(
            "INSERT INTO scorecard_kpis (id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE perspective=VALUES(perspective), kpi_name=VALUES(kpi_name), "
            "target=VALUES(target), actual=VALUES(actual), owner=VALUES(owner), status=VALUES(status), "
            "assigned_user_id=VALUES(assigned_user_id)",
            (sid, ORG_ID, perspective, kpi, target, actual, owner_emp, status, owner_emp),
        )

    upsert_scorecard(7001, 901, "Financial", "Revenue", 100, 80, "on-track")
    upsert_scorecard(7002, 902, "Customer", "NPS", 50, 45, "at-risk")

    conn.commit()
    cur.close()
    conn.close()
    print("  Â· bootstrap complete.")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Scenario runner
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def login(client: HttpVerifier, email: str) -> str:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    if resp.status_code != 200:
        raise RuntimeError(f"login {email} failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


def check(results, name, condition, detail=""):
    results.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail and not condition else ""))


def run_scenarios(client: HttpVerifier):
    print()
    print("  â”€â”€ Logging in â”€â”€")
    admin = login(client, "admin@rbac.local")
    manager = login(client, "manager@rbac.local")
    member = login(client, "member@rbac.local")
    peer = login(client, "peer@rbac.local")
    print("  Â· 4 accounts logged in OK")

    results = []
    h = {"Authorization": f"Bearer {token}"} if False else {}

    def H(token):
        return {"Authorization": f"Bearer {token}"}

    print()
    print("  â”€â”€ Scenario A: member -> peer member's task (expect 403, task message) â”€â”€")
    r = client.get("/tasks/5001", headers=H(member))
    check(results, "A1 GET /tasks/5001 (peer task) returns 403",
          r.status_code == 403, f"got {r.status_code}")
    detail = r.json().get("detail", "") if r.status_code != 200 else ""
    check(results, "A2 denial message matches task-ownership text",
          detail == "This task is not assigned to you; it is assigned to a different user.",
          f"got: {detail!r}")

    print()
    print("  â”€â”€ Scenario B: member -> manager's task/data (expect 403, data message) â”€â”€")
    r = client.get("/tasks/5002", headers=H(member))
    check(results, "B1 GET /tasks/5002 (manager task) returns 403",
          r.status_code == 403, f"got {r.status_code}")
    detail = r.json().get("detail", "") if r.status_code != 200 else ""
    check(results, "B2 denial message matches data-access text",
          detail == "You don't have permission to access this data",
          f"got: {detail!r}")

    r = client.get("/risks/6001", headers=H(member))
    check(results, "B3 GET /risks/6001 (manager risk) returns 403",
          r.status_code == 403, f"got {r.status_code}")
    detail = r.json().get("detail", "") if r.status_code != 200 else ""
    check(results, "B4 denial message matches data-access text",
          detail == "You don't have permission to access this data",
          f"got: {detail!r}")

    r = client.get("/scorecards/7001", headers=H(member))
    check(results, "B5 GET /scorecards/7001 (manager scorecard) returns 403",
          r.status_code == 403, f"got {r.status_code}")
    detail = r.json().get("detail", "") if r.status_code != 200 else ""
    check(results, "B6 denial message matches data-access text",
          detail == "You don't have permission to access this data",
          f"got: {detail!r}")

    print()
    print("  â”€â”€ Scenario C: manager -> direct subordinate (expect 200) â”€â”€")
    for label, path in (
        ("C1 GET /tasks/5003 (subordinate task)", "/tasks/5003"),
        ("C2 GET /risks/6002 (subordinate risk)", "/risks/6002"),
        ("C3 GET /scorecards/7002 (subordinate scorecard)", "/scorecards/7002"),
    ):
        r = client.get(path, headers=H(manager))
        check(results, label, r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    print()
    print("  â”€â”€ List scoping â”€â”€")
    r = client.get("/tasks", headers=H(member))
    ids = [t.get("id") for t in (r.json() or {}).get("tasks", [])] if r.status_code == 200 else []
    check(results, "L1 member /tasks list contains own task only",
          r.status_code == 200 and sorted(ids) == [5003], f"got {ids}")

    r = client.get("/tasks", headers=H(manager))
    ids = [t.get("id") for t in (r.json() or {}).get("tasks", [])] if r.status_code == 200 else []
    check(results, "L2 manager /tasks list contains self + subordinates",
          r.status_code == 200 and sorted(ids) == [5001, 5002, 5003], f"got {ids}")

    print()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  RESULTS: {passed}/{total} checks passed")
    return passed == total


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    ap = argparse.ArgumentParser(description="Phase 2 RBAC local HTTP verification")
    ap.add_argument("--live", action="store_true", help="run against a real server (requires MYSQL_* + BASE_URL)")
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8001/api/v1"))
    args = ap.parse_args()

    print("=" * 62)
    print("  STRATROOM PHASE 2 RBAC â€” LOCAL HTTP VERIFICATION")
    print("=" * 62)
    print()
    print("  Accounts (all password Passw0rd!):")
    for emp_id, _, _, _, _, title, email, role in ACCOUNTS:
        print(f"    emp {emp_id:>3}  {role:<8} {title:<12} {email}")
    print()

    if args.live:
        bootstrap_mysql_live()
        client = LiveHttp(args.base_url)
    else:
        from app.main import app

        fakedb = FakeDB()
        fakedb.seed_accounts()
        fakedb.seed_records()
        install_fake_bridge(fakedb)
        client = OfflineHttp(app)

    ok = run_scenarios(client)
    print()
    print("  " + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
