"""Query Enhancer — prepares enriched context before AgentRunner.

Retrieves relevant memories from MySQL, recent conversation summaries, and
organization context to provide a richer system prompt. Does NOT classify
intent, replace agents, orchestrate, or redesign routing.
"""
import logging

from app.ai.memory import retrieve_memory
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.ai.enhancer")

MAX_RECENT_CONVERSATIONS = 3
MAX_RECENT_MESSAGES_PER_CONV = 3


async def enhance_context(
    *,
    agent_name: str,
    user_id: int | None,
    org_id: int | None,
    user_message: str,
    conversation_id: int | None = None,
) -> str:
    """Build an enriched context block to prepend to the system prompt.

    Combines:
      1. Relevant long-term memories (MySQL ai_memory)
      2. Recent conversation summaries (MySQL agent_conversations)
      3. Organization context hint

    Returns empty string on failure — agents continue without enhancement.
    """
    sections = []

    # 1. Long-term memories
    memories = await retrieve_memory(
        user_id=user_id, org_id=org_id, agent_name=agent_name, limit=8,
    )
    if memories:
        mem_lines = []
        for m in memories:
            conf = m.get("confidence", 0.5)
            mem_lines.append(f"- [{conf:.0%}] {m['insight']}")
        sections.append(
            "--- RELEVANT MEMORIES ---\n" + "\n".join(mem_lines)
        )

    # 2. Recent conversation summaries (other conversations for this agent)
    recent = await _recent_conversation_summaries(agent_name, user_id, conversation_id)
    if recent:
        sections.append(
            "--- RECENT CONVERSATIONS ---\n" + "\n".join(recent)
        )

    # 3. Org context (lightweight — just agent name + module count hint)
    if org_id:
        sections.append(f"--- CONTEXT ---\nOrganization ID: {org_id} | Agent: {agent_name}")

    return "\n\n".join(sections)


async def _recent_conversation_summaries(
    agent_name: str,
    user_id: int | None,
    exclude_conversation_id: int | None = None,
) -> list[str]:
    """Fetch summaries of recent conversations for this user+agent from MySQL."""
    try:
        params_list = [agent_name]
        query = (
            "SELECT c.id, c.title, c.created_at "
            "FROM agent_conversations c "
            "WHERE c.agent_name = %s "
        )
        if user_id:
            query += "AND c.user_id = %s "
            params_list.append(user_id)
        if exclude_conversation_id:
            query += "AND c.id != %s "
            params_list.append(exclude_conversation_id)
        query += "ORDER BY c.created_at DESC LIMIT %s"
        params_list.append(MAX_RECENT_CONVERSATIONS)

        convos = await bridge._mysql(query, tuple(params_list))

        summaries = []
        for conv in convos:
            msgs = await bridge._mysql(
                "SELECT role, content FROM agent_messages "
                "WHERE conversation_id = %s ORDER BY id DESC LIMIT %s",
                (conv["id"], MAX_RECENT_MESSAGES_PER_CONV),
            )
            if msgs:
                snippet_parts = []
                for msg in reversed(msgs):
                    prefix = "User" if msg["role"] == "user" else "Agent"
                    snippet_parts.append(f"{prefix}: {msg['content'][:150]}")
                summaries.append(
                    f"[{conv['title'] or 'Chat'}]: " + " | ".join(snippet_parts)
                )
        return summaries
    except Exception:
        logger.exception("Failed to fetch recent conversation summaries")
        return []
