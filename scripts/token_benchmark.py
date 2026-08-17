"""
Token Benchmark — before/after character restrictions

Simulates a set of standard agent queries and computes estimated token
consumption (chars/4 heuristic) under the OLD (unrestricted) and NEW
(capped) I/O bounds.

OLD behavior:
  - no input length cap (only the 50k global validation ceiling)
  - response cap = 50,000 chars (guardrails) with no per-agent bound
  - max_tokens ceiling = none (callers could request up to 16384)

NEW behavior:
  - MAX_CHAT_INPUT_CHARS = 8000 (rejects/truncates oversize queries)
  - MAX_RESPONSE_CHARS   = 16000 (hard cap at provider boundary)
  - MAX_LLM_MAX_TOKENS   = 2048 (max_tokens clamped)
  - MAX_TOOL_RESULT_CHARS= 4000 (tool summaries capped)

Run: python scripts/token_benchmark.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.ai.tokens import sanitize_input, cap_response, estimate_tokens  # noqa: E402

# A representative "standard query" workload by agent
QUERIES = {
    "strategy": "Summarise top 3 risks requiring executive action today",
    "risk": "Show me the high heat risks in the Technology department with their owners",
    "scorecard": "Which KPIs are off-track this quarter across all four perspectives?",
    "finance": "What is the forecast for hitting our annual revenue target?",
    "task": "List all my pending tasks assigned to me sorted by priority",
    "meetings": "Prepare an agenda for the next executive risk review meeting",
    "incident": "Summarise open incidents and flag anything critical from the last 7 days",
    "compliance": "Which compliance frameworks have the most open audit findings?",
    "audit": "List audit findings with severity critical and their mitigation status",
    "decision": "Show all registered decisions awaiting approval",
}

# Representative model output lengths (chars) for a standard query per agent
OUTPUT_LEN = {
    "strategy": 3800, "risk": 5200, "scorecard": 4100, "finance": 3600,
    "task": 6800, "meetings": 4200, "incident": 5600, "compliance": 4900,
    "audit": 6100, "decision": 3900,
}

# A pathological "spike" query (long paste / malicious payload)
SPIKE_INPUT = "x" * 45000
SPIKE_OUTPUT = "y" * 45000


def old_tokens(in_len: int, out_len: int) -> int:
    # OLD (pre-Task-2) behavior: only the 50k validation ceiling + 50k guardrail.
    in_capped = min(in_len, 50000)
    out_capped = min(out_len, 50000)
    return estimate_tokens("x" * in_capped) + estimate_tokens("x" * out_capped)


def new_tokens(in_len: int, out_len: int) -> int:
    in_capped, _ = sanitize_input("x" * in_len)
    # Output is bounded by BOTH the char cap and the max_tokens clamp
    # (max_tokens=2048 ~ 8192 chars at the 4-chars-per-token heuristic).
    token_char_bound = settings.MAX_LLM_MAX_TOKENS * 4
    effective_out = min(settings.MAX_RESPONSE_CHARS, token_char_bound)
    out_capped, _ = cap_response("x" * min(out_len, effective_out))
    return estimate_tokens(in_capped) + estimate_tokens(out_capped)


def main():
    print("=" * 74)
    print("  STRATROOM TOKEN BENCHMARK — BEFORE / AFTER I/O RESTRICTIONS")
    print("=" * 74)
    print()
    print(f"  Bounds  input_cap={settings.MAX_CHAT_INPUT_CHARS}  response_cap={settings.MAX_RESPONSE_CHARS}  "
          f"max_tokens_cap={settings.MAX_LLM_MAX_TOKENS}  tool_cap={settings.MAX_TOOL_RESULT_CHARS}")
    print()
    hdr = f"  {'agent':<12}{'in_chars':>9}{'out_chars':>10}{'old_tok':>10}{'new_tok':>10}{'delta':>9}{'reduction':>10}"
    print(hdr)
    print("  " + "-" * 70)

    totals = {"old": 0, "new": 0}
    rows = []
    for agent, query in QUERIES.items():
        in_len = len(query)
        out_len = OUTPUT_LEN[agent]
        old_t = old_tokens(in_len, out_len)
        new_t = new_tokens(in_len, out_len)
        totals["old"] += old_t
        totals["new"] += new_t
        reduction = (1 - new_t / old_t) * 100 if old_t else 0
        rows.append((agent, in_len, out_len, old_t, new_t, new_t - old_t, reduction))

    # Spike case (token-spike protection)
    spike_from = len(SPIKE_INPUT)
    spike_to = len(SPIKE_OUTPUT)
    spike_old = old_tokens(spike_from, spike_to)
    spike_new = new_tokens(spike_from, spike_to)
    totals["old"] += spike_old
    totals["new"] += spike_new
    spike_red = (1 - spike_new / spike_old) * 100 if spike_old else 0

    for agent, in_len, out_len, old_t, new_t, delta, reduction in rows:
        print(f"  {agent:<12}{in_len:>9}{out_len:>10}{old_t:>10}{new_t:>10}{delta:>9}{reduction:>9.1f}%")
    print("  " + "-" * 70)
    print(f"  {'spike(45k)':<12}{spike_from:>9}{spike_to:>10}{spike_old:>10}{spike_new:>10}"
          f"{spike_new - spike_old:>9}{spike_red:>9.1f}%")
    print("  " + "-" * 70)
    avg_old = totals["old"] / (len(rows) + 1)
    avg_new = totals["new"] / (len(rows) + 1)
    avg_reduction = (1 - avg_new / avg_old) * 100 if avg_old else 0
    print(f"  {'AVERAGE':<12}{'':>19}{avg_old:>10.0f}{avg_new:>10.0f}{avg_new - avg_old:>9.0f}"
          f"{avg_reduction:>9.1f}%")
    print()
    print("  Estimated tokens use chars/4 heuristic (monitoring grade, not provider-exact).")
    print("  'old' models the pre-Task-2 behavior: 50k validation ceiling, 50k guardrail, no max_tokens clamp.")
    print()


if __name__ == "__main__":
    main()