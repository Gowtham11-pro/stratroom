import urllib.request, json, ssl

BASE = "http://103.191.132.36:8088"
ctx = ssl._create_unverified_context()

data = json.dumps({"email":"admin@stratroom.com","password":"changeme"}).encode()
req = urllib.request.Request(f"{BASE}/auth/login", data=data,
    headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req, context=ctx) as r:
    token = json.loads(r.read())["access_token"]

modules = ["/risks","/tasks","/scorecards","/org","/meetings",
           "/incidents","/budgets","/dashboard/stats","/projects",
           "/swot","/pestel","/compliance","/audit","/complaints","/bcp"]
all_ok = True
print("=== Smoke test: all modules ===")
for m in modules:
    req = urllib.request.Request(f"{BASE}{m}", headers={"Authorization":f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            body = r.read()
            j = json.loads(body)
            status = "OK" if isinstance(j, (dict, list)) else "BAD_JSON"
            print(f"  {m:20s} -> HTTP {r.status} {status} ({len(body)} bytes)")
    except urllib.error.HTTPError as e:
        body = e.read()[:120]
        print(f"  {m:20s} -> HTTP {e.code} {body.decode()}")
        all_ok = False
    except Exception as e:
        print(f"  {m:20s} -> ERROR {e}")
        all_ok = False

print(f"\n{'✅ All modules OK' if all_ok else '❌ Some modules failed'}")
