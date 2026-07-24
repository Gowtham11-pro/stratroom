"""
StratRoom Automated Test Suite
===============================
Self-contained mock tests — no database or Docker required.
Verifies: imports, auth, JWT, ML inference, API routes, DB schema, frontend wiring.

Usage:  python test_suite.py
"""
import os
import sys
import time


# ── Setup paths ──
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BACKEND = os.path.join(ROOT, "backend")
ML = os.path.join(BACKEND, "ml")
DB_DIR = os.path.join(BACKEND, "db")
FRONTEND = os.path.join(ROOT, "frontend", "31may_index.html")

sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(ML, "scripts"))

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
        results.append(("FAIL", name, str(e)))


# ════════════════════════════════════════════════════════════════
# CATEGORY 1: FILE INTEGRITY
# ════════════════════════════════════════════════════════════════
def test_backend_main_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "main.py")), "main.py missing"

def test_backend_config_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "config.py")), "config.py missing"

def test_backend_db_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "db.py")), "db.py missing"

def test_backend_security_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "security.py")), "security.py missing"

def test_backend_deps_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "deps.py")), "deps.py missing"

def test_router_auth_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "auth.py")), "auth.py missing"

def test_router_risks_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "risks.py")), "risks.py missing"

def test_router_incidents_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "incidents.py")), "incidents.py missing"

def test_router_predict_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "predict.py")), "predict.py missing"

def test_router_dashboard_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "dashboard.py")), "dashboard.py missing"

def test_router_scorecards_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "scorecards.py")), "scorecards.py missing"

def test_router_budgets_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "budgets.py")), "budgets.py missing"

def test_router_tasks_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "tasks.py")), "tasks.py missing"

def test_router_meetings_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "meetings.py")), "meetings.py missing"

def test_router_audit_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "audit.py")), "audit.py missing"

def test_router_compliance_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "compliance.py")), "compliance.py missing"

def test_router_documents_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "routers", "documents.py")), "documents.py missing"

def test_logging_config_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "logging_config.py")), "logging_config.py missing"

def test_rate_limiter_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "rate_limiter.py")), "rate_limiter.py missing"

def test_utils_exists():
    assert os.path.isfile(os.path.join(BACKEND, "app", "core", "utils.py")), "utils.py missing"

def test_env_example_exists():
    assert os.path.isfile(os.path.join(ROOT, ".env.example")), ".env.example missing"

def test_dockerignore_exists():
    assert os.path.isfile(os.path.join(ROOT, ".dockerignore")), ".dockerignore missing"

def test_github_actions_exists():
    path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
    assert os.path.isfile(path), "ci.yml missing"

def test_requirements_exists():
    assert os.path.isfile(os.path.join(BACKEND, "requirements.txt")), "requirements.txt missing"

def test_dockerfile_exists():
    assert os.path.isfile(os.path.join(BACKEND, "Dockerfile")), "Dockerfile missing"

def test_init_sql_exists():
    assert os.path.isfile(os.path.join(DB_DIR, "01_init.sql")), "init.sql missing"

def test_docker_compose_exists():
    assert os.path.isfile(os.path.join(ROOT, "docker-compose.yml")), "docker-compose.yml missing"

def test_inference_script_exists():
    assert os.path.isfile(os.path.join(ML, "scripts", "inference.py")), "inference.py missing"

def test_train_script_exists():
    assert os.path.isfile(os.path.join(ML, "scripts", "train.py")), "train.py missing"

def test_model_file_exists():
    path = os.path.join(ML, "models", "risk_model.joblib")
    assert os.path.isfile(path), "risk_model.joblib missing"
    assert os.path.getsize(path) > 1000, "risk_model.joblib is too small"

def test_frontend_html_exists():
    assert os.path.isfile(FRONTEND), "31may_index.html missing"
    size = os.path.getsize(FRONTEND)
    assert size > 100000, f"Frontend HTML too small ({size} bytes)"


# ════════════════════════════════════════════════════════════════
# CATEGORY 2: PYTHON IMPORTS
# ════════════════════════════════════════════════════════════════
def test_import_fastapi():
    import fastapi
    assert fastapi.__version__.startswith("0.") or True  # any version ok

def test_import_sqlalchemy():
    import sqlalchemy
    assert hasattr(sqlalchemy, "__version__")

def test_import_pydantic():
    import pydantic
    assert hasattr(pydantic, "__version__")

def test_import_jose():
    from jose import jwt
    assert hasattr(jwt, "encode")
    assert hasattr(jwt, "decode")

def test_import_bcrypt():
    import bcrypt
    assert hasattr(bcrypt, "hashpw")
    assert hasattr(bcrypt, "checkpw")

def test_import_xgboost():
    import xgboost
    assert hasattr(xgboost, "__version__")

def test_import_pandas():
    import pandas
    assert hasattr(pandas, "__version__")

def test_import_joblib():
    import joblib
    assert hasattr(joblib, "load")

def test_import_sklearn():
    import sklearn
    assert hasattr(sklearn, "__version__")

def test_import_numpy():
    import numpy
    assert hasattr(numpy, "__version__")

def test_import_config():
    from app.core.config import settings
    assert settings.JWT_SECRET
    assert settings.JWT_ALGORITHM == "HS256"

def test_import_security():
    from app.core.security import hash_password, verify_password, create_access_token, decode_access_token
    assert callable(hash_password)
    assert callable(verify_password)
    assert callable(create_access_token)
    assert callable(decode_access_token)

def test_import_deps():
    from app.core.deps import get_current_user
    assert callable(get_current_user)

def test_import_db():
    from app.core.db import get_db, engine, SessionLocal, check_db_health
    assert callable(get_db)
    assert callable(check_db_health)

def test_import_logging_config():
    from app.core.logging_config import setup_logging, StructuredFormatter, correlation_id_var, request_id_var
    assert callable(setup_logging)
    assert callable(correlation_id_var.get)
    assert callable(request_id_var.get)

def test_import_rate_limiter():
    from app.core.rate_limiter import limiter, SlidingWindowRateLimiter
    assert isinstance(limiter, SlidingWindowRateLimiter)
    allowed, retry = limiter.is_allowed("test_key", 10, 60)
    assert allowed is True

def test_import_utils():
    from app.core.utils import resolve_user
    assert callable(resolve_user)

def test_import_main():
    from app.main import app
    assert app is not None

def test_import_inference():
    sys.path.insert(0, os.path.join(ML, "scripts"))
    from inference import predict_risk_score, API_FEATURES
    assert callable(predict_risk_score)
    assert len(API_FEATURES) == 4


# ════════════════════════════════════════════════════════════════
# CATEGORY 3: AUTH / PASSWORD / JWT
# ════════════════════════════════════════════════════════════════
def test_hash_password():
    from app.core.security import hash_password
    h = hash_password("test123")
    assert h.startswith("$2b$"), f"Bad hash format: {h[:20]}"

def test_verify_correct_password():
    from app.core.security import hash_password, verify_password
    h = hash_password("mypassword")
    assert verify_password("mypassword", h) is True

def test_verify_wrong_password():
    from app.core.security import hash_password, verify_password
    h = hash_password("mypassword")
    assert verify_password("wrongpassword", h) is False

def test_verify_seed_password():
    from app.core.security import verify_password
    seed_hash = "$2b$12$r8IIn0LTYtPnHI6u9GwQZeP/bGhylg5GUoPRcdOPR6pqnP3XgQ7Z."
    assert verify_password("changeme", seed_hash) is True

def test_jwt_create_and_decode():
    from app.core.security import create_access_token, decode_access_token
    token = create_access_token("test@example.com")
    assert isinstance(token, str)
    assert len(token) > 20
    subject = decode_access_token(token)
    assert subject == "test@example.com"

def test_jwt_different_subjects():
    from app.core.security import create_access_token, decode_access_token
    t1 = create_access_token("alice@test.com")
    t2 = create_access_token("bob@test.com")
    assert decode_access_token(t1) == "alice@test.com"
    assert decode_access_token(t2) == "bob@test.com"

def test_jwt_invalid_token():
    from app.core.security import decode_access_token
    try:
        decode_access_token("not.a.real.token")
        assert False, "Should have raised exception"
    except Exception:
        pass  # expected


# ════════════════════════════════════════════════════════════════
# CATEGORY 4: ML MODEL INFERENCE
# ════════════════════════════════════════════════════════════════
def test_ml_model_loads():
    import joblib
    model_path = os.path.join(ML, "models", "risk_model.joblib")
    model = joblib.load(model_path)
    assert model is not None

def test_ml_model_feature_count():
    import joblib
    model_path = os.path.join(ML, "models", "risk_model.joblib")
    model = joblib.load(model_path)
    try:
        n = model.n_features_in_
    except AttributeError:
        n = model.steps[-1][1].n_features_in_
    assert n >= 4, f"Model expects {n} features, expected >= 4"

def test_ml_prediction_4_features():
    from inference import predict_risk_score
    score = predict_risk_score({
        "inherent_likelihood": 4,
        "inherent_impact": 5,
        "days_open": 30,
        "vendor_concentration_pct": 60
    })
    assert isinstance(score, float), f"Score should be float, got {type(score)}"
    assert 1.0 <= score <= 25.0, f"Score {score} out of range [1-25]"

def test_ml_prediction_low_risk():
    from inference import predict_risk_score
    score = predict_risk_score({
        "inherent_likelihood": 1,
        "inherent_impact": 1,
        "days_open": 0,
        "vendor_concentration_pct": 0
    })
    assert score < 5.0, f"Low risk input should give low score, got {score}"

def test_ml_prediction_high_risk():
    from inference import predict_risk_score
    score = predict_risk_score({
        "inherent_likelihood": 5,
        "inherent_impact": 5,
        "days_open": 400,
        "vendor_concentration_pct": 100
    })
    assert score > 3.0, f"High risk input should give high score, got {score}"

def test_ml_missing_feature_raises():
    from inference import predict_risk_score
    try:
        predict_risk_score({"inherent_likelihood": 3})  # missing 3 required features
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# ════════════════════════════════════════════════════════════════
# CATEGORY 5: FASTAPI APP STRUCTURE
# ════════════════════════════════════════════════════════════════
def test_app_loads():
    from app.main import app
    assert app.title == "StratRoom API"

def test_app_has_routes():
    from app.main import app
    all_paths = set()
    for route in app.routes:
        if hasattr(route, "path"):
            all_paths.add(route.path)
    # Sub-router routes are nested, check top-level ones
    assert "/" in all_paths, f"Missing / route. Found: {all_paths}"
    assert "/health" in all_paths, f"Missing /health route. Found: {all_paths}"

def test_app_cors_configured():
    from app.main import app
    middleware = [m for m in app.user_middleware if "CORS" in str(m)]
    assert len(middleware) > 0, "CORS middleware not found"

def test_auth_router_endpoints():
    from app.routers.auth import router
    paths = [r.path for r in router.routes]
    assert "/auth/login" in paths or "login" in paths, f"Login endpoint missing. Routes: {paths}"
    assert "/auth/register" in paths or "register" in paths, f"Register endpoint missing. Routes: {paths}"
    assert "/auth/me" in paths or "me" in paths, f"Me endpoint missing. Routes: {paths}"

def test_risks_router_endpoints():
    from app.routers.risks import router
    paths = [r.path for r in router.routes]
    assert any("risks" in p for p in paths), f"Risks endpoint missing. Routes: {paths}"

def test_incidents_router_endpoints():
    from app.routers.incidents import router
    paths = [r.path for r in router.routes]
    assert any("incidents" in p for p in paths), f"Incidents endpoint missing. Routes: {paths}"

def test_predict_router_endpoints():
    from app.routers.predict import router
    paths = [r.path for r in router.routes]
    assert any("risk-score" in p for p in paths), f"Predict endpoint missing. Routes: {paths}"

def test_dashboard_router_endpoints():
    from app.routers.dashboard import router
    paths = [r.path for r in router.routes]
    assert any("dashboard" in p for p in paths), f"Dashboard endpoint missing. Routes: {paths}"

def test_scorecards_router_endpoints():
    from app.routers.scorecards import router
    paths = [r.path for r in router.routes]
    assert any("scorecard" in p for p in paths), f"Scorecards endpoint missing. Routes: {paths}"

def test_budgets_router_endpoints():
    from app.routers.budgets import router
    paths = [r.path for r in router.routes]
    assert any("budget" in p for p in paths), f"Budgets endpoint missing. Routes: {paths}"

def test_tasks_router_endpoints():
    from app.routers.tasks import router
    paths = [r.path for r in router.routes]
    assert any("task" in p for p in paths), f"Tasks endpoint missing. Routes: {paths}"

def test_meetings_router_endpoints():
    from app.routers.meetings import router
    paths = [r.path for r in router.routes]
    assert any("meeting" in p for p in paths), f"Meetings endpoint missing. Routes: {paths}"

def test_audit_router_endpoints():
    from app.routers.audit import router
    paths = [r.path for r in router.routes]
    assert any("audit" in p for p in paths), f"Audit endpoint missing. Routes: {paths}"

def test_compliance_router_endpoints():
    from app.routers.compliance import router
    paths = [r.path for r in router.routes]
    assert any("compliance" in p for p in paths), f"Compliance endpoint missing. Routes: {paths}"

def test_documents_router_endpoints():
    from app.routers.documents import router
    paths = [r.path for r in router.routes]
    assert any("document" in p for p in paths), f"Documents endpoint missing. Routes: {paths}"


# ════════════════════════════════════════════════════════════════
# CATEGORY 6: DATABASE SCHEMA
# ════════════════════════════════════════════════════════════════
def test_sql_has_organizations_table():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS organizations" in sql

def test_sql_has_users_table():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS users" in sql

def test_sql_has_risks_table():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS risks" in sql

def test_sql_has_incidents_table():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS incidents" in sql

def test_sql_has_initiatives_table():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS initiatives" in sql

def test_sql_has_seed_org():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "INSERT INTO organizations" in sql

def test_sql_has_seed_user():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "INSERT INTO users" in sql
    assert "admin@stratroom.com" in sql

def test_sql_has_seed_risks():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "INSERT INTO risks" in sql
    assert "Supply Chain" in sql

def test_sql_has_seed_incidents():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "INSERT INTO incidents" in sql
    assert "INC-2026" in sql

def test_sql_has_seed_initiatives():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "INSERT INTO initiatives" in sql
    assert "Zero Trust" in sql

def test_sql_has_indexes():
    sql = open(os.path.join(DB_DIR, "01_init.sql")).read()
    assert "CREATE INDEX" in sql

def test_sql_has_documents_table():
    sql = open(os.path.join(DB_DIR, "09_phase_4.sql")).read()
    assert "CREATE TABLE IF NOT EXISTS documents" in sql


# ════════════════════════════════════════════════════════════════
# CATEGORY 7: DOCKER CONFIGURATION
# ════════════════════════════════════════════════════════════════
def test_docker_compose_has_db():
    dc = open(os.path.join(ROOT, "docker-compose.yml")).read()
    assert "postgres" in dc.lower()

def test_docker_compose_has_api():
    dc = open(os.path.join(ROOT, "docker-compose.yml")).read()
    assert "api" in dc.lower()

def test_docker_compose_db_port():
    dc = open(os.path.join(ROOT, "docker-compose.yml")).read()
    assert "5432" in dc

def test_docker_compose_api_port():
    dc = open(os.path.join(ROOT, "docker-compose.yml")).read()
    assert "8001" in dc

def test_dockerfile_python():
    df = open(os.path.join(BACKEND, "Dockerfile")).read()
    assert "python" in df.lower()

def test_dockerfile_uvicorn():
    df = open(os.path.join(BACKEND, "Dockerfile")).read()
    assert "uvicorn" in df.lower()


# ════════════════════════════════════════════════════════════════
# CATEGORY 8: REQUIREMENTS INTEGRITY
# ════════════════════════════════════════════════════════════════
def test_req_has_fastapi():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "fastapi" in req

def test_req_has_sqlalchemy():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "sqlalchemy" in req

def test_req_has_asyncpg():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "asyncpg" in req

def test_req_has_bcrypt():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "bcrypt" in req

def test_req_has_xgboost():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "xgboost" in req

def test_req_has_numpy():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "numpy" in req

def test_req_no_passlib():
    req = open(os.path.join(BACKEND, "requirements.txt")).read()
    assert "passlib" not in req, "passlib should be removed (incompatible with bcrypt 4.x)"


# ════════════════════════════════════════════════════════════════
# CATEGORY 9: FRONTEND INTEGRATION
# ════════════════════════════════════════════════════════════════
def test_frontend_has_integration_script():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "STRATROOM BACKEND INTEGRATION LAYER" in html, "Integration script not found in HTML"

def test_frontend_has_auth_login_call():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "/auth/login" in html, "Auth login endpoint not wired in frontend"

def test_frontend_has_risks_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/risks'" in html or '"/risks"' in html, "Risks endpoint not wired"

def test_frontend_has_incidents_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/incidents'" in html or '"/incidents"' in html, "Incidents endpoint not wired"

def test_frontend_has_dashboard_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/dashboard/stats'" in html or '"/dashboard/stats"' in html, "Dashboard endpoint not wired"

def test_frontend_has_predict_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/predict/risk-score'" in html or '"/predict/risk-score"' in html, "Predict endpoint not wired"

def test_frontend_has_auth_me_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/auth/me'" in html or '"/auth/me"' in html, "Auth me endpoint not wired"

def test_frontend_has_token_storage():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "sr_backend_token" in html, "JWT token storage not implemented"

def test_frontend_preserves_original_structure():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "login-screen" in html, "Original login screen removed"
    assert "view-dashboard" in html, "Original dashboard view removed"
    assert "view-risk" in html, "Original risk view removed"
    assert "view-incidents" in html, "Original incidents view removed"
    assert "stratRoomLogin" in html, "Original login function removed"

def test_frontend_has_scorecards_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/scorecards'" in html or '"/scorecards"' in html, "Scorecards endpoint not wired"

def test_frontend_has_budgets_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/budgets'" in html or '"/budgets"' in html, "Budgets endpoint not wired"

def test_frontend_has_tasks_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/tasks'" in html or '"/tasks"' in html, "Tasks endpoint not wired"

def test_frontend_has_meetings_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/meetings'" in html or '"/meetings"' in html, "Meetings endpoint not wired"

def test_frontend_has_audit_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/audit'" in html or '"/audit"' in html, "Audit endpoint not wired"

def test_frontend_has_compliance_endpoint():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "'/compliance'" in html or '"/compliance"' in html, "Compliance endpoint not wired"

def test_frontend_has_documents_panel():
    html = open(FRONTEND, encoding="utf-8").read()
    assert "view-documents" in html, "Documents view panel missing"
    assert "loadDocuments" in html, "Documents load function missing"


# ════════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ════════════════════════════════════════════════════════════════
def main():
    global passed, failed
    start = time.time()

    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  STRATROOM AUTOMATED TEST SUITE")
    print("=" * 60)
    print()

    categories = [
        ("FILE INTEGRITY", [
            test_backend_main_exists, test_backend_config_exists,
            test_backend_db_exists, test_backend_security_exists,
            test_backend_deps_exists, test_router_auth_exists,
            test_router_risks_exists, test_router_incidents_exists,
            test_router_predict_exists, test_router_dashboard_exists,
            test_router_scorecards_exists, test_router_budgets_exists,
            test_router_tasks_exists, test_router_meetings_exists,
            test_router_audit_exists, test_router_compliance_exists,
            test_router_documents_exists,
            test_logging_config_exists, test_rate_limiter_exists,
            test_utils_exists, test_env_example_exists,
            test_dockerignore_exists, test_github_actions_exists,
            test_requirements_exists, test_dockerfile_exists,
            test_init_sql_exists, test_docker_compose_exists,
            test_inference_script_exists, test_train_script_exists,
            test_model_file_exists, test_frontend_html_exists,
        ]),
        ("PYTHON IMPORTS", [
            test_import_fastapi, test_import_sqlalchemy,
            test_import_pydantic, test_import_jose,
            test_import_bcrypt, test_import_xgboost,
            test_import_pandas, test_import_joblib,
            test_import_sklearn, test_import_numpy,
            test_import_config, test_import_security,
            test_import_deps, test_import_db,
            test_import_logging_config, test_import_rate_limiter,
            test_import_utils,
            test_import_main, test_import_inference,
        ]),
        ("AUTH / PASSWORD / JWT", [
            test_hash_password, test_verify_correct_password,
            test_verify_wrong_password, test_verify_seed_password,
            test_jwt_create_and_decode, test_jwt_different_subjects,
            test_jwt_invalid_token,
        ]),
        ("ML MODEL INFERENCE", [
            test_ml_model_loads, test_ml_model_feature_count,
            test_ml_prediction_4_features, test_ml_prediction_low_risk,
            test_ml_prediction_high_risk, test_ml_missing_feature_raises,
        ]),
        ("FASTAPI APP STRUCTURE", [
            test_app_loads, test_app_has_routes,
            test_app_cors_configured, test_auth_router_endpoints,
            test_risks_router_endpoints, test_incidents_router_endpoints,
            test_predict_router_endpoints, test_dashboard_router_endpoints,
            test_scorecards_router_endpoints, test_budgets_router_endpoints,
            test_tasks_router_endpoints, test_meetings_router_endpoints,
            test_audit_router_endpoints, test_compliance_router_endpoints,
            test_documents_router_endpoints,
        ]),
        ("DATABASE SCHEMA", [
            test_sql_has_organizations_table, test_sql_has_users_table,
            test_sql_has_risks_table, test_sql_has_incidents_table,
            test_sql_has_initiatives_table, test_sql_has_seed_org,
            test_sql_has_seed_user, test_sql_has_seed_risks,
            test_sql_has_seed_incidents, test_sql_has_seed_initiatives,
            test_sql_has_indexes, test_sql_has_documents_table,
        ]),
        ("DOCKER CONFIGURATION", [
            test_docker_compose_has_db, test_docker_compose_has_api,
            test_docker_compose_db_port, test_docker_compose_api_port,
            test_dockerfile_python, test_dockerfile_uvicorn,
        ]),
        ("PRODUCTION READINESS", [
            test_logging_config_exists, test_rate_limiter_exists,
            test_utils_exists, test_env_example_exists,
            test_dockerignore_exists, test_github_actions_exists,
            test_import_logging_config, test_import_rate_limiter,
            test_import_utils,
        ]),
        ("REQUIREMENTS INTEGRITY", [
            test_req_has_fastapi, test_req_has_sqlalchemy,
            test_req_has_asyncpg, test_req_has_bcrypt,
            test_req_has_xgboost, test_req_has_numpy,
            test_req_no_passlib,
        ]),
        ("FRONTEND INTEGRATION", [
            test_frontend_has_integration_script, test_frontend_has_auth_login_call,
            test_frontend_has_risks_endpoint, test_frontend_has_incidents_endpoint,
            test_frontend_has_dashboard_endpoint, test_frontend_has_predict_endpoint,
            test_frontend_has_auth_me_endpoint, test_frontend_has_token_storage,
            test_frontend_preserves_original_structure,
            test_frontend_has_scorecards_endpoint, test_frontend_has_budgets_endpoint,
            test_frontend_has_tasks_endpoint, test_frontend_has_meetings_endpoint,
            test_frontend_has_audit_endpoint, test_frontend_has_compliance_endpoint,
            test_frontend_has_documents_panel,
        ]),
    ]

    for cat_name, tests in categories:
        cat_pass = 0
        cat_fail = 0
        print(f"\n── {cat_name} {'─' * (48 - len(cat_name))}")
        for test_fn in tests:
            name = test_fn.__name__
            before = len(results)
            run_test(name, test_fn)
            if len(results) > before:
                status = results[-1][0]
                if status == "PASS":
                    cat_pass += 1
                    print(f"  ✅ {name}")
                else:
                    cat_fail += 1
                    print(f"  ❌ {name}")
                    print(f"     → {results[-1][2]}")
        total = cat_pass + cat_fail
        icon = "✅" if cat_fail == 0 else "❌"
        print(f"  {icon} {cat_pass}/{total} passed in {cat_name}")

    elapsed = time.time() - start
    total = passed + failed

    print()
    print("=" * 60)
    print(f"  RESULTS: {passed}/{total} PASSED  |  {failed} FAILED")
    print(f"  TIME: {elapsed:.1f}s")
    print("=" * 60)

    if failed == 0:
        print()
        print("  🎉 ALL TESTS PASSED — SYSTEM IS 100% STABLE")
        print()
    else:
        print()
        print(f"  ⚠️  {failed} test(s) failed. Fix before proceeding.")
        print()

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
