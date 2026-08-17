"""
Task 2 & Task 3 verification — Token Optimization & UI Branding

Verifies:
  - Input character-length caps and control-character rejection at the HTTP layer.
  - Response output length caps enforced at the provider boundary.
  - max_tokens ceiling clamping.
  - Benchmark logging (per-response token estimates) for the /agents/chat path.
  - StratRoom branding consistency in agent prompts.

Usage: python test_token_and_branding.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.ai import tokens  # noqa: E402
from app.ai.tokens import estimate_tokens, sanitize_input, valid_input_chars, cap_response  # noqa: E402
from app.ai.llm_providers import _clamp_max_tokens  # noqa: E402
from app.agents import prompts  # noqa: E402

passed = 0
failed = 0
results = []


def run_test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        results.append(("PASS", name, ""))
    except Exception as e:
        failed += 1
        results.append(("FAIL", name, f"{type(e).__name__}: {e}"))


# ────────────────────────────────────────────────────────────────
# Token utility unit tests
# ────────────────────────────────────────────────────────────────
def test_estimate_tokens():
    assert estimate_tokens("hello world this is a sample") == 7  # 28 chars // 4
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_sanitize_control_chars():
    cleaned, truncated = sanitize_input("a  b\x00c\rd")
    assert "\x00" not in cleaned and "\r" not in cleaned
    assert not truncated


def test_sanitize_truncates_over_limit():
    settings.MAX_CHAT_INPUT_CHARS = 10
    try:
        cleaned, truncated = sanitize_input("x" * 50)
        assert truncated and len(cleaned) <= 10
    finally:
        settings.MAX_CHAT_INPUT_CHARS = 8000


def test_valid_input_chars():
    assert valid_input_chars("normal query text")
    assert not valid_input_chars("has\x00control")
    assert not valid_input_chars("has\x1fchar")


def test_cap_response():
    text = "y" * 500
    settings.MAX_RESPONSE_CHARS = 100
    try:
        capped, truncated = cap_response(text)
        assert truncated
        assert len(capped) > 100  # marker appended
        assert capped.startswith("y" * 100)
        assert "[Response truncated" in capped
    finally:
        settings.MAX_RESPONSE_CHARS = 16000


def test_cap_response_under_limit_untouched():
    capped, truncated = cap_response("short answer")
    assert not truncated and capped == "short answer"


def test_benchmark_records():
    tokens.reset_benchmark()
    tokens.token_benchmark.record(agent="strategy", input_chars=100, output_chars=400)
    tokens.token_benchmark.record(agent="risk", input_chars=200, output_chars=800)
    snap = tokens.token_benchmark.snapshot()
    assert snap["total_responses"] == 2
    assert snap["avg_total_tokens_per_response"] > 0
    assert len(tokens.token_benchmark.recent()) == 2


# ────────────────────────────────────────────────────────────────
# max_tokens clamping
# ────────────────────────────────────────────────────────────────
def test_max_tokens_clamp():
    settings.MAX_LLM_MAX_TOKENS = 2048
    assert _clamp_max_tokens(99999) == 2048
    assert _clamp_max_tokens(500) == 500
    assert _clamp_max_tokens(-5) == 2048


# ────────────────────────────────────────────────────────────────
# Branding consistency in prompts
# ────────────────────────────────────────────────────────────────
def test_prompts_brand_stratroom():
    for agent, prompt in prompts.AGENT_PROMPTS.items():
        assert "StratRoom" in prompt, f"agent prompt '{agent}' missing StratRoom branding"


def test_agent_domains_consistent():
    from app.routers.agents import AGENT_DOMAINS

    for dom in AGENT_DOMAINS:
        assert dom in prompts.AGENT_PROMPTS, f"AGENT_DOMAIN '{dom}' missing from AGENT_PROMPTS"


# ────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────
def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("=" * 60)
    print("  STRATROOM TASK 2 & 3 — TOKEN + BRANDING TESTS")
    print("=" * 60)
    print()
    print("  Bounds from settings:")
    print(f"    MAX_CHAT_INPUT_CHARS : {settings.MAX_CHAT_INPUT_CHARS}")
    print(f"    MAX_RESPONSE_CHARS   : {settings.MAX_RESPONSE_CHARS}")
    print(f"    MAX_LLM_MAX_TOKENS   : {settings.MAX_LLM_MAX_TOKENS}")
    print(f"    MAX_TOOL_RESULT_CHARS: {settings.MAX_TOOL_RESULT_CHARS}")
    print()
    for fn in tests:
        run_test(fn.__name__, fn)
    for r in results:
        if r[0] == "PASS":
            print(f"  PASS  {r[1]}")
        else:
            print(f"  FAIL  {r[1]}: {r[2]}")
    print()
    total = passed + failed
    print(f"  RESULTS: {passed}/{total} PASSED | {failed} FAILED")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)