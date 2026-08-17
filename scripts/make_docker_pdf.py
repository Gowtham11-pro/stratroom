"""Generate a Docker inventory PDF from the live server's Docker daemon.

Usage:
    $env:SSH_PASS='...'; python scripts/make_docker_pdf.py

Output: Docker_Inventory.pdf in the repo root.
All data is fetched live from the server — no hardcoded values.
"""

import os
import re
import shlex
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

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Docker_Inventory.pdf")

DARK = colors.HexColor("#1f2a44")
ACCENT = colors.HexColor("#6a3fb5")
LIGHT = colors.HexColor("#f2effa")
MUTED = colors.HexColor("#5a6270")
GOOD = colors.HexColor("#1e7d32")
WARN = colors.HexColor("#b26a00")
BAD = colors.HexColor("#b00020")


def run_cmd(client, cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err


def fetch_docker():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASS)

    data = {}

    out, _ = run_cmd(client, "docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'")
    data["containers"] = [l.split("\t") for l in out.strip().splitlines() if l.strip()]

    out, _ = run_cmd(client, "docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'")
    running = set()
    for l in out.strip().splitlines():
        if l.strip():
            running.add(l.split("\t")[0])
    data["running"] = running

    out, _ = run_cmd(client, "docker images --format '{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.SharedSize}}'")
    data["images"] = [l.split("\t") for l in out.strip().splitlines() if l.strip()]

    out, _ = run_cmd(client, "docker volume ls --format '{{.Driver}}\t{{.Name}}'")
    vols = [l.split("\t") for l in out.strip().splitlines() if l.strip()]
    named = [v[1] for v in vols if v[0] == "local" and not re.match(r"^[0-9a-f]{64}$", v[1])]
    anon = [v[1] for v in vols if v[0] == "local" and re.match(r"^[0-9a-f]{64}$", v[1])]
    data["volumes_named"] = named
    data["volumes_anon"] = anon

    out, _ = run_cmd(client, "docker network ls --format '{{.ID}}\t{{.Name}}\t{{.Driver}}\t{{.Scope}}'")
    data["networks"] = [l.split("\t") for l in out.strip().splitlines() if l.strip()]

    out, _ = run_cmd(client, "cd /opt/stratroom-new && docker compose ps --format '{{.Name}}\t{{.Service}}\t{{.Status}}'")
    data["compose"] = [l.split("\t") for l in out.strip().splitlines() if l.strip()]

    out, _ = run_cmd(client, "ls -d /opt/stratroom-new/backup_* 2>/dev/null | wc -l")
    data["backup_count"] = out.strip()

    out, _ = run_cmd(client, "hostname; uname -a | cut -d' ' -f1,2,3; docker --version")
    data["server"] = out.strip()

    client.close()
    return data


def build_pdf(data):
    doc = SimpleDocTemplate(
        OUT,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="StratRoom - Docker Inventory",
        author="StratRoom",
    )

    title_style = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=25, textColor=DARK, spaceAfter=2)
    subtitle_style = ParagraphStyle("subtitle", fontName="Helvetica", fontSize=11, leading=15, textColor=MUTED, spaceAfter=8)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=ACCENT, spaceBefore=12, spaceAfter=6)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, spaceAfter=0)
    cell_bold = ParagraphStyle("cell_bold", parent=cell, fontName="Helvetica-Bold")
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED, spaceAfter=4)

    story = [
        Paragraph("StratRoom - Docker Inventory (Live Server)", title_style),
        Paragraph(f"Generated {date.today().isoformat()}  |  host: {data['server'].splitlines()[0] if data['server'] else HOST}", subtitle_style),
        HRFlowable(width="100%", thickness=1.2, color=ACCENT, spaceAfter=8),
    ]

    # ── Containers ──
    story.append(Paragraph("1. Containers (docker ps -a)", h1))
    header = ["Name", "Image", "Status", "Ports", "Running"]
    rows = [header]
    for c in data["containers"]:
        name = c[0] if len(c) > 0 else ""
        image = c[1] if len(c) > 1 else ""
        status = c[2] if len(c) > 2 else ""
        ports = c[3] if len(c) > 3 else ""
        is_running = name in data["running"]
        st_para = Paragraph("YES", ParagraphStyle("run", parent=cell, textColor=GOOD, fontName="Helvetica-Bold"))
        if not is_running:
            st_para = Paragraph("no", ParagraphStyle("runno", parent=cell, textColor=BAD))
        rows.append([
            Paragraph(name, cell_bold),
            Paragraph(image, cell),
            Paragraph(status, cell),
            Paragraph(ports or "-", cell),
            st_para,
        ])
    t = Table(rows, colWidths=[60 * mm, 55 * mm, 75 * mm, 75 * mm, 22 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
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

    # ── Images ──
    story.append(Paragraph("2. Images (docker images)", h1))
    iheader = ["Repository:Tag", "ID", "Size", "Shared Size"]
    irows = [iheader]
    for im in data["images"]:
        repo = im[0] if len(im) > 0 else ""
        iid = im[1] if len(im) > 1 else ""
        size = im[2] if len(im) > 2 else ""
        shared = im[3] if len(im) > 3 else ""
        irows.append([
            Paragraph(repo, cell_bold),
            Paragraph(iid, cell),
            Paragraph(size, cell),
            Paragraph(shared or "-", cell),
        ])
    t = Table(irows, colWidths=[120 * mm, 60 * mm, 55 * mm, 52 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
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

    # ── Compose ──
    story.append(Paragraph("3. Active Compose Project (/opt/stratroom-new)", h1))
    cheader = ["Name", "Service", "Status"]
    crows = [cheader]
    for c in data["compose"]:
        crows.append([Paragraph(c[0], cell_bold), Paragraph(c[1], cell), Paragraph(c[2], cell)])
    if len(crows) == 1:
        crows.append([Paragraph("-", cell), Paragraph("-", cell), Paragraph("no services via compose ps", cell)])
    t = Table(crows, colWidths=[120 * mm, 80 * mm, 87 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c3de")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # ── Volumes ──
    story.append(Paragraph("4. Volumes (docker volume ls)", h1))
    vrows = [[Paragraph("Named volumes", cell_bold)]] + [[Paragraph(v, cell)] for v in data["volumes_named"]]
    vrows.append([Paragraph(f"Anonymous volumes (64-char ids): {len(data['volumes_anon'])}", cell)])
    t = Table(vrows, colWidths=[287 * mm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c3de")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    # ── Networks ──
    story.append(Paragraph("5. Networks (docker network ls)", h1))
    nrows = [[Paragraph("ID", cell_bold), Paragraph("Name", cell_bold), Paragraph("Driver", cell_bold), Paragraph("Scope", cell_bold)]]
    for n in data["networks"]:
        nrows.append([
            Paragraph(n[0], cell),
            Paragraph(n[1], cell_bold),
            Paragraph(n[2], cell),
            Paragraph(n[3], cell),
        ])
    t = Table(nrows, colWidths=[70 * mm, 110 * mm, 60 * mm, 47 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
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

    # ── Notes ──
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#c9c3de")))
    story.append(Paragraph(
        f"Facts observed live from the server at {date.today().isoformat()} via the Docker CLI. "
        f"Backup directories in /opt/stratroom-new: {data['backup_count']}. "
        "Container/image purpose labels are NOT included here (only raw CLI output) to avoid inference.",
        small,
    ))

    doc.build(story)
    print(f"PDF written: {OUT}")


def main():
    data = fetch_docker()
    print(f"containers={len(data['containers'])} images={len(data['images'])} "
          f"volumes_named={len(data['volumes_named'])} volumes_anon={len(data['volumes_anon'])} "
          f"networks={len(data['networks'])} compose={len(data['compose'])} backups={data['backup_count']}")
    build_pdf(data)


if __name__ == "__main__":
    main()
