"""AI Memory — long-term insight storage for agents.

Stores meaningful insights from agent conversations, retrieves them for context
enhancement, and prunes stale/low-value entries. All operations fail gracefully.
"""
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("stratroom.ai.memory")

MAX_MEMORIES_PER_AGENT = 200
CONFIDENCE_THRESHOLD = 0.3
MIN_INSIGHT_LENGTH = 40

_TRIVIAL_PATTERNS = re.compile(
    r"^(hello|hi|hey|thanks|thank you|ok|okay|sure|yes|no|got it|understood|"
    r"good morning|good afternoon|good evening|bye|goodbye|see you|"
    r"help|what can you do|who are you)[\s!?.]*$",
    re.IGNORECASE,
)


def _compute_confidence(message: str, response: str) -> float:
    """Simple heuristic: data-rich responses get higher confidence."""
    score = 0.4
    if any(c.isdigit() for c in response):
        score += 0.15
    if "%" in response or "$" in response:
        score += 0.1
    if any(kw in response.lower() for kw in ("recommend", "should", "priority", "risk", "critical")):
        score += 0.15
    if len(response) > 200:
        score += 0.1
    if len(message) > 30:
        score += 0.1
    return min(score, 1.0)


def _is_insight_worthy(message: str, response: str) -> bool:
    """Filter out greetings, small talk, and trivial exchanges."""
    if _TRIVIAL_PATTERNS.match(message.strip()):
        return False
    if len(response.strip()) < MIN_INSIGHT_LENGTH:
        return False
    if len(message.strip()) < 10:
        return False
    return True


def _normalize(text_content: str) -> str:
    """Normalize for dedup comparison: lowercase, collapse whitespace, first 80 chars."""
    normalized = re.sub(r"\s+", " ", text_content.strip().lower())
    return normalized[:80]


async def store_memory(
    db: AsyncSession,
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    insight: str,
    source: str = "conversation",
    confidence: float | None = None,
    message: str = "",
) -> bool:
    """Store an insight. Returns True if stored, False if skipped (trivial/duplicate).

    Never raises.
    """
    try:
        async with db.begin_nested():
            if not _is_insight_worthy(message, insight):
                return False

            if confidence is None:
                confidence = _compute_confidence(message, insight)

            if confidence < CONFIDENCE_THRESHOLD:
                return False

            # Duplicate detection: check for existing insight with same prefix
            prefix = _normalize(insight)
            existing = await db.execute(
                text(
                    "SELECT id FROM ai_memory "
                    "WHERE user_id = :uid AND agent_name = :agent "
                    "AND LEFT(LOWER(insight), 80) = :prefix LIMIT 1"
                ),
                {"uid": user_id, "agent": agent_name, "prefix": prefix},
            )
            if existing.first():
                return False

            await db.execute(
                text(
                    "INSERT INTO ai_memory (user_id, org_id, agent_name, insight, source, confidence) "
                    "VALUES (:uid, :org_id, :agent, :insight, :source, :conf)"
                ),
                {
                    "uid": user_id,
                    "org_id": org_id,
                    "agent": agent_name,
                    "insight": insight[:5000],
                    "source": source,
                    "conf": confidence,
                },
            )
            return True
    except Exception:
        logger.exception("Failed to store memory")
        return False


async def retrieve_memory(
    db: AsyncSession,
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    limit: int = 10,
) -> list[dict]:
    """Retrieve relevant memories for a user+agent, ranked by confidence and recency.

    Falls back to org-wide memories if no user-specific ones exist.
    Never raises.
    """
    try:
        async with db.begin_nested():
            # User-specific memories first
            result = await db.execute(
                text(
                    "SELECT id, insight, confidence, source, created_at, access_count "
                    "FROM ai_memory "
                    "WHERE user_id = :uid AND agent_name = :agent "
                    "ORDER BY confidence DESC, accessed_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "agent": agent_name, "lim": limit},
            )
            rows = result.mappings().all()

            # Fall back to org-wide memories if few user-specific ones
            if len(rows) < 3 and org_id:
                result = await db.execute(
                    text(
                        "SELECT id, insight, confidence, source, created_at, access_count "
                        "FROM ai_memory "
                        "WHERE org_id = :org_id AND agent_name = :agent "
                        "AND (user_id IS NULL OR user_id != :uid) "
                        "ORDER BY confidence DESC, accessed_at DESC LIMIT :lim"
                    ),
                    {"org_id": org_id, "uid": user_id, "agent": agent_name, "lim": limit},
                )
                org_rows = result.mappings().all()
                existing_ids = {r["id"] for r in rows}
                for r in org_rows:
                    if r["id"] not in existing_ids and len(rows) < limit:
                        rows.append(r)

            # Update access timestamps in fire-and-forget style
            memory_ids = [r["id"] for r in rows]
            if memory_ids:
                await _update_access_batch(db, memory_ids)

            return [dict(r) for r in rows]
    except Exception:
        logger.exception("Failed to retrieve memory")
        return []


async def _update_access_batch(db: AsyncSession, memory_ids: list[int]):
    """Batch update access for multiple memory IDs."""
    try:
        await db.execute(
            text(
                "UPDATE ai_memory SET access_count = access_count + 1, accessed_at = now() "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": memory_ids},
        )
    except Exception:
        logger.exception("Failed to batch-update memory access")


async def prune_memory(
    db: AsyncSession,
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    max_memories: int = MAX_MEMORIES_PER_AGENT,
) -> int:
    """Remove oldest/least-accessed memories when count exceeds max.

    Returns number of pruned entries. Never raises.
    """
    try:
        # Count current memories
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM ai_memory "
                "WHERE user_id = :uid AND agent_name = :agent"
            ),
            {"uid": user_id, "agent": agent_name},
        )
        count = result.scalar() or 0

        if count <= max_memories:
            return 0

        excess = count - max_memories
        await db.execute(
            text(
                "DELETE FROM ai_memory WHERE id IN ("
                "  SELECT id FROM ai_memory "
                "  WHERE user_id = :uid AND agent_name = :agent "
                "  ORDER BY access_count ASC, confidence ASC, created_at ASC "
                "  LIMIT :excess"
                ")"
            ),
            {"uid": user_id, "agent": agent_name, "excess": excess},
        )
        logger.info("Pruned %d memories for user=%s agent=%s", excess, user_id, agent_name)
        return excess
    except Exception:
        logger.exception("Failed to prune memory")
        return 0
