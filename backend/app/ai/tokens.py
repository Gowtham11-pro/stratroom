"""Token accounting & I/O bounds for the AI layer.

Centralizes:
  - Rough token estimation (chars/4 heuristic, no heavyweight tokenizer lib)
  - Input character set / length sanitization
  - Output response length caps
  - In-memory benchmark aggregation (avg tokens per response, per agent)

All bounds are read from `settings` so operators can tune them via env vars
without code changes.
"""
import logging
import re
import threading
import time

from app.core.config import settings

logger = logging.getLogger("stratroom.ai.tokens")

# ── Sanitisation: reject/disallow control characters in user input ──
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NEWLINE = re.compile(r"[ \t]{2,}")


def estimate_tokens(text: str | None) -> int:
    """Cheap, deterministic token estimate.

    Models undercount short punctuation-heavy text and overcount ASCII; a
    bytes/4 heuristic is a well-understood approximation for monitoring
    trends (before/after comparisons) even if not provider-exact.
    """
    if not text:
        return 0
    # ~4 bytes per token is a common rule of thumb for English text.
    return max(1, len(text) // 4)


def sanitize_input(text: str | None, max_chars: int | None = None) -> tuple[str, bool]:
    """Restrict an inbound user message.

    Returns (sanitized_text, was_truncated). Drops disallowed control chars and
    collapses repetitive whitespace. If max_chars is given and the cleaned text
    exceeds it, the text is truncated (always the last resort — never raises).
    """
    if text is None:
        return "", False
    cleaned = _CONTROL_CHARS.sub(" ", text)
    cleaned = _NEWLINE.sub(" ", cleaned.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = cleaned.strip()
    limit = max_chars if max_chars is not None else settings.MAX_CHAT_INPUT_CHARS
    was_truncated = False
    if limit and len(cleaned) > limit:
        cleaned = cleaned[:limit]
        was_truncated = True
    return cleaned, was_truncated


def valid_input_chars(text: str) -> bool:
    """True if input contains no control characters (safe to accept as-is)."""
    return not _CONTROL_CHARS.search(text or "")


def cap_response(text: str | None, max_chars: int | None = None) -> tuple[str, bool]:
    """Enforce a hard output length cap across all providers/agents.

    Returns (capped_text, was_truncated). Adds a visible marker when truncated.
    """
    if text is None:
        return "", False
    text = text.strip()
    limit = max_chars if max_chars is not None else settings.MAX_RESPONSE_CHARS
    if limit and len(text) > limit:
        text = text[:limit]
        text = text.rstrip() + "\n\n[Response truncated to keep output within limits]"
        return text, True
    return text, False


class TokenBenchmark:
    """In-memory accumulator for token benchmarks.

    Records input/output token estimates per response and stores a short
    rolling window so operators can read "average tokens consumed per
    response" for standard queries.
    """

    def __init__(self, window: int = 200):
        self._lock = threading.Lock()
        self._window = window
        self._recent: list[dict] = []
        self._totals: dict[str, float] = {
            "input_chars": 0.0,
            "output_chars": 0.0,
            "input_tokens": 0.0,
            "output_tokens": 0.0,
        }
        self._count = 0
        self._started = time.time()

    def record(self, *, agent: str, input_chars: int, output_chars: int) -> None:
        in_tok = estimate_tokens("x" * input_chars)
        out_tok = estimate_tokens("x" * output_chars)
        with self._lock:
            self._recent.append({
                "ts": time.time(),
                "agent": agent,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
            })
            if len(self._recent) > self._window:
                self._recent = self._recent[-self._window:]
            for k, v in (("input_chars", input_chars), ("output_chars", output_chars),
                         ("input_tokens", in_tok), ("output_tokens", out_tok)):
                self._totals[k] += v
            self._count += 1

    def snapshot(self) -> dict:
        with self._lock:
            n = self._count
            avg = {k: (round(self._totals[k] / n, 1) if n else 0) for k in self._totals}
            avg.update({
                "total_responses": n,
                "avg_total_tokens_per_response": round(avg["input_tokens"] + avg["output_tokens"], 1),
                "uptime_seconds": round(time.time() - self._started, 0),
            })
            return avg

    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._recent)


token_benchmark = TokenBenchmark()


def log_benchmark_line(agent: str, input_chars: int, output_chars: int) -> None:
    """Emit a structured log line for standard-query benchmark monitoring."""
    in_tok = estimate_tokens("x" * input_chars)
    out_tok = estimate_tokens("x" * output_chars)
    logger.info(
        "BENCH token_usage agent=%s input_chars=%d output_chars=%d "
        "input_tokens=%d output_tokens=%d total_tokens=%d",
        agent, input_chars, output_chars, in_tok, out_tok, in_tok + out_tok,
    )


def reset_benchmark() -> None:
    token_benchmark._recent.clear()
    token_benchmark._totals = {k: 0.0 for k in token_benchmark._totals}
    token_benchmark._count = 0
    token_benchmark._started = time.time()