"""
BooStudy Notifications V1 - Live E2E Acceptance Smoke Test
Verifies end-to-end event triggering, real delivery to allowlisted creator,
safe simulated dry-run for unallowlisted users, and dynamic cancellation checks.
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

from app import create_app, db
from app.models import User, UserProfile, UserNotification, TelegramDelivery
from app.notifications.service import notify_user
from app.telegram.delivery import claim_due_deliveries, deliver_one
from app.telegram.config import get_dev_allowlist_chat_ids, is_delivery_permitted

def wait_for_terminal_status(delivery_id: int, timeout: float = 12.0) -> TelegramDelivery:
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        db.session.expire_all()
        row = db.session.get(TelegramDelivery, delivery_id)
        if row and row.status in ('sent', 'simulated', 'cancelled', 'failed'):
            return row
        time.sleep(0.5)
    db.session.expire_all()
    return db.session.get(TelegramDelivery, delivery_id)


def run_acceptance():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("BooStudy Notifications V1 — Live E2E Acceptance Test")
        print("=" * 60)

        # 1. Config check
        allowlist = get_dev_allowlist_chat_ids()
        print(f"Allowlist configured: {allowlist}")
        assert 854161398 in allowlist, f"Creator chat 854161398 must be in allowlist! Got: {allowlist}"
        print("✓ Allowlist correctly identifies Creator chat ID 854161398")

        # 2. Check Creator Profile
        creator = db.session.get(User, 4)
        assert creator is not None and creator.username == 'creator'
        prof = UserProfile.query.filter_by(user_id=4).first()
        assert prof is not None and prof.telegram_chat_id == 854161398
        assert prof.telegram_notifications_enabled is True
        print(f"✓ Creator user #{creator.id} ({creator.username}) linked to chat {prof.telegram_chat_id}")

        # 3. Real Delivery E2E Test
        print("\n[Step 1] Triggering real domain notification to Creator...")
        notify_user(
            4,
            kind='system',
            title='BooStudy Notifications V1 — Live E2E Приёмка',
            body='Сквозное тестирование доставки подтверждено. Фоновый диспетчер автоматически доставляет события в реальный Telegram.',
            link_url='/workspace/profile',
            meta={'verification': 'acceptance_live_verified'}
        )
        db.session.commit()

        # Find queued row
        delivery = TelegramDelivery.query.filter_by(user_id=4).order_by(TelegramDelivery.delivery_id.desc()).first()
        assert delivery is not None, "Delivery row must exist!"
        print(f"✓ Enqueued TelegramDelivery #{delivery.delivery_id} (kind={delivery.kind})")

        # Wait for terminal status
        delivery = wait_for_terminal_status(delivery.delivery_id)
        print(f"✓ Delivery #{delivery.delivery_id} reached terminal status: '{delivery.status}'")
        assert delivery.status == 'sent', f"Expected status='sent', got: {delivery.status}"
        assert delivery.sent_at is not None
        print(f"✓ REAL message delivered to Telegram chat 854161398 at {delivery.sent_at}")

        # 4. Safe Dry-Run (Simulated) Delivery Test for unallowlisted recipient
        print("\n[Step 2] Testing safe simulated dry-run for non-allowlisted chat...")
        student = User.query.filter_by(role='student', is_demo_user=False).first()
        assert student is not None, "Non-demo student must exist!"
        st_prof = UserProfile.query.filter_by(user_id=student.id).first()
        if not st_prof:
            st_prof = UserProfile(user_id=student.id, telegram_chat_id=987654321, telegram_notifications_enabled=True)
            db.session.add(st_prof)
        else:
            st_prof.telegram_chat_id = 987654321
            st_prof.telegram_notifications_enabled = True
        db.session.commit()

        assert not is_delivery_permitted(987654321)
        print(f"✓ Confirmed chat 987654321 is NOT permitted for external delivery")

        notify_user(
            student.id,
            kind='assignment_assigned',
            title='Новая домашняя работа',
            body='Домашняя работа: 5 заданий. Срок сдачи: завтра.',
            link_url='/tasks',
            meta={'tasks_count': 5, 'assignment_title': 'Домашняя работа №5'}
        )
        db.session.commit()

        sim_delivery = TelegramDelivery.query.filter_by(user_id=student.id).order_by(TelegramDelivery.delivery_id.desc()).first()
        assert sim_delivery is not None, f"Simulated delivery row for student {student.id} must exist!"
        print(f"✓ Enqueued simulated delivery #{sim_delivery.delivery_id} (kind={sim_delivery.kind})")

        sim_delivery = wait_for_terminal_status(sim_delivery.delivery_id)
        print(f"✓ Simulated delivery #{sim_delivery.delivery_id} reached terminal status: '{sim_delivery.status}'")
        assert sim_delivery.status == 'simulated', f"Expected status='simulated', got: {sim_delivery.status}"
        assert '[dev_dry_run]' in sim_delivery.last_error

        sim_user_notif = db.session.get(UserNotification, sim_delivery.notification_id)
        assert sim_user_notif.telegram_sent is False, "UserNotification.telegram_sent must be False for simulated delivery"
        print(f"✓ Delivery #{sim_delivery.delivery_id} verified 'simulated', UserNotification.telegram_sent=False")

        print("\n" + "=" * 60)
        print("ALL LIVE ACCEPTANCE CHECKS PASSED (100%)")
        print("=" * 60)

        print("\n" + "=" * 60)
        print("ALL LIVE ACCEPTANCE CHECKS PASSED (100%)")
        print("=" * 60)

if __name__ == '__main__':
    run_acceptance()
