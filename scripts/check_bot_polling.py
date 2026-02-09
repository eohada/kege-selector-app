"""
Проверка статуса Telegram-бота: webhook/long-polling конфликт.
"""
import os
import sys
import json
import time
from typing import Any

import requests


def _get_token() -> str:
    token = os.environ.get("BOT_TOKEN") or os.environ.get("UREP_BOT_TOKEN")
    if not token:
        print("BOT_TOKEN/UREP_BOT_TOKEN не задан.", file=sys.stderr)
        sys.exit(2)
    return token.strip()


def _tg_get(base_url: str, method: str, params: dict | None = None) -> dict[str, Any]:
    url = f"{base_url}/{method}"
    try:
        resp = requests.get(url, params=params, timeout=10)
    except Exception as e:
        return {"ok": False, "error": f"request_failed: {e}"}
    try:
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": f"invalid_json: {e}", "status_code": resp.status_code, "text": resp.text[:200]}


def main() -> int:
    token = _get_token()
    base_url = f"https://api.telegram.org/bot{token}"

    print("== Telegram Bot Diagnostics ==")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    me = _tg_get(base_url, "getMe")
    print("\n[getMe]")
    print(json.dumps(me, ensure_ascii=False, indent=2))
    if not me.get("ok"):
        return 1

    webhook = _tg_get(base_url, "getWebhookInfo")
    print("\n[getWebhookInfo]")
    print(json.dumps(webhook, ensure_ascii=False, indent=2))

    updates = _tg_get(
        base_url,
        "getUpdates",
        params={"timeout": 1, "limit": 1, "allowed_updates": "[]"},
    )
    print("\n[getUpdates]")
    print(json.dumps(updates, ensure_ascii=False, indent=2))

    if not updates.get("ok") and updates.get("error_code") == 409:
        print("\n⚠️  Конфликт getUpdates: другой инстанс уже держит long-polling.")
        if webhook.get("ok") and webhook.get("result", {}).get("url"):
            print("ℹ️  Также активен webhook — polling и webhook одновременно не работают.")
        return 3

    print("\n✅ Конфликтов getUpdates не обнаружено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
