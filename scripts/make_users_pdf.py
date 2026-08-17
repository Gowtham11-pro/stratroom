"""Generate a styled PDF directory of every user in the live StratRoom DB.

Usage:
    $env:SSH_PASS='...'; python scripts/make_users_pdf.py

Output: Users_List.pdf in the repo root.
"""

import json
import os
import sys
from datetime import date

import paramiko
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
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

HOST = "103.191.132.36"
PORT = 55004
USER = "root"
PASS = os.environ["SSH_PASS"]

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Users_List.pdf")

DARK = colors.HexColor("#1f2a44")
ACCENT = colors.HexColor("#6a3fb5")
LIGHT = colors.HexColor("#f2effa")
MUTED = colors.HexColor("#5a6270")
GOOD = colors.HexColor("#1e7d32")
WARN = colors.HexColor("#b26a00")

FETCH_SCRIPT = r"""
import json, pymysql

c = pymysql.connect(
    host="host.docker.internal", port=3306, user="stratroom",
    password="Admin#123", database="orgstructure",
    cursorclass=pymysql.cursors.DictCursor,
)
data = {}

cur = c.cursor()
cur.execute(
    "SELECT emp_id, org_id, dept_id, first_name, last_name, title, department, "
    "email_address, status, parent_emp_id FROM employee_details"
)
data["employees"] = cur.fetchall()

cur = c.cursor()
cur.execute(
    "SELECT emp_id, org_id, user_name, status, email_address, dept_id "
    "FROM employee_credentials"
)
data["credentials"] = cur.fetchall()

cur = c.cursor()
cur.execute(
    "SELECT emp_id, org_id, dept_id, name, email_address, department, designation, "
    "role, login_status, active, userAccess, role_id FROM user_role_management"
)
data["roles"] = cur.fetchall()

print(json.dumps(data, default=str))
c.close()
"""


def fetch_users():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASS)

    stdin, stdout, stderr = client.exec_command("docker exec -i stratroom_api python3")
    stdin.write(FETCH_SCRIPT)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    client.close()

    if err.strip():
        print("STDERR from container:\n", err[:1000], file=sys.stderr)

    payload = out.strip()
    start = payload.find("{")
    if start == -1:
        raise RuntimeError("No JSON returned from container fetch")
    return json.loads(payload[start:])


def merged_directory(data):
    emps = {e["emp_id"]: e for e in data["employees"]}
    creds = {c["emp_id"]: c for c in data["credentials"]}
    roles = {r["emp_id"]: r for r in data["roles"]}

    emp_ids = set(emps) | set(creds) | set(roles)
    rows = []
    for eid in emp_ids:
        e = emps.get(eid, {})
        c = creds.get(eid, {})
        r = roles.get(eid, {})
        org_id = e.get("org_id") or c.get("org_id") or r.get("org_id") or 0
        rows.append({
            "emp_id": eid,
            "org_id": org_id,
            "name": (e.get("first_name") or "") + (" " + (e.get("last_name") or "") if e.get("last_name") else ""),
            "email": c.get("email_address") or e.get("email_address") or r.get("email_address") or "",
            "department": r.get("department") or e.get("department") or "",
            "title": e.get("title") or r.get("designation") or "",
            "designation": r.get("designation") or "",
            "role": r.get("role") or "",
            "login_status": c.get("status") or r.get("login_status") or e.get("status") or "",
            "active": r.get("active") if r.get("active") is not None else None,
        })
    rows.sort(key=lambda x: (x["org_id"], x["emp_id"]))
    return rows


def org_name(oid):
    return {
        3: "Org 3 - Domain (legacy test org)",
        4: "Org 4 - Demo (Board of Directors)",
        6: "Org 6 - Test Org Emp",
        7: "Org 7 - Test Org Dept",
        8: "Org 8 - LCA Lesotho",
    }.get(oid, f"Org {oid}")


def build_pdf(rows):
    doc = SimpleDocTemplate(
        OUT,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="StratRoom - User Directory",
        author="StratRoom",
    )

    title_style = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=25, textColor=DARK, spaceAfter=2)
    subtitle_style = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11, leading=15, textColor=MUTED, spaceAfter=8)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=ACCENT, spaceBefore=12, spaceAfter=6)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, spaceAfter=0)
    cell_bold = ParagraphStyle("cell_bold", parent=cell, fontName="Helvetica-Bold")
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED, spaceAfter=4)

    story = [
        Paragraph("StratRoom - Full User Directory", title_style),
        Paragraph(f"Generated {date.today().isoformat()}  |  {len(rows)} people across all organizations", subtitle_style),
        HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=8),
    ]

    orgs = {}
    for r in rows:
        orgs.setdefault(r["org_id"], []).append(r)

    # Summary table
    summary_header = ["Org", "Description", "People", "Active", "Inactive"]
    summary_rows = [summary_header]
    for oid in sorted(orgs):
        members = orgs[oid]
        active = sum(1 for m in members if (m["login_status"] or "").lower().startswith("act"))
        summary_rows.append([
            str(oid),
            org_name(oid),
            str(len(members)),
            str(active),
            str(len(members) - active),
        ])
    t = Table(summary_rows, colWidths=[22 * mm, 130 * mm, 28 * mm, 28 * mm, 28 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c3de")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    for oid in sorted(orgs):
        members = orgs[oid]
        story.append(Paragraph(f"Org {oid} - {org_name(oid)} ({len(members)} people)", h1))

        header = ["Emp ID", "Name", "Email", "Department", "Title / Designation", "Role", "Status"]
        body = []
        for m in members:
            status = m["login_status"] or ("Inactive" if m["active"] == 0 else "")
            status = status or ""
            st_para = Paragraph(status, cell)
            if status.lower().startswith("act"):
                st_para = Paragraph(status, ParagraphStyle("st_act", parent=cell, textColor=GOOD, fontName="Helvetica-Bold"))
            elif status.lower().startswith("inact"):
                st_para = Paragraph(status, ParagraphStyle("st_inact", parent=cell, textColor=WARN))
            body.append([
                Paragraph(str(m["emp_id"]), cell_bold),
                Paragraph((m["name"] or "").strip() or "-", cell),
                Paragraph((m["email"] or "").strip() or "-", cell),
                Paragraph((m["department"] or "").strip() or "-", cell),
                Paragraph(((m["designation"] or "").strip() or "-"), cell),
                Paragraph((m["role"] or "").strip() or "-", cell),
                st_para,
            ])

        t = Table([header] + body, colWidths=[22 * mm, 40 * mm, 70 * mm, 45 * mm, 55 * mm, 40 * mm, 30 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c3de")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#c9c3de")))
    story.append(Paragraph("Passwords are stored as a shared legacy hash and are intentionally not included. "
                           "Status reflects login/account status; blank means no credential record.", small))

    doc.build(story)
    print(f"PDF written: {OUT}")


def main():
    data = fetch_users()
    rows = merged_directory(data)
    build_pdf(rows)
    print(f"Total people merged: {len(rows)}")


if __name__ == "__main__":
    main()
