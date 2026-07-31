"""AI Memory — long-term insight storage for agents.

Stores meaningful insights from agent conversations in MySQL, retrieves them
for context enhancement, and prunes stale/low-value entries. All operations
fail gracefully.
"""
import logging
import re

from app.services.java_bridge import bridge

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
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    insight: str,
    source: str = "conversation",
    confidence: float | None = None,
    message: str = "",
) -> bool:
    """Store an insight in MySQL ai_memory. Returns True if stored, False if skipped (trivial/duplicate).

    Never raises.
    """
    try:
        if not _is_insight_worthy(message, insight):
            return False

        if confidence is None:
            confidence = _compute_confidence(message, insight)

        if confidence < CONFIDENCE_THRESHOLD:
            return False

        # Duplicate detection: check for existing insight with same prefix
        prefix = _normalize(insight)
        existing = await bridge._mysql(
            "SELECT id FROM ai_memory "
            "WHERE user_id = %s AND agent_name = %s "
            "AND LEFT(LOWER(insight), 80) = %s LIMIT 1",
            (user_id, agent_name, prefix),
        )
        if existing:
            return False

        await bridge._mysql_write(
            "INSERT INTO ai_memory (user_id, org_id, agent_name, insight, source, confidence) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, org_id, agent_name, insight[:5000], source, confidence),
        )
        return True
    except Exception:
        logger.exception("Failed to store memory")
        return False


async def retrieve_memory(
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    limit: int = 10,
) -> list[dict]:
    """Retrieve relevant memories from MySQL ai_memory, ranked by confidence and recency.

    Falls back to org-wide memories if no user-specific ones exist.
    Never raises.
    """
    try:
        # User-specific memories first
        rows = await bridge._mysql(
            "SELECT id, insight, confidence, source, created_at, access_count "
            "FROM ai_memory "
            "WHERE user_id = %s AND agent_name = %s "
            "ORDER BY confidence DESC, accessed_at DESC LIMIT %s",
            (user_id, agent_name, limit),
        )

        # Fall back to org-wide memories if few user-specific ones
        if len(rows) < 3 and org_id:
            org_rows = await bridge._mysql(
                "SELECT id, insight, confidence, source, created_at, access_count "
                "FROM ai_memory "
                "WHERE org_id = %s AND agent_name = %s "
                "AND (user_id IS NULL OR user_id != %s) "
                "ORDER BY confidence DESC, accessed_at DESC LIMIT %s",
                (org_id, agent_name, user_id, limit),
            )
            existing_ids = {r["id"] for r in rows}
            for r in org_rows:
                if r["id"] not in existing_ids and len(rows) < limit:
                    rows.append(r)

        # Update access timestamps in fire-and-forget style
        memory_ids = [r["id"] for r in rows]
        if memory_ids:
            await _update_access_batch(memory_ids)

        return rows
    except Exception:
        logger.exception("Failed to retrieve memory")
        return []


async def _update_access_batch(memory_ids: list[int]):
    """Batch update access for multiple memory IDs in MySQL."""
    try:
        placeholders = ",".join(["%s"] * len(memory_ids))
        await bridge._mysql_write(
            f"UPDATE ai_memory SET access_count = access_count + 1, accessed_at = NOW() "
            f"WHERE id IN ({placeholders})",
            tuple(memory_ids),
        )
    except Exception:
        logger.exception("Failed to batch-update memory access")


async def prune_memory(
    *,
    user_id: int | None,
    org_id: int | None,
    agent_name: str,
    max_memories: int = MAX_MEMORIES_PER_AGENT,
) -> int:
    """Remove oldest/least-accessed memories from MySQL when count exceeds max.

    Returns number of pruned entries. Never raises.
    """
    try:
        # Count current memories
        count_rows = await bridge._mysql(
            "SELECT COUNT(*) as cnt FROM ai_memory "
            "WHERE user_id = %s AND agent_name = %s",
            (user_id, agent_name),
        )
        count = count_rows[0]["cnt"] if count_rows else 0

        if count <= max_memories:
            return 0

        excess = count - max_memories
        # MySQL requires JOIN for DELETE with LIMIT
        await bridge._mysql_write(
            "DELETE m FROM ai_memory m "
            "JOIN ("
            "  SELECT id FROM ai_memory "
            "  WHERE user_id = %s AND agent_name = %s "
            "  ORDER BY access_count ASC, confidence ASC, created_at ASC "
            "  LIMIT %s"
            ") AS to_delete ON m.id = to_delete.id",
            (user_id, agent_name, excess),
        )
        logger.info("Pruned %d memories for user=%s agent=%s", excess, user_id, agent_name)
        return excess
    except Exception:
        logger.exception("Failed to prune memory")
        return 0
