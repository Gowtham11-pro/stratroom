"""
Test: why is Agent Council stuck on "Loading..."?
Diagnose the /agents/status endpoint response.
"""
import paramiko, json, os

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root', password=os.environ["SSH_PASS"])

def curl_api(method, path, token=None, body=None):
    h = '-H "Content-Type: application/json"'
    if token:
        h += f' -H "Authorization: Bearer {token}"'
    d = ""
    if body:
        d = f"-d '{json.dumps(body)}'"
    stdin, stdout, stderr = ssh.exec_command(
        f'curl -s -m 10 -X {method} http://localhost:8001{path} {h} {d} 2>&1'
    )
    out = stdout.read().decode().strip()
    try:
        return json.loads(out) if out else None
    except:
        return out

# Step 1: Login
print("=== Step 1: Login ===")
token_data = curl_api("POST", "/api/v1/auth/login", body={"email": "admin@stratroom.com"})
if isinstance(token_data, dict) and "access_token" in token_data:
    TOKEN = token_data["access_token"]
    print("  Login OK - token obtained")
else:
    print("  Login FAILED:", str(token_data)[:100])
    ssh.close()
    exit(1)

# Step 2: Call /agents/status
print("\n=== Step 2: GET /agents/status ===")
status = curl_api("GET", "/agents/status", token=TOKEN)
if status is None:
    print("  /agents/status returned None")
elif isinstance(status, dict):
    agents = status.get("agents", {})
    metrics = status.get("metrics", {})
    print(f"  Agents count: {len(agents)}")
    print(f"  Metrics: {json.dumps(metrics, default=str)}")
    for domain, data in agents.items():
        print(f"    {domain}: status={data.get('status')}, runs={data.get('total_runs')}, convs={data.get('conversation_count')}")
    if not agents:
        print("  WARNING: agents dict is empty!")
    if "agents" not in status:
        print("  WARNING: 'agents' key missing from response!")
        print(f"  Response keys: {list(status.keys())}")
else:
    print(f"  Unexpected response type: {type(status)}")
    print(f"  Response: {str(status)[:200]}")

# Step 3: Check if the /agents/status route is even registered
print("\n=== Step 3: Check health ===")
health = curl_api("GET", "/health")
print(f"  Health: {json.dumps(health, default=str) if isinstance(health, dict) else health}")

# Step 4: Check MySQL ai_agent_runs table
print("\n=== Step 4: Check MySQL ai_agent_runs ===")
stdin, stdout, stderr = ssh.exec_command(
    "docker exec stratroom_api python3 -c \"from app.services.java_bridge import bridge; import asyncio; async def t(): r=await bridge._mysql('SELECT COUNT(*) as cnt FROM ai_agent_runs'); print(r); r2=await bridge._mysql('SELECT DISTINCT agent_name FROM ai_agent_runs'); print('agents:', r2); asyncio.run(t())\" 2>&1"
)
print("  stdout:", stdout.read().decode()[:300])
print("  stderr:", stderr.read().decode()[:200])

# Step 5: Check agent_conversations table
print("\n=== Step 5: Check agent_conversations ===")
stdin, stdout, stderr = ssh.exec_command(
    "docker exec stratroom_api python3 -c \"from app.services.java_bridge import bridge; import asyncio; async def t(): r=await bridge._mysql('SELECT COUNT(*) as cnt FROM agent_conversations'); print(r); asyncio.run(t())\" 2>&1"
)
print("  stdout:", stdout.read().decode()[:200])
print("  stderr:", stderr.read().decode()[:200])

# Step 6: Check what happens when frontend loads the page
print("\n=== Step 6: Simulate frontend loadAgentStatus ===")
stdin, stdout, stderr = ssh.exec_command(
    "docker exec stratroom_api curl -s -m 10 -H 'Authorization: Bearer ${TOKEN}' http://localhost:8000/agents/status?_t=$(date +%s) 2>&1 | head -200"
)
# Actually use the token we have
stdin, stdout, stderr = ssh.exec_command(
    f'curl -s -m 10 -H "Authorization: Bearer {TOKEN}" http://localhost:8000/agents/status?_t=$(date +%s) 2>&1 | head -500'
)
print("  Response:", stdout.read().decode()[:500])

ssh.close()
