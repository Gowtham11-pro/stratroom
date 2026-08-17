import paramiko, os, time, sys

HOST = "103.191.132.36"
PORT = 55004
USER = "root"
PASS = os.environ["SSH_PASS"]
BASE = "/opt/stratroom-new"
LOCAL_BASE = r"D:\project001\stratroom"

files = [
    "backend/Dockerfile",
    "backend/requirements.txt",
    "backend/app/main.py",
    "backend/app/agents/base.py",
    "backend/app/agents/prompts.py",
    "backend/app/agents/risk_tools.py",
    "backend/app/agents/scorecard_tools.py",
    "backend/app/agents/task_tools.py",
    "backend/app/agents/incident_tools.py",
    "backend/app/agents/decision_tools.py",
    "backend/app/agents/initiative_tools.py",
    "backend/app/agents/tools.py",
    "backend/app/core/config.py",
    "backend/app/core/db.py",
    "backend/app/core/deps.py",
    "backend/app/core/security.py",
    "backend/app/core/rbac.py",
    "backend/app/core/utils.py",
    "backend/app/core/migrations.py",
    "backend/app/routers/agents.py",
    "backend/app/routers/ai.py",
    "backend/app/routers/api_v1.py",
    "backend/app/routers/audit.py",
    "backend/app/routers/auth.py",
    "backend/app/routers/bcp.py",
    "backend/app/routers/budgets.py",
    "backend/app/routers/compat.py",
    "backend/app/routers/complaints.py",
    "backend/app/routers/compliance.py",
    "backend/app/routers/dashboard.py",
    "backend/app/routers/documents.py",
    "backend/app/routers/incidents.py",
    "backend/app/routers/decisions.py",
    "backend/app/routers/initiatives.py",
    "backend/app/routers/meetings.py",
    "backend/app/routers/org.py",
    "backend/app/routers/pestel_projects.py",
    "backend/app/routers/risks.py",
    "backend/app/routers/scorecards.py",
    "backend/app/routers/swot.py",
    "backend/app/routers/tasks.py",
    "backend/app/services/java_bridge.py",
    "backend/app/services/monte_carlo.py",
    "backend/app/ai/tokens.py",
    "backend/app/ai/llm_providers.py",
    "backend/app/ai/metrics.py",
    "backend/app/ai/memory.py",
    "backend/app/ai/query_enhancer.py",
    "frontend/31may_index.html",
    "docker-compose.yml",
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS)
sftp = client.open_sftp()

print("=== Step 1: Backup current files ===")
backup_dir = f"{BASE}/backup_{int(time.time())}"
stdin, stdout, stderr = client.exec_command(f"mkdir -p {backup_dir}")
if stdout.channel.recv_exit_status() != 0:
    print("FATAL: Failed to create backup directory")
    sys.exit(1)

for f in files:
    dest = f"{BASE}/{f}"
    bak = f"{backup_dir}/{os.path.basename(f)}"
    stdin, stdout, stderr = client.exec_command(f"cp {dest} {bak} 2>/dev/null; echo 'done'")
    ec = stdout.channel.recv_exit_status()
    if ec != 0:
        print(f"  WARN: Could not backup {os.path.basename(f)} (might be new file)")
    else:
        print(f"  Backed up {os.path.basename(f)}")

print("\n=== Step 2: Upload new files ===")
for f in files:
    local = os.path.join(LOCAL_BASE, f)
    if not os.path.exists(local):
        print(f"  SKIP: {f} not found locally")
        continue
    remote = f"{BASE}/{f}"
    rdir = os.path.dirname(remote)
    stdin, stdout, stderr = client.exec_command(f"mkdir -p {rdir}")
    stdout.channel.recv_exit_status()
    sftp.put(local, remote)
    print(f"  Uploaded {os.path.basename(f)} ({os.path.getsize(local)} bytes)")

sftp.close()

print("\n=== Step 3: Rebuild API container ===")
stdin, stdout, stderr = client.exec_command(
    f"cd {BASE} && docker compose up -d --no-deps --build api",
    timeout=300
)
for line in iter(stdout.readline, ""):
    print(f"  {line.strip()}")
ec = stdout.channel.recv_exit_status()
if ec != 0:
    err = stderr.read().decode().strip()[:200]
    print(f"  FAIL: docker compose build failed (exit={ec}): {err}")
    sys.exit(1)

print("\n=== Step 4: Copy frontend to Apache doc root and container ===")
apache_cmd = (
    f"cp {BASE}/frontend/31may_index.html /var/www/stratroom-ai/index.html && "
    f"docker cp {BASE}/frontend/31may_index.html $(docker ps -q -f name=api | head -n 1):/app/frontend/31may_index.html 2>/dev/null || true"
)
stdin, stdout, stderr = client.exec_command(apache_cmd)
ec = stdout.channel.recv_exit_status()
if ec != 0:
    err = stderr.read().decode().strip()[:120]
    print(f"  FAIL: {err}")
    sys.exit(1)
print("  OK: Copied 31may_index.html to Apache doc root and API container")

print("\n=== Step 5: Wait for container health ===")
time.sleep(10)
stdin, stdout, stderr = client.exec_command(
    f"curl -s -m 5 http://localhost:8001/health 2>/dev/null || echo 'FAILED'"
)
result = stdout.read().decode().strip()
if result == "FAILED" or "error" in result.lower():
    print(f"  FAIL: Health check failed: {result[:200]}")
    sys.exit(1)
print(f"  Health check: {result[:200]}")

client.close()
print("\n=== Deployment complete ===")
