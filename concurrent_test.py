"""Concurrent blast test for MySQL connection race fix.
Fires 20 concurrent requests per route per batch, repeated for 30s."""

import sys, json, time, urllib.request, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://103.191.132.36:8088"
ssl_ctx = ssl._create_unverified_context()

def login():
    data = json.dumps({"email": "admin@stratroom.com", "password": "changeme"}).encode()
    req = urllib.request.Request(f"{BASE}/auth/login", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return json.loads(resp.read())["access_token"]

TOKEN = sys.argv[1] if len(sys.argv) > 1 else login()
ROUTES = ["/risks", "/tasks", "/scorecards", "/org", "/meetings"]

results = {r: {"ok":0,"4xx":0,"5xx":0,"err":0,"bad_json":0} for r in ROUTES}
errors = []

def request_one(route):
    try:
        req = urllib.request.Request(f"{BASE}{route}",
            headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            body = resp.read()
            code = resp.status
        if code == 200:
            try:
                j = json.loads(body)
                if not isinstance(j, (dict, list)):
                    results[route]["bad_json"] += 1
            except Exception:
                results[route]["bad_json"] += 1
            results[route]["ok"] += 1
        elif 400 <= code < 500:
            results[route]["4xx"] += 1
        else:
            results[route]["5xx"] += 1
    except urllib.error.HTTPError as e:
        c = e.code
        if 400 <= c < 500:
            results[route]["4xx"] += 1
        else:
            results[route]["5xx"] += 1
    except Exception as e:
        results[route]["err"] += 1
        errors.append((route, str(e)))

print(f"=== Concurrent Blast Test ===")
print(f"Target: {BASE}")
print(f"Routes: {', '.join(ROUTES)}")
print(f"Per batch: 20 concurrent requests per route")
print(f"Duration: ~30s\n")

start = time.time()
batch = 0
total_requests = 0
with ThreadPoolExecutor(max_workers=50) as pool:
    while time.time() - start < 30:
        batch += 1
        futs = []
        for route in ROUTES:
            for _ in range(20):
                futs.append(pool.submit(request_one, route))
        for f in as_completed(futs):
            f.result()
        total_requests += len(futs)
        elapsed = time.time() - start
        r = results
        print(f"Batch {batch:2d} | {elapsed:5.1f}s | {total_requests:4d} req | "
              f"ok={sum(r[x]['ok'] for x in ROUTES)} "
              f"4xx={sum(r[x]['4xx'] for x in ROUTES)} "
              f"5xx={sum(r[x]['5xx'] for x in ROUTES)} "
              f"bad_json={sum(r[x]['bad_json'] for x in ROUTES)} "
              f"err={sum(r[x]['err'] for x in ROUTES)}")
        time.sleep(0.5)

elapsed = time.time() - start
print(f"\n=== FINAL ({elapsed:.0f}s, {total_requests} requests) ===")
for route in ROUTES:
    r = results[route]
    t = sum(r.values())
    print(f"  {route:20s}: {t:4d} total — "
          f"200={r['ok']} 4xx={r['4xx']} 5xx={r['5xx']} "
          f"bad_json={r['bad_json']} err={r['err']}")

bad = sum(r["bad_json"] for r in results.values())
fives = sum(r["5xx"] for r in results.values())
exc = sum(r["err"] for r in results.values())
ok = bad == 0 and fives == 0 and exc == 0
print(f"\n{'✅ PASS' if ok else '❌ FAIL'}")
if not ok:
    print(f"  bad_json={bad}  5xx={fives}  exceptions={exc}")
    if errors:
        for route, msg in errors[:5]:
            print(f"  {route}: {msg}")
sys.exit(0 if ok else 1)
