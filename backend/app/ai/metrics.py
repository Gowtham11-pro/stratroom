"""Lightweight AI observability — logs agent runs to the database and tracks in-memory counters."""
import logging
import time
import threading

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.ai.metrics")


class _Counters:
    """Thread-safe in-memory aggregate counters. No DB dependency."""
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.total_requests = 0
            self.successful_requests = 0
            self.failed_requests = 0
            self.total_duration_ms = 0
            self.retry_count = 0
            self.tool_failures = 0
            self.memory_retrieval_failures = 0
            self.guardrail_blocks = 0
            self._started = time.time()

    def record(self, *, status: str, duration_ms: int = 0, retries: int = 0):
        with self._lock:
            self.total_requests += 1
            if status == "success":
                self.successful_requests += 1
            else:
                self.failed_requests += 1
            self.total_duration_ms += duration_ms
            self.retry_count += retries

    def record_tool_failure(self):
        with self._lock:
            self.tool_failures += 1

    def record_memory_failure(self):
        with self._lock:
            self.memory_retrieval_failures += 1

    def record_guardrail_block(self):
        with self._lock:
            self.guardrail_blocks += 1

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self._started
            avg_ms = (self.total_duration_ms / self.total_requests) if self.total_requests else 0
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "average_duration_ms": round(avg_ms, 1),
                "retry_count": self.retry_count,
                "tool_failures": self.tool_failures,
                "memory_retrieval_failures": self.memory_retrieval_failures,
                "guardrail_blocks": self.guardrail_blocks,
                "uptime_seconds": round(uptime, 0),
            }


counters = _Counters()


async def log_agent_run(
    db: AsyncSession,
    *,
    org_id: int | None,
    user_id: int | None,
    agent_name: str,
    provider: str,
    model: str,
    conversation_id: int | None,
    status: str,
    duration_ms: int | None = None,
    token_count: int | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
):
    """Insert a row into ai_agent_runs and update in-memory counters.

    Never raises — failures are logged and swallowed.
    """
    try:
        counters.record(status=status, duration_ms=duration_ms or 0, retries=retry_count)
        await db.execute(
            text(
                "INSERT INTO ai_agent_runs "
                "(org_id, user_id, agent_name, provider, model, conversation_id, "
                "status, duration_ms, token_count, error_message) "
                "VALUES (:org_id, :user_id, :agent, :provider, :model, :conv_id, "
                ":status, :duration, :tokens, :error)"
            ),
            {
                "org_id": org_id,
                "user_id": user_id,
                "agent": agent_name,
                "provider": provider,
                "model": model,
                "conv_id": conversation_id,
                "status": status,
                "duration": duration_ms,
                "tokens": token_count,
                "error": error_message,
            },
        )
    except Exception:
        logger.exception("Failed to log AI agent run")
