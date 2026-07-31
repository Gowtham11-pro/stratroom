import os
import paramiko
import base64
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore

files = [
    ("D:\\project001\\stratroom\\backend\\app\\services\\java_bridge.py", "/opt/stratroom-new/backend/app/services/java_bridge.py"),
    ("D:\\project001\\stratroom\\backend\\app\\core\\config.py", "/opt/stratroom-new/backend/app/core/config.py"),
    ("D:\\project001\\stratroom\\backend\\app\\core\\utils.py", "/opt/stratroom-new/backend/app/core/utils.py"),
    ("D:\\project001\\stratroom\\backend\\app\\main.py", "/opt/stratroom-new/backend/app/main.py"),
    ("D:\\project001\\stratroom\\backend\\requirements.txt", "/opt/stratroom-new/backend/requirements.txt"),
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('103.191.132.36', port=55004, username='root', password=os.environ["SSH_PASS"])

for local_path, remote_path in files:
    with open(local_path, 'rb') as f:
        content = f.read()
    encoded = base64.b64encode(content).decode()

    parent = remote_path.rsplit('/', 1)[0]
    stdin, stdout, stderr = client.exec_command(f'mkdir -p {parent}')
    stderr.read()

    cmd = f'echo "{encoded}" | base64 -d > {remote_path}'
    stdin, stdout, stderr = client.exec_command(cmd)
    err = stderr.read().decode().strip()
    if err:
        print(f"ERROR uploading {remote_path}: {err}")
    else:
        stdin2, stdout2, stderr2 = client.exec_command(f'wc -c < {remote_path}')
        size = stdout2.read().decode().strip()
        print(f"OK  {remote_path} ({size} bytes)")

print("\n--- Rebuilding Docker container ---")
stdin, stdout, stderr = client.exec_command('cd /opt/stratroom-new && docker compose up -d --build api')
out = stdout.read().decode('utf-8', errors='replace')
print(out)
err = stderr.read().decode('utf-8', errors='replace').strip()
if err:
    print(f"BUILD STDERR: {err}")

print("\n--- Health check ---")
import time
time.sleep(5)
stdin, stdout, stderr = client.exec_command('curl -s http://localhost:8001/health')
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode('utf-8', errors='replace').strip()
if err:
    print(f"HEALTH STDERR: {err}")

client.close()