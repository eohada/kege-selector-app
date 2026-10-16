"""
Fast, non-destructive Telegram ecosystem status inspector for BooStudy.
Outputs JSON with runtime, conflict, and SQLite diagnostics.
Never outputs secrets.
"""
import os
import sys
import json
import sqlite3
import socket
import requests

def get_diagnostics() -> dict:
    # 1. Load env
    try:
        from dotenv import load_dotenv
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        env_path = os.path.join(root, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass

    # 2. Token discovery
    token_sources = [
        'TELEGRAM_DEV_BOT_TOKEN',
        'MAIN_BOT_TOKEN',
        'BOT_TOKEN',
        'TELEGRAM_BOT_TOKEN',
    ]
    token = ""
    source = "NONE"
    for ts in token_sources:
        val = (os.environ.get(ts) or "").strip()
        if val:
            token = val
            source = ts
            break

    is_dev_token = source == 'TELEGRAM_DEV_BOT_TOKEN'
    masked_token = "NOT_SET"
    bot_info = {}
    conflict_detected = False
    conflict_reason = ""

    if token:
        bot_id = token.split(':')[0] if ':' in token else 'invalid'
        masked_token = f"{bot_id}:***"
        
        # Fast getMe check
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=4)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    res = data.get("result", {})
                    bot_info = {
                        "id": res.get("id"),
                        "username": res.get("username"),
                        "first_name": res.get("first_name", ""),
                        "can_join_groups": res.get("can_join_groups"),
                    }
            elif r.status_code == 401:
                conflict_reason = "Unauthorized (invalid token)"
        except Exception as e:
            conflict_reason = f"Network error: {e}"

        # Fast conflict check via getUpdates probe (timeout=1)
        if bot_info.get("username"):
            try:
                # If username is production bot (@boostudy_bot), test if another poller is active
                up_resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates?timeout=1&limit=1",
                    timeout=3
                )
                if up_resp.status_code == 409:
                    conflict_detected = True
                    conflict_reason = "HTTP 409 Conflict: another getUpdates client is active"
            except Exception:
                pass

    # 3. Check SQLite DB
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    db_path = os.environ.get('SQLITE_DB_PATH') or os.path.join(root, 'instance', 'boostudy_dev.db')
    db_exists = os.path.exists(db_path)
    db_size_kb = round(os.path.getsize(db_path) / 1024, 1) if db_exists else 0
    users_count = 0
    pending_codes_count = 0

    if db_exists:
        try:
            conn = sqlite3.connect(db_path)
            users_count = conn.execute("SELECT COUNT(*) FROM Users").fetchone()[0]
            pending_codes_count = conn.execute(
                "SELECT COUNT(*) FROM UserProfiles WHERE telegram_link_code IS NOT NULL"
            ).fetchone()[0]
            conn.close()
        except Exception:
            pass

    # 4. Check backend port 5000
    backend_running = False
    try:
        s = socket.create_connection(("127.0.0.1", 5000), timeout=1)
        s.close()
        backend_running = True
    except Exception:
        pass

    return {
        "token_source": source,
        "is_dev_token": is_dev_token,
        "masked_token": masked_token,
        "bot": bot_info,
        "conflict_detected": conflict_detected,
        "conflict_reason": conflict_reason,
        "db_path": db_path,
        "db_exists": db_exists,
        "db_size_kb": db_size_kb,
        "users_count": users_count,
        "pending_codes_count": pending_codes_count,
        "backend_running": backend_running,
    }

if __name__ == '__main__':
    diag = get_diagnostics()
    print(json.dumps(diag, ensure_ascii=True, indent=2))
