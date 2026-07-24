import asyncio
import logging
import time

import httpx

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
    provider = provider.lower()

    if provider == "anthropic":
        return await _call_anthropic(api_key, model, system_prompt, messages, max_tokens, base_url)
    elif provider == "google":
        return await _call_google(api_key, model, system_prompt, messages, base_url)
    elif provider == "ollama":
        endpoint = ollama_endpoint or base_url or api_key or "http://localhost:11434"
        endpoint = _normalize_ollama_endpoint(endpoint)
        return await _call_ollama(endpoint, model, system_prompt, messages)
    elif provider in PROVIDER_ENDPOINTS:
        return await _call_openai_compatible(provider, api_key, model, system_prompt, messages, max_tokens, base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")


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
    if base_url:
        url = base_url.rstrip("/") + "/chat/completions"
    else:
        url = PROVIDER_ENDPOINTS[provider]
    all_messages = [{"role": "system", "content": system_prompt}] + messages
    body = {"model": model, "messages": all_messages, "max_tokens": max_tokens}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    client = _get_client(provider)
    resp = await client.post(url, json=body, headers=headers)
    resp.raise_for_status()
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
