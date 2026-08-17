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
from app.ai.tokens import (
    sanitize_input,
    cap_response,
    estimate_tokens,
    token_benchmark,
    log_benchmark_line,
)
from app.core.config import settings
from app.services.java_bridge import bridge

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
        # ── Enforce inbound length / character restrictions (Task 2) ──
        user_message, _in_truncated = sanitize_input(user_message)

        context = await fetch_agent_context(db, self.agent_name, org_id, ctx)
        if settings.MAX_RESPONSE_CHARS and len(context or "") > settings.MAX_PROMPT_LENGTH:
            context = (context or "")[:settings.MAX_PROMPT_LENGTH]

        # Enrich context with memories and recent conversations
        enhanced = ""
        try:
            enhanced = await enhance_context(
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
            history = await self._load_history(conversation_id)
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
                    json.dumps(tool_result, default=str) if isinstance(tool_result, (dict, list))
                    else str(tool_result)
                )
                if settings.MAX_TOOL_RESULT_CHARS and len(result_summary) > settings.MAX_TOOL_RESULT_CHARS:
                    result_summary = result_summary[:settings.MAX_TOOL_RESULT_CHARS] + "…[truncated]"
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
            output_text = response_text or ""
            await log_agent_run(
                org_id=org_id,
                user_id=user_id,
                agent_name=self.agent_name,
                provider=provider,
                model=model,
                conversation_id=conversation_id,
                status=status,
                duration_ms=elapsed_ms,
                token_count=estimate_tokens(user_message) + estimate_tokens(output_text),
                error_message=error_message,
                retry_count=retry_count,
            )
            token_benchmark.record(
                agent=self.agent_name,
                input_chars=len(user_message or ""),
                output_chars=len(output_text),
            )
            log_benchmark_line(self.agent_name, len(user_message or ""), len(output_text))

        # Output guardrails
        is_valid, response_text, guardrail_reason = validate_response(response_text, self.agent_name)
        if not is_valid:
            counters.record_guardrail_block()
            logger.warning("Guardrail triggered for agent=%s: %s", self.agent_name, guardrail_reason)

        if not conversation_id:
            try:
                conversation_id = await self._create_conversation(user_id, org_id)
            except Exception:
                logger.exception("Failed to create conversation for agent=%s", self.agent_name)
                conversation_id = None

        if conversation_id:
            try:
                await self._save_message(conversation_id, "user", user_message)
                await self._save_message(conversation_id, "assistant", response_text)
            except Exception:
                logger.exception("Failed to save messages for agent=%s conv=%s", self.agent_name, conversation_id)

        # Store insight and prune — failures are silent
        try:
            await store_memory(
                user_id=user_id,
                org_id=org_id,
                agent_name=self.agent_name,
                insight=response_text[:2000],
                source=f"conversation:{conversation_id}",
                message=user_message,
            )
            await prune_memory(
                user_id=user_id, org_id=org_id, agent_name=self.agent_name,
            )
        except Exception:
            counters.record_memory_failure()
            logger.warning("Memory store/prune failed for agent=%s", self.agent_name)

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

        # ── Agent-agnostic initiative/project intent ─────────────────────
        # Runs for EVERY agent (tasks, strategy, projects, ...) so that
        # "update initiative 8 progress to 80%" is NEVER misread as a task.
        prog_match = re.search(
            r"(?:update|set|change)\s+(?:the\s+)?progress\s+(?:of|for)?\s+(?:initiative|project)\s+[#:=\s]*(si-)?(\d+)\s+to\s+(\d+)",
            msg_lower,
        )
        if not prog_match:
            prog_match = re.search(
                r"(?:update|set|change)\s+(?:initiative|project)\s+[#:=\s]*(si-)?(\d+)\s+progress\s+to\s+(\d+)",
                msg_lower,
            )
        if not prog_match:
            prog_match = re.search(
                r"(?:update|set|change)\s+(?:initiative|project)\s+[#:=\s]*(si-)?(\d+)\s+to\s+(\d+)",
                msg_lower,
            )
        if prog_match:
            iid = prog_match.group(2)
            pct = prog_match.group(3)
            return (
                f"Update progress for initiative {iid} to {pct}%. "
                f"Call the update_initiative_progress tool with id={iid},progress={pct} immediately. "
                f"Do NOT ask for confirmation; execute the tool call now."
            )

        # Initiative/project named without a numeric ID (e.g. "for Market Analysis"):
        # cannot be auto-resolved — ask for the ID instead of mutating a task.
        if re.search(
            r"(?:update|set|change).*(?:initiative|project).*progress",
            msg_lower.replace("%", ""),
        ) and not re.search(r"(?:initiative|project)\s+[#:=\s]*\d+", msg_lower):
            return (
                "The user wants to update an initiative/project by name, which cannot be "
                "resolved without an ID. Do NOT map it to a task. Politely ask the user for "
                "the numeric initiative ID (e.g. 'update initiative 5 progress to 80%')."
            )

        if self.agent_name in ("projects", "strategy"):
            if any(p in msg_lower for p in (
                "list of initiatives", "all initiatives", "list initiatives",
                "show initiatives", "show me the initiatives", "display initiatives",
                "initiative list", "project list", "list of projects", "all projects",
            )):
                return (
                    "Show me all initiatives in the organization. "
                    "Call the query_initiatives tool to fetch the full initiative list."
                )

        if self.agent_name == "task":
            caller_email = (ctx or {}).get("email") or ""
            if any(p in msg_lower for p in (
                "my tasks", "my task", "assigned to me", "assigned to my",
                "my open tasks", "assigned for me",
            )):
                if caller_email:
                    return (
                        "Show me the tasks assigned to me. My email is " + caller_email + ". "
                        "Call the query_tasks tool with owner=" + caller_email + " "
                        "and report only the tasks whose owner is me."
                    )
                return (
                    "Show me the tasks assigned to me. "
                    "Call the query_tasks tool with owner=<my email> and report only my own tasks."
                )
            if any(p in msg_lower for p in (
                "high priority", "high-priority", "critical tasks", "critical priority",
                "top priority", "priority tasks", "critical task",
            )):
                return (
                    "Show me the Critical and High priority tasks. "
                    "Call the query_tasks tool with priority=Critical+High."
                )
            if any(p in msg_lower for p in (
                "tasks assigned to dominic", "dominic's tasks", "dominics tasks",
                "tasks for dominic", "tasks owned by dominic",
            )):
                return (
                    "Show me the tasks assigned to Dominic. "
                    "Call the query_tasks tool with owner=Dominic and report only tasks assigned to Dominic."
                )

            # Auto-detect task progress update intent: e.g. "update progress of task 102 to 80%" or "set task 5 progress to 60%"
            prog_match = re.search(r"(?:update|set|change)\s+(?:the\s+)?progress\s+(?:of|for)?\s+task\s+#?(\d+)\s+to\s+(\d+)", msg_lower)
            if not prog_match:
                prog_match = re.search(r"(?:update|set|change)\s+task\s+#?(\d+)\s+progress\s+to\s+(\d+)", msg_lower)
            if prog_match:
                tid = prog_match.group(1)
                pct = prog_match.group(2)
                return (
                    f"Update progress for task {tid} to {pct}%. "
                    f"Call the update_task_progress tool with id={tid},progress={pct} immediately."
                )

            # Auto-detect task status update intent: e.g. "mark task 102 as completed" or "change status of task 5 to in progress"
            stat_match = re.search(r"(?:mark|set|change)\s+(?:the\s+)?(?:status\s+of\s+)?task\s+#?(\d+)\s+(?:status\s+)?(?:as|to)\s+([a-z_\s]+)", msg_lower)
            if stat_match:
                tid = stat_match.group(1)
                target_stat = stat_match.group(2).strip()
                if any(s in target_stat for s in ("completed", "complete", "done", "finished", "in_progress", "in progress", "pending")):
                    norm_stat = "completed" if any(s in target_stat for s in ("completed", "complete", "done", "finished")) else ("in_progress" if "progress" in target_stat else "pending")
                    return (
                        f"Update status for task {tid} to {norm_stat}. "
                        f"Call the update_task_status tool with id={tid},status={norm_stat} immediately."
                    )

            if any(p in msg_lower for p in (
                "list of tasks", "all tasks", "list tasks", "show tasks",
                "list of all tasks", "list the tasks", "show me the tasks",
                "display tasks", "view tasks", "get all tasks",
            )):
                return (
                    "Show me all tasks in the organization. "
                    "Call the query_tasks tool to fetch the full task list."
                )

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
        from app.agents.task_tools import query_user_tasks, update_task_progress, update_task_status, create_task_tool, create_risk_mitigation_task
        from app.agents.risk_tools import query_risks, create_risk, update_risk, delete_risk, risk_simulator
        from app.agents.incident_tools import update_incident_status
        from app.agents.decision_tools import query_decisions, create_decision, update_decision_status
        from app.agents.scorecard_tools import query_scorecards, query_scorecard_summary, create_scorecard, update_scorecard, delete_scorecard
        from app.agents.initiative_tools import query_initiatives, update_initiative_progress

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

        def _tid(parsed: dict):
            """Resolve the task id from either 'id' or 'task_id' key."""
            return parsed.get("id") or parsed.get("task_id")

        try:
            # ── TASK TOOLS ──
            if tool_name == "query_tasks":
                parsed = _parse_kv(args_raw)
                email = ctx.get("email") if ctx else None
                return await query_user_tasks(
                    db, user_id, org_id,
                    status_filter=parsed.get("status"),
                    priority_filter=parsed.get("priority"),
                    owner_email=parsed.get("owner"),
                    is_admin=is_admin,
                    email=email,
                    self_only=True,
                )

            elif tool_name in ("update_task", "update_task_status"):
                parsed = _parse_kv(args_raw)
                task_id = _tid(parsed)
                if not task_id or not isinstance(task_id, int):
                    return {"error": "Missing or invalid task id. Usage: [TOOL_CALL:update_task_status:id=102,status=in_progress] or task_id=102"}
                email = ctx.get("email") if ctx else None
                return await update_task_status(
                    db, user_id, org_id, task_id,
                    status=parsed.get("status"),
                    is_admin=is_admin,
                    email=email,
                )

            elif tool_name == "update_task_progress":
                parsed = _parse_kv(args_raw)
                task_id = _tid(parsed)
                if not task_id or not isinstance(task_id, int):
                    return {"error": "Missing or invalid task id. Usage: [TOOL_CALL:update_task_progress:id=102,progress=80] or task_id=102,progress=80"}
                email = ctx.get("email") if ctx else None
                return await update_task_progress(
                    db, user_id, org_id, task_id,
                    progress=parsed.get("progress"),
                    is_admin=is_admin,
                    email=email,
                )

            elif tool_name == "create_task":
                parsed = _parse_kv(args_raw)
                email = ctx.get("email") if ctx else None
                return await create_task_tool(
                    db, org_id,
                    title=parsed.get("title", ""),
                    agent=parsed.get("agent"),
                    priority=parsed.get("priority", "Medium"),
                    owner=parsed.get("owner"),
                    due_date=parsed.get("due_date"),
                    status=parsed.get("status", "pending"),
                    assigned_user_id=parsed.get("assigned_user_id"),
                    email=email,
                    is_admin=is_admin,
                )

            elif tool_name == "create_risk_mitigation_task":
                parsed = _parse_kv(args_raw)
                risk_id = parsed.get("risk_id")
                if not risk_id or not isinstance(risk_id, int):
                    return {"error": "Missing or invalid risk_id. Usage: [TOOL_CALL:create_risk_mitigation_task:risk_id=12,mitigation=...,owner=...,priority=High]"}
                email = ctx.get("email") if ctx else None
                return await create_risk_mitigation_task(
                    db, org_id,
                    risk_id=risk_id,
                    mitigation=parsed.get("mitigation", ""),
                    owner=parsed.get("owner"),
                    priority=parsed.get("priority", "High"),
                    due_date=parsed.get("due_date"),
                    email=email,
                    is_admin=is_admin,
                )

            # ── INITIATIVE / PROJECT TOOLS ──
            elif tool_name == "query_initiatives":
                parsed = _parse_kv(args_raw)
                email = ctx.get("email") if ctx else None
                return await query_initiatives(
                    db, user_id, org_id,
                    is_admin=is_admin,
                    email=email,
                    owner_filter=parsed.get("owner"),
                    status_filter=parsed.get("status"),
                )

            elif tool_name == "update_initiative_progress":
                parsed = _parse_kv(args_raw)
                initiative_id = _tid(parsed)
                if not initiative_id or not isinstance(initiative_id, int):
                    return {"error": "Missing or invalid initiative id. Usage: [TOOL_CALL:update_initiative_progress:id=8,progress=80] or initiative_id=8,progress=80"}
                email = ctx.get("email") if ctx else None
                return await update_initiative_progress(
                    db, user_id, org_id,
                    initiative_id=initiative_id,
                    progress=parsed.get("progress"),
                    is_admin=is_admin,
                    email=email,
                )

            # ── INCIDENT TOOLS ──
            elif tool_name == "update_incident_status":
                parsed = _parse_kv(args_raw)
                incident_id = parsed.get("incident_id")
                if not incident_id or not isinstance(incident_id, int):
                    return {"error": "Missing or invalid incident_id. Usage: [TOOL_CALL:update_incident_status:incident_id=4,severity=High]"}
                email = ctx.get("email") if ctx else None
                return await update_incident_status(
                    db, user_id, org_id, incident_id,
                    status=parsed.get("status"),
                    severity=parsed.get("severity"),
                    primary_assignee=parsed.get("primary_assignee"),
                    is_admin=is_admin,
                    email=email,
                )

            # ── DECISION TOOLS ──
            elif tool_name == "query_decisions":
                parsed = _parse_kv(args_raw)
                email = ctx.get("email") if ctx else None
                return await query_decisions(
                    db, user_id, org_id,
                    status_filter=parsed.get("status"),
                    is_admin=is_admin,
                    email=email,
                )

            elif tool_name == "create_decision":
                parsed = _parse_kv(args_raw)
                email = ctx.get("email") if ctx else None
                return await create_decision(
                    db, org_id,
                    title=parsed.get("title", ""),
                    description=parsed.get("description", ""),
                    status=parsed.get("status", "Pending"),
                    owner=parsed.get("owner"),
                    priority=parsed.get("priority", "Medium"),
                    due_date=parsed.get("due_date"),
                    email=email,
                    is_admin=is_admin,
                )

            elif tool_name == "update_decision_status":
                parsed = _parse_kv(args_raw)
                decision_id = parsed.get("decision_id")
                if not decision_id or not isinstance(decision_id, int):
                    return {"error": "Missing or invalid decision_id. Usage: [TOOL_CALL:update_decision_status:decision_id=5,status=Approved]"}
                email = ctx.get("email") if ctx else None
                return await update_decision_status(
                    db, user_id, org_id, decision_id,
                    status=parsed.get("status"),
                    owner=parsed.get("owner"),
                    is_admin=is_admin,
                    email=email,
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
                email = ctx.get("email") if ctx else None
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
                    email=email,
                    is_admin=is_admin,
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

            elif tool_name in ("delete_risk", "delete_risk_tool"):
                parsed = _parse_kv(args_raw)
                risk_id = parsed.get("id")
                if not risk_id or not isinstance(risk_id, int):
                    return {"error": "Missing or invalid risk id. Usage: [TOOL_CALL:delete_risk:id=123]"}
                return await delete_risk(
                    db, user_id, org_id, risk_id,
                    is_admin=is_admin,
                    email=(ctx or {}).get("email"),
                )

            elif tool_name in ("risk_simulator", "run_risk_simulation", "simulate_risks"):
                parsed = _parse_kv(args_raw)
                runs = parsed.get("runs", 10000)
                confidence = parsed.get("confidence", 0.95)
                return await risk_simulator(
                    db, user_id, org_id,
                    runs=runs,
                    confidence=confidence,
                    is_admin=is_admin,
                    email=(ctx or {}).get("email"),
                )

            # ── SCORECARD TOOLS ──
            elif tool_name == "query_scorecards":
                parsed = _parse_kv(args_raw)
                is_manager = (ctx or {}).get("is_manager", False)
                return await query_scorecards(
                    user_id, org_id,
                    perspective_filter=parsed.get("perspective"),
                    status_filter=parsed.get("status"),
                    is_admin=is_admin,
                    is_manager=is_manager,
                )

            elif tool_name == "query_scorecard_summary":
                is_manager = (ctx or {}).get("is_manager", False)
                return await query_scorecard_summary(
                    user_id, org_id,
                    is_admin=is_admin,
                    is_manager=is_manager,
                )

            elif tool_name == "create_scorecard":
                parsed = _parse_kv(args_raw)
                is_manager = (ctx or {}).get("is_manager", False)
                return await create_scorecard(
                    org_id,
                    perspective=parsed.get("perspective", ""),
                    kpi_name=parsed.get("kpi_name", ""),
                    target=parsed.get("target"),
                    actual=parsed.get("actual"),
                    owner=parsed.get("owner", ""),
                    status=parsed.get("status", "on-track"),
                    assigned_user_id=parsed.get("assigned_user_id"),
                    is_admin=is_admin,
                    is_manager=is_manager,
                )

            elif tool_name == "update_scorecard":
                parsed = _parse_kv(args_raw)
                sc_id = parsed.get("id")
                if not sc_id or not isinstance(sc_id, int):
                    return {"error": "Missing or invalid scorecard id. Usage: [TOOL_CALL:update_scorecard:id=123,status=...]"}
                return await update_scorecard(
                    user_id, org_id, sc_id,
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
                    user_id, org_id, sc_id,
                    is_admin=is_admin,
                )

            else:
                return {"error": f"Unknown tool: {tool_name}. Available: query_tasks, update_task, update_task_status, update_task_progress, create_task, create_risk_mitigation_task, query_initiatives, update_initiative_progress, update_incident_status, query_decisions, create_decision, update_decision_status, query_risks, create_risk, update_risk, delete_risk, query_scorecards, query_scorecard_summary, create_scorecard, update_scorecard, delete_scorecard"}

        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return {"error": f"Tool execution failed: {str(e)[:200]}"}

    async def _create_conversation(self, user_id: int | None, org_id: int | None = None) -> int | None:
        resp = await bridge.post(bridge.db_service, "/conversations", json={
            "agent_name": self.agent_name,
            "user_id": user_id,
            "org_id": org_id,
            "title": f"{self.agent_name} chat",
        })
        return resp.get("id") if isinstance(resp, dict) else None

    async def _save_message(self, conversation_id: int, role: str, content: str):
        await bridge.post(bridge.db_service, f"/conversations/{conversation_id}/messages", json={
            "role": role,
            "content": content[:50000],
        })

    async def _load_history(self, conversation_id: int, limit: int = 20) -> list:
        messages = await bridge.get(
            bridge.db_service, f"/conversations/{conversation_id}/messages",
        )
        if not isinstance(messages, list):
            return []
        return [{"role": m["role"], "content": m["content"]} for m in messages[-limit:]]
