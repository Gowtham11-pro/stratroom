import urllib.request, json, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://103.191.132.36:8088"
ctx = ssl._create_unverified_context()

data = json.dumps({"email":"admin@stratroom.com","password":"changeme"}).encode()
req = urllib.request.Request(f"{BASE}/auth/login", data=data,
    headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req, context=ctx) as r:
    token = json.loads(r.read())["access_token"]

results = []
def hit_scorecards():
    req = urllib.request.Request(f"{BASE}/scorecards", headers={"Authorization":f"Bearer {token}"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        body = r.read()
        j = json.loads(body)
        has_p = "perspective" in body.decode().lower()
        return (r.status, len(body), has_p)

print("=== Burst: 10 concurrent /scorecards ===")
with ThreadPoolExecutor(max_workers=10) as pool:
    futs = [pool.submit(hit_scorecards) for _ in range(10)]
    for f in as_completed(futs):
        results.append(f.result())

ok = all(r[0]==200 for r in results)
all_p = all(r[2] for r in results)
for i, (code, size, has_p) in enumerate(results):
    flag = "OK" if has_p else "NO PERSPECTIVES"
    print(f"  [{i+1:2d}] HTTP {code} {size}B {flag}")
print(f"\nAll 200 OK: {ok}, All have perspectives: {all_p}")
