import urllib.request, json, ssl, time

BASE = "http://103.191.132.36:8088"
ctx = ssl._create_unverified_context()

data = json.dumps({"email":"admin@stratroom.com","password":"changeme"}).encode()
req = urllib.request.Request(f"{BASE}/auth/login", data=data,
    headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req, context=ctx) as r:
    token = json.loads(r.read())["access_token"]

# Test both routes 20 times each
endpoints = [
    ("/scorecards", "bare /scorecards (scorecard_kpis MySQL)"),
    ("/stratroom/scoreCardList", "compat /scoreCardList (Java bridge MySQL)"),
]

for path, desc in endpoints:
    print(f"=== {desc} ===")
    errors = 0
    missing_perspectives = 0
    ok = 0
    for i in range(20):
        req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization":f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                body = r.read()
                j = json.loads(body)
                code = r.status

                # Check for "no perspectives" error in response
                body_str = body.decode()[:500].lower()
                if "no perspectives" in body_str or "perspective" not in body_str:
                    missing_perspectives += 1
                    print(f"  [{i+1:2d}] HTTP {code} ⚠️  no perspectives data")
                elif code == 200:
                    ok += 1
                else:
                    errors += 1
                    print(f"  [{i+1:2d}] HTTP {code} ❌")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:100]
            print(f"  [{i+1:2d}] HTTP {e.code} ❌ {body}")
            errors += 1
        except Exception as e:
            print(f"  [{i+1:2d}] ERROR ❌ {e}")
            errors += 1
        time.sleep(0.1)

    print(f"  Results: {ok} OK, {missing_perspectives} no-perspectives, {errors} errors")
    print()

# Also do a burst of 10 concurrent scorecard requests
print("=== Burst: 10 concurrent /scorecards ===")
from concurrent.futures import ThreadPoolExecutor, as_completed
results = []
def hit_scorecards():
    req = urllib.request.Request(f"{BASE}/scorecards", headers={"Authorization":f"Bearer {token}"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        body = r.read()
        j = json.loads(body)
        has_perspectives = "perspective" in body.decode().lower()
        return (r.status, len(body), has_perspectives)

with ThreadPoolExecutor(max_workers=10) as pool:
    futs = [pool.submit(hit_scorecards) for _ in range(10)]
    for f in as_completed(futs):
        results.append(f.result())

for i, (code, size, has_p) in enumerate(results):
    flag = "✅" if has_p else "❌ NO PERSPECTIVES"
    print(f"  [{i+1:2d}] HTTP {code} {size}B {flag}")
