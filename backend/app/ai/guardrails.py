"""Lightweight output guardrails for LLM responses.

Validates responses without blocking valid business content. All checks are
non-destructive: failures log an issue and return a safe fallback, never crash.
"""
import logging
import re

logger = logging.getLogger("stratroom.ai.guardrails")

MAX_RESPONSE_LENGTH = 50000
MAX_REPETITIVE_RATIO = 0.7
MIN_RESPONSE_LENGTH = 5

_PII_PATTERNS = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]


def validate_response(response: str, agent_name: str = "") -> tuple[bool, str, str]:
    """Validate an LLM response.

    Returns:
        (is_valid, cleaned_response, reason)
        - is_valid: True if response passes all checks
        - cleaned_response: original or truncated/sanitized response
        - reason: human-readable reason if invalid, empty string if valid
    """
    if not response or not response.strip():
        return False, "I apologize, but I was unable to generate a response. Please try again.", "empty_response"

    cleaned = response.strip()

    # Length check
    if len(cleaned) > MAX_RESPONSE_LENGTH:
        cleaned = cleaned[:MAX_RESPONSE_LENGTH] + "\n\n[Response truncated due to length]"
        logger.warning("Response truncated for agent=%s: original length=%d", agent_name, len(response))

    # Repetitive output detection
    is_repetitive, reason = _check_repetitive(cleaned)
    if is_repetitive:
        logger.warning("Repetitive output detected for agent=%s: %s", agent_name, reason)
        cleaned = _deduplicate_repetitive(cleaned)

    # PII detection — mask patterns
    cleaned, pii_found = _mask_pii(cleaned)
    if pii_found:
        logger.info("PII masked in response for agent=%s: %s", agent_name, pii_found)

    return True, cleaned, ""


def _check_repetitive(text: str) -> tuple[bool, str]:
    """Detect repetitive/looping output."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 5:
        return False, ""

    # Check for repeated lines
    unique_lines = set(lines)
    ratio = 1.0 - (len(unique_lines) / len(lines))
    if ratio > MAX_REPETITIVE_RATIO:
        return True, f"repetition_ratio={ratio:.2f}"

    # Check for repeated phrases (3+ word sequences)
    words = text.lower().split()
    if len(words) < 20:
        return False, ""
    trigrams = set()
    dup_trigrams = 0
    for i in range(len(words) - 2):
        tg = tuple(words[i:i + 3])
        if tg in trigrams:
            dup_trigrams += 1
        trigrams.add(tg)
    trigram_ratio = dup_trigrams / max(len(words) - 2, 1)
    if trigram_ratio > 0.4:
        return True, f"trigram_repetition={trigram_ratio:.2f}"

    return False, ""


def _deduplicate_repetitive(text: str) -> str:
    """Remove consecutive duplicate lines."""
    lines = text.split("\n")
    result = []
    prev = None
    for line in lines:
        stripped = line.strip()
        if stripped == prev:
            continue
        prev = stripped
        result.append(line)
    return "\n".join(result)


def _mask_pii(text: str) -> tuple[str, list[str]]:
    """Mask PII patterns (emails, phones, SSNs). Returns (masked_text, found_types)."""
    found = []
    masked = text
    for pii_type, pattern in _PII_PATTERNS:
        matches = pattern.findall(masked)
        if matches:
            found.append(pii_type)
            masked = pattern.sub(f"[REDACTED_{pii_type.upper()}]", masked)
    return masked, found
