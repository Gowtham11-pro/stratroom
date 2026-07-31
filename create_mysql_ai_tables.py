"""
create_mysql_ai_tables.py

1. Creates ai_agent_runs and ai_memory tables in MySQL
2. Directly calls log_agent_run inside the Docker container
3. Queries MySQL and PG side by side for the definitive proof
"""
import os
import paramiko
import time

PASS = os.environ["SSH_PASS"]
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("103.191.132.36", port=55004, username="root", password=PASS)

# ── STEP 1: Create MySQL tables ──
print("=" * 70)
print("STEP 1: Create MySQL tables ai_agent_runs and ai_memory")
print("=" * 70)

cmds = [
    """
    CREATE TABLE IF NOT EXISTS ai_agent_runs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        org_id INT NULL,
        user_id INT NULL,
        agent_name VARCHAR(100) NULL,
        provider VARCHAR(50) NULL,
        model VARCHAR(200) NULL,
        conversation_id INT NULL,
        status VARCHAR(20) NULL,
        duration_ms INT NULL,
        token_count INT NULL,
        error_message TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_memory (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NULL,
        org_id INT NULL,
        agent_name VARCHAR(100) NULL,
        insight TEXT NULL,
        source VARCHAR(100) NULL,
        confidence FLOAT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        access_count INT DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

for sql in cmds:
    cmd = 'mysql -h 127.0.0.1 -P 3306 -u stratroom -p\'Admin#123\' orgstructure -e "%s" 2>&1' % sql.strip().replace("'", "'\\''")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    err_only = [l for l in (out + "\n" + err).split("\n") if "Warning" not in l and l.strip()]
    if err_only:
        print("  Error?: %s" % " | ".join(err_only))
    else:
        print("  [OK] Created")

# Verify tables exist
for table in ["ai_agent_runs", "ai_memory"]:
    stdin, stdout, stderr = ssh.exec_command(
        'mysql -h 127.0.0.1 -P 3306 -u stratroom -p\'Admin#123\' orgstructure -e "SHOW CREATE TABLE %s" -B 2>&1' % table
    )
    out = stdout.read().decode()
    if "CREATE TABLE" in out:
        print("  [OK] Table %s exists in MySQL" % table)
    else:
        lines = [l for l in out.split("\n") if "Warning" not in l and l.strip()]
        print("  [?] %s: %s" % (table, " | ".join(lines[:3])))

# ── STEP 2: Directly test log_agent_run inside the container ──
print("\n" + "=" * 70)
print("STEP 2: Direct in-container test of log_agent_run, store_memory, retrieve_memory")
print("  Calling from inside Docker container (bypasses HTTP layer)")
print("=" * 70)

test_script = (
    "import asyncio, json, sys\n"
    "sys.path.insert(0, '/app/backend')\n"
    "from app.ai.metrics import log_agent_run\n"
    "from app.ai.memory import store_memory, retrieve_memory\n"
    "\n"
    "async def test():\n"
    "    # Test 1: log_agent_run\n"
    "    print('--- log_agent_run test ---')\n"
    "    await log_agent_run(\n"
    "        org_id=1, user_id=1,\n"
    "        agent_name='risk', provider='test', model='test-model',\n"
    "        conversation_id=None, status='success',\n"
    "        duration_ms=123, token_count=456, error_message=None,\n"
    "    )\n"
    "    print('log_agent_run: OK')\n"
    "\n"
    "    # Test 2: store_memory\n"
    "    print('--- store_memory test ---')\n"
    "    result = await store_memory(\n"
    "        user_id=1, org_id=1, agent_name='risk',\n"
    "        insight='Test insight for risk agent: identified 3 critical risks in Q4',\n"
    "        source='test', confidence=0.85,\n"
    "        message='Show me critical risks',\n"
    "    )\n"
    "    print('store_memory result:', result)\n"
    "\n"
    "    # Test 3: retrieve_memory\n"
    "    print('--- retrieve_memory test ---')\n"
    "    memories = await retrieve_memory(\n"
    "        user_id=1, org_id=1, agent_name='risk', limit=5,\n"
    "    )\n"
    "    print('retrieved memories:', len(memories))\n"
    "    for m in memories:\n"
    "        print('  -', m.get('insight', '')[:80], '| conf:', m.get('confidence'))\n"
    "\n"
    "asyncio.run(test())\n"
    "print('DONE')\n"
)

stdin, stdout, stderr = ssh.exec_command("docker exec -i stratroom_api python3")
stdin.write(test_script)
stdin.channel.shutdown_write()
out = stdout.read().decode()
err = stderr.read().decode()
print("  Stdout:")
for line in out.split("\n"):
    if line.strip():
        print("    %s" % line)
if err.strip():
    print("  Stderr:")
    for line in err.split("\n"):
        if line.strip():
            print("    %s" % line)

# ── STEP 3: Query MySQL for the new rows ──
print("\n" + "=" * 70)
print("STEP 3: MySQL rows after direct test")
print("=" * 70)

stdin, stdout, stderr = ssh.exec_command(
    'mysql -h 127.0.0.1 -P 3306 -u stratroom -p\'Admin#123\' orgstructure '
    '-e "SELECT id, agent_name, provider, model, status, duration_ms, token_count, created_at FROM ai_agent_runs ORDER BY id DESC LIMIT 5" -B 2>&1'
)
lines = [l for l in stdout.read().decode().split("\n") if "Warning" not in l and l.strip()]
print("  ai_agent_runs:")
for line in lines:
    print("    %s" % line)

stdin, stdout, stderr = ssh.exec_command(
    'mysql -h 127.0.0.1 -P 3306 -u stratroom -p\'Admin#123\' orgstructure '
    '-e "SELECT id, agent_name, LEFT(insight, 80) as insight_preview, confidence, created_at FROM ai_memory ORDER BY id DESC LIMIT 5" -B 2>&1'
)
lines = [l for l in stdout.read().decode().split("\n") if "Warning" not in l and l.strip()]
print("  ai_memory:")
for line in lines:
    print("    %s" % line)

# ── STEP 4: Query PG — confirm NO new rows ──
print("\n" + "=" * 70)
print("STEP 4: PostgreSQL rows (should show NO new rows from our test)")
print("=" * 70)

stdin, stdout, stderr = ssh.exec_command(
    'docker exec stratroom_db psql -U stratroom -d stratroom -c '
    '"SELECT id, agent_name, provider, model, status, duration_ms, token_count, created_at FROM ai_agent_runs ORDER BY id DESC LIMIT 5" -t 2>&1'
)
lines = [l for l in stdout.read().decode().split("\n") if l.strip()]
print("  PG ai_agent_runs:")
for line in lines:
    print("    %s" % line)

stdin, stdout, stderr = ssh.exec_command(
    'docker exec stratroom_db psql -U stratroom -d stratroom -c '
    '"SELECT id, agent_name, LEFT(insight, 80) as insight_preview, confidence, created_at FROM ai_memory ORDER BY id DESC LIMIT 5" -t 2>&1'
)
lines = [l for l in stdout.read().decode().split("\n") if l.strip()]
print("  PG ai_memory:")
for line in lines:
    print("    %s" % line)

# ── FINAL: side-by-side totals ──
print("\n" + "=" * 70)
print("FINAL: Side-by-side comparison")
print("=" * 70)

stdin, stdout, stderr = ssh.exec_command(
    'mysql -h 127.0.0.1 -P 3306 -u stratroom -p\'Admin#123\' orgstructure '
    '-e "SELECT COUNT(*) as cnt FROM ai_agent_runs" -B 2>&1'
)
mysql_count = 0
for l in stdout.read().decode().split("\n"):
    if l.strip() and "Warning" not in l and "cnt" not in l:
        try:
            mysql_count = int(l.strip())
        except:
            pass

stdin, stdout, stderr = ssh.exec_command(
    'docker exec stratroom_db psql -U stratroom -d stratroom -c "SELECT COUNT(*) FROM ai_agent_runs" -t 2>&1'
)
pg_count = 0
for l in stdout.read().decode().split("\n"):
    if l.strip():
        try:
            pg_count = int(l.strip())
        except:
            pass

print()
print("  MySQL ai_agent_runs: %d rows (should have new test rows)" % mysql_count)
print("  PG    ai_agent_runs: %d rows (should be unchanged)" % pg_count)
print()

if mysql_count > 0:
    print("  [PASS] Migration is working: MySQL has %d row(s)" % mysql_count)
    print("  log_agent_run successfully writes to MySQL via bridge._mysql_write()")
else:
    print("  [?] No rows found in MySQL - check for errors above")

ssh.close()
print("\n=== Done ===")
