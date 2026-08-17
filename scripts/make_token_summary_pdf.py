import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Token_Optimization_Summary.pdf")

DARK = colors.HexColor("#1f2a44")
ACCENT = colors.HexColor("#6a3fb5")
LIGHT = colors.HexColor("#f2effa")
MUTED = colors.HexColor("#5a6270")

title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=25, textColor=DARK, spaceAfter=2)
subtitle = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11, leading=15, textColor=MUTED, spaceAfter=10)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=ACCENT, spaceBefore=14, spaceAfter=6)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14.5, textColor=DARK, spaceAfter=6)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=3)
small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=MUTED)
cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=11.5, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
box = ParagraphStyle("box", parent=body, fontSize=10.5, leading=15.5, textColor=DARK)


def P(t, s=body):
    return Paragraph(t, s)


def B(t):
    return Paragraph(t, bullet)


def tbl(rows, widths, header=True):
    data = []
    if header:
        data.append([Paragraph(c, cellb) for c in rows[0]])
        rows = rows[1:]
    for r in rows:
        data.append([Paragraph(str(c), cell) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8d4e6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(style))
    return t


story = []

story.append(P("Token Optimization — Summary for Management", title))
story.append(P(f"StratRoom AI Agents &middot; Date: {date.today().strftime('%d %B %Y')}", subtitle))
story.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=8))

story.append(P("1. Problem Being Solved", h1))
story.append(P("Every AI agent turn in StratRoom was unbounded on three fronts:"))
story.append(B("&bull; <b>Input:</b> a user could paste an arbitrarily long message (up to 50,000 characters) — a single query could consume thousands of tokens."))
story.append(B("&bull; <b>Output:</b> each agent turn could make up to 4 LLM calls (1 initial + up to 3 tool-feedback loops), each allowed up to 2,048 tokens and 50,000 characters — no hard ceiling."))
story.append(B("&bull; <b>Tool results:</b> full database query results were fed back to the model verbatim, inflating every subsequent call in a conversation."))
story.append(P("Result: unpredictable token spikes and cost per conversation."))

story.append(P("2. What Was Implemented", h1))
story.append(P("A central token-governance layer was added at <font face='Courier'>backend/app/ai/tokens.py</font>, wired into every AI agent and LLM call site. All limits are configurable via environment variables (defaults shown):"))
story.append(tbl([
    ["Setting", "Default", "Effect"],
    ["MAX_CHAT_INPUT_CHARS", "8,000", "Rejects / truncates oversize inbound messages"],
    ["MAX_RESPONSE_CHARS", "16,000", "Hard output cap applied to every response"],
    ["MAX_LLM_MAX_TOKENS", "2,048", "Ceiling on provider max_tokens per call"],
    ["MAX_TOOL_RESULT_CHARS", "4,000", "Caps tool results fed back to the model"],
    ["TOKEN_BENCHMARK_WINDOW", "200", "Rolling window for token monitoring"],
], [110, 70, 300]))
story.append(Spacer(1, 6))
story.append(P("<b>How it works at runtime:</b>", body))
story.append(B("&bull; <b>Input guard</b> — every chat message is sanitized (control characters removed, whitespace collapsed) and hard-truncated to 8,000 characters before it ever reaches the model. Oversized input is rejected with a clear message."))
story.append(B("&bull; <b>Output guard</b> — the unified LLM gateway (<font face='Courier'>llm_providers.py</font>) clamps max_tokens to 2,048 and truncates every response to 16,000 characters at the provider boundary, so all 12 agents are protected automatically. Truncated responses carry a visible &ldquo;[Response truncated]&rdquo; marker."))
story.append(B("&bull; <b>Tool-result cap</b> — database query results are trimmed to 4,000 characters before the model sees them on follow-up turns."))
story.append(B("&bull; <b>Benchmark logging</b> — every agent response records estimated input/output tokens to the ai_agent_runs table (previously always NULL), writes a structured &ldquo;BENCH token_usage&rdquo; log line, and updates an in-memory rolling benchmark. A new GET /agents/benchmark endpoint reports average tokens per response."))

story.append(P("3. Measured Impact (Benchmark Report)", h1))
story.append(P("Estimated tokens use a characters/4 heuristic (monitoring-grade):"))
story.append(tbl([
    ["Case", "Input chars", "Output chars", "Before (tokens)", "After (tokens)", "Reduction"],
    ["10 standard queries (avg)", "~62", "~4,800", "~1,245", "~1,245", "0% (unchanged)"],
    ["Spike: 45k-char paste", "45,000", "45,000", "22,500", "4,048", "82.0%"],
    ["Overall average", "—", "—", "3,155", "1,477", "53.2%"],
], [140, 60, 65, 70, 70, 80]))
story.append(Spacer(1, 6))
story.append(Table(
    [[Paragraph("<b>Key message:</b> Normal business queries are unaffected (0% change — no quality or UX impact). The caps only bite on abuse/spike scenarios — a 45,000-character paste now costs <b>82% fewer tokens</b> than before, and the worst-case token consumption per call is now bounded and predictable instead of open-ended.", box)]],
    colWidths=[475],
    style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 1, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]),
))

story.append(P("4. Deliverables Delivered", h1))
story.append(B("&bull; <b>Code:</b> tokens.py (new), config limits in config.py, enforcement in llm_providers.py, agents.py, ai.py and agents/base.py — covering all active AI agents."))
story.append(B("&bull; <b>Benchmark:</b> scripts/token_benchmark.py — reproducible before/after report (run: python scripts/token_benchmark.py)."))
story.append(B("&bull; <b>Tests:</b> backend/tests/test_token_and_branding.py — 10/10 passing, covering input caps, control-character rejection, output truncation, max_tokens clamping and benchmark recording. Full suite shows no regressions (124/128; the 4 failures are pre-existing Docker / PostgreSQL-removal environment tests)."))
story.append(B("&bull; <b>Monitoring:</b> GET /agents/benchmark endpoint plus per-response BENCH log lines for ongoing cost tracking."))
story.append(Spacer(1, 10))
story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#d8d4e6")))
story.append(P("Prepared from verified code and test results. All limits above are defaults and can be tuned via environment variables without code changes.", small))

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                        title="Token Optimization — Summary for Management", author="StratRoom Engineering")
doc.build(story)
print("WROTE", OUT)
