import asyncio
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger("stratroom.ai.llm")


def _normalize_ollama_endpoint(endpoint: str) -> str:
    """Replace localhost/127.0.0.1 with host.docker.internal when running inside Docker."""
    import socket
    import os
    if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER"):
        for host in ("localhost", "127.0.0.1"):
            if host in endpoint:
                endpoint = endpoint.replace(host, "host.docker.internal")
                break
    return endpoint

_provider_clients: dict[str, httpx.AsyncClient] = {}


def _get_client(provider: str) -> httpx.AsyncClient:
    """Get or create a shared httpx client per provider for connection reuse."""
    if provider not in _provider_clients or _provider_clients[provider].is_closed:
        _provider_clients[provider] = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30,
            ),
        )
    return _provider_clients[provider]

PROVIDER_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "moonshot": "https://api.moonshot.cn/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "xai": "https://api.x.ai/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "google": "generativelanguage.googleapis.com",
    "ollama": "localhost:11434",
    "qwen": "https://api.together.xyz/v1/chat/completions",
    "qwen2.5": "https://api.together.xyz/v1/chat/completions",
}

DEFAULT_TIMEOUT = 120

_RETRYABLE_ERRORS = (
    httpx.HTTPStatusError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ConnectError,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def _extract_provider_error(resp: httpx.Response, provider: str, model: str) -> ValueError:
    """Build a clear, non-retryable error from a provider rejection.

    Permanent client errors (e.g. an unavailable/deprecated model) should be
    surfaced to the caller immediately instead of being retried and hidden
    behind a generic 502.
    """
    detail = ""
    try:
        data = resp.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            detail = err.get("message") or ""
        elif isinstance(err, str):
            detail = err
    except Exception:
        pass
    if not detail:
        detail = resp.text[:200]

    msg = (
        f"Configured model '{model}' was rejected by provider '{provider}' "
        f"(HTTP {resp.status_code})."
    )
    if detail:
        msg += f" Provider response: {detail}"
    return ValueError(msg)


def _clamp_max_tokens(max_tokens: int) -> int:
    """Clamp a caller-supplied max_tokens to the configured global ceiling.

    Prevents any single agent/route from requesting an unbounded (or overly
    generous) response budget that would spike token consumption.
    """
    if not isinstance(max_tokens, int) or max_tokens < 1:
        max_tokens = 2048
    ceiling = settings.MAX_LLM_MAX_TOKENS
    if max_tokens > ceiling:
        logger.info("max_tokens clamped %d -> %d", max_tokens, ceiling)
        max_tokens = ceiling
    return max_tokens


async def call_llm(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 2048,
    ollama_endpoint: str | None = None,
    base_url: str | None = None,
) -> str:
    """Unified LLM call for all providers.

    Args:
        provider: Provider name (openai, anthropic, google, ollama, deepseek, etc.)
        api_key: Provider API key (or Ollama endpoint URL for ollama).
        model: Model identifier.
        system_prompt: System prompt text.
        messages: List of {"role": "user"|"assistant", "content": "..."} dicts.
        max_tokens: Maximum tokens in response.
        ollama_endpoint: Override Ollama endpoint URL.
        base_url: Override provider base URL (e.g. for NVIDIA NIM, Groq, Azure, etc.)

    Returns:
        Response text string.
    """
def _generate_smart_mock_response(system_prompt: str, messages: list[dict]) -> str:
    user_msg = (messages[-1]["content"] if messages else "").strip()
    msg_lower = user_msg.lower()

    domain = "Strategy"
    sp_lower = system_prompt.lower()[:300]
    if "risk" in sp_lower:
        domain = "Risk"
    elif "finance" in sp_lower or "budget" in sp_lower:
        domain = "Finance"
    elif "task" in sp_lower:
        domain = "Task"
    elif "incident" in sp_lower:
        domain = "Incident"
    elif "compliance" in sp_lower or "audit" in sp_lower:
        domain = "Governance"

    org_data = ""
    if "--- CURRENT ORGANIZATION DATA ---" in system_prompt:
        org_data = system_prompt.split("--- CURRENT ORGANIZATION DATA ---")[-1]

    if not user_msg or msg_lower in ("hi", "hello", "hey", "greetings", "help", "who are you"):
        return (
            f"Hello! I am your **{domain} Agent**. I am online and continuously monitoring your "
            f"live organization data.\n\n"
            f"Here is a summary of what I can help you with today:\n"
            f"• **KPI & Scorecard Analysis**: Ask about off-track metrics, target gaps, or perspective scores.\n"
            f"• **Strategic Risk & Mitigations**: Review top critical risks and action plans.\n"
            f"• **Executive Decision Prep**: Reforecast scenarios, project timelines, and board updates.\n\n"
            f"What specific area would you like to explore?"
        )

    if any(w in msg_lower for w in ("kpi", "off-track", "off track", "lagging", "performance")):
        return (
            "🎯 **KPI & Scorecard Performance Overview**\n\n"
            "Based on current live data, here are the key performance highlights:\n\n"
            "🔴 **Critical / Off-Track KPIs**:\n"
            "• **Talent Retention**: Current 58% vs 80% Target (22-point gap, accelerated attrition in Engineering)\n"
            "• **Digital Transformation**: Current 38% vs 60% Target (22-point delivery gap)\n\n"
            "🟢 **Leading Indicators & Highlights**:\n"
            "• **Group Revenue Growth**: 82% vs 80% Target (Exceeding target by +2.0%)\n"
            "• **ESG & Sustainability Score**: 91% vs 85% Target (+6.0% leading posture)\n\n"
            "💡 **Recommended Action**: Escalate Talent Retention to the board executive session and approve the DT recovery roadmap."
        )

    if "talent" in msg_lower or "retention" in msg_lower:
        return (
            "👥 **Talent Retention Deep-Dive & Root Cause Analysis**\n\n"
            "• **Current Metric**: 58.0% (Target: 80.0%, Status: 🔴 Critical)\n"
            "• **Primary Driver**: High attrition across Senior Engineering & Technical Lead tiers.\n"
            "• **Strategic Risk**: Key project delivery delay on Digital Transformation initiative (DT-001).\n\n"
            "📌 **Key Recommendations**:\n"
            "1. **Engineering Retention Incentive**: Implement 15% retention pool for critical project leads.\n"
            "2. **CHRO Review**: Conduct targeted exit interviews and workload rebalancing by Oct 15.\n"
            "3. **Board Escalation**: Submit Talent Retention recovery paper for upcoming board meeting."
        )

    if any(w in msg_lower for w in ("dt", "digital", "forecast", "transform")):
        return (
            "🚀 **Digital Transformation (DT) Reforecast & Trajectory**\n\n"
            "• **Current Progress**: 38.0% completion vs 60.0% milestone target\n"
            "• **Budget Status**: $2.4M allocated, 92% spent\n"
            "• **Causal Impact**: DT delay creates a downstream bottleneck for MEA expansion, risking up to $45M Year 3 revenue.\n\n"
            "⚡ **Recommended Actions**:\n"
            "1. Reallocate $2.4M capital contingency to reinforce engineering delivery teams.\n"
            "2. Establish weekly CTO/CFO milestone checkpoint for Oct 15 approval."
        )

    if any(w in msg_lower for w in ("urgent", "issue", "critical", "risk", "alert")):
        return (
            "🚨 **Current Critical Priorities & Urgent Issues**\n\n"
            "1. 🔴 **Talent Retention Gap**: 58% actual vs 80% target — Engineering attrition accelerating.\n"
            "2. 🔴 **Cyber Risk Heat**: 24/25 inherent heat (+34% surge in phishing & external scan attempts).\n"
            "3. 🟠 **Digital Transformation Delivery**: 38% completion against 60% target.\n\n"
            "Action item: Escalate items #1 and #2 to the Executive Risk Committee immediately."
        )

    if any(w in msg_lower for w in ("board", "summary", "meeting", "executive", "decision")):
        return (
            "📋 **Executive Board Briefing & Health Summary**\n\n"
            "• **Financial Performance**: Strong revenue posture (82% vs 80% target, +2% variance).\n"
            "• **Operational & Digital Execution**: DT project lagging at 38% delivery vs 60% target.\n"
            "• **People & Organizational Risk**: Talent retention at critical 58% level requiring board attention.\n"
            "• **ESG Posture**: Outstanding performance at 91% vs 85% target.\n\n"
            "Recommendation: Prioritize talent retention escalation and approve DT budget reallocation."
        )

    return (
        f"🤖 **{domain} Agent Insights**\n\n"
        f"I analyzed your query: *\"{user_msg}\"*\n\n"
        f"**Key Findings from Live Context**:\n"
        f"• **Strategic Posture**: Overall performance is stable with strong Revenue (82%) and ESG (91%) indicators.\n"
        f"• **Attention Areas**: Talent Retention (58%) and Digital Transformation (38%) require active oversight.\n"
        f"• **Next Steps**: Review the scorecard metrics and module action items for targeted intervention."
    )


async def call_llm(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 2048,
    ollama_endpoint: str | None = None,
    base_url: str | None = None,
) -> str:
    """Unified LLM call for all providers."""
    provider = provider.lower()
    max_tokens = _clamp_max_tokens(max_tokens)

    if provider == "mock":
        return _generate_smart_mock_response(system_prompt, messages)
    if provider == "anthropic":
        text = await _call_anthropic(api_key, model, system_prompt, messages, max_tokens, base_url)
    elif provider == "google":
        text = await _call_google(api_key, model, system_prompt, messages, base_url)
    elif provider == "ollama":
        endpoint = ollama_endpoint or base_url or api_key or "http://localhost:11434"
        endpoint = _normalize_ollama_endpoint(endpoint)
        text = await _call_ollama(endpoint, model, system_prompt, messages)
    elif provider in PROVIDER_ENDPOINTS:
        text = await _call_openai_compatible(provider, api_key, model, system_prompt, messages, max_tokens, base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Global output cap — enforced at the provider boundary so every route and
    # every agent benefits, regardless of whether the caller remembered.
    from app.ai.tokens import cap_response

    capped, _truncated = cap_response(text)
    return capped


async def call_llm_with_retry(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 2048,
    max_retries: int = 2,
    ollama_endpoint: str | None = None,
    base_url: str | None = None,
) -> tuple[str, int]:
    """LLM call with retry and exponential backoff.

    Returns:
        (response_text, retry_count) tuple.
    """
    last_error = None
    retry_count = 0
    for attempt in range(max_retries + 1):
        try:
            result = await call_llm(
                provider, api_key, model, system_prompt, messages, max_tokens, ollama_endpoint, base_url
            )
            return result, retry_count
        except _RETRYABLE_ERRORS as e:
            last_error = e
            retry_count = attempt + 1
            is_rate_limit = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
            logger.warning(
                "LLM call failed (attempt %d/%d): provider=%s model=%s rate_limit=%s error=%s",
                attempt + 1, max_retries + 1, provider, model, is_rate_limit, str(e)[:200],
            )
            if attempt < max_retries:
                delay = (2 ** attempt) + (0.5 if is_rate_limit else 0)
                await asyncio.sleep(delay)
        except ValueError:
            raise
        except Exception as e:
            logger.error("Non-retryable LLM error: provider=%s error=%s", provider, str(e)[:200])
            raise
    raise last_error


async def _call_openai_compatible(
    provider: str, api_key: str, model: str,
    system_prompt: str, messages: list[dict], max_tokens: int,
    base_url: str | None = None,
) -> str:
    if provider in ("qwen", "qwen2.5"):
        if not model or model.lower() in ("qwen", "qwen2.5"):
            model = "Qwen/Qwen2.5-72B-Instruct-Turbo"
    if base_url:
        url = base_url.rstrip("/") + "/chat/completions"
    else:
        url = PROVIDER_ENDPOINTS[provider]
    all_messages = [{"role": "system", "content": system_prompt}] + messages
    body = {"model": model, "messages": all_messages, "max_tokens": max_tokens}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    client = _get_client(provider)
    resp = await client.post(url, json=body, headers=headers)
    if resp.status_code >= 400:
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        raise _extract_provider_error(resp, provider, model)
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _call_anthropic(
    api_key: str, model: str, system_prompt: str, messages: list[dict], max_tokens: int,
    base_url: str | None = None,
) -> str:
    if base_url:
        url = base_url.rstrip("/") + "/v1/messages"
    else:
        url = PROVIDER_ENDPOINTS["anthropic"]
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    client = _get_client("anthropic")
    resp = await client.post(url, json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


async def _call_google(
    api_key: str, model: str, system_prompt: str, messages: list[dict],
    base_url: str | None = None,
) -> str:
    if base_url:
        url = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}"
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    combined = system_prompt
    for m in messages:
        role = "User" if m["role"] == "user" else "Assistant"
        combined += f"\n\n{role}: {m['content']}"
    body = {"contents": [{"parts": [{"text": combined}]}]}
    client = _get_client("google")
    resp = await client.post(url, json=body)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_ollama(
    endpoint: str, model: str, system_prompt: str, messages: list[dict],
) -> str:
    url = f"{endpoint}/api/chat"
    all_messages = [{"role": "system", "content": system_prompt}] + messages
    body = {"model": model, "messages": all_messages, "stream": False}
    client = _get_client("ollama")
    resp = await client.post(url, json=body)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"]
