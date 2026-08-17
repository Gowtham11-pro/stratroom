"""
Phase 2 RBAC Test Suite — Hierarchical Access + Task Ownership

Self-contained offline tests (no database / Docker required). Verifies the
three Manager-specified scenarios:

  S1. Member querying another member's task      -> denied (exact message)
  S2. Member querying Manager data               -> denied (exact message)
  S3. Manager querying direct subordinate data   -> allowed

Usage:  python test_rbac_phase2.py
"""
import asyncio
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

from app.core import rbac  # noqa: E402

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


def identity(emp_id, role, org_id=1, dept_id=None):
    return {
        "user_id": emp_id,
        "emp_id": emp_id,
        "org_id": org_id,
        "email": f"user{emp_id}@test.com",
        "employee": {"emp_id": emp_id, "dept_id": dept_id},
        "app_role": role,
        "designation": role,
        "enterprise_role": {"role": role},
        "department": None,
        "location": None,
    }


# ── Fake hierarchy (emp_id, parent_emp_id) ──
#   1 (manager, dept 10) -> 2, 3 ;  2 -> 4 ;  5 (manager, dept 99) isolated
FAKE_HIERARCHY = [
    {"emp_id": 1, "parent_emp_id": None},
    {"emp_id": 2, "parent_emp_id": 1},
    {"emp_id": 3, "parent_emp_id": 1},
    {"emp_id": 4, "parent_emp_id": 2},
    {"emp_id": 5, "parent_emp_id": None},
]
DEPT_MEMBERS = [{"emp_id": 3}, {"emp_id": 7}]
# title lookup for owner-role detection
EMP_TITLES = {
    1: "Manager",
    5: "Manager",
    2: "Analyst",
    3: "Analyst",
    4: "Analyst",
}

MANAGER = identity(1, "manager", dept_id=10)
MEMBER_2 = identity(2, "member", dept_id=10)
MEMBER_3 = identity(3, "member", dept_id=10)
MEMBER_4 = identity(4, "member", dept_id=10)
OTHER_MANAGER = identity(5, "manager", dept_id=99)
ADMIN = identity(6, "admin", dept_id=10)


def task_owned_by(owner_id):
    return {"id": 100, "owner": owner_id, "assigned_user_id": owner_id}


def risk_owned_by(owner_id):
    return {"id": 200, "owner": owner_id}


def _patch_fake():
    """Monkeypatch the bridge so rbac's hierarchy queries use the fake tree."""

    async def fake_mysql(sql, params=(), one=False):
        if "parent_emp_id" in sql:
            return list(FAKE_HIERARCHY)
        if "dept_id" in sql:
            return list(DEPT_MEMBERS)
        if "SELECT title FROM employee_details" in sql:
            eid = params[0] if params else None
            title = EMP_TITLES.get(eid)
            return [{"title": title}] if title else []
        return []

    rbac.bridge._mysql = fake_mysql


def run(coro):
    return asyncio.run(coro)


# ────────────────────────────────────────────────────────────────
# Core helper assertions (no bridge needed)
# ────────────────────────────────────────────────────────────────
def test_task_message_constant():
    assert rbac.MSG_TASK_NOT_ASSIGNED == (
        "This task is not assigned to you; it is assigned to a different user."
    ), "Task ownership message is wrong"


def test_data_message_constant():
    assert rbac.MSG_ACCESS_RESTRICTED == (
        "You don't have permission to access this data"
    ), "Data-access message is wrong"


# ────────────────────────────────────────────────────────────────
# S1: Member querying another member's task -> denied (exact message)
# ────────────────────────────────────────────────────────────────
def test_s1_member_task_not_assigned():
    _patch_fake()
    try:
        run(rbac.enforce_task_access(MEMBER_2, 3))  # member 2 views a task of member 3
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 403, f"want 403, got {e}"
        assert getattr(e, "detail", None) == rbac.MSG_TASK_NOT_ASSIGNED


def test_s1_member_task_list_filtered():
    _patch_fake()
    rows = [task_owned_by(2), task_owned_by(3), task_owned_by(1)]
    visible = run(rbac.filter_visible_rows(MEMBER_2, rows))
    owners = {r["id"] for r in visible}
    assert owners == {100}, "member should see only own tasks"


# ────────────────────────────────────────────────────────────────
# S2: Member querying Manager data -> denied (exact message)
# ────────────────────────────────────────────────────────────────
def test_s2_member_manager_data_denied():
    _patch_fake()
    try:
        run(rbac.enforce_record_access(MEMBER_2, 1))  # member views manager 1's risk
        assert False, "expected HTTPException"
    except Exception as e:
        assert getattr(e, "status_code", None) == 403, f"want 403, got {e}"
        assert getattr(e, "detail", None) == rbac.MSG_ACCESS_RESTRICTED


def test_s2_member_risk_list_filter():
    _patch_fake()
    rows = [risk_owned_by(1), risk_owned_by(2), risk_owned_by(5)]
    visible = run(rbac.filter_visible_rows(MEMBER_2, rows))
    owners = {r["owner"] for r in visible}
    assert owners == {2}, f"member should see only own risk, got {owners}"


def test_s2_member_manager_TASK_denied_data_msg():
    """Scenario B: member probing a manager's TASK gets the data-access message,
    not the peer-task message."""
    _patch_fake()
    try:
        run(rbac.enforce_task_access(MEMBER_2, 1))  # member views manager 1's task
        raise AssertionError("expected HTTPException")
    except Exception as e:
        assert getattr(e, "status_code", None) == 403, f"want 403, got {e}"
        assert getattr(e, "detail", None) == rbac.MSG_ACCESS_RESTRICTED


# ────────────────────────────────────────────────────────────────
# S3: Manager -> direct subordinate data -> allowed
# ────────────────────────────────────────────────────────────────
def test_s3_manager_direct_report_task_allowed():
    _patch_fake()
    for owner in (1, 2, 3, 4):  # self + direct + indirect reports
        try:
            run(rbac.enforce_task_access(MANAGER, owner))
        except Exception as e:
            assert False, f"manager should view task of {owner}, got {e}"


def test_s3_manager_direct_report_list_filter():
    _patch_fake()
    rows = [task_owned_by(2), task_owned_by(3), task_owned_by(4),
            task_owned_by(1), task_owned_by(5)]
    visible = run(rbac.filter_visible_rows(MANAGER, rows))
    owners = {r["owner"] for r in visible}
    assert 5 not in owners, f"manager saw unrelated owner 5: {owners}"
    assert owners == {1, 2, 3, 4}, f"manager scope wrong: {owners}"


def test_s3_manager_out_of_scope_denied():
    _patch_fake()
    try:
        run(rbac.enforce_record_access(MANAGER, 5))  # unrelated manager's data
        raise AssertionError("expected HTTPException")
    except Exception as e:
        assert getattr(e, "status_code", None) == 403, f"want 403, got {e}"
        assert getattr(e, "detail", None) == rbac.MSG_ACCESS_RESTRICTED


# ────────────────────────────────────────────────────────────────
# Admin bypass + own-record always allowed
# ────────────────────────────────────────────────────────────────
def test_admin_can_view_anything():
    _patch_fake()
    for owner in (1, 2, 3, 4, 5):
        run(rbac.enforce_record_access(ADMIN, owner))


def test_own_record_always_allowed():
    _patch_fake()
    try:
        run(rbac.enforce_task_access(MEMBER_2, 2))
    except Exception as e:
        assert False, f"member should access own task, got {e}"


# ────────────────────────────────────────────────────────────────
# runner
# ────────────────────────────────────────────────────────────────
def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("=" * 60)
    print("  STRATROOM PHASE 2 RBAC TEST SUITE")
    print("=" * 60)
    for fn in tests:
        run_test(fn.__name__, fn)
    print()
    for r in results:
        if r[0] == "PASS":
            print(f"  PASS  {r[1]}")
        else:
            print(f"  FAIL  {r[1]}: {r[2]}")
    print()
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} PASSED | {failed} FAILED")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)