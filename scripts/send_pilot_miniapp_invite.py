#!/usr/bin/env python3
"""
scripts/send_pilot_miniapp_invite.py
Sends a direct native Telegram WebApp invitation button to the project owner
or allowlisted pilot tester using the active bot token.

Usage:
    python scripts/send_pilot_miniapp_invite.py [--chat-id CHAT_ID] [--force]
"""

import argparse
import asyncio
import os
import sys

# Ensure repository root is on sys.path
rootDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if rootDir not in sys.path:
    sys.path.insert(0, rootDir)

from dotenv import load_dotenv
load_dotenv(os.path.join(rootDir, ".env"))

from app.telegram.config import (
    get_main_bot_token,
    get_mini_app_url,
    is_mini_app_enabled,
    is_mini_app_permitted_for_chat_id,
    get_mini_app_allowlist_chat_ids,
)


async def send_invite(chat_id: int, force: bool = False) -> None:
    token = get_main_bot_token()
    if not token:
        print("[ERROR] No bot token configured (TELEGRAM_BOT_TOKEN / MAIN_BOT_TOKEN / TELEGRAM_DEV_BOT_TOKEN).")
        sys.exit(1)

    url = get_mini_app_url()
    enabled = is_mini_app_enabled()

    print("=" * 60)
    print("   BooStudy Telegram Mini App - Pilot Inviter")
    print("=" * 60)
    print(f"Target Chat ID:   {chat_id}")
    print(f"Mini App URL:     {url}")
    print(f"Mini App Enabled: {enabled}")
    print(f"Bot Token ID:     {token.split(':')[0]}")

    if not enabled and not force:
        print("\n[ERROR] Mini App is currently disabled (TELEGRAM_MINI_APP_ENABLED != 1).")
        print("Set TELEGRAM_MINI_APP_ENABLED=1 or pass --force to bypass.")
        sys.exit(1)

    permitted = is_mini_app_permitted_for_chat_id(chat_id)
    if not permitted and not force:
        print(f"\n[ERROR] Chat ID {chat_id} is not permitted by Mini App Pilot allowlist.")
        print(f"Current allowlist: {get_mini_app_allowlist_chat_ids()}")
        sys.exit(1)

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from telegram.request import HTTPXRequest

    bot = Bot(token=token, request=HTTPXRequest(connection_pool_size=4, read_timeout=15, connect_timeout=10))

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Открыть Mini App (Pilot)", web_app=WebAppInfo(url=url))]
    ])

    text = (
        "👋 <b>Добро пожаловать в BooStudy Mini App (Pilot)!</b>\n\n"
        "Для вас активирован закрытый доступ к мобильному кабинету платформы.\n\n"
        "Нажмите кнопку ниже, чтобы открыть приложение:"
    )

    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        print(f"\n[OK] Invitation successfully sent to {chat_id}! (Message ID: {msg.message_id})")
    except Exception as e:
        print(f"\n[ERROR] Failed to send message: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Send Mini App WebApp Invite to Pilot User")
    parser.add_argument("--chat-id", type=int, default=None, help="Telegram Chat ID of recipient")
    parser.add_argument("--force", action="store_true", help="Bypass enabled/allowlist validation checks")
    args = parser.parse_args()

    chat_id = args.chat_id
    if not chat_id:
        allowlist = get_mini_app_allowlist_chat_ids()
        if allowlist:
            chat_id = sorted(list(allowlist))[0]
        else:
            creator_id = int(os.environ.get("BOOTSTRAP_CREATOR_CHAT_ID") or 0)
            if creator_id > 0:
                chat_id = creator_id

    if not chat_id:
        print("[ERROR] No chat ID specified and none found in allowlist or BOOTSTRAP_CREATOR_CHAT_ID.")
        print("Please provide --chat-id <ID>.")
        sys.exit(1)

    asyncio.run(send_invite(chat_id, force=args.force))


if __name__ == "__main__":
    main()
