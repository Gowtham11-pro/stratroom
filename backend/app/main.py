import os
import uuid
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse

from app.core.config import settings
from app.core.logging_config import setup_logging, correlation_id_var, request_id_var
from app.core.db import check_db_health
from app.core.rate_limiter import limiter
from app.ai.metrics import counters
from app.services.java_bridge import bridge
from app.routers import (
    auth, incidents, risks, predict, dashboard, scorecards, budgets,
    tasks, meetings, audit, complaints, compliance, swot, pestel_projects, org,
    bcp, ai, initiatives, agents, ml, documents, compat, api_v1,
)

setup_logging(
    level=settings.LOG_LEVEL,
    json_mode=settings.LOG_JSON_MODE,
)

logger = logging.getLogger("stratroom")

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("StratRoom API starting — env=%s version=%s", settings.ENVIRONMENT, settings.APP_VERSION)
    yield
    await bridge.close()
    logger.info("StratRoom API shutting down")


app = FastAPI(
    title="StratRoom API",
    description="Enterprise AI Governance & Risk Management Platform",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
    max_age=600,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:16])
    request.state.request_id = request_id
    correlation_id = uuid.uuid4().hex[:12]
    request.state.correlation_id = correlation_id

    token_r = request_id_var.set(request_id)
    token_c = correlation_id_var.set(correlation_id)

    is_health = request.url.path in ("/health", "/ready", "/live", "/metrics")
    if not is_health:
        client_ip = request.client.host if request.client else "unknown"
        rate_key = f"ip:{client_ip}"
        allowed, retry_after = limiter.is_allowed(
            rate_key, settings.RATE_LIMIT_PER_MINUTE, window_seconds=60
        )
        if not allowed:
            request_id_var.reset(token_r)
            correlation_id_var.reset(token_c)
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": retry_after},
                headers={"X-Request-ID": request_id, "Retry-After": str(retry_after)},
            )

    start = time.time()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        logger.exception("Unhandled exception on %s %s [req=%s]", request.method, request.url.path, request_id)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    finally:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        request_id_var.reset(token_r)
        correlation_id_var.reset(token_c)

        is_health = request.url.path in ("/health", "/ready", "/live")
        if not is_health:
            logger.info(
                "%s %s %s %sms [req=%s]",
                request.method, request.url.path, status_code, elapsed_ms, request_id,
            )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.exception(
        "Unhandled exception on %s %s [req=%s corr=%s]",
        request.method, request.url.path, request_id, correlation_id,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
        headers={"X-Request-ID": request_id, "X-Correlation-ID": correlation_id},
    )


app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(risks.router)
app.include_router(predict.router)
app.include_router(dashboard.router)
app.include_router(scorecards.router)
app.include_router(budgets.router)
app.include_router(tasks.router)
app.include_router(meetings.router)
app.include_router(audit.router)
app.include_router(complaints.router)
app.include_router(compliance.router)
app.include_router(swot.router)
app.include_router(pestel_projects.router)
app.include_router(org.router)
app.include_router(bcp.router)
app.include_router(ai.router)
app.include_router(initiatives.router)
app.include_router(agents.router)
app.include_router(ml.router)
app.include_router(documents.router)
app.include_router(compat.router)
app.include_router(api_v1.router)


@app.get("/health", tags=["monitoring"])
async def health():
    """Liveness probe — confirms process is running."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/ready", tags=["monitoring"])
async def readiness():
    """Readiness probe — confirms service can handle requests."""
    db_ok = await check_db_health()
    mysql_ok = False
    try:
        await bridge.get(bridge.db_service, "/userList")
        mysql_ok = True
    except Exception:
        pass
    all_ok = db_ok or mysql_ok
    return {
        "status": "ready" if all_ok else "degraded",
        "database": "ok" if db_ok else "unavailable",
        "mysql": "ok" if mysql_ok else "unavailable",
        "uptime_seconds": round(time.time() - _start_time, 0),
    }


@app.get("/metrics", tags=["monitoring"])
async def metrics():
    """Basic metrics endpoint for monitoring systems."""
    return {
        "uptime_seconds": round(time.time() - _start_time, 0),
        "ai_metrics": counters.snapshot(),
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "31may_index.html")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(
        HTML_PATH,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
