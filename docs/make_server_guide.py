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

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Server_Access_Guide.pdf")

# ---------------- styles ----------------
ss = getSampleStyleSheet()

S_TITLE = ParagraphStyle("S_TITLE", parent=ss["Title"], fontName="Helvetica-Bold",
                         fontSize=24, textColor=C_WHITE, leading=28)
S_SUB   = ParagraphStyle("S_SUB", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=11, textColor=C_LBLUE, leading=15)
S_H1    = ParagraphStyle("S_H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                         fontSize=15, textColor=C_NAVY, spaceBefore=14, spaceAfter=6,
                         leading=19)
S_H2    = ParagraphStyle("S_H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=11.5, textColor=C_BLUE, spaceBefore=10, spaceAfter=4,
                         leading=15)
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


# ---------------- Flow Chart 1 : full request path ----------------
def chart1():
    d = Drawing(560, 470)
    _note(d, 0, 560, 460, "FLOW CHART 1  —  Full request path: client -> server -> data", 9.5, C_NAVY)

    _box(d, 200, 428, 160, 26, "Browser / curl / Postman", fill=C_LGRAY, border=C_GRAY, font_size=9)
    _arrow(d, 280, 428, 280, 406)

    _box(d, 120, 372, 320, 32,
         ["Apache reverse proxy  :8088", "ProxyPass / -> localhost:8001   (production)"],
         fill=C_LORANGE, border=C_ORANGE, font_size=8.5)
    _arrow(d, 280, 372, 280, 350)

    _box(d, 150, 314, 260, 34,
         ["FastAPI :8001  -  container stratroom_api", "serves SPA  •  116 routes  •  2 route layers"],
         fill=C_LBLUE, border=C_BLUE, font_size=8.5)
    _arrow(d, 190, 314, 115, 288)
    _arrow(d, 280, 314, 280, 288)
    _arrow(d, 370, 314, 445, 288)

    _box(d, 40, 262, 150, 26, "/api/v1/*  —  22 routes", font_size=8)
    _box(d, 205, 262, 150, 26, "/stratroom/*  —  19 compat", font_size=8)
    _box(d, 370, 262, 150, 26, "Bare /risks /tasks ... — 7", font_size=8)

    d.add(Line(115, 238, 445, 238, strokeColor=C_GRAY, strokeWidth=1.3))
    _arrow(d, 115, 262, 115, 238)
    _arrow(d, 280, 262, 280, 238)
    _arrow(d, 445, 262, 445, 238)
    _arrow(d, 280, 238, 280, 216)

    _box(d, 150, 180, 260, 34,
         ["JavaBridge  (pymysql + HTTP proxies)", "routes known paths -> MySQL SQL"],
         fill=C_LGREEN, border=C_GREEN, font_size=8.5)
    _arrow(d, 220, 180, 220, 154)
    _arrow(d, 340, 180, 340, 154)

    _box(d, 40, 120, 220, 32,
         ["MySQL - orgstructure (single store)", "host.docker.internal:3306 -> host 3306"],
         fill=C_LGREEN, border=C_GREEN, font_size=8)
    _box(d, 300, 120, 220, 32,
         ["Java services (host)", "host.docker.internal:9010-9060"],
         fill=C_LORANGE, border=C_ORANGE, font_size=8)
    d.add(Line(260, 136, 300, 136, strokeColor=C_GRAY, strokeWidth=1.0,
               strokeDashArray=[4, 3]))
    _note(d, 260, 40, 130, "HTTP fallback", 7, C_GRAY)

    _note(d, 0, 560, 78,
          "Production traffic enters only via Apache :8088. Local dev hits FastAPI directly on :8001.",
          7.6, C_GRAY)
    _note(d, 0, 560, 60,
          "AI/ML endpoints (/ai/chat, /agents/chat, /ml/*) call external LLM providers and XGBoost - not MySQL.",
          7.6, C_GRAY)
    return d


# ---------------- Flow Chart 2 : login & JWT ----------------
def chart2():
    d = Drawing(560, 500)
    _note(d, 0, 560, 490, "FLOW CHART 2  —  Login & JWT authentication flow", 9.5, C_NAVY)

    _box(d, 130, 446, 300, 38,
         ["1. Client submits login",
          "SPA form:  POST /auth/login {email, password}",
          "API:       POST /api/v1/auth/login {email}"],
         fill=C_LGRAY, border=C_GRAY, font_size=8)
    _arrow(d, 280, 446, 280, 422)

    _box(d, 130, 394, 300, 26, "2. Auth router verifies credentials  (auth.py)", font_size=8.5)
    _arrow(d, 280, 394, 280, 368)

    _box(d, 130, 326, 300, 40,
         ["3. User lookup",
          "MySQL  users  table  (hashed_password)",
          "fallback:  JavaBridge  /userList"],
         font_size=8)
    _arrow(d, 280, 326, 280, 300)

    _box(d, 130, 272, 300, 26,
         ["4. JWT issued - HS256, 60-min expiry", "access_token returned to client"],
         fill=C_LGREEN, border=C_GREEN, font_size=8)
    _arrow(d, 280, 272, 280, 246)

    _box(d, 130, 218, 300, 26,
         ["5. Client calls a protected API", "Authorization:  Bearer <access_token>"],
         font_size=8)
    _arrow(d, 280, 218, 280, 192)

    _box(d, 130, 146, 300, 44,
         ["6. RBAC enforcement - require_role()",
          "role:  app_role -> designation -> enterprise_role",
          "admin=100   manager=50   member=10"],
         fill=C_LORANGE, border=C_ORANGE, font_size=8)
    _arrow(d, 280, 146, 280, 120)

    _box(d, 130, 92, 300, 26, "7. org_id-scoped response from MySQL",
         fill=C_LGREEN, border=C_GREEN, font_size=8.5)

    _arrow(d, 430, 231, 470, 231, dashed=True)
    _box(d, 435, 196, 115, 58,
         ["if token expired:", "401 -> purge sr_backend_token", "-> show login screen"],
         fill=colors.HexColor("#fdecea"), border=C_RED, font_size=7, text_color=C_RED)
    return d


# ---------------- Flow Chart 3 : SSH tunnel -> MySQL ----------------
def chart3():
    d = Drawing(560, 300)
    _note(d, 0, 560, 280, "FLOW CHART 3  —  SSH tunnel -> MySQL (from your Windows machine)", 9.5, C_NAVY)

    _box(d, 20, 150, 130, 60,
         ["Your machine", "listens on 127.0.0.1:3307",
          "(mysql CLI, Workbench,", "mysqldump)"],
         fill=C_LGRAY, border=C_GRAY, font_size=7.6)
    _arrow(d, 150, 180, 188, 180)

    _box(d, 188, 150, 192, 60,
         ["SSH tunnel (plink)",
          "-L 0.0.0.0:3307:localhost:3306",
          "-P 55004  root@103.191.132.36",
          "encrypted pipe"],
         font_size=7.6)
    _arrow(d, 380, 180, 418, 180)

    _box(d, 418, 150, 122, 60,
         ["Production host", "103.191.132.36",
          "SSH daemon  :55004", "local MySQL  :3306"],
         fill=C_LORANGE, border=C_ORANGE, font_size=7.6)
    _arrow(d, 479, 150, 479, 118)

    _box(d, 405, 62, 148, 56,
         ["MySQL - orgstructure", "localhost:3306 on host", "schema: orgstructure"],
         fill=C_LGREEN, border=C_GREEN, font_size=7.6)

    _note(d, 0, 560, 20,
          "Any tool that connects to 127.0.0.1:3307 on your machine actually reaches the production MySQL host on port 3306.",
          7.6, C_GRAY)
    return d


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


# ---------------- reusable table helper ----------------
def data_table(headers, rows, widths, header_fill=C_NAVY):
    data = [[CELLB(h) for h in headers]]
    for r in rows:
        data.append([CELL(c) if not isinstance(c, str) or c.startswith("<") else CELL(c) for c in r])
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


# ---------------- document ----------------
def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title="StratRoom - How to Access the Server",
        author="StratRoom Engineering",
    )

    story = []

    # ---- cover / header block ----
    cover = Table([[Paragraph("StratRoom", S_TITLE)],
                   [Paragraph("How to Access the Server", S_TITLE)],
                   [Paragraph(
                       "A practical, illustrated guide to reaching the StratRoom production "
                       "and local server - web, API, SSH, database and Docker.",
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

    # ---- 1. Overview ----
    story.append(H1("1. Overview"))
    story.append(P(
        "<b>StratRoom</b> is a full-stack, AI-powered enterprise governance dashboard. The production "
        "server is hosted at <b>103.191.132.36</b>: an <b>Apache reverse proxy on port 8088</b> forwards all "
        "traffic to a <b>FastAPI</b> application on port <b>8001</b>, which runs inside the Docker container "
        "<b>stratroom_api</b>. Every read and write is persisted to a single <b>MySQL</b> store, schema "
        "<b>orgstructure</b>. PostgreSQL was fully removed in July 2026."))
    story.append(P(
        "There are five ways to reach the server. Use the quick reference below, then read the matching "
        "section for the detailed steps and flow chart."))

    rows = [
        ["Production web (browser)", "http://103.191.132.36:8088", "Human users; demo alias demo.stratroom.io:8088"],
        ["Local web (Docker dev)", "http://localhost:8001", "Local development; Swagger docs at /docs"],
        ["API (curl / scripts)", "http://103.191.132.36:8088/api/v1/...", "JWT bearer token required after login"],
        ["SSH to host", "plink -P 55004 -l root 103.191.132.36", "Ops/admin; password via env SSH_PASS"],
        ["MySQL database", "tunnel 127.0.0.1:3307 -> host 3306", "orgstructure schema; mysql/mysqldump tools"],
        ["Docker container", "docker exec -it stratroom_api bash", "Inside the app; PYTHONPATH=/app/backend"],
    ]
    story.append(data_table(
        ["Access method", "Entry point", "Use when"],
        rows, [40 * mm, 60 * mm, 78 * mm]))
    story.append(Spacer(1, 6))

    # ---- Chart 1 ----
    story.extend(chart(chart1(),
        "Chart 1 - The complete path from a client to the data. Production traffic always enters via "
        "Apache :8088; local development goes straight to FastAPI :8001."))

    # ---- 2. Web access ----
    story.append(H1("2. Web (browser) access"))
    story.append(H2("2.1 Production"))
    story.append(BUL("Open <b>http://103.191.132.36:8088</b> (or <b>http://demo.stratroom.io:8088</b>) in any browser."))
    story.append(BUL("Apache :8088 forwards the request with <b>ProxyPass / -> localhost:8001</b> to FastAPI."))
    story.append(BUL("FastAPI's <b>serve_frontend()</b> returns the single-file SPA "
                     "<font face='Courier'>31may_index.html</font> (1.5 MB, 20 dashboard modules)."))
    story.append(BUL("No credentials are needed to load the page - you sign in on the login screen "
                     "(see Chart 2)."))
    story.append(H2("2.2 Local development (Docker)"))
    story.append(CODE(
        "docker compose up -d --build          # builds + starts container stratroom_api\n"
        "curl http://localhost:8001/health     # liveness  -> {\"status\":\"ok\"}\n"
        "curl http://localhost:8001/ready      # readiness -> database + mysql status\n"
        "browser: http://localhost:8001        # SPA\n"
        "browser: http://localhost:8001/docs   # Swagger UI (only when ENABLE_DOCS=true)"))
    story.append(P(
        "The Docker Compose file maps host port <b>8001</b> to container port <b>8000</b>. "
        "<b>Important:</b> the Apache document root <font face='Courier'>/var/www/stratroom-ai/index.html</font> "
        "is <b>not</b> what is served in production - the live page comes from inside the container."))

    # ---- Chart 2 ----
    story.append(PageBreak())
    story.append(H1("3. Authentication & login"))
    story.append(P(
        "StratRoom has two live login paths, both verified in production. The SPA login form uses the "
        "password-verified path; API tools usually use the passwordless path."))
    rows = [
        ["Passwordless", "POST /api/v1/auth/login", '{"email":"admin@stratroom.com"}', "Checks MySQL users, falls back to JavaBridge /userList. Returns JWT access_token."],
        ["Password-verified", "POST /auth/login", '{"email":"admin@stratroom.com","password":"changeme"}', "bcrypt check against MySQL users.hashed_password. This is what the SPA form calls."],
    ]
    story.append(data_table(
        ["Path", "Endpoint", "Body", "Notes"],
        rows, [28 * mm, 42 * mm, 52 * mm, 56 * mm]))
    story.append(Spacer(1, 8))
    story.extend(chart(chart2(),
        "Chart 2 - Login produces a signed JWT (HS256, 60 minutes). Every later API call carries it in the "
        "Authorization header; require_role() resolves admin / manager / member. On expiry the SPA purges "
        "its stored tokens and returns to the login screen."))

    # ---- 3. API access ----
    story.append(H1("4. API access (curl)"))
    story.append(P(
        "The API is a FastAPI service exposing <b>116 routes</b>. The pattern is always the same: "
        "<b>login -> get token -> call endpoint with the Bearer token</b>. Below are working commands "
        "from the production host URL (use <font face='Courier'>localhost:8001</font> locally)."))

    story.append(H2("4.1 Health and readiness"))
    story.append(CODE(
        "curl.exe http://103.191.132.36:8088/health   # {\"status\":\"ok\",\"version\":\"1.0.0\",...}\n"
        "curl.exe http://103.191.132.36:8088/ready    # {\"status\":\"ready\",\"database\":\"ok\",\"mysql\":\"ok\",...}"))
    story.append(H2("4.2 Login and capture the JWT"))
    story.append(CODE(
        "# PowerShell (passwordless v1 path)\n"
        "$token = (curl.exe -s -m 10 -X POST http://103.191.132.36:8088/api/v1/auth/login `\n"
        "  -H \"Content-Type: application/json\" `\n"
        "  -d '{\"email\":\"admin@stratroom.com\"}' | ConvertFrom-Json).access_token\n\n"
        "# bash\n"
        "TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        "  -d '{\"email\":\"admin@stratroom.com\"}' \\\n"
        "  | python -c \"import sys,json; print(json.load(sys.stdin)['access_token'])\")"))
    story.append(H2("4.3 Call authenticated endpoints"))
    story.append(CODE(
        "# Bare route -> MySQL scorecard_kpis\n"
        "curl.exe -s -m 10 http://103.191.132.36:8088/scorecards -H \"Authorization: Bearer $token\"\n\n"
        "# Compat route -> MySQL via JavaBridge\n"
        "curl.exe -s -m 10 \"http://103.191.132.36:8088/stratroom/riskList?pageId=3196\" -H \"Authorization: Bearer $token\"\n\n"
        "# v1 endpoints -> login, dashboard, org, incidents, tasks, AI insights...\n"
        "curl.exe -s -m 10 http://103.191.132.36:8088/api/v1/dashboard/kpis -H \"Authorization: Bearer $token\""))
    story.append(P(
        "Route families: <b>/api/v1/*</b> (22 routes), <b>/stratroom/*</b> compat (19 routes, MySQL via "
        "JavaBridge), and 7 bare routes (<font face='Courier'>/risks</font>, <font face='Courier'>/tasks</font>, "
        "<font face='Courier'>/scorecards</font>, <font face='Courier'>/budgets</font>, <font face='Courier'>/org</font>, "
        "<font face='Courier'>/meetings</font>, <font face='Courier'>/dashboard/stats</font>). All require the "
        "member role; unauthenticated calls get <b>401</b>."))

    # ---- 4. SSH ----
    story.append(H1("5. SSH access to the host"))
    story.append(P(
        "For administration (deploys, tunnels, service checks) you SSH to the production host. All SSH scripts "
        "read the password from the environment variable <b>SSH_PASS</b> - it is never hard-coded."))
    story.append(CODE(
        "$env:SSH_PASS = \"<your-password>\"   # never hard-code it in a script\n\n"
        "# interactive session (putty/plink, port 55004, user root)\n"
        "plink -ssh -P 55004 -l root -pw \"$env:SSH_PASS\" 103.191.132.36\n\n"
        "# open the MySQL tunnel (bind 0.0.0.0 - required for Docker Desktop host.docker.internal)\n"
        "plink -ssh -P 55004 -l root -pw \"$env:SSH_PASS\" -L 0.0.0.0:3307:localhost:3306 -N 103.191.132.36\n\n"
        "# from the host you can reach the container directly\n"
        "ssh root@103.191.132.36 'docker ps'           # shows stratroom_api (8001 -> 8000)"))
    story.append(Spacer(1, 4))

    # ---- Chart 3 ----
    story.extend(chart(chart3(),
        "Chart 3 - The plink tunnel maps your local port 3307 to the host's MySQL on 3306, so local tools "
        "can talk to the production database over an encrypted SSH connection."))

    # ---- 5. MySQL ----
    story.append(H1("6. MySQL database access"))
    story.append(P(
        "All data lives in MySQL schema <b>orgstructure</b> on the host (port 3306). The container reaches "
        "it through <b>host.docker.internal:3306</b>; you reach it from your machine through the tunnel above."))
    story.append(CODE(
        "# with the tunnel running, connect as if MySQL were local\n"
        "mysql -h 127.0.0.1 -P 3307 -u root -p orgstructure\n\n"
        "# dump / restore through the same tunnel\n"
        "mysqldump -h 127.0.0.1 -P 3307 -u root -p orgstructure > backup_2026.sql\n"
        "mysql    -h 127.0.0.1 -P 3307 -u root -p orgstructure < backup_2026.sql"))
    story.append(P(
        "<b>Restoring the 'Document from Gowtham' dump:</b> the file <font face='Courier'>D:\\project001\\Document "
        "from Gowtham</font> (approx. 707 MB, no extension) is a MySQL dump - its header starts with "
        "<font face='Courier'>-- MySQL</font>. Import it with the command above, replacing "
        "<font face='Courier'>backup_2026.sql</font> with that file path. Treat it as a restore of the "
        "<font face='Courier'>orgstructure</font> schema."))
    rows = [
        ["users", "Auth + hashed_password (bcrypt); login identity"],
        ["employee_details", "Org tree via parent_emp_id (org_members is empty); 65 rows"],
        ["user_role_management", "Designation -> RBAC role mapping; 65 rows"],
        ["score_card", "108 scorecard definitions (names/weights/dates)"],
        ["scorecard_kpis", "408 KPI values (target/actual/status) - different data from score_card"],
        ["tasks / risks / incidents / meetings / initiatives / audit_findings", "Application module data"],
        ["agent_conversations / agent_messages / ai_agent_runs / ai_memory", "AI layer persistence"],
        ["risk_details / budget_detail / compliance_details ...", "JavaBridge legacy tables"],
    ]
    story.append(data_table(["Key tables", "What they hold"], rows, [60 * mm, 118 * mm]))

    # ---- 6. Docker ----
    story.append(H1("7. Docker access"))
    story.append(P(
        "The app runs as a single container named <b>stratroom_api</b> (FastAPI on port 8000 inside, mapped "
        "to 8001 on the host). Use these commands for daily operations."))
    story.append(CODE(
        "docker ps                                # confirm stratroom_api is Up (healthy)\n"
        "docker logs stratroom_api --tail 50 -f   # live logs; JSON access logs - grep for 4xx/5xx\n"
        "docker exec -it stratroom_api bash       # shell inside the container\n"
        "    python -c \"import app.main\"          # PYTHONPATH=/app/backend; imports use app.*\n"
        "docker compose up -d --build             # rebuild after backend code changes\n"
        "docker cp /opt/stratroom-new/frontend/31may_index.html stratroom_api:/app/frontend/31may_index.html\n"
        "    # frontend-only deploy - no restart needed; the live page updates immediately"))
    story.append(P(
        "Backend deploys use <b>deploy.py</b> (copies 41 files, restarts the container, exits on error). "
        "Frontend-only changes use the <b>docker cp</b> line above - the Apache doc root is cosmetic only."))

    # ---- 7. Credentials & health ----
    story.append(H1("8. Credentials & health checks"))
    story.append(H2("8.1 Default users (org_id = 1)"))
    rows = [
        ["admin@stratroom.com", "changeme", "admin", "Full CRUD on all org data"],
        ["admin@test.com", "changeme", "member", "Assigned data only"],
    ]
    story.append(data_table(["Email", "Password", "Role", "Notes"], rows,
                            [48 * mm, 26 * mm, 22 * mm, 82 * mm]))
    story.append(H2("8.2 Health endpoints"))
    rows = [
        ["GET /health", "Liveness probe", '{"status":"ok","version":"1.0.0","environment":"production"}'],
        ["GET /ready", "Readiness (DB + MySQL)", '{"status":"ready","database":"ok","mysql":"ok",...}'],
        ["GET /metrics", "AI counters, uptime, version", '{"uptime_seconds":N,"ai_metrics":{...},...}'],
    ]
    story.append(data_table(["Endpoint", "Purpose", "Expected response"], rows,
                            [30 * mm, 48 * mm, 100 * mm]))

    # ---- 8. Gotchas ----
    story.append(H1("9. Troubleshooting & gotchas"))
    for item in [
        "<b>Rate limiter is in-memory per-process.</b> The container must run with <font face='Courier'>--workers 1</font>; more workers breaks limiting (120 req/min global, 30/min AI).",
        "<b>JWT_SECRET must be a static 64-char hex.</b> If unset it is auto-generated and every token dies on restart - logins break until users sign in again.",
        "<b>CORS_ORIGINS</b> must list the real frontend domain, or browser calls from other origins are blocked.",
        "<b>Compat routes (/stratroom/*) require a JWT.</b> Unauthenticated requests get 401, not fallback data.",
        "<b>Database is MySQL only.</b> The PostgreSQL container was removed in July 2026; db.py yields None gracefully and is not used for real I/O.",
        "<b>Different data, not duplicates:</b> <font face='Courier'>score_card</font> (definitions) vs <font face='Courier'>scorecard_kpis</font> (values); <font face='Courier'>audit_findings</font> is the audit table, not <font face='Courier'>audit</font>.",
        "<b>Org tree</b> uses <font face='Courier'>employee_details.parent_emp_id</font> because the org_members table is empty.",
        "<b>Dashboard summary</b> returns 0 for any bridge data that fails rather than crashing.",
        "<b>Frontend is a single 1.5 MB file</b> (<font face='Courier'>31may_index.html</font>). No build step - edit it directly.",
    ]:
        story.append(BUL(item))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.8, color=C_GRAY))
    story.append(CAP("End of guide - generated automatically from the StratRoom repository documentation."))

    doc.build(story)
    print("WROTE:", OUT)


if __name__ == "__main__":
    build()
