"""
Initiative Tools Test Suite — query_initiatives + update_initiative_progress

Self-contained offline tests (no database / Docker required). Uses a fake
bridge that stubs `_mysql`, `_mysql_write`, and `_parse_json_col` so the
initiative tools can be exercised end-to-end.

Usage:  python test_initiative_tools.py
"""
import asyncio
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

from app.agents.initiative_tools import (  # noqa: E402
    _parse_initiative_progress,
    _status_light,
    _status_indicator,
    query_initiatives,
    update_initiative_progress,
)
from app.services.java_bridge import bridge  # noqa: E402

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


# ── Fake initiative store (id -> row) ─────────────────────────────
# owner 2 owns initiative id 8; admin bypasses ownership.
def _initiative_row(iid, code, owner, progressval):
    iv = {
        "name": f"Initiative {iid}",
        "description": "A test initiative",
        "ownerName": f"owner-{owner}",
        "progressval": str(progressval),
        "progress": progressval,
        "statusIndicator": "RED",
        "statusLight": "progress-bar progress-bar-danger",
    }
    return {
        "id": iid,
        "initiative_id": code,
        "initiative_value": json.dumps(iv),
        "owner": owner,
        "status_indicator": "RED",
    }


FAKE_INITIATIVES = {
    8: _initiative_row(8, "SI-01", 2, 0),
    9: _initiative_row(9, "SI-02", 3, 60),
    10: _initiative_row(10, "SI-03", 2, 100),
}

writes = []


def _patch_fake():
    global writes
    writes = []

    async def fake_mysql(sql, params=(), one=False):
        low = sql.lower()
        if "from employee_details" in low and "email_address" in low:
            email = (params[0] if params else "").lower()
            if email == "member2@test.com":
                return [{"emp_id": 2, "org_id": 1}]
            return []
        if "from initiatives_details" in low:
            rows_all = list(FAKE_INITIATIVES.values())
            # single-record fetch by id (with optional owner scope)
            if "where id = %s" in low:
                iid = params[0] if params else None
                row = FAKE_INITIATIVES.get(iid)
                if row and "and owner = %s" in low:
                    owner = params[1] if len(params) > 1 else None
                    if row["owner"] != owner:
                        return []
                if one:
                    return row
                return [row] if row else []
            # list query (admin: all; member: owner-scoped)
            if "owner = %s" in low:
                owner = params[0] if params else None
                rows = [r for r in rows_all if r["owner"] == owner]
            else:
                rows = rows_all
            if one:
                return rows[0] if rows else None
            return rows
        return []

    async def fake_mysql_write(sql, params=()):
        writes.append({"sql": sql, "params": params})
        return 1

    def fake_parse_json_col(row, col):
        return json.loads(row.get(col) or "{}")

    bridge._mysql = fake_mysql
    bridge._mysql_write = fake_mysql_write
    bridge._parse_json_col = fake_parse_json_col


# ── Unit tests for helpers ─────────────────────────────────────────
def test_progress_parser_clamps_low():
    val, err, clamped = _parse_initiative_progress(-50)
    assert (val, err, clamped) == (0, None, True), "should clamp to 0"


def test_progress_parser_clamps_high():
    val, err, clamped = _parse_initiative_progress(150)
    assert (val, err, clamped) == (100, None, True), "should clamp to 100"


def test_progress_parser_accepts_bounds():
    assert _parse_initiative_progress(0) == (0, None, False)
    assert _parse_initiative_progress(100) == (100, None, False)
    assert _parse_initiative_progress("75") == (75, None, False)


def test_progress_parser_rejects_bad():
    val, err, clamped = _parse_initiative_progress("abc")
    assert val is None and err, "should reject non-integer progress"
    val, err, clamped = _parse_initiative_progress(None)
    assert val is None and err, "should reject missing progress"


def test_status_light_mapping():
    assert "progress-bar-success" in _status_light(100)
    assert "progress-bar-warning" in _status_light(50)
    assert "progress-bar-danger" in _status_light(10)


def test_status_indicator_mapping():
    assert _status_indicator(100) == "GREEN"
    assert _status_indicator(75) == "GREEN"
    assert _status_indicator(74) == "AMBER"
    assert _status_indicator(40) == "AMBER"
    assert _status_indicator(39) == "RED"
    assert _status_indicator(0) == "RED"


# ── query_initiatives ──────────────────────────────────────────────
def test_query_initiatives_member_sees_own_only():
    _patch_fake()
    out = run(query_initiatives(None, 2, 1, is_admin=False, email="member2@test.com"))
    assert "error" not in out, f"unexpected error: {out}"
    ids = [i["id"] for i in out["initiatives"]]
    assert ids == [8, 10], f"member 2 should own only 8 and 10, got {ids}"
    assert out["summary"]["total"] == 2


def test_query_initiatives_admin_sees_all():
    _patch_fake()
    out = run(query_initiatives(None, 1, 1, is_admin=True))
    ids = {i["id"] for i in out["initiatives"]}
    assert ids == {8, 9, 10}, f"admin should see all initiatives, got {ids}"


def test_query_initiatives_member_unknown_email():
    _patch_fake()
    out = run(query_initiatives(None, 99, 1, is_admin=False, email="ghost@test.com"))
    assert "error" in out, "unknown email should produce an error"


# ── update_initiative_progress ─────────────────────────────────────
def test_update_progress_owner_success():
    _patch_fake()
    out = run(update_initiative_progress(
        None, 2, 1, initiative_id=8, progress=80,
        is_admin=False, email="member2@test.com",
    ))
    assert "error" not in out, f"unexpected error: {out}"
    assert out["old_progress"] == 0
    assert out["new_progress"] == 80
    assert "SI-01" in out["confirmation"]
    assert "GREEN" in out["confirmation"]
    assert len(writes) == 1
    write_params = writes[0]["params"]
    blob = json.loads(write_params[0])
    assert blob["progressval"] == "80"
    assert blob["progress"] == 80
    assert blob["statusIndicator"] == "GREEN"
    assert "width-per-80" in blob["statusLight"]


def test_update_progress_admin_updates_any():
    _patch_fake()
    out = run(update_initiative_progress(
        None, 1, 1, initiative_id=9, progress=100, is_admin=True,
    ))
    assert "error" not in out, f"unexpected error: {out}"
    assert out["new_progress"] == 100
    assert "SI-02" in out["confirmation"]
    assert "fully complete" in out["confirmation"]
    assert len(writes) == 1
    assert "WHERE id = %s" in writes[0]["sql"]
    assert "owner" not in writes[0]["sql"].lower()


def test_update_progress_not_owner_denied():
    _patch_fake()
    out = run(update_initiative_progress(
        None, 3, 1, initiative_id=9, progress=50,
        is_admin=False, email="member2@test.com",
    ))
    assert "error" in out, "member 2 updating initiative owned by 3 should be denied"
    assert "not yours" in out["error"]


def test_update_progress_not_found():
    _patch_fake()
    out = run(update_initiative_progress(
        None, 1, 1, initiative_id=999, progress=50, is_admin=True,
    ))
    assert "error" in out, "missing initiative should produce an error"
    assert "not found" in out["error"]


def test_update_progress_missing_value():
    _patch_fake()
    out = run(update_initiative_progress(
        None, 2, 1, initiative_id=8, progress=None,
        is_admin=False, email="member2@test.com",
    ))
    assert "error" in out, "missing progress should produce an error"


def test_update_progress_owner_scoped_write():
    _patch_fake()
    run(update_initiative_progress(
        None, 2, 1, initiative_id=8, progress=40,
        is_admin=False, email="member2@test.com",
    ))
    assert "WHERE id = %s AND owner = %s" in writes[0]["sql"], (
        f"non-admin write must be owner-scoped, got: {writes[0]['sql']}"
    )


# ── runner ─────────────────────────────────────────────────────────
def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("=" * 60)
    print("  STRATROOM INITIATIVE TOOLS TEST SUITE")
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
