"""Generate a clean PDF from chat_engine_architecture.md with real mermaid diagrams.

Pipeline:
  1. Read md, extract mermaid blocks, convert the rest to HTML (markdown).
  2. Download (once) mermaid.min.js -> temp cache, inline it.
  3. Render each mermaid block with mermaid.render in headless Chromium (playwright).
  4. page.pdf(print_background=True) -> OUT, then verify with pymupdf.
"""
import html
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

SRC = Path(__file__).parent / "chat_engine_architecture.md"
OUT = Path(__file__).parent / "chat_engine_architecture_clean.pdf"
TMP = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "kilo"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"
MERMAID_JS = TMP / "mermaid.min.js"

CHROMIUM = r"C:\Users\selva\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"

def ensure_mermaid():
    if not MERMAID_JS.exists() or MERMAID_JS.stat().st_size < 1000:
        MERMAID_JS.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading mermaid.min.js ...")
        urllib.request.urlretrieve(MERMAID_URL, MERMAID_JS)
    return MERMAID_JS.read_text(encoding="utf-8")


def extract_mermaid_blocks(text):
    """Map each mermaid block to a figure key.

    The graph *type* is the reliable discriminator; content disambiguates
    only within the same type (TD flowcharts and LR flowcharts are generic):
      1. graph TB        -> architecture_high_level
      2. sequenceDiagram -> request_lifecycle
      3. flowchart TD    -> tool_cool / conversation_flow / output_validate (by content)
      4. flowchart LR    -> memory_lifecycle / input_sanitize (by content)
    Content-based fallbacks run only within the matching type so that e.g. a
    sequence diagram mentioning "TOOL_CALL" in a note cannot be misread as the
    tool-calling loop.
    """
    TD_CONTENT = [
        ("TOOL_CALL", "tool_loop"),
        ("conversation_id", "conversation_flow"),
        ("Raw LLM output", "output_validate"),
        ("PII", "output_validate"),
    ]
    LR_CONTENT = [
        ("Strip control chars", "input_sanitize"),
        ("ai_memory", "memory_lifecycle"),
        ("confidence", "memory_lifecycle"),
    ]
    blocks = []
    for m in re.finditer(r"```mermaid\n(.*?)```", text, re.DOTALL):
        code = m.group(1).strip("\n")
        first = next((l.strip() for l in code.split("\n") if l.strip()), "")
        key = None
        if first == "sequenceDiagram":
            key = "request_lifecycle"
        elif first == "graph TB":
            key = "architecture_high_level"
        elif first == "flowchart TD":
            for needle, candidate in TD_CONTENT:
                if needle in code:
                    key = candidate
                    break
            if key is None:
                key = "output_validate"
        elif first == "flowchart LR":
            for needle, candidate in LR_CONTENT:
                if needle in code:
                    key = candidate
                    break
            if key is None:
                key = "memory_lifecycle"
        else:
            key = "output_validate"
        blocks.append((m.start(), m.end(), key, code))
    return blocks


FIG_TITLES = {
    "architecture_high_level": "High-Level System Architecture",
    "request_lifecycle": "Request Lifecycle (Sequence Diagram)",
    "tool_loop": "Tool-Calling Loop (max 3 iterations)",
    "memory_lifecycle": "Memory Lifecycle",
    "conversation_flow": "Conversation History Flow",
    "input_sanitize": "Input Sanitization Pipeline",
    "output_validate": "Output Validation Pipeline",
}

PLUGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
__CSS__
</style>
<script>__MERMAID_JS__</script>
</head><body>
<h1 class="title">StratRoom Chat Engine &mdash; Data Retrieval Architecture</h1>
__BODY__
<script>
window.__mermaidDone = false;
document.addEventListener('DOMContentLoaded', async function () {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'base',
    themeVariables: {
      primaryColor: '#e3f2fd', primaryBorderColor: '#1b4965', primaryTextColor: '#0d1b2a',
      lineColor: '#556', secondaryColor: '#fff3e0', tertiaryColor: '#e8f5e9',
      fontFamily: 'Segoe UI, Arial, sans-serif'
    },
    flowchart: { curve: 'basis', htmlLabels: true },
    sequence: { actorMargin: 55, messageMargin: 38, mirrorActors: false }
  });
  var figs = document.querySelectorAll('figure.mermaid-wrap');
  for (var i = 0; i < figs.length; i++) {
    var wrap = figs[i];
    var raw = wrap.querySelector('.mermaid-placeholder').textContent;
    try {
      var out = await mermaid.render('mmd-fig' + (i + 1), raw);
      var div = document.createElement('div');
      div.className = 'svg-host';
      div.innerHTML = out.svg;
      var el = div.querySelector('svg');
      if (el) {
        el.setAttribute('width', '100%');
        el.setAttribute('height', 'auto');
        el.style.maxWidth = '100%';
        el.style.height = 'auto';
      }
      wrap.insertBefore(div, wrap.querySelector('figcaption'));
    } catch (e) {
      wrap.innerHTML = '<div class="mmd-error">[diagram failed to render: ' + e.message + ']</div>';
    }
  }
  window.__mermaidDone = true;
});
</script>
</body></html>"""

CSS = """
@page { size: A4; margin: 16mm 14mm 18mm;
  @bottom-center { content: "StratRoom Chat Engine Architecture | Page " counter(page) " of " counter(pages); font-size: 8pt; color: #888; } }
html, body { margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.5pt; line-height: 1.5; color: #1a1a1a; }
h1.title { font-size: 20pt; color: #0d1b2a; border-bottom: 2px solid #1b4965; padding-bottom: 6px; margin: 0 0 8pt 0; }
h1 { font-size: 17pt; color: #0d1b2a; border-bottom: 2px solid #1b4965; padding-bottom: 4px; }
h2 { font-size: 13pt; color: #1b4965; border-bottom: 1px solid #bee9e8; padding-bottom: 2px; margin: 16pt 0 6pt 0; page-break-after: avoid; }
h3 { font-size: 11pt; color: #2d6a4f; margin: 10pt 0 4pt 0; page-break-after: avoid; }
h4 { font-size: 10pt; color: #40916c; margin: 8pt 0 4pt 0; page-break-after: avoid; }
blockquote { border-left: 3px solid #1b4965; background: #f0f7f4; padding: 6px 12px; color: #333; margin: 8pt 0; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 8pt; color: #c7254e; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; padding: 8pt 10pt;
      font-family: Consolas, 'Courier New', monospace; font-size: 7.5pt; white-space: pre-wrap;
      page-break-inside: avoid; overflow-wrap: break-word; }
pre code { color: #24292e; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8pt; table-layout: fixed;
        page-break-inside: auto; word-wrap: break-word; }
th { background: #1b4965; color: #fff; padding: 4pt 6pt; text-align: left; border: 1px solid #1b4965; font-weight: bold; }
td { padding: 3pt 6pt; border: 1px solid #d0d7de; vertical-align: top; word-wrap: break-word; }
tr { page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #dee2e6; margin: 8pt 0; }
strong { font-weight: bold; }
ul, ol { margin: 4pt 0 4pt 18pt; padding: 0; }
li { margin: 2pt 0; }
a { color: #1b4965; text-decoration: none; }
section.mermaid-wrap { page-break-inside: avoid; margin: 10pt auto; text-align: center; }
.mermaid-wrap svg { max-width: 100% !important; height: auto; margin: 4pt auto; }
.mermaid-wrap figcaption { font-size: 8pt; color: #666; margin-top: 2pt; text-align: center; }
.mermaid-placeholder { display: none; }
.mmd-error { background: #fdf2f2; border: 1px solid #f5c6c6; color: #b02a37; padding: 8pt; text-align: left; }
@media print { section.mermaid-wrap { page-break-inside: avoid; } }
"""


def md_to_html(raw):
    import markdown as md
    return md.markdown(raw, extensions=["tables", "fenced_code", "toc", "sane_lists"])


def build_html(raw, mermaid_js, blocks):
    chunks, cursor = [], 0
    for i, (start, end, key, code) in enumerate(blocks, start=1):
        chunks.append(raw[cursor:start])
        esc = html.escape(code)
        title = FIG_TITLES.get(key, key)
        chunks.append(
            '<section class="mermaid-wrap" data-fig="%d" data-key="%s">'
            '<div class="mermaid-placeholder">%s</div>'
            '<figcaption>Figure %d &mdash; %s</figcaption></section>'
            % (i, html.escape(key), esc, i, title)
        )
        cursor = end
    chunks.append(raw[cursor:])
    raw = "".join(chunks)

    body = md_to_html(raw)
    doc = PLUGIN_HTML
    doc = doc.replace("__CSS__", CSS)
    doc = doc.replace("__MERMAID_JS__", mermaid_js)
    doc = doc.replace("__BODY__", body)
    return doc


def main():
    raw = SRC.read_text(encoding="utf-8")
    blocks = extract_mermaid_blocks(raw)
    if not blocks:
        print("ERROR: no mermaid blocks found", file=sys.stderr)
        sys.exit(2)
    mermaid_js = ensure_mermaid()
    html_doc = build_html(raw, mermaid_js, blocks)

    tmp_dir = TMP
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_html = tmp_dir / "chat_engine_doc.html"
    tmp_html.write_text(html_doc, encoding="utf-8")

    from playwright.sync_api import sync_playwright

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(tmp_html.as_uri(), wait_until="networkidle")
        page.wait_for_function("window.__mermaidDone === true", timeout=60000)
        page.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
        )
        browser.close()

    import pymupdf
    doc = pymupdf.open(str(OUT))
    print(f"PDF written: {OUT}")
    print(f"Pages: {doc.page_count}")
    print(f"Size: {OUT.stat().st_size / 1024:.1f} KB", flush=True)


if __name__ == "__main__":
    main()