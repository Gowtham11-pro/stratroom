import paramiko, os, json, datetime

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root',
            password=os.environ['SSH_PASS'])

# Helper: run mysql command
def mysql(sql):
    stdin, stdout, stderr = ssh.exec_command(
        f"mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e \"{sql}\" 2>&1"
    )
    return stdout.read().decode()

# Helper: run psql command and return results as list of dicts
def psql(sql):
    stdin, stdout, stderr = ssh.exec_command(
        f"docker exec stratroom_db psql -U stratroom -d stratroom -t -A -F',' -c \"{sql}\" 2>&1"
    )
    return stdout.read().decode()

# Helper: run python inside container
def container_python(script):
    stdin, stdout, stderr = ssh.exec_command("docker exec -i stratroom_api python3")
    stdin.write(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    err = stderr.read().decode()
    return out, err

print("=" * 60)
print("PHASE 2: Create table + migrate data")
print("=" * 60)

# Step 1: Create the MySQL table
print("\n=== Step 1: Creating scorecard_kpis table ===")
result = mysql("""
    CREATE TABLE IF NOT EXISTS scorecard_kpis (
        id INT AUTO_INCREMENT PRIMARY KEY,
        org_id INT NOT NULL,
        perspective VARCHAR(200) NOT NULL,
        kpi_name VARCHAR(500) NOT NULL,
        target DECIMAL(15,2) NULL,
        actual DECIMAL(15,2) NULL,
        owner VARCHAR(255) NULL,
        status VARCHAR(20) DEFAULT 'on-track',
        assigned_user_id INT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_org (org_id),
        INDEX idx_user (assigned_user_id)
    ) ENGINE=InnoDB CHARSET=utf8mb4;
""")
print(result)

# Verify table exists
result = mysql("DESCRIBE scorecard_kpis;")
print("Table schema:")
print(result)

# Step 2: Export PG data to JSON
print("=== Step 2: Exporting PG scorecards data ===")
pg_data = psql("""
    SELECT json_agg(json_build_object(
        'id', id,
        'org_id', org_id,
        'perspective', perspective,
        'kpi_name', kpi_name,
        'target', target::text,
        'actual', actual::text,
        'owner', owner,
        'status', status,
        'assigned_user_id', assigned_user_id,
        'created_at', created_at::text
    ) ORDER BY id)
    FROM scorecards;
""")
print(f"PG export raw length: {len(pg_data)} chars")
# The psql output has the header line, let's extract JSON
lines = pg_data.strip().split('\n')
json_str = ''
for line in lines:
    line = line.strip()
    if line and not line.startswith('[') and not line.startswith('json_agg') and not line.startswith('-'):
        json_str += line
    elif line.startswith('['):
        json_str = line

if not json_str.startswith('['):
    # Try the combined approach
    json_str = ''.join(line for line in lines if line.strip() and not line.startswith('json_agg') and not line.startswith('-'))
    json_str = json_str.strip()

print(f"JSON string starts with: {json_str[:50]}...")

try:
    rows = json.loads(json_str)
    print(f"Parsed {len(rows)} rows from PG")
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}")
    print(f"Raw output first 200 chars: {json_str[:200]}")
    ssh.close()
    exit(1)

# Step 3: Import into MySQL via a container Python script
print("\n=== Step 3: Importing data into MySQL ===")
# Build a batch insert script
insert_values = []
for r in rows:
    target = r.get('target')
    actual = r.get('actual')
    owner = r.get('owner') or ''
    status = r.get('status') or 'on-track'
    auid = r.get('assigned_user_id')
    
    target_str = 'NULL' if target is None else target
    actual_str = 'NULL' if actual is None else actual
    auid_str = 'NULL' if auid is None else str(auid)
    owner_escaped = owner.replace("'", "\\'")
    perspective_escaped = r['perspective'].replace("'", "\\'")
    kpi_escaped = r['kpi_name'].replace("'", "\\'")
    
    insert_values.append(
        f"({r['id']}, {r['org_id']}, '{perspective_escaped}', '{kpi_escaped}', "
        f"{target_str}, {actual_str}, "
        f"'{owner_escaped}', '{status}', {auid_str}, NOW())"
    )

# Batch insert in chunks of 50
chunk_size = 50
total_inserted = 0
for i in range(0, len(insert_values), chunk_size):
    chunk = insert_values[i:i+chunk_size]
    values_sql = ",\n".join(chunk)
    sql = f"INSERT INTO scorecard_kpis (id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id, created_at) VALUES\n{values_sql};"
    
    # Write SQL to a temp file and execute
    stdin, stdout, stderr = ssh.exec_command(
        "mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure 2>&1"
    )
    stdin.write(sql)
    stdin.channel.shutdown_write()
    out = stdout.read().decode()
    err = stderr.read().decode()
    if err:
        print(f"Chunk {i//chunk_size + 1} error: {err[:200]}")
    
    total_inserted += len(chunk)
    if (i // chunk_size) % 5 == 0:
        print(f"  Inserted {total_inserted}/{len(rows)}...")

print(f"  Total inserted: {total_inserted}")

# Step 4: Verify row count
print("\n=== Step 4: Verifying row count ===")
count_result = mysql("SELECT COUNT(*) as cnt FROM scorecard_kpis;")
print(count_result)

# Extract the count
for line in count_result.split('\n'):
    line = line.strip()
    if line.isdigit():
        actual_count = int(line)
        break
else:
    # Try different format
    parts = count_result.strip().split()
    for p in parts:
        if p.isdigit():
            actual_count = int(p)
            break
    else:
        actual_count = 0

print(f"Expected: 409, Got: {actual_count}")
if actual_count == 409:
    print("[PASS] Row count matches")
else:
    print("[FAIL] Row count mismatch")

# Step 5: Spot-check specific rows
print("\n=== Step 5: Spot-check data integrity ===")

# 5a: Check the org_id=4 row
print("--- Spot-check: org_id=4 row ---")
result = mysql("SELECT id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id FROM scorecard_kpis WHERE org_id = 4;")
print(result)

# 5b: Check the NULL assigned_user_id row
print("--- Spot-check: NULL assigned_user_id row ---")
result = mysql("SELECT id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id FROM scorecard_kpis WHERE assigned_user_id IS NULL;")
print(result)

# 5c: Check a few sample rows with full content
print("--- Spot-check: First 3 rows ---")
result = mysql("SELECT id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id FROM scorecard_kpis ORDER BY id LIMIT 3;")
print(result)

# 5d: Check last 3 rows
print("--- Spot-check: Last 3 rows ---")
result = mysql("SELECT id, org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id FROM scorecard_kpis ORDER BY id DESC LIMIT 3;")
print(result)

# 5e: Verify perspective distribution matches PG
print("--- Spot-check: Perspective distribution ---")
result = mysql("SELECT perspective, COUNT(*) as cnt FROM scorecard_kpis GROUP BY perspective ORDER BY cnt DESC;")
print(result)

# 5f: Verify org_id distribution matches PG
print("--- Spot-check: org_id distribution ---")
result = mysql("SELECT org_id, COUNT(*) as cnt FROM scorecard_kpis GROUP BY org_id ORDER BY org_id;")
print(result)

# 5g: Check a row with actual values (non-null target/actual)
print("--- Spot-check: Row with non-null target/actual ---")
result = mysql("SELECT id, perspective, kpi_name, target, actual, owner, status FROM scorecard_kpis WHERE target IS NOT NULL AND actual IS NOT NULL LIMIT 5;")
print(result)

print("\n" + "=" * 60)
print("PHASE 2 COMPLETE")
print("=" * 60)
ssh.close()
