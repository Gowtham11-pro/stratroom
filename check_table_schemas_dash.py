import paramiko, os
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('103.191.132.36', port=55004, username='root', password=os.environ['SSH_PASS'])

tables = [
    'risk_details', 'task_details', 'scorecard_kpis', 'employee_details',
    'universal_incident', 'budget_detail', 'meeting_management', 
    'compliance_details', 'initiatives_details', 'audit_management',
    'formulation_initiatives', 'users'
]
for t in tables:
    stdin, stdout, stderr = ssh.exec_command(
        f"mysql -h 127.0.0.1 -P 3306 -u stratroom -p'Admin#123' orgstructure -e \"DESCRIBE {t}\" 2>&1"
    )
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(f"\n=== {t} ===")
    if 'ERROR 1146' in err or 'ERROR 1054' in err:
        print(f"(not found)")
    elif out:
        lines = out.split('\n')
        for line in lines[:8]:
            print(f"  {line}")
        if len(lines) > 8:
            print(f"  ... {len(lines)-1} columns total")
    else:
        print(f"(empty or error: {err[:100]})")

ssh.close()
