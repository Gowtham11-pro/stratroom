"""Generate a clean PDF from chat_engine_architecture.md using PyMuPDF Story API.

Handles:
  - Mermaid blocks -> rendered as styled HTML diagram tables
  - Tables, code blocks, headings with clean typography
  - Page numbers + running header
  - Windows system fonts via Archive + @font-face (Segoe UI / Consolas)
"""
import os
import re
import shutil
import sys
from pathlib import Path

import pymupdf
import markdown as md

SRC = Path(__file__).parent / "chat_engine_architecture.md"
OUT = Path(__file__).parent / "chat_engine_architecture.pdf"

FONT_DIR = os.environ.get("WINDIR", "C:/Windows") + "/Fonts"


def _pick(fonts: list[str]) -> str:
    for name in fonts:
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return p
    return os.path.join(FONT_DIR, fonts[-1])


sans = _pick(["segoeui.ttf", "arial.ttf", "tahoma.ttf"])
sans_b = _pick(["segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf"])
sans_i = _pick(["segoeuii.ttf", "ariali.ttf", "timesi.ttf"])
sans_bi = _pick(["segoeuiz.ttf", "arialbi.ttf", "timesbi.ttf"])
mono = _pick(["consola.ttf", "cour.ttf"])
mono_b = _pick(["consolab.ttf", "courbd.ttf"])

arch = pymupdf.Archive()
for _path in (sans, sans_b, sans_i, sans_bi, mono, mono_b):
    arch.add(Path(_path).read_bytes(), path=f"fonts/{os.path.basename(_path)}")

# ── Mermaid -> HTML diagram replacements ─────────────────────────────────────
MERMAID_HTML = {
    "architecture_high_level": """
<div class="diagram">
<h4>Figure 1 — High-Level System Architecture</h4>
<table class="flow">
<tr><td class="box frontend" colspan="4"><b>Frontend</b><br/>Single-File SPA (31may_index.html)</td></tr>
<tr><td class="arrow" colspan="4">&#8595; POST /agents/chat</td></tr>
<tr>
<td class="box backend"><b>FastAPI Router</b><br/>routers/agents.py</td>
<td class="arrow w">&#8594;</td>
<td class="box backend"><b>AgentRunner</b><br/>agents/base.py</td>
</tr>
<tr><td class="arrow" colspan="4">&#8595;</td></tr>
<tr>
<td class="box ai"><b>Context Enhancer</b><br/>ai/query_enhancer.py</td>
<td class="box ai"><b>Memory Store</b><br/>ai/memory.py</td>
<td class="box ai"><b>LLM Providers</b><br/>ai/llm_providers.py</td>
<td class="box ai"><b>Guardrails</b><br/>ai/guardrails.py</td>
</tr>
<tr><td class="arrow" colspan="4">&#8595; tool calls / &#8593; results</td></tr>
<tr>
<td class="box tools">Task Tools</td>
<td class="box tools">Risk Tools</td>
<td class="box tools">Scorecard Tools</td>
<td class="box tools">Initiative Tools</td>
</tr>
<tr>
<td class="box tools">Incident Tools</td>
<td class="box tools">Decision Tools</td>
<td class="box tools">&nbsp;</td>
<td class="box tools">&nbsp;</td>
</tr>
<tr><td class="arrow" colspan="4">&#8595; SQL queries &#8594; <b>JavaBridge</b> (services/java_bridge.py) &#8594; <b>MySQL</b> (orgstructure)</td></tr>
<tr><td class="arrow" colspan="4">&#8595; HTTP API calls</td></tr>
<tr>
<td class="box llm">OpenAI</td>
<td class="box llm">Anthropic</td>
<td class="box llm">Google</td>
<td class="box llm">Ollama</td>
</tr>
<tr><td class="box llm" colspan="4">DeepSeek / Together / Mistral / xAI / Qwen</td></tr>
</table>
</div>
""",
    "request_lifecycle": """
<div class="diagram">
<h4>Figure 2 — Request Lifecycle (Sequence Diagram)</h4>
<table class="seq">
<tr><td class="seqn">1</td><td>User types message and selects an agent in the SPA</td></tr>
<tr><td class="seqn">2</td><td>Frontend sends <code>POST /agents/chat</code> with <code>{agent, message, provider, model}</code></td></tr>
<tr><td class="seqn">3</td><td>FastAPI router resolves provider/model, creates <code>AgentRunner</code>, calls <code>runner.run()</code></td></tr>
<tr><td class="seqn">4</td><td><b>Input sanitization</b> — strips control chars, truncates to 8,000 chars</td></tr>
<tr><td class="seqn">5</td><td><b>Module data fetch</b> — SQL SELECTs from <code>task_details</code>, <code>risk_details</code>, <code>scorecard_kpis</code>, etc. via JavaBridge</td></tr>
<tr><td class="seqn">6</td><td><b>Memory enrichment</b> — queries <code>ai_memory</code> (up to 8 insights) + <code>agent_conversations</code> (last 3 convos &#215; 3 messages)</td></tr>
<tr><td class="seqn">7</td><td><b>System prompt assembly</b> — persona + enriched context + live org data block</td></tr>
<tr><td class="seqn">8</td><td><b>Intent auto-detection</b> — rewrites "my tasks" &#8594; query_tasks with owner filter</td></tr>
<tr><td class="seqn">9</td><td><b>First LLM call</b> — sends assembled prompt to chosen provider</td></tr>
<tr><td class="seqn">10</td><td><b>Tool-calling loop</b> (max 3 iterations): parse <code>[TOOL_CALL:name:args]</code>, execute SQL, feed result back for LLM summarization</td></tr>
<tr><td class="seqn">11</td><td><b>Output guardrails</b> — validate length, deduplicate, mask PII</td></tr>
<tr><td class="seqn">12</td><td><b>Persist</b> — save messages to <code>agent_messages</code>, store insight in <code>ai_memory</code>, prune old memories</td></tr>
<tr><td class="seqn">13</td><td><b>Log metrics</b> — insert row into <code>ai_agent_runs</code></td></tr>
<tr><td class="seqn">14</td><td>Return JSON response to frontend &#8594; displayed to user</td></tr>
</table>
</div>
""",
    "tool_loop": """
<div class="diagram">
<h4>Figure 3 — Tool-Calling Loop (max 3 iterations)</h4>
<table class="flow">
<tr><td class="box llm" colspan="4"><b>LLM Response</b></td></tr>
<tr><td class="arrow" colspan="4">&#8595;</td></tr>
<tr><td class="box backend" colspan="4"><b>Contains [TOOL_CALL:name:args] ?</b></td></tr>
<tr><td class="arrow" colspan="4">no &#8594; final answer | yes &#8595;</td></tr>
<tr><td class="box tools" colspan="4"><b>Execute tool via _execute_tool()</b> &#8594; MySQL query</td></tr>
<tr><td class="arrow" colspan="4">&#8595;</td></tr>
<tr><td class="box backend" colspan="4"><b>Truncate result &gt; 4,000 chars</b> &#8594; wrap in [TOOL_RESULT]</td></tr>
<tr><td class="arrow" colspan="4">&#8595;</td></tr>
<tr><td class="box ai" colspan="4"><b>Feed result back to LLM</b>: "Summarize this result naturally"</td></tr>
<tr><td class="arrow" colspan="4">&#8595; second LLM call</td></tr>
<tr><td class="box frontend" colspan="4"><b>Loop back to check for more tool calls</b> (max 3)</td></tr>
<tr><td class="box llm" colspan="4"><b>Final natural-language answer returned to user</b></td></tr>
</table>
</div>
""",
    "memory_lifecycle": """
<div class="diagram">
<h4>Figure 4 — Memory Lifecycle</h4>
<table class="seq">
<tr><td class="seqn">1</td><td><b>Store:</b> LLM response passed to <code>store_memory()</code> (ai/memory.py)</td></tr>
<tr><td class="seqn">2</td><td>Filtered: trivial exchanges (greetings/small talk), responses &lt; 40 chars, messages &lt; 10 chars &#8594; skipped</td></tr>
<tr><td class="seqn">3</td><td>Confidence scored 0.0-1.0 (base 0.4 + data-richness bonuses); rejected if &lt; 0.3</td></tr>
<tr><td class="seqn">4</td><td>Deduplicated via first-80-chars comparison against existing <code>ai_memory</code> rows</td></tr>
<tr><td class="seqn">5</td><td><b>INSERT</b> into <code>ai_memory</code> (user_id, org_id, agent_name, insight, confidence, source)</td></tr>
<tr><td class="seqn">6</td><td><b>Retrieve:</b> SELECT user-specific memories ordered by confidence DESC, accessed_at DESC (limit 8)</td></tr>
<tr><td class="seqn">7</td><td>Fallback: if fewer than 3 user-specific, supplement with org-wide memories</td></tr>
<tr><td class="seqn">8</td><td><b>Prune:</b> after each store, if count &gt; 200 per agent, delete lowest access_count + confidence + oldest</td></tr>
</table>
</div>
""",
    "conversation_flow": """
<div class="diagram">
<h4>Figure 5 — Conversation History Flow</h4>
<table class="seq">
<tr><td class="seqn">1</td><td>New user message arrives; check <code>conversation_id</code></td></tr>
<tr><td class="seqn">2</td><td>If present: load last 20 messages from <code>agent_messages</code> via <code>_load_history()</code></td></tr>
<tr><td class="seqn">3</td><td>If absent: start a fresh message list</td></tr>
<tr><td class="seqn">4</td><td>Append the new user message and send the assembled <code>messages</code> to the LLM</td></tr>
<tr><td class="seqn">5</td><td>After the LLM responds, create a conversation via <code>POST /conversations</code> if none existed</td></tr>
<tr><td class="seqn">6</td><td>Save both user and assistant messages to <code>agent_messages</code></td></tr>
<tr><td class="seqn">7</td><td>Store an insight in <code>ai_memory</code>, then prune stale memories</td></tr>
</table>
</div>
""",
    "input_sanitize": """
<div class="diagram">
<h4>Figure 6 — Input Sanitization Pipeline</h4>
<table class="seq">
<tr><td class="seqn">1</td><td>Raw user input from the chat request</td></tr>
<tr><td class="seqn">2</td><td>Strip control characters (&#92;x00-&#92;x08, &#92;x0b, &#92;x0c, &#92;x0e-&#92;x1f, &#92;x7f)</td></tr>
<tr><td class="seqn">3</td><td>Collapse multi-whitespace; trim leading/trailing spaces</td></tr>
<tr><td class="seqn">4</td><td>Truncate to <code>MAX_CHAT_INPUT_CHARS</code> (8,000)</td></tr>
<tr><td class="seqn">5</td><td>Clean input ready for the agent pipeline</td></tr>
</table>
</div>
""",
    "output_validate": """
<div class="diagram">
<h4>Figure 7 — Output Validation Pipeline</h4>
<table class="seq">
<tr><td class="seqn">1</td><td>Raw LLM output from provider</td></tr>
<tr><td class="seqn">2</td><td>Empty response (&lt; 5 chars) &#8594; safe fallback message returned</td></tr>
<tr><td class="seqn">3</td><td>Length &gt; 50,000 chars &#8594; truncated with marker</td></tr>
<tr><td class="seqn">4</td><td>Repetitive output detected (&gt; 70% duplicate lines, &gt; 40% duplicate trigrams) &#8594; deduplicated</td></tr>
<tr><td class="seqn">5</td><td>PII detection (emails, phones, SSNs) &#8594; masked with [REDACTED_*]</td></tr>
<tr><td class="seqn">6</td><td>Clean, validated response returned to user</td></tr>
</table>
</div>
""",
}


def extract_mermaid_blocks(text: str):
    blocks = []
    for m in re.finditer(r"```mermaid\n(.*?)```", text, re.DOTALL):
        code = m.group(1)
        first_line = next((l.strip() for l in code.split("\n") if l.strip()), "")
        key = None
        if first_line == "sequenceDiagram":
            key = "request_lifecycle"
        elif first_line == "graph TB":
            key = "architecture_high_level"
        elif first_line == "flowchart LR":
            key = "memory_lifecycle"
        elif first_line == "flowchart TD":
            if "TOOL_CALL" in code:
                key = "tool_loop"
            elif "conversation_id" in code:
                key = "conversation_flow"
            else:
                key = "output_validate"
        blocks.append((m.start(), m.end(), key, code))
    return blocks


def build_html(raw: str, css: str) -> str:
    blocks = extract_mermaid_blocks(raw)
    if blocks:
        chunks, cursor = [], 0
        for start, end, key, code in blocks:
            chunks.append(raw[cursor:start])
            chunks.append(MERMAID_HTML.get(key, f"<pre>{code}</pre>"))
            cursor = end
        chunks.append(raw[cursor:])
        raw = "".join(chunks)

    html_body = md.markdown(raw, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    return f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"


CSS = """
@font-face { font-family: sans; src: url(fonts/__SANS__); font-weight: normal; font-style: normal; }
@font-face { font-family: sans; src: url(fonts/__SANSB__); font-weight: bold; font-style: normal; }
@font-face { font-family: sans; src: url(fonts/__SANSI__); font-weight: normal; font-style: italic; }
@font-face { font-family: sans; src: url(fonts/__SANSCI__); font-weight: bold; font-style: italic; }
@font-face { font-family: mono; src: url(fonts/__MONO__); font-weight: normal; font-style: normal; }
@font-face { font-family: mono; src: url(fonts/__MONOB__); font-weight: bold; font-style: normal; }

body { font-family: sans; font-size: 9.5pt; line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 21pt; color: #0d1b2a; border-bottom: 2px solid #1b4965; padding-bottom: 6px; font-family: sans; font-weight: bold; }
h2 { font-size: 14pt; color: #1b4965; border-bottom: 1px solid #bee9e8; padding-bottom: 3px; margin-top: 18px; font-family: sans; font-weight: bold; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #2d6a4f; margin-top: 12px; font-family: sans; font-weight: bold; page-break-after: avoid; }
h4 { font-size: 10pt; color: #40916c; margin-top: 8px; font-family: sans; font-weight: bold; page-break-after: avoid; }
blockquote { border-left: 3px solid #1b4965; background: #f0f7f4; padding: 6px 12px; color: #333; }
code { font-family: mono; font-size: 8pt; color: #c7254e; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; padding: 8px 10px; font-family: mono; font-size: 7.5pt; white-space: pre-wrap; page-break-inside: avoid; }
pre code { font-family: mono; color: #24292e; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; font-size: 8.5pt; page-break-inside: auto; }
th { background: #1b4965; color: #fff; padding: 5px 7px; text-align: left; font-weight: bold; border: 1px solid #1b4965; }
td { padding: 4px 7px; border: 1px solid #d0d7de; vertical-align: top; }
tr { page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #dee2e6; }
strong { font-weight: bold; }

.diagram { background: #f8fbfa; border: 1px solid #d0e8e2; border-radius: 6px; padding: 10px; margin: 10px 0; page-break-inside: avoid; }
.diagram h4 { margin: 0 0 6px 0; color: #1b4965; }
table.flow { border-collapse: collapse; width: 100%; }
table.flow td { text-align: center; border: none; padding: 3px; }
td.box { border: 1.5px solid #999 !important; border-radius: 4px; font-size: 8pt; }
td.arrow { border: none !important; font-size: 9pt; color: #555; padding: 2px; }
td.w { width: 30px; }
td.frontend { background: #e3f2fd; }
td.backend { background: #fff3e0; }
td.ai { background: #e8f5e9; }
td.tools { background: #fce4ec; }
td.llm { background: #e0f7fa; }
td.box b { display: block; }
table.seq { border-collapse: collapse; width: 100%; }
table.seq td { border: none; border-bottom: 1px solid #e0e0e0; padding: 4px 8px; font-size: 8.5pt; }
td.seqn { width: 24px; font-weight: bold; color: #1b4965; text-align: center; background: #eef5f8; }
""".replace(
    "__SANS__", os.path.basename(sans)
).replace(
    "__SANSB__", os.path.basename(sans_b)
).replace(
    "__SANSI__", os.path.basename(sans_i)
).replace(
    "__SANSCI__", os.path.basename(sans_bi)
).replace(
    "__MONO__", os.path.basename(mono)
).replace(
    "__MONOB__", os.path.basename(mono_b)
)


def main():
    raw = SRC.read_text(encoding="utf-8")
    html_doc = build_html(raw, CSS)

    mediabox = pymupdf.paper_rect("a4")
    writer = pymupdf.DocumentWriter(str(OUT))

    content_rect = mediabox - (42, 48, 42, 40)
    story = pymupdf.Story(html=html_doc, user_css=CSS, archive=arch)

    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _filled = story.place(content_rect)
        story.draw(dev)
        writer.end_page()
    writer.close()

    # ── Stamp footer page numbers ───────────────────────────────────────────
    doc = pymupdf.open(str(OUT))
    total = doc.page_count
    for i, page in enumerate(doc):
        r = page.rect
        label = f"StratRoom Chat Engine Architecture — Page {i + 1} of {total}"
        w = pymupdf.get_text_length(label, fontname="helv", fontsize=8)
        page.insert_text(
            pymupdf.Point((r.width - w) / 2, r.height - 14),
            label, fontsize=8, fontname="helv", color=(0.55, 0.55, 0.55),
        )
    doc.save(str(OUT) + ".tmp", garbage=3, deflate=True)
    doc.close()
    shutil.move(str(OUT) + ".tmp", str(OUT))

    print(f"PDF written: {OUT}")
    print(f"Pages: {total}")
    print(f"Size: {OUT.stat().st_size / 1024:.1f} KB", flush=True)


if __name__ == "__main__":
    main()
