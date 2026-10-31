#!/usr/bin/env python3
"""Diagnostic script: Inspect BooStudy Telegram Outbox status and delivery metrics."""
from __future__ import annotations

import os
import sys

# Ensure repository root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from wsgi import app
from core.db_models import db, TelegramDelivery, UserNotification, UserProfile, PendingAssignmentNotification
from app.telegram.config import get_dev_allowlist_chat_ids, is_delivery_permitted, MAIN_BOT_TOKEN, TELEGRAM_BOT_USERNAME


def main():
    with app.app_context():
        print("=" * 60)
        print("       BooStudy Telegram Outbox Diagnostic Report")
        print("=" * 60)
        
        env = os.environ.get('ENVIRONMENT') or 'local'
        print(f"Environment:               {env}")
        print(f"Bot Username:              @{TELEGRAM_BOT_USERNAME or 'not_set'}")
        print(f"Token Configured:          {'Yes' if MAIN_BOT_TOKEN else 'No'}")
        print(f"Dev Allowlist Chat IDs:    {sorted(list(get_dev_allowlist_chat_ids()))}")
        print("-" * 60)

        # Status summary
        status_counts = (
            db.session.query(TelegramDelivery.status, db.func.count(TelegramDelivery.delivery_id))
            .group_by(TelegramDelivery.status)
            .all()
        )
        print("Telegram Delivery Queue Statuses:")
        if not status_counts:
            print("  (Queue is currently empty)")
        else:
            for status, count in status_counts:
                print(f"  - {status:15s}: {count}")

        # Kind breakdown
        print("-" * 60)
        kind_counts = (
            db.session.query(TelegramDelivery.kind, db.func.count(TelegramDelivery.delivery_id))
            .group_by(TelegramDelivery.kind)
            .order_by(db.func.count(TelegramDelivery.delivery_id).desc())
            .limit(10)
            .all()
        )
        print("Top 10 Delivery Kinds:")
        for kind, count in kind_counts:
            print(f"  - {kind or 'generic':25s}: {count}")

        # Pending assignments
        pending_asgn = PendingAssignmentNotification.query.count()
        print("-" * 60)
        print(f"Pending Assignment Debounce Queue: {pending_asgn} records")

        # Recent 10 deliveries
        print("-" * 60)
        print("Recent 10 Telegram Deliveries:")
        recent = (
            TelegramDelivery.query
            .order_by(TelegramDelivery.created_at.desc())
            .limit(10)
            .all()
        )
        for r in recent:
            chat_id = r.telegram_chat_id or (r.payload or {}).get('direct_chat_id')
            if r.status == 'sent':
                perm_str = "REAL DELIVERED"
            elif r.status == 'simulated':
                perm_str = "SIMULATED DRY-RUN"
            else:
                permitted = is_delivery_permitted(chat_id, user_id=r.user_id)
                perm_str = "ALLOWLIST" if permitted else "SIMULATED"
            err = f" | Error: {r.last_error[:40]}" if r.last_error else ""
            print(f"  #{r.delivery_id} [{r.status}] user={r.user_id} chat={chat_id} ({perm_str}) kind={r.kind}{err}")

        print("=" * 60)


if __name__ == '__main__':
    main()
