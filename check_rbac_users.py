"""Check RBAC users with different roles in MySQL and test login."""
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
    try: return json.loads(out) if out else None
    except: return out

# Step 1: Check MySQL users table - find all distinct roles and sample users
print("=== MySQL Users: Roles & Sample Accounts ===")
stdin, stdout, stderr = ssh.exec_command(
    "mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e "
    "\"SELECT id, email, role, full_name, org_id FROM users ORDER BY id LIMIT 10;\" 2>&1"
)
print(stdout.read().decode())

stdin, stdout, stderr = ssh.exec_command(
    "mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e "
    "\"SELECT DISTINCT role FROM users ORDER BY role;\" 2>&1"
)
print("\nDistinct roles:", stdout.read().decode().strip())

# Step 2: Find users with different roles
for role in ["admin", "manager", "member"]:
    stdin, stdout, stderr = ssh.exec_command(
        f"mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e "
        f"\"SELECT id, email, full_name, role FROM users WHERE role = '{role}' LIMIT 3;\" 2>&1"
    )
    print(f"\n--- {role.upper()} users ---")
    print(stdout.read().decode())

# Step 3: Test login for admin@stratroom.com
print("\n=== Testing Role-Based Logins ===")

# 3a. admin@stratroom.com (admin role)
print("\n--- Test: admin@stratroom.com (admin) ---")
r = curl_api("POST", "/auth/login", body={"email":"admin@stratroom.com","password":"changeme"})
print(f"  Login: {'OK' if r and 'access_token' in r else 'FAIL'} -> {str(r)[:80]}")
if r and 'access_token' in r:
    me = curl_api("GET", "/auth/me", token=r['access_token'])
    print(f"  /auth/me: role={me.get('role')}, name={me.get('full_name')}, id={me.get('id')}")

# 3b. Check if admin@test.com works (mentioned earlier as member)
print("\n--- Test: admin@test.com (member role) ---")
r = curl_api("POST", "/auth/login", body={"email":"admin@test.com","password":"changeme"})
print(f"  Login: {'OK' if r and 'access_token' in r else 'FAIL'} -> {str(r)[:80]}")
if r and 'access_token' in r:
    me = curl_api("GET", "/auth/me", token=r['access_token'])
    print(f"  /auth/me: role={me.get('role')}, name={me.get('full_name')}")

# 3c. Check for other users
stdin, stdout, stderr = ssh.exec_command(
    "mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e "
    "\"SELECT id, email, role FROM users WHERE role IN ('admin','manager','member') ORDER BY role, id LIMIT 20;\" 2>&1"
)
print("\n--- All users by role ---")
print(stdout.read().decode())

ssh.close()
