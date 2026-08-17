"""Generate the StratRoom PDF report: Task & Initiative Progress Update Module + Chat Agent Integration.

Follows the visual style of docs/make_server_guide.py (reportlab, A4, navy header blocks,
flow charts as reportlab Drawing objects, data tables).

Run:  python docs/make_progress_module_report.py
"""
import math
import os
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable,
    KeepTogether, HRFlowable, PageBreak,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon
from reportlab.graphics import renderPDF

# ---------------- palette ----------------
C_NAVY    = colors.HexColor("#0b3d6f")
C_BLUE    = colors.HexColor("#1f6fb2")
C_LBLUE   = colors.HexColor("#e8f1fb")
C_GREEN   = colors.HexColor("#2e7d32")
C_LGREEN  = colors.HexColor("#e6f4ea")
C_ORANGE  = colors.HexColor("#d97b1f")
C_LORANGE = colors.HexColor("#fdf0e0")
C_GRAY    = colors.HexColor("#6b7280")
C_LGRAY   = colors.HexColor("#f3f4f6")
C_WHITE   = colors.white
C_DARK    = colors.HexColor("#1f2937")
C_RED     = colors.HexColor("#b3261e")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Progress_Update_Module_Report.pdf")

# ---------------- styles ----------------
ss = getSampleStyleSheet()

S_TITLE = ParagraphStyle("S_TITLE", parent=ss["Title"], fontName="Helvetica-Bold",
                         fontSize=22, textColor=C_WHITE, leading=26)
S_TITLE2 = ParagraphStyle("S_TITLE2", parent=ss["Title"], fontName="Helvetica-Bold",
                          fontSize=15, textColor=C_WHITE, leading=18)
S_SUB   = ParagraphStyle("S_SUB", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=10.5, textColor=C_LBLUE, leading=15)
S_H1    = ParagraphStyle("S_H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                         fontSize=15, textColor=C_NAVY, spaceBefore=14, spaceAfter=6,
                         leading=19)
S_H2    = ParagraphStyle("S_H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=11.5, textColor=C_BLUE, spaceBefore=10, spaceAfter=4,
                         leading=15)
S_H3    = ParagraphStyle("S_H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                         fontSize=10.5, textColor=C_NAVY, spaceBefore=8, spaceAfter=3,
                         leading=14)
S_P     = ParagraphStyle("S_P", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=9.6, textColor=C_DARK, leading=13.5, spaceAfter=5)
S_BUL   = ParagraphStyle("S_BUL", parent=S_P, leftIndent=14, bulletIndent=4, spaceAfter=3)
S_CODE  = ParagraphStyle("S_CODE", parent=ss["Code"], fontName="Courier",
                         fontSize=7.6, leading=10.5, backColor=C_LGRAY,
                         borderColor=C_GRAY, borderWidth=0.6, borderPadding=6,
                         spaceBefore=2, spaceAfter=6)
S_CAP   = ParagraphStyle("S_CAP", parent=S_P, fontName="Helvetica-Oblique",
                         fontSize=8.2, textColor=C_GRAY, alignment=TA_CENTER,
                         leading=11, spaceAfter=4)
S_CELL  = ParagraphStyle("S_CELL", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=8.4, leading=11)
S_CELLB = ParagraphStyle("S_CELLB", parent=S_CELL, fontName="Helvetica-Bold",
                         textColor=C_WHITE)
S_TBLT  = ParagraphStyle("S_TBLT", parent=S_CELL, fontName="Helvetica-Bold", textColor=C_NAVY)

def H1(t):  return Paragraph(t, S_H1)
def H2(t):  return Paragraph(t, S_H2)
def H3(t):  return Paragraph(t, S_H3)
def P(t):   return Paragraph(t, S_P)
def BUL(t): return Paragraph(t, S_BUL, bulletText="\u2022")
def CODE(t):return Paragraph(t, S_CODE)
def CAP(t): return Paragraph(t, S_CAP)
def CELL(t):return Paragraph(t, S_CELL)
def CELLB(t):return Paragraph(t, S_CELLB)


# ---------------- graphics helpers ----------------
def _box(d, x, y, w, h, lines, fill=C_LBLUE, border=C_BLUE, text_color=C_DARK,
         font_size=9, radius=6, border_width=1.2, font_name="Helvetica"):
    d.add(Rect(x, y, w, h, rx=radius, ry=radius, fillColor=fill,
               strokeColor=border, strokeWidth=border_width))
    if isinstance(lines, str):
        lines = [lines]
    n = len(lines)
    line_h = h / float(n)
    for i, ln in enumerate(lines):
        ty = y + h - line_h * (i + 0.5)
        d.add(String(x + w / 2.0, ty, ln, textAnchor="middle", fontSize=font_size,
                     fillColor=text_color, fontName=font_name))


def _arrow(d, x1, y1, x2, y2, color=C_GRAY, width=1.3, dashed=False):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=width,
               strokeDashArray=[4, 3] if dashed else None))
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 9.0
    bx = x2 - L * math.cos(ang)
    by = y2 - L * math.sin(ang)
    px = -L * 0.55 * math.sin(ang)
    py = L * 0.55 * math.cos(ang)
    d.add(Polygon([x2, y2, bx + px, by + py, bx - px, by - py],
                  fillColor=color, strokeColor=color))


def _note(d, x, w, y, text, font_size=7.6, color=C_GRAY):
    d.add(String(x + w / 2.0, y, text, textAnchor="middle", fontSize=font_size,
                 fillColor=color, fontName="Helvetica-Oblique"))


# ---------------- Flow Chart 1 : front-end -> agent chat pipeline ----------------
def chart1():
    d = Drawing(560, 300)
    _note(d, 0, 560, 278, "FLOW CHART 1  —  Chat Agent integration: front-end -> /agents/chat -> tool execution", 9.5, C_NAVY)

    _box(d, 20, 226, 185, 40,
         ["SPA  -  31may_index.html", "sendModuleChat('tasks')", "agent=task  provider/model from UI"],
         fill=C_LGRAY, border=C_GRAY, font_size=7.6)
    _arrow(d, 205, 246, 262, 246)

    _box(d, 262, 214, 278, 52,
         ["FastAPI  POST /agents/chat  (agents.py)", "AgentChatRequest {agent, message, provider,", "model, api_key, base_url, conversation_id}", "require_role('member')  ->  JWT"],
         fill=C_LORANGE, border=C_ORANGE, font_size=7.6)
    _arrow(d, 401, 214, 401, 190)

    _box(d, 262, 154, 278, 34,
         ["AgentRunner.run()  (base.py)", "sanitize input  ->  fetch agent context  ->  history"],
         fill=C_LBLUE, border=C_BLUE, font_size=7.6)
    _arrow(d, 401, 154, 401, 130)

    _box(d, 30, 96, 245, 32,
         ["_auto_fetch_tool()  intent detection", "rewrites ambiguous queries BEFORE the LLM"],
         fill=C_LBLUE, border=C_BLUE, font_size=7.6)
    _arrow(d, 262, 130, 262, 112, dashed=True)

    _box(d, 300, 96, 240, 32,
         ["call_llm_with_retry()", "Ollama / OpenAI-compat / mock", "emits [TOOL_CALL:name:args]"],
         fill=C_LGREEN, border=C_GREEN, font_size=7.6)
    _arrow(d, 401, 112, 401, 96)

    _box(d, 30, 34, 245, 40,
         ["Tool execution  loop  (max 3)", "_execute_tool() dispatch table", "result fed back -> LLM summary"],
         fill=C_LGREEN, border=C_GREEN, font_size=7.6)
    _arrow(d, 262, 96, 262, 74)
    _arrow(d, 300, 96, 300, 74)

    _box(d, 300, 34, 240, 40,
         ["MySQL  orgstructure", "task_details / initiatives_details", "JSON columns + status columns"],
         fill=C_LORANGE, border=C_ORANGE, font_size=7.6)
    _arrow(d, 401, 74, 401, 74)

    _note(d, 0, 560, 12,
          "The tool-calling loop runs up to 3 iterations: execute the tool, then ask the LLM to summarize the result naturally.",
          7.6, C_GRAY)
    return d


# ---------------- Flow Chart 2 : intent routing decision ----------------
def chart2():
    d = Drawing(560, 380)
    _note(d, 0, 560, 360, "FLOW CHART 2  —  Intent detection & routing in _auto_fetch_tool()", 9.5, C_NAVY)

    _box(d, 130, 318, 300, 30,
         ["User message arrives (any agent: task / projects / strategy ...)"],
         fill=C_LGRAY, border=C_GRAY, font_size=8)
    _arrow(d, 280, 318, 280, 294)

    _box(d, 70, 262, 420, 30,
         ["initiative|project  +  numeric ID  +  progress  ->  UPDATE INITIATIVE",
          "update initiative 8 progress to 80%   |   set project 12 to 60%"],
         fill=C_GREEN, border=C_GREEN, font_size=7.6)
    _arrow(d, 280, 294, 280, 292)
    _box(d, 70, 232, 420, 28,
         ["-> rewritten to  \"Call update_initiative_progress tool with id=X, progress=Y\"",
          "(never misread as a task - runs for EVERY agent)"],
         fill=C_LGREEN, border=C_GREEN, font_size=7.2)

    _arrow(d, 280, 232, 280, 208)
    _box(d, 70, 176, 420, 30,
         ["initiative|project  +  NAME (no ID)  +  progress  ->  ASK FOR ID",
          "update initiative progress to 80% for Market Analysis"],
         fill=C_ORANGE, border=C_ORANGE, font_size=7.6)
    _box(d, 70, 138, 420, 28,
         ["-> \"cannot resolve by name; do NOT map it to a task; ask for the ID\"",
          "prevents task mutation by a name-only initiative query"],
         fill=C_LORANGE, border=C_ORANGE, font_size=7.2)

    _arrow(d, 280, 176, 280, 168)

    _arrow(d, 280, 138, 280, 114)
    _box(d, 70, 82, 420, 30,
         ["task  +  numeric ID  ->  TASK intent",
          "update progress of task 102 to 80%   |   set task 5 progress to 60%"],
         fill=C_LBLUE, border=C_BLUE, font_size=7.6)
    _box(d, 70, 46, 420, 28,
         ["-> rewritten to  \"Call update_task_progress tool with id=X, progress=Y\""],
         fill=C_LBLUE, border=C_BLUE, font_size=7.2)

    _note(d, 0, 560, 16,
          "Detection order: initiative/project block is evaluated BEFORE the task block for every agent.",
          7.6, C_GRAY)
    return d


# ---------------- Flow Chart 3 : update task / initiative write path ----------------
def chart3():
    d = Drawing(560, 330)
    _note(d, 0, 560, 312, "FLOW CHART 3  —  update_task_progress() / update_initiative_progress() write path", 9.5, C_NAVY)

    _box(d, 150, 274, 260, 30,
         ["Tool called from _execute_tool() with { id, progress }"],
         fill=C_LGRAY, border=C_GRAY, font_size=8)
    _arrow(d, 280, 274, 280, 250)

    _box(d, 90, 214, 380, 34,
         ["1. Validate + clamp progress to 0-100",
          "int(progress); clamp = max(0, min(100, raw)); flag 'clamped'"],
         fill=C_LBLUE, border=C_BLUE, font_size=7.6)
    _arrow(d, 280, 214, 280, 190)

    _box(d, 90, 154, 380, 34,
         ["2. Resolve identity + RBAC scoping",
          "admin: unscoped   |   member: owner/emp_id + org_id scoped"],
         fill=C_LORANGE, border=C_ORANGE, font_size=7.6)
    _arrow(d, 280, 154, 280, 130)

    _box(d, 90, 94, 380, 34,
         ["3. Fetch row + verify ownership; parse JSON column",
          "task_details.task_value   |   initiatives_details.initiative_value"],
         fill=C_LBLUE, border=C_BLUE, font_size=7.6)
    _arrow(d, 280, 94, 280, 70)

    _box(d, 60, 34, 440, 34,
         ["4. Update JSON + status, write back via bridge._mysql_write()",
          "task: tv['progress'], auto status pending/in_progress/completed   |   initiative: progressval + statusLight/statusIndicator"],
         fill=C_GREEN, border=C_GREEN, font_size=7.4)

    _note(d, 0, 560, 16,
          "All other JSON keys are preserved (read-modify-write). Confirmation string reports the effective value incl. clamping.",
          7.6, C_GRAY)
    return d


# ---------------- reusable table helper ----------------
def data_table(headers, rows, widths, header_fill=C_NAVY):
    data = [[CELLB(h) for h in headers]]
    for r in rows:
        data.append([CELL(c) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_fill),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_LGRAY]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(style))
    return t


class ChartFlowable(Flowable):
    def __init__(self, drawing):
        super().__init__()
        self.drawing = drawing
        self.width = drawing.width
        self.height = drawing.height

    def draw(self):
        renderPDF.draw(self.drawing, self.canv, 0, 0)


def chart(drawing, caption):
    t = Table([[ChartFlowable(drawing)]], colWidths=[150 * mm])
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return [t, CAP(caption)]


# ---------------- document ----------------
def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="StratRoom - Task & Initiative Progress Update Module + Chat Agent Integration",
        author="StratRoom Engineering",
    )
    story = []

    # ---- cover / header block ----
    cover = Table([[Paragraph("StratRoom", S_TITLE)],
                   [Paragraph("Task &amp; Initiative Progress Update Module", S_TITLE)],
                   [Paragraph("Chat Agent Integration &amp; Intent Routing", S_TITLE2)],
                   [Paragraph(
                       "A structured technical report on the progress-update tooling, its "
                       "automated intent routing in the Chat Engine, RBAC scoping, data model, "
                       "verification results, and deployment steps.",
                       S_SUB)],
                   [Paragraph("Prepared %s  •  Version 1.0  •  Internal documentation" % date.today().strftime("%B %Y"), S_SUB)]],
                  colWidths=[178 * mm])
    cover.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(cover)
    story.append(Spacer(1, 10))

    # ---- contents ----
    story.append(H1("Contents"))
    toc = [
        "1.  Executive summary",
        "2.  Scope & terminology",
        "3.  Architecture at a glance",
        "4.  The Progress Update Module (task_details / initiatives_details)",
        "5.  Chat Agent Integration (end-to-end flow)",
        "6.  Intent detection & routing (_auto_fetch_tool)",
        "7.  Tool execution (_execute_tool) & RBAC",
        "8.  Direct API endpoints (task-action / initiative-action)",
        "9.  Provider resolution & configuration",
        "10. Verification & test results",
        "11. Deployment",
        "12. Troubleshooting & gotchas",
        "13. Appendix — reference tables, regexes, SQL",
    ]
    for t in toc:
        story.append(BUL(t))
    story.append(Spacer(1, 4))

    # ---- 1. Executive summary ----
    story.append(H1("1. Executive summary"))
    story.append(P(
        "This report documents the <b>Task &amp; Initiative Progress Update Module</b> and its integration with the "
        "<b>StratRoom Chat Agent</b>. The module lets users update the progress percentage of <b>tasks</b> "
        "(stored in <font face='Courier'>task_details</font>) and <b>initiatives / projects</b> (stored in "
        "<font face='Courier'>initiatives_details</font>) either directly through dedicated API endpoints or "
        "through natural-language chat."))
    story.append(P(
        "A focused hardening pass was applied in August 2026 after a production incident in which the phrase "
        "<font face='Courier'>\"update initiative 8 progress to 80%\"</font> erroneously updated <b>Task #8</b> instead of "
        "<b>Initiative SI-01</b>. The root cause was that initiative/project intent detection was gated to the "
        "<font face='Courier'>projects</font> and <font face='Courier'>strategy</font> agents only, so in the "
        "<b>tasks</b> chat the query fell through to the LLM which mis-identified it as a task. The fix makes "
        "initiative/project detection <b>agent-agnostic</b> and adds prompt-level guardrails. All changes were "
        "deployed to production and verified live."))

    key_facts = [
        ["Feature area", "Progress update for tasks (0-100%) and initiatives (0-100%), query + update"],
        ["Backend endpoints", "POST /agents/chat, POST /agents/task-action, POST /agents/initiative-action, GET /agents/effective-config"],
        ["Key files", "app/agents/base.py, prompts.py, task_tools.py, initiative_tools.py; app/routers/agents.py"],
        ["Persistence", "MySQL schema orgstructure; JSON columns task_value / initiative_value + status columns"],
        ["RBAC model", "admin = unscoped; member = owner + org scoped (JOIN employee_details)"],
        ["Clamping", "Progress clamped to 0-100 in both tools; confirmation reports effective value"],
        ["Incident fixed", "Initiative intent now detected for ALL agents; task prompt warns initiative != task"],
        ["Deployment", "docker cp backend files into stratroom_api + docker restart; or deploy.py full build"],
    ]
    story.append(data_table(
        ["Key facts", "Detail"],
        key_facts, [55 * mm, 123 * mm]))
    story.append(Spacer(1, 6))

    # ---- 2. Scope & terminology ----
    story.append(H1("2. Scope &amp; terminology"))
    story.append(H3("2.1 In scope"))
    for item in [
        "<b>update_task_progress()</b> — writes the progress key into task_details.task_value and auto-derives task status.",
        "<b>update_initiative_progress()</b> — writes progressval/progress/statusLight/statusIndicator into initiatives_details.initiative_value.",
        "<b>query_user_tasks()</b> / <b>query_initiatives()</b> — RBAC-scoped reads used by chat and the API endpoints.",
        "<b>_auto_fetch_tool()</b> — the pre-LLM intent rewriter that routes initiative/task phrasing correctly.",
        "<b>_execute_tool()</b> — the dispatch table that turns [TOOL_CALL:name:args] into a Python call.",
        "The <b>/agents/chat</b> request path, <b>/agents/task-action</b> and <b>/agents/initiative-action</b> direct endpoints.",
    ]:
        story.append(BUL(item))
    story.append(H3("2.2 Terminology"))
    rows = [
        ["Task", "A work unit in task_details; has progress, status, priority, owner, due_date."],
        ["Initiative / Project", "A strategic initiative in initiatives_details; has initiative_id (e.g. SI-01), progressval, statusLight, statusIndicator."],
        ["Agent", "An LLM persona with its own system prompt (task, strategy, projects, risk, ...). Chat selects it via the moduleId->agent map."],
        ["Tool call", "LLM-issued marker [TOOL_CALL:name:arg=val,...] that the runner executes and feeds back."],
        ["RBAC", "Role-based access control: admin vs member scoping applied in every tool."],
        ["Bridge", "JavaBridge wrapper for MySQL I/O (bridge._mysql / bridge._mysql_write), used by all tools."],
    ]
    story.append(data_table(["Term", "Meaning"], rows, [40 * mm, 138 * mm]))
    story.append(Spacer(1, 4))

    # ---- 3. Architecture ----
    story.append(H1("3. Architecture at a glance"))
    story.append(P(
        "The single-file SPA (<font face='Courier'>31may_index.html</font>) sends module chats to "
        "<font face='Courier'>POST /agents/chat</font>. Apache :8088 proxies to FastAPI :8001 inside "
        "container <font face='Courier'>stratroom_api</font>. The agent endpoint builds an "
        "<font face='Courier'>AgentRunner</font> for the requested agent domain, runs intent detection "
        "against the user message, calls the configured LLM, executes any emitted tool call through "
        "<font face='Courier'>_execute_tool()</font>, and returns a natural-language reply plus "
        "<font face='Courier'>tool_results</font>."))
    story.append(P(
        "All progress writes go to <b>MySQL schema orgstructure</b>. The JSON columns "
        "<font face='Courier'>task_details.task_value</font> and "
        "<font face='Courier'>initiatives_details.initiative_value</font> hold the rich record; "
        "<font face='Courier'>status</font> / <font face='Courier'>priority</font> columns mirror "
        "the most important facets for faster indexing and the legacy UI."))
    story.extend(chart(chart1(),
        "Chart 1 - The full chat path. sendModuleChat() maps a UI module to an agent domain, posts to "
        "/agents/chat, and the runner rewrites the query, calls the LLM, and executes tool calls against MySQL."))

    # ---- 4. The module ----
    story.append(H1("4. The Progress Update Module"))
    story.append(H2("4.1 Data model"))
    rows = [
        ["task_details", "ID, task_value (JSON), status, priority, owner, source_module, page_name, updated_time, created_time"],
        ["initiatives_details", "id, initiative_id (SI-01), initiative_value (JSON), owner, updated_time, updated_by"],
    ]
    story.append(data_table(["Table", "Key columns"], rows, [48 * mm, 130 * mm]))
    story.append(P(
        "<font face='Courier'>task_value</font> carries keys such as Name/title, progress, status, "
        "dueDate, assignedUserId, sourceModule, agent. <font face='Courier'>initiative_value</font> "
        "carries name, description, progressval, progress, statusLight (CSS classes), statusIndicator "
        "(GREEN/AMBER/RED), ownerName. Both are edited <b>read-modify-write</b> so unrelated keys survive."))
    story.append(H2("4.2 Progress semantics & auto-status"))
    rows = [
        ["progress = 0", "status = pending", "Task remains Pending"],
        ["0 < progress < 100", "status = in_progress", "Task marked as In Progress"],
        ["progress >= 100", "status = completed", "Task auto-marked as Completed"],
        ["initiative: 0-39", "statusIndicator = RED", "statusLight = progress-bar-danger"],
        ["initiative: 40-74", "statusIndicator = AMBER", "statusLight = progress-bar-warning"],
        ["initiative: 75-100", "statusIndicator = GREEN", "statusLight = progress-bar-success"],
    ]
    story.append(data_table(
        ["Range", "Derived value", "Confirmation wording"],
        rows, [40 * mm, 60 * mm, 78 * mm]))
    story.append(P(
        "Both tools clamp the requested value to <b>0-100</b>. If the raw value was out of range "
        "(e.g. <font face='Courier'>305</font>), the confirmation string explicitly states "
        "<i>\"requested value X was out of range and has been clamped to Y% (progress must be 0-100)\"</i> "
        "so the LLM and the user see the effective DB value."))
    story.append(H2("4.3 RBAC scoping"))
    story.append(BUL("<b>Admin:</b> updates are unscoped — single-table UPDATE by ID (business data spans orgs while admins sit in org 1)."))
    story.append(BUL("<b>Member:</b> identity resolved from email -> employee_details; writes are scoped with "
                     "<font face='Courier'>AND owner = emp_id</font> (tasks also JOIN employee_details on org_id)."))
    story.append(BUL("Ownership mismatch -> <font face='Courier'>\"This task/initiative is not yours.\"</font>; missing row -> "
                     "<font face='Courier'>\"...not found.\"</font>"))
    story.extend(chart(chart3(),
        "Chart 3 - The write path for both progress tools: clamp -> identity/RBAC -> ownership check -> "
        "read-modify-write JSON -> status derivation -> confirmation."))

    # ---- 5. Chat integration ----
    story.append(PageBreak())
    story.append(H1("5. Chat Agent Integration (end-to-end)"))
    story.append(H2("5.1 Front-end request"))
    story.append(CODE(
        "agentMap = { risk:'risk', scorecard:'strategy', budget:'finance', tasks:'task',\n"
        "             meetings:'meetings', projects:'projects', incidents:'incident',\n"
        "             compliance:'compliance', audit:'audit', swot:'strategy', pestel:'strategy',\n"
        "             forecast:'strategy', docintel:'strategy', org:'strategy', bcp:'compliance' }\n\n"
        "fetch('/agents/chat', {\n"
        "  method: 'POST',\n"
        "  headers: {'Content-Type':'application/json','Authorization':'Bearer '+getToken()},\n"
        "  body: JSON.stringify({\n"
        "    agent: agentMap[moduleId],            // e.g. 'task'\n"
        "    message: userMsg,\n"
        "    provider: cfg.provider,               // e.g. 'ollama'\n"
        "    api_key: cfg.apiKey || '',\n"
        "    model: cfg.model || 'llama3.2',\n"
        "    conversation_id: _agentConversations[agentDomain] || null,\n"
        "    base_url: cfg.baseUrl\n"
        "  })\n"
        "});"))
    story.append(P(
        "The browser aborts the request after <b>45 s</b> (AbortController) and shows a timeout "
        "message if no reply arrives. Provider/model are read from the UI LLM config "
        "(<font face='Courier'>_getLLMConfig()</font>); the response renders AI bubbles plus "
        "interactive task/initiative cards from <font face='Courier'>tool_results</font>."))

    story.append(H2("5.2 Server-side processing (AgentRunner.run)"))
    steps = [
        ["1", "sanitize_input()", "Enforce inbound length / character restrictions on the user message."],
        ["2", "fetch_agent_context()", "Load CURRENT ORGANIZATION DATA for the agent's modules."],
        ["3", "enhance_context() / history", "Attach AI memories and the conversation history."],
        ["4", "_auto_fetch_tool()", "Rewrite confusing queries (see section 6) BEFORE calling the LLM."],
        ["5", "call_llm_with_retry()", "Call the configured provider with system prompt + context + message."],
        ["6", "Tool-calling loop (max 3)", "Parse [TOOL_CALL:...], execute via _execute_tool(), feed result back, ask LLM to summarize."],
        ["7", "Persistence + metrics", "Log agent run, store conversation + messages, token benchmark."],
    ]
    story.append(data_table(
        ["#", "Stage", "Responsibility"],
        steps, [10 * mm, 42 * mm, 126 * mm]))

    story.append(H2("5.3 Tool-call pattern"))
    story.append(CODE(
        "# Regex used by the runner (base.py:31)\n"
        "_TOOL_CALL_RE = re.compile(r\"\\[TOOL_CALL:([^\\]:]+)(?::([^\\]]*))?\\]\")\n\n"
        "# Example emitted by the LLM and executed by _execute_tool():\n"
        "[TOOL_CALL:update_initiative_progress:id=8,progress=80]\n"
        "[TOOL_CALL:update_task_progress:id=102,progress=60]\n"
        "[TOOL_CALL:query_initiatives]\n\n"
        "# kv parser accepts id= or task_id=/initiative_id= aliases and int-casts values."))
    story.append(P(
        "The runner feeds the tool result back to the LLM with the instruction to summarize it "
        "naturally and, for updates, to confirm the change was saved. Tool results also travel in the "
        "JSON response so the SPA can render rich cards."))

    # ---- 6. Intent detection ----
    story.append(H1("6. Intent detection &amp; routing (_auto_fetch_tool)"))
    story.append(P(
        "<font face='Courier'>_auto_fetch_tool()</font> (base.py) runs before the LLM and rewrites "
        "ambiguous queries into precise, self-contained instructions. It is the primary defence that "
        "prevents initiative/project phrasing from being mis-routed to task tools."))
    story.append(H2("6.1 Routing table"))
    rows = [
        ["update initiative 8 progress to 80%", "INITIATIVE", "Call update_initiative_progress with id=8, progress=80."],
        ["set project 12 to 60%", "INITIATIVE", "Call update_initiative_progress with id=12, progress=60."],
        ["update the progress of initiative SI-02 to 75%", "INITIATIVE", "SI- prefix is accepted (lowercased). id=2, progress=75."],
        ["update initiative progress to 80% for Market Analysis", "NAME-ONLY (ASK ID)", "Politely ask for the numeric initiative ID; never touch a task."],
        ["update progress of task 102 to 80%", "TASK", "Call update_task_progress with id=102, progress=80."],
        ["set task 5 progress to 60%", "TASK", "Call update_task_progress with id=5, progress=60."],
        ["mark task 102 as completed", "TASK STATUS", "Call update_task_status with id=102, status=completed."],
        ["show me all initiatives", "QUERY", "Call query_initiatives (projects/strategy agents)."],
        ["list all tasks", "QUERY", "Call query_tasks."],
    ]
    story.append(data_table(
        ["Example phrase", "Intent", "Rewrite target"],
        rows, [62 * mm, 34 * mm, 82 * mm]))
    story.append(P(
        "The initiative/project block is evaluated <b>before</b> the task block and is <b>not gated by "
        "agent name</b> — so the same phrase routes to initiative tools from the tasks chat, the projects "
        "chat, or any other module chat. Task detection then only ever fires for phrases that explicitly "
        "name a <b>task</b>."))
    story.append(H2("6.2 Prompt-level guardrail (task agent)"))
    story.append(P(
        "The <font face='Courier'>task</font> system prompt (prompts.py) now states: "
        "<i>\"The words 'initiative' and 'project' refer to the Initiatives module, NOT to tasks ... "
        "NEVER call a task tool. Instead call update_initiative_progress ... If the user only names an "
        "initiative without a numeric ID, politely ask for the numeric initiative ID rather than guessing "
        "a task.\"</i> The prompt also documents <font face='Courier'>update_initiative_progress</font> and "
        "<font face='Courier'>query_initiatives</font> as valid tools for the task agent."))
    story.extend(chart(chart2(),
        "Chart 2 - Intent routing: initiative/project detection runs for every agent, name-only references "
        "are intercepted, and only explicit task phrasing reaches the task tools."))

    # ---- 7. Tool execution ----
    story.append(H1("7. Tool execution (_execute_tool) &amp; RBAC"))
    story.append(P(
        "<font face='Courier'>_execute_tool(db, tool_name, args_raw, user_id, org_id, is_admin, ctx)</font> "
        "parses the kv arguments and dispatches to the matching Python tool. The full registry advertised "
        "in the error message is: query_tasks, update_task, update_task_status, update_task_progress, "
        "create_task, create_risk_mitigation_task, query_initiatives, update_initiative_progress, "
        "update_incident_status, query_decisions, create_decision, update_decision_status, query_risks, "
        "create_risk, update_risk, delete_risk, query_scorecards, query_scorecard_summary, "
        "create_scorecard, update_scorecard, delete_scorecard."))
    rows = [
        ["query_tasks", "query_user_tasks(db, user_id, org_id, status, priority, owner, is_admin, email)", "Read, RBAC-scoped, self_only=True for chat"],
        ["update_task_progress", "update_task_progress(db, user_id, org_id, task_id, progress, is_admin, email)", "Write, clamp 0-100, auto status"],
        ["update_task_status", "update_task_status(db, user_id, org_id, task_id, status, is_admin, email)", "Write, normalized status"],
        ["query_initiatives", "query_initiatives(db, user_id, org_id, is_admin, email, owner, status)", "Read, RBAC-scoped"],
        ["update_initiative_progress", "update_initiative_progress(db, user_id, org_id, initiative_id, progress, is_admin, email)", "Write, clamp 0-100, statusLight/statusIndicator"],
    ]
    story.append(data_table(
        ["Tool name", "Python call", "Kind"],
        rows, [42 * mm, 92 * mm, 44 * mm]))
    story.append(BUL("ID aliases: <font face='Courier'>id=</font>, <font face='Courier'>task_id=</font>, "
                     "<font face='Courier'>initiative_id=</font> all resolve via <font face='Courier'>_tid()</font>."))
    story.append(BUL("Progress values are int-cast; non-integers return an error with usage guidance."))
    story.append(BUL("All writes go through <font face='Courier'>bridge._mysql_write()</font> with "
                     "parameterized queries (no string-injected SQL)."))

    # ---- 8. Direct endpoints ----
    story.append(H1("8. Direct API endpoints (no LLM)"))
    story.append(P(
        "In addition to chat, two direct endpoints execute the same tools without an LLM round trip. "
        "These are used by the SPA for explicit buttons and by scripts."))
    rows = [
        ["POST /agents/task-action", '{"action":"query" | "update" | "update_progress", "task_id":N, "status":"...", "progress":N}',
         "query_user_tasks / update_task_status / update_task_progress"],
        ["POST /agents/initiative-action", '{"action":"query" | "update_progress", "initiative_id":N, "progress":N}',
         "query_initiatives / update_initiative_progress"],
        ["GET /agents/effective-config", "—", "Server default provider/model + key_configured flag for the provider badge"],
    ]
    story.append(data_table(
        ["Endpoint", "Request body", "Backing functions"],
        rows, [48 * mm, 68 * mm, 62 * mm]))
    story.append(P(
        "Both write endpoints require <font face='Courier'>require_role('member')</font> and use the "
        "caller's RBAC context (is_admin, org_id, email) just like the chat path. Errors map to 422 "
        "(missing fields) or 404 (not found / not yours)."))

    # ---- 9. Provider resolution ----
    story.append(H1("9. Provider resolution &amp; configuration"))
    story.append(P(
        "The chat endpoint resolves the LLM provider from the request, falling back to server defaults "
        "when the client supplies neither an api_key nor a base_url."))
    rows = [
        ["Client supplied api_key or base_url", "provider = req.provider or server default; api_key = req.api_key or server default"],
        ["Client supplied neither", "provider = server AI_PROVIDER or req.provider; api_key = server AI_API_KEY"],
        ["ollama", "No API key required; endpoint = base_url/api_key override or default (localhost:11434)"],
        ["mock", "Deterministic canned reply for tests; still exercises the full HTTP + routing path"],
        ["Provider badge", "GET /agents/effective-config returns server defaults so the UI shows e.g. 'TOGETHER' instead of hardcoded text"],
    ]
    story.append(data_table(
        ["Condition", "Resolution"],
        rows, [50 * mm, 128 * mm]))
    story.append(P(
        "Allowed providers (settings.ALLOWED_PROVIDERS): openai, anthropic, google, deepseek, moonshot, "
        "together, mistral, xai, ollama, mock."))

    # ---- 10. Verification ----
    story.append(PageBreak())
    story.append(H1("10. Verification &amp; test results"))
    story.append(H2("10.1 Automated tests"))
    rows = [
        ["tests/test_initiative_tools.py", "15/15 PASS", "progress parser (clamp low/high/bounds + new 3-tuple), status light/indicator, query RBAC, update ownership, not-found, missing-value, owner-scoped write"],
        ["tests/test_suite.py", "124/128 PASS", "Full offline suite. 4 failures are pre-existing and unrelated (PostgreSQL removal in Jul 2026): test_import_db, docker-compose PG, asyncpg requirement."],
    ]
    story.append(data_table(
        ["Suite", "Result", "Coverage"],
        rows, [48 * mm, 26 * mm, 104 * mm]))
    story.append(H2("10.2 Live production verification (August 2026)"))
    live = [
        ["Restore", "Task #8 'Deploy Fraud Detection...' => 100 / completed; Task #32 'market research' => 0 / pending", "Confirmed via POST /agents/task-action query"],
        ["Routing", "'update initiative 8 progress to 80%' from task agent -> routes to update_initiative_progress:id=8,progress=80 (NOT update_task_progress)", "Verified in container with AgentRunner._auto_fetch_tool"],
        ["Routing", "'set project 9 to 60%' -> update_initiative_progress:id=9", "Verified in container"],
        ["Routing", "'update progress of task 102 to 80%' -> update_task_progress:id=102", "Unchanged/regression-free"],
        ["Name-only", "'update initiative progress to 80% for Market Analysis' -> asks for numeric ID, never mutates a task", "Verified in container"],
        ["No mutation", "POST /agents/chat with provider=mock for all three failing queries left Task #8 and #32 untouched", "tasks untouched == True"],
        ["Deployed signals", "base.py (agent-agnostic block), prompts.py (guardrails + tools), task_tools.py / initiative_tools.py (clamp feedback)", "grep + python import OK inside stratroom_api"],
    ]
    story.append(data_table(
        ["Check", "Result", "Evidence"],
        live, [40 * mm, 92 * mm, 46 * mm]))

    # ---- 11. Deployment ----
    story.append(H1("11. Deployment"))
    story.append(P(
        "Two deploy styles are in use. For this change only three backend files changed "
        "(base.py, prompts.py, task_tools.py, initiative_tools.py), so the hot-swap path was used."))
    story.append(H2("11.1 Hot-swap (fast, for backend-only file changes)"))
    story.append(CODE(
        "# 1. copy files into the build source on the host\n"
        "scp backend/app/agents/base.py root@103.191.132.36:/opt/stratroom-new/backend/app/agents/\n"
        "# ... repeat for prompts.py, task_tools.py, initiative_tools.py\n\n"
        "# 2. copy into the running container + restart (PYTHONPATH=/app/backend)\n"
        "docker cp /opt/stratroom-new/backend/app/agents/base.py stratroom_api:/app/backend/app/agents/base.py\n"
        "docker restart stratroom_api\n\n"
        "# 3. verify\n"
        "curl -s -m 5 http://localhost:8001/health\n"
        "docker exec stratroom_api python -c \"from app.agents.base import AgentRunner; print('ok')\""))
    story.append(H2("11.2 Full build (deploy.py)"))
    story.append(P(
        "<font face='Courier'>deploy.py</font> copies 41 files, backs them up, rebuilds the API container "
        "with <font face='Courier'>docker compose up -d --no-deps --build api</font>, copies the SPA to "
        "the Apache doc root, waits, and health-checks. It exits non-zero on any failure. SSH password is "
        "read from <font face='Courier'>os.environ['SSH_PASS']</font>."))
    story.append(CODE(
        "$env:SSH_PASS='<password>'; python deploy.py"))

    # ---- 12. Troubleshooting ----
    story.append(H1("12. Troubleshooting &amp; gotchas"))
    for item in [
        "<b>\"update initiative X\" touched a task in chat.</b> Ensure the deployed base.py contains the agent-agnostic block; if the container hostname differs from stratroom_api, apply docker cp to the real name (docker ps).",
        "<b>Chat times out after 45 s.</b> Usually a slow or unreachable LLM. With intent detection the query is rewritten before the LLM, which cuts most reduceable latency; check /agents/status for provider health.",
        "<b>Provider badge shows the wrong provider.</b> GET /agents/effective-config surfaces server defaults {provider, model, key_configured}; the SPA prefers client-side LLM config.",
        "<b>Progress made up.</b> Both progress tools clamp to 0-100 and report the effective value, so 305 is stored as 100 with an explicit clamping note.",
        "<b>Member can update a task they don't own?</b> No — writes are scoped by owner/emp_id (+ org_id for tasks) and return a 'not yours' error.",
        "<b>SI-02 phrases not detected.</b> Now handled: the regex accepts a lowercased si- prefix before the numeric ID.",
        "<b>JSON keys lost on update?</b> They should not be — tools read the column, mutate only progress-related keys, and write the whole JSON back.",
        "<b>Rate limiter.</b> In-memory per-process; container must run --workers 1 (120 req/min global, 30/min AI).",
        "<b>JWT_SECRET ephemeral.</b> If unset it is auto-generated and regenerated on restart; keep a static 64-char hex in production.",
    ]:
        story.append(BUL(item))

    # ---- 13. Appendix ----
    story.append(PageBreak())
    story.append(H1("13. Appendix"))
    story.append(H2("13.1 Intent-detection regexes (base.py _auto_fetch_tool)"))
    story.append(CODE(
        "p1 = r\"(?:update|set|change)\\s+(?:the\\s+)?progress\\s+(?:of|for)?\\s+\"\n"
        "     r\"(?:initiative|project)\\s+[#:=s]*(si-)?(\\d+)\\s+to\\s+(\\d+)\"\n"
        "p2 = r\"(?:update|set|change)\\s+(?:initiative|project)\\s+[#:=s]*(si-)?(\\d+)\\s+\"\n"
        "     r\"progress\\s+to\\s+(\\d+)\"\n"
        "p3 = r\"(?:update|set|change)\\s+(?:initiative|project)\\s+[#:=s]*(si-)?(\\d+)\\s+\"\n"
        "     r\"to\\s+(\\d+)\"\n"
        "# name-only guard (no numeric ID):\n"
        "if re.search(r\"(?:update|set|change).*(?:initiative|project).*progress\",\n"
        "             msg_lower.replace(\"%\", \"\")) and \\\n"
        "   not re.search(r\"(?:initiative|project)\\s+[#:=s]*\\d+\", msg_lower):\n"
        "    return \"...ask for the numeric initiative ID...\""))
    story.append(H2("13.2 Reference: sample SQL (admin update paths)"))
    story.append(CODE(
        "-- task progress (admin; member adds JOIN employee_details + owner/org scoping)\n"
        "UPDATE task_details t SET t.task_value = %s, t.updated_time = NOW() WHERE t.ID = %s;\n"
        "UPDATE task_details t SET t.status = %s WHERE t.ID = %s;\n\n"
        "-- initiative progress\n"
        "UPDATE initiatives_details SET initiative_value = %s, updated_time = NOW(),\n"
        "                                updated_by = %s WHERE id = %s;"))
    story.append(H2("13.3 Confirmation-string examples"))
    rows = [
        ["Task #8 from 100% to 80%", "Successfully updated progress for Task #8 from 100% to 80% in the database. Task marked as In Progress."],
        ["Task progress 305 (clamped)", "Successfully updated progress for Task #32 from 0% to 100% in the database. Note: the requested value 305 was out of range and has been clamped to 100% (progress must be 0-100). Task auto-marked as Completed."],
        ["Initiative #8 to 80%", "Successfully updated progress for Initiative #8 (SI-01) from 0% to 80% in the database. Initiative status: GREEN."],
    ]
    story.append(data_table(
        ["Scenario", "Confirmation text"],
        rows, [52 * mm, 126 * mm]))
    story.append(H2("13.4 Key source references"))
    refs = [
        ["base.py", "_auto_fetch_tool (line ~243)", "Agent-agnostic initiative intent + name-only guard, task detection"],
        ["base.py", "_execute_tool (line ~374)", "Dispatch table incl. update_task_progress / update_initiative_progress"],
        ["prompts.py", "\"task\" prompt (line ~176)", "initiative != task rule + tools documentation"],
        ["task_tools.py", "update_task_progress (line ~424)", "clamp 0-100, status auto-derive, RBAC writes"],
        ["initiative_tools.py", "update_initiative_progress (line ~113)", "clamp 0-100, statusLight/statusIndicator, RBAC writes"],
        ["routers/agents.py", "agent_chat / task-action / initiative-action", "HTTP entry points, provider resolution, RBAC"],
        ["frontend/31may_index.html", "sendModuleChat (line ~20517)", "moduleId->agent map, /agents/chat payload, 45s abort"],
    ]
    story.append(data_table(
        ["File", "Symbol", "Notes"],
        refs, [40 * mm, 62 * mm, 76 * mm]))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_GRAY))
    story.append(CAP("End of report - generated automatically from the StratRoom repository (Progress_Update_Module_Report.pdf)."))

    doc.build(story)
    print("WROTE:", OUT)


if __name__ == "__main__":
    build()