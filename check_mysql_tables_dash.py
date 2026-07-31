import paramiko, os
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root', password=os.environ['SSH_PASS'])

# Show all tables related to our modules
tables = [
    'task_details', 'risk_details', 'scorecard_kpis', 'employee_details',
    'incident_details', 'budget_lines', 'meeting_details', 'compliance_frameworks',
    'initiative_details', 'project_details', 'audit_findings', 'audit_details',
    'users'
]
for t in tables:
    stdin, stdout, stderr = ssh.exec_command(
        f"mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e "
        f"\"SELECT '{t}' as table_name, COUNT(*) as cnt, 'CHECK' as status FROM {t} LIMIT 1\" 2>&1"
    )
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if 'ERROR 1146' in err or 'doesn\'t exist' in err:
        print(f"✗ {t} — TABLE NOT FOUND")
    elif out:
        print(out)
    else:
        print(f"? {t} — {err[:100] if err else 'no output'}")

# Also show actual table list
stdin, stdout, stderr = ssh.exec_command(
    "mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e \"SHOW TABLES\" 2>&1"
)
print("\n=== ALL TABLES ===")
print(stdout.read().decode())
ssh.close()
