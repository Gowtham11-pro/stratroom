import json
import re
import time
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import AGENT_PROMPTS
from app.agents.tools import fetch_agent_context
from app.ai.llm_providers import call_llm_with_retry
from app.ai.metrics import log_agent_run, counters
from app.ai.query_enhancer import enhance_context
from app.ai.memory import store_memory, prune_memory
from app.ai.guardrails import validate_response

logger = logging.getLogger("stratroom.ai.agents")

# ── Tool call pattern ────────────────────────────────────────────────────────
# The LLM outputs [TOOL_CALL:tool_name:arg1:arg2:...] and the runner
# executes the tool, then feeds the result back for a final answer.
_TOOL_CALL_RE = re.compile(r"\[TOOL_CALL:([^\]:]+)(?::([^\]]*))?\]")


class AgentRunner:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.system_prompt = AGENT_PROMPTS.get(agent_name, "You are a helpful assistant.")

    async def run(
        self,
        db: AsyncSession,
        user_message: str,
        provider: str,
        api_key: str,
        model: str,
        user_id: int | None = None,
        org_id: int | None = None,
        conversation_id: int | None = None,
        base_url: str | None = None,
        is_admin: bool = False,
        ctx: dict | None = None,
    ) -> dict:
        context = await fetch_agent_context(db, self.agent_name, org_id)

        # Enrich context with memories and recent conversations
        enhanced = ""
        try:
            enhanced = await enhance_context(
                db,
                agent_name=self.agent_name,
                user_id=user_id,
                org_id=org_id,
                user_message=user_message,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.warning("Query enhancement failed for agent=%s", self.agent_name)

        full_system = self.system_prompt
        if enhanced:
            full_system += "\n\n" + enhanced
        full_system += "\n\n--- CURRENT ORGANIZATION DATA ---\n" + context

        messages = []
        if conversation_id:
            history = await self._load_history(db, conversation_id)
            messages = history

        # Rewrite confusing queries (e.g. "my tasks" -> "all tasks")
        try:
            rewritten = await self._auto_fetch_tool(db, user_message, user_id, org_id, is_admin, ctx)
            if rewritten and rewritten != user_message:
                user_message = rewritten
        except Exception:
            pass

        messages.append({"role": "user", "content": user_message})

        start_ms = time.time()
        status = "success"
        error_message = None
        response_text = ""
        retry_count = 0
        tool_results = []

        try:
            response_text, retry_count = await call_llm_with_retry(
                provider=provider,
                api_key=api_key,
                model=model,
                system_prompt=full_system,
                messages=messages,
                base_url=base_url,
            )

            # ── Tool-calling loop (max 3 iterations) ────────────────────
            for _tool_iter in range(3):
                tool_match = _TOOL_CALL_RE.search(response_text)
                if not tool_match:
                    break

                tool_name = tool_match.group(1).strip()
                tool_args_raw = tool_match.group(2).strip() if tool_match.group(2) else ""

                tool_result = await self._execute_tool(
                    db, tool_name, tool_args_raw, user_id, org_id, is_admin, ctx
                )
                tool_results.append({
                    "tool": tool_name,
                    "args": tool_args_raw,
                    "result": tool_result,
                })

                # Replace the tool call marker with the result for the LLM
                tool_block = tool_match.group(0)
                result_summary = (
                    json.dumps(tool_result) if isinstance(tool_result, dict)
                    else str(tool_result)
                )
                response_text = response_text.replace(
                    tool_block,
                    f"[TOOL_RESULT:{tool_name}]{result_summary}[/TOOL_RESULT]",
                )

                # Feed back to LLM for a natural-language summary
                messages.append({"role": "assistant", "content": response_text})
                messages.append({
                    "role": "user",
                    "content": (
                        f"The tool '{tool_name}' returned the following result. "
                        f"Summarize it naturally for the user. If the user asked to update something, "
                        f"confirm the change was saved to the database.\n\n"
                        f"[TOOL_RESULT]{result_summary}[/TOOL_RESULT]"
                    ),
                })

                response_text, retry_count2 = await call_llm_with_retry(
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    system_prompt=full_system,
                    messages=messages,
                    base_url=base_url,
                )
                retry_count += retry_count2

        except Exception as exc:
            status = "error"
            error_message = str(exc)[:500]
            raise
        finally:
            elapsed_ms = int((time.time() - start_ms) * 1000)
            await log_agent_run(
                db,
                org_id=org_id,
                user_id=user_id,
                agent_name=self.agent_name,
                provider=provider,
                model=model,
                conversation_id=conversation_id,
                status=status,
                duration_ms=elapsed_ms,
                error_message=error_message,
                retry_count=retry_count,
            )
            try:
                await db.commit()
            except Exception:
                logger.warning("Failed to commit metrics in finally block for agent=%s", self.agent_name)

        # Output guardrails
        is_valid, response_text, guardrail_reason = validate_response(response_text, self.agent_name)
        if not is_valid:
            counters.record_guardrail_block()
            logger.warning("Guardrail triggered for agent=%s: %s", self.agent_name, guardrail_reason)

        if not conversation_id:
            try:
                conversation_id = await self._create_conversation(db, user_id, org_id)
            except Exception:
                logger.exception("Failed to create conversation for agent=%s", self.agent_name)
                conversation_id = None

        if conversation_id:
            try:
                await self._save_message(db, conversation_id, "user", user_message)
                await self._save_message(db, conversation_id, "assistant", response_text)
            except Exception:
                logger.exception("Failed to save messages for agent=%s conv=%s", self.agent_name, conversation_id)

        # Store insight and prune — failures are silent
        try:
            await store_memory(
                db,
                user_id=user_id,
                org_id=org_id,
                agent_name=self.agent_name,
                insight=response_text[:2000],
                source=f"conversation:{conversation_id}",
                message=user_message,
            )
            await prune_memory(
                db, user_id=user_id, org_id=org_id, agent_name=self.agent_name,
            )
        except Exception:
            counters.record_memory_failure()
            logger.warning("Memory store/prune failed for agent=%s", self.agent_name)

        try:
            await db.commit()
        except Exception:
            logger.warning("Failed to commit agent session for agent=%s", self.agent_name)

        final_ms = int((time.time() - start_ms) * 1000)

        result = {
            "conversation_id": conversation_id,
            "response": response_text,
            "agent": self.agent_name,
            "duration_ms": final_ms,
        }

        # Attach tool results if any tools were executed
        if tool_results:
            result["tool_results"] = tool_results

        return result

    # ── Auto-fetch: detect intent & rephrase query ─────────────────────
    async def _auto_fetch_tool(
        self,
        db: AsyncSession,
        user_message: str,
        user_id: int | None,
        org_id: int | None,
        is_admin: bool = False,
        ctx: dict | None = None,
    ) -> str:
        """Detect common intents and rephrase confusing queries for the LLM."""
        msg_lower = user_message.lower()

        if self.agent_name == "task":
            if "my task" in msg_lower or "my tasks" in msg_lower:
                return "Show me all tasks in the organization"
        return user_message

    # ── Tool execution ──────────────────────────────────────────────────
    async def _execute_tool(
        self,
        db: AsyncSession,
        tool_name: str,
        args_raw: str,
        user_id: int | None,
        org_id: int | None,
        is_admin: bool = False,
        ctx: dict | None = None,
    ) -> dict | str:
        """Route tool calls to the appropriate handler."""
        from app.agents.task_tools import query_user_tasks, update_task_progress, create_task_tool
        from app.agents.risk_tools import query_risks, create_risk, update_risk, delete_risk
        from app.agents.scorecard_tools import query_scorecards, query_scorecard_summary, create_scorecard, update_scorecard, delete_scorecard

        if not user_id or not org_id:
            return {"error": "User context not available."}

        def _parse_kv(args_raw: str) -> dict:
            """Parse key=value,key=value into a dict. Casts ints."""
            result = {}
            if not args_raw:
                return result
            for p in args_raw.split(","):
                p = p.strip()
                if "=" in p:
                    k, v = p.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # Try int conversion
                    try:
                        v = int(v)
                    except ValueError:
                        pass
                    result[k] = v
            return result

        try:
            # ── TASK TOOLS ──
            if tool_name == "query_tasks":
                parsed = _parse_kv(args_raw)
                return await query_user_tasks(
                    db, user_id, org_id,
                    status_filter=parsed.get("status"),
                    priority_filter=parsed.get("priority"),
                    is_admin=is_admin,
                )

            elif tool_name == "update_task":
                parsed = _parse_kv(args_raw)
                task_id = parsed.get("id")
                if not task_id or not isinstance(task_id, int):
                    return {"error": "Missing or invalid task id. Usage: [TOOL_CALL:update_task:id=123,status=in_progress]"}
                return await update_task_progress(
                    db, user_id, org_id, task_id,
                    status=parsed.get("status"),
                    is_admin=is_admin,
                )

            elif tool_name == "create_task":
                parsed = _parse_kv(args_raw)
                return await create_task_tool(
                    db, org_id,
                    title=parsed.get("title", ""),
                    agent=parsed.get("agent"),
                    priority=parsed.get("priority", "Medium"),
                    owner=parsed.get("owner"),
                    due_date=parsed.get("due_date"),
                    status=parsed.get("status", "pending"),
                    assigned_user_id=parsed.get("assigned_user_id"),
                )

            # ── RISK TOOLS ──
            elif tool_name == "query_risks":
                parsed = _parse_kv(args_raw)
                return await query_risks(
                    db, user_id, org_id,
                    status_filter=parsed.get("status"),
                    min_heat=parsed.get("min_heat"),
                    is_admin=is_admin,
                    email=(ctx or {}).get("email"),
                )

            elif tool_name == "create_risk":
                parsed = _parse_kv(args_raw)
                return await create_risk(
                    db, org_id,
                    name=parsed.get("name", ""),
                    owner=parsed.get("owner", ""),
                    description=parsed.get("description", ""),
                    mitigation=parsed.get("mitigation", ""),
                    inherent_likelihood=parsed.get("inherent_likelihood", 3),
                    inherent_impact=parsed.get("inherent_impact", 3),
                    residual_likelihood=parsed.get("residual_likelihood", 2),
                    residual_impact=parsed.get("residual_impact", 2),
                )

            elif tool_name == "update_risk":
                parsed = _parse_kv(args_raw)
                risk_id = parsed.get("id")
                if not risk_id or not isinstance(risk_id, int):
                    return {"error": "Missing or invalid risk id. Usage: [TOOL_CALL:update_risk:id=123,name=...,status=...]"}
                return await update_risk(
                    db, user_id, org_id, risk_id,
                    is_admin=is_admin,
                    email=(ctx or {}).get("email"),
                    name=parsed.get("name"),
                    owner=parsed.get("owner"),
                    description=parsed.get("description"),
                    mitigation=parsed.get("mitigation"),
                    inherent_likelihood=parsed.get("inherent_likelihood"),
                    inherent_impact=parsed.get("inherent_impact"),
                    residual_likelihood=parsed.get("residual_likelihood"),
                    residual_impact=parsed.get("residual_impact"),
                )

            elif tool_name == "delete_risk":
                parsed = _parse_kv(args_raw)
                risk_id = parsed.get("id")
                if not risk_id or not isinstance(risk_id, int):
                    return {"error": "Missing or invalid risk id. Usage: [TOOL_CALL:delete_risk:id=123]"}
                return await delete_risk(
                    db, user_id, org_id, risk_id,
                    is_admin=is_admin,
                    email=(ctx or {}).get("email"),
                )

            # ── SCORECARD TOOLS ──
            elif tool_name == "query_scorecards":
                parsed = _parse_kv(args_raw)
                is_manager = (ctx or {}).get("is_manager", False)
                return await query_scorecards(
                    db, user_id, org_id,
                    perspective_filter=parsed.get("perspective"),
                    status_filter=parsed.get("status"),
                    is_admin=is_admin,
                    is_manager=is_manager,
                )

            elif tool_name == "query_scorecard_summary":
                is_manager = (ctx or {}).get("is_manager", False)
                return await query_scorecard_summary(
                    db, user_id, org_id,
                    is_admin=is_admin,
                    is_manager=is_manager,
                )

            elif tool_name == "create_scorecard":
                parsed = _parse_kv(args_raw)
                return await create_scorecard(
                    db, org_id,
                    perspective=parsed.get("perspective", ""),
                    kpi_name=parsed.get("kpi_name", ""),
                    target=parsed.get("target"),
                    actual=parsed.get("actual"),
                    owner=parsed.get("owner", ""),
                    status=parsed.get("status", "on-track"),
                    assigned_user_id=parsed.get("assigned_user_id"),
                )

            elif tool_name == "update_scorecard":
                parsed = _parse_kv(args_raw)
                sc_id = parsed.get("id")
                if not sc_id or not isinstance(sc_id, int):
                    return {"error": "Missing or invalid scorecard id. Usage: [TOOL_CALL:update_scorecard:id=123,status=...]"}
                return await update_scorecard(
                    db, user_id, org_id, sc_id,
                    is_admin=is_admin,
                    perspective=parsed.get("perspective"),
                    kpi_name=parsed.get("kpi_name"),
                    target=parsed.get("target"),
                    actual=parsed.get("actual"),
                    owner=parsed.get("owner"),
                    status=parsed.get("status"),
                    assigned_user_id=parsed.get("assigned_user_id"),
                )

            elif tool_name == "delete_scorecard":
                parsed = _parse_kv(args_raw)
                sc_id = parsed.get("id")
                if not sc_id or not isinstance(sc_id, int):
                    return {"error": "Missing or invalid scorecard id. Usage: [TOOL_CALL:delete_scorecard:id=123]"}
                return await delete_scorecard(
                    db, user_id, org_id, sc_id,
                    is_admin=is_admin,
                )

            else:
                return {"error": f"Unknown tool: {tool_name}. Available: query_tasks, update_task, create_task, query_risks, create_risk, update_risk, delete_risk, query_scorecards, query_scorecard_summary, create_scorecard, update_scorecard, delete_scorecard"}

        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return {"error": f"Tool execution failed: {str(e)[:200]}"}

    async def _create_conversation(self, db: AsyncSession, user_id: int | None, org_id: int | None = None) -> int:
        result = await db.execute(
            text(
                "INSERT INTO agent_conversations (agent_name, user_id, org_id, title) "
                "VALUES (:agent, :uid, :org_id, :title) RETURNING id"
            ),
            {"agent": self.agent_name, "uid": user_id, "org_id": org_id, "title": f"{self.agent_name} chat"},
        )
        return result.scalar()

    async def _save_message(self, db: AsyncSession, conversation_id: int, role: str, content: str):
        await db.execute(
            text(
                "INSERT INTO agent_messages (conversation_id, role, content) "
                "VALUES (:cid, :role, :content)"
            ),
            {"cid": conversation_id, "role": role, "content": content[:50000]},
        )

    async def _load_history(self, db: AsyncSession, conversation_id: int, limit: int = 20) -> list:
        result = await db.execute(
            text(
                "SELECT role, content FROM agent_messages "
                "WHERE conversation_id = :cid ORDER BY id DESC LIMIT :lim"
            ),
            {"cid": conversation_id, "lim": limit},
        )
        rows = result.mappings().all()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
