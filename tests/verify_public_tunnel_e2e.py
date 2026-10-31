# tests/verify_public_tunnel_e2e.py
"""
Live end-to-end security and functional verification against public Cloudflare Tunnel.
Tests public HTTPS endpoints directly over the internet.
"""

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import sys
import os

from dotenv import load_dotenv

load_dotenv("F:/projects/kege_selector_app_current/.env")

# 1. Read Tunnel Config or CLI override
base_url = None
for arg in sys.argv[1:]:
    if arg.startswith("http://") or arg.startswith("https://"):
        base_url = arg.rstrip("/")
    elif arg.startswith("--base-url="):
        base_url = arg.split("=", 1)[1].rstrip("/")

if not base_url:
    tunnel_cfg_file = "F:/projects/kege_selector_app_current/instance/mini_app_tunnel_env.json"
    if os.path.exists(tunnel_cfg_file):
        try:
            with open(tunnel_cfg_file, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
            public_tg_app_url = cfg.get("public_url", "")
            base_url = public_tg_app_url.replace("/tg-app", "").rstrip("/")
        except Exception:
            pass

if not base_url:
    base_url = "http://127.0.0.1:5050"

public_tg_app_url = f"{base_url}/tg-app"
bot_token = os.environ.get("TELEGRAM_DEV_BOT_TOKEN")

print(f"[*] Testing Base URL: {base_url}")
print(f"[*] Mini App URL:     {public_tg_app_url}")
print(f"[*] Bot Token ID:     {bot_token.split(':')[0] if bot_token else 'NONE'}")

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def do_request(path, headers=None, method="GET", json_data=None):
    url = f"{base_url}{path}"
    data_bytes = None
    all_headers = {}
    if json_data is not None:
        data_bytes = json.dumps(json_data).encode("utf-8")
        all_headers["Content-Type"] = "application/json"
    if headers:
        all_headers.update(headers)
    req = urllib.request.Request(url, method=method, data=data_bytes)
    for k, v in all_headers.items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=12) as resp:
            body = resp.read()
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:
        return 0, str(e).encode(), {}

def make_init_data(tg_id: int, first_name="Owner", username="owner_dev"):
    user_json = json.dumps({"id": tg_id, "first_name": first_name, "username": username}, separators=(',', ':'))
    auth_date = str(int(time.time()))
    data_dict = {"auth_date": auth_date, "user": user_json}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data_dict.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    data_dict["hash"] = calc_hash
    return urllib.parse.urlencode(data_dict)

results = []

def record(name, passed, detail=""):
    results.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name} - {detail}")

print("\n--- 1. Public Entry & Static Assets ---")
# 1. /tg-app/
status, body, _ = do_request("/tg-app/")
record("Mini App Shell (/tg-app/)", status == 200 and len(body) > 1000, f"HTTP {status}, {len(body)} bytes")

# 2. Whitelisted static asset
status, body, _ = do_request("/static/platform-feedback.js")
record("Static Resource (/static/platform-feedback.js)", status == 200, f"HTTP {status}, {len(body)} bytes")

# 3. Local vendor Telegram SDK
status, body, _ = do_request("/static/js/vendor/telegram-web-app.js")
record("Vendor Telegram SDK (/static/js/vendor/telegram-web-app.js)", status == 200 and len(body) > 50000, f"HTTP {status}, {len(body)} bytes")

# 4. Local Toast script
status, body, _ = do_request("/static/toast.js")
record("Static Toast Script (/static/toast.js)", status == 200, f"HTTP {status}, {len(body)} bytes")

# 5. Healthz
status, body, _ = do_request("/healthz")
record("Health Check (/healthz)", status == 200 and b"healthy" in body, f"HTTP {status}")

print("\n--- 2. Security Boundaries & Route Isolation ---")
blocked_paths = [
    "/admin",
    "/admin/",
    "/login",
    "/workspace",
    "/workspace/profile",
    "/api/tasks",
    "/api/auth/login",
    "/tg-app/../admin",
    "//admin",
    "/tg-app/%2e%2e/admin",
]
for p in blocked_paths:
    status, body, _ = do_request(p)
    is_blocked = (status == 403)
    record(f"Route Blocked: {p}", is_blocked, f"HTTP {status} (Expected 403)")

print("\n--- 3. Mini App API Authentication & Integrity ---")
# Missing initData
status, body, _ = do_request("/tg-app/api/bootstrap", method="POST", json_data={})
try:
    data = json.loads(body.decode())
    passed = status in (401, 403) and data.get("error") in ("init_data_missing", "invalid_init_data")
except:
    passed = False
record("API Missing initData", passed, f"HTTP {status}, response: {body.decode()[:60]}")

# Invalid signature initData
fake_init_data = "auth_date=1700000000&user=%7B%22id%22%3A854161398%7D&hash=deadbeef00000000000000000000000000000000000000000000000000000000"
status, body, _ = do_request("/tg-app/api/bootstrap", method="POST", json_data={"init_data": fake_init_data})
try:
    data = json.loads(body.decode())
    passed = status in (401, 403) and data.get("error") == "invalid_init_data"
except:
    passed = False
record("API Invalid Hash Signature", passed, f"HTTP {status}, response: {body.decode()[:60]}")

# Non-allowlisted User ID (valid signature, but untrusted telegram_id)
foreign_init_data = make_init_data(999888777, first_name="Hacker")
status, body, _ = do_request("/tg-app/api/bootstrap", method="POST", json_data={"init_data": foreign_init_data})
try:
    data = json.loads(body.decode())
    passed = status == 403 and data.get("error") == "telegram_id_not_allowlisted"
except:
    passed = False
record("API Foreign User (Allowlist Guard)", passed, f"HTTP {status}, response: {body.decode()[:60]}")

print("\n--- 4. Authorized Creator Mini App Access ---")
# Authorized Creator (854161398)
creator_init_data = make_init_data(854161398, first_name="Creator", username="creator")
status, body, _ = do_request("/tg-app/api/bootstrap", method="POST", json_data={"init_data": creator_init_data})
try:
    data = json.loads(body.decode())
    user_info = data.get("user", {})
    context_info = data.get("context", {})
    passed = status == 200 and data.get("ok") is True and user_info.get("role") == "creator"
    detail = f"HTTP 200, user={user_info.get('username')}, active_context={context_info.get('active_context')}, contexts={context_info.get('available_contexts')}"
except Exception as e:
    passed = False
    detail = f"HTTP {status}, err={e}, body={body.decode()[:80]}"
record("Creator Bootstrap Endpoint", passed, detail)

# Schedule Endpoint
status, body, _ = do_request("/tg-app/api/teacher/schedule", method="POST", json_data={"init_data": creator_init_data})
try:
    data = json.loads(body.decode())
    passed = status == 200 and data.get("ok") is True and "schedule" in data
    detail = f"HTTP 200, lessons_count={len(data.get('schedule', []))}"
except Exception as e:
    passed = False
    detail = f"HTTP {status}, err={e}"
record("Teacher Schedule Endpoint", passed, detail)

# Operations Health Endpoint (RBAC Creator Only)
status, body, _ = do_request("/tg-app/api/operations/health", method="POST", json_data={"init_data": creator_init_data})
try:
    data = json.loads(body.decode())
    passed = status == 200 and data.get("ok") is True and "summary" in data and "deliveries" in data
    detail = f"HTTP 200, deliveries_total={data.get('deliveries', {}).get('total', 0)}"
except Exception as e:
    passed = False
    detail = f"HTTP {status}, err={e}"
record("Operations Health Endpoint (Creator RBAC)", passed, detail)

print("\n================== SUMMARY ==================")
all_passed = all(p for _, p, _ in results)
passed_count = sum(1 for _, p, _ in results if p)
total_count = len(results)
print(f"Total: {total_count}, Passed: {passed_count}, Failed: {total_count - passed_count}")

if all_passed:
    print("\n>>> ALL PUBLIC TUNNEL SECURITY & E2E CHECKS PASSED (100%) <<<")
    sys.exit(0)
else:
    print("\n>>> ONE OR MORE CHECKS FAILED <<<")
    sys.exit(1)
