"""
Integration tests for Telegram Bots V2 & Telegram Mini Apps (TMA)
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from core.db_models import db, User, TelegramAuthCode, BugReport, utc_now

def run_telegram_bots_v2_tests():
    print("\n============================================================")
    print("STARTING TELEGRAM BOTS V2 & TMA INTEGRATION TESTS")
    print("============================================================\n")

    app = create_app('testing')
    client = app.test_client()

    with app.app_context():
        db.drop_all()
        db.create_all()

        # 1. Setup test user & valid link code
        user = User.query.filter_by(username='tg_test_user').first()
        if not user:
            user = User(
                username='tg_test_user',
                email='tg_test_user@boostudy.ru',
                role='creator',
                creator_bot_mode='ADMIN'
            )
            db.session.add(user)
            db.session.commit()

        auth_code = TelegramAuthCode(
            user_id=user.id,
            code='VALID123',
            expires_at=utc_now() + timedelta(hours=1),
            is_used=False
        )
        db.session.add(auth_code)
        db.session.commit()

        # --- TEST 1: POST /api/webhooks/main-bot with /start valid_code -> Binds telegram_id ---
        print("[TEST 1] Testing /start VALID123 on Main Bot webhook...")
        update_payload = {
            "update_id": 1001,
            "message": {
                "message_id": 1,
                "date": 1600000000,
                "chat": {"id": 99887766, "type": "private"},
                "from": {"id": 99887766, "first_name": "TestUser"},
                "text": "/start VALID123"
            }
        }
        res1 = client.post('/api/webhooks/main-bot', json=update_payload)
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"
        res1_json = res1.get_json()
        assert res1_json.get("ok") is True, f"Expected ok True, got {res1_json}"

        import time
        time.sleep(0.5)

        # Refresh user from DB
        db.session.refresh(user)
        assert user.telegram_id == 99887766, f"Expected telegram_id 99887766, got {user.telegram_id}"
        assert user.telegram_chat_id == 99887766, f"Expected telegram_chat_id 99887766, got {user.telegram_chat_id}"
        
        db.session.refresh(auth_code)
        assert auth_code.is_used is True, "Expected auth_code.is_used to be True"
        print(" -> ✅ SUCCESS: User bound telegram_id & chat_id correctly!\n")

        # --- TEST 2: Testing CREATOR mode switch (ADMIN <-> TEACHER) ---
        print("[TEST 2] Testing CREATOR mode switch handler...")
        assert user.creator_bot_mode == 'ADMIN'
        
        update_switch_payload = {
            "update_id": 1002,
            "message": {
                "message_id": 2,
                "date": 1600000005,
                "chat": {"id": 99887766, "type": "private"},
                "from": {"id": 99887766, "first_name": "TestUser"},
                "text": "🔄 Сменить режим: 👨‍🏫 Преподаватель"
            }
        }
        res2 = client.post('/api/webhooks/main-bot', json=update_switch_payload)
        assert res2.status_code == 200
        time.sleep(0.5)
        db.session.refresh(user)
        assert user.creator_bot_mode == 'TEACHER', f"Expected TEACHER, got {user.creator_bot_mode}"

        # Switch back
        update_switch_back = {
            "update_id": 1003,
            "message": {
                "message_id": 3,
                "date": 1600000010,
                "chat": {"id": 99887766, "type": "private"},
                "from": {"id": 99887766, "first_name": "TestUser"},
                "text": "🔄 Сменить режим: 👑 Админ"
            }
        }
        res2_back = client.post('/api/webhooks/main-bot', json=update_switch_back)
        assert res2_back.status_code == 200
        time.sleep(0.5)
        db.session.refresh(user)
        assert user.creator_bot_mode == 'ADMIN', f"Expected ADMIN, got {user.creator_bot_mode}"
        print(" -> ✅ SUCCESS: CREATOR mode toggled ADMIN ↔ TEACHER correctly!\n")

        # --- TEST 3: POST /api/webhooks/qa-bot inline button [ ✅ Исправлено ] ---
        print("[TEST 3] Testing QA Bot inline button callback for BugReport status...")
        bug = BugReport(
            title="Тестовая ошибка в интерфейсе",
            description="Кнопка не нажимается",
            severity="CRITICAL",
            status="NEW",
            reporter_id=user.id
        )
        db.session.add(bug)
        db.session.commit()

        qa_cb_payload = {
            "update_id": 2001,
            "callback_query": {
                "id": "cb_query_999",
                "from": {"id": 99887766},
                "message": {
                    "message_id": 50,
                    "chat": {"id": 99887766}
                },
                "data": f"qa_status:resolved:{bug.id}"
            }
        }
        res3 = client.post('/api/webhooks/qa-bot', json=qa_cb_payload)
        assert res3.status_code == 200
        time.sleep(0.5)
        db.session.refresh(bug)
        assert bug.status == 'RESOLVED', f"Expected BugReport status RESOLVED, got {bug.status}"
        print(f" -> ✅ SUCCESS: BugReport #{bug.id} status updated to RESOLVED via QA Bot callback!\n")

        # --- TEST 4: GET /tma/schedule returns 200 OK & Telegram.WebApp SDK ---
        print("[TEST 4] Testing GET /tma/schedule rendering & Telegram.WebApp SDK inclusion...")
        res4 = client.get('/tma/schedule')
        assert res4.status_code == 200, f"Expected 200, got {res4.status_code}"
        assert b'Telegram.WebApp' in res4.data or b'telegram.org/js/telegram-web-app.js' in res4.data, "Missing Telegram.WebApp SDK script"
        print(" -> ✅ SUCCESS: GET /tma/schedule returned 200 OK with Telegram.WebApp SDK!\n")

        # --- TEST 5: POST /api/tma/auth & POST /api/tma/schedule personalization ---
        print("[TEST 5] Testing /api/tma/auth & /api/tma/schedule for linked vs unlinked user...")
        
        # Linked user test
        res5_linked = client.post('/api/tma/auth', json={'telegram_id': 99887766})
        assert res5_linked.status_code == 200
        res5_linked_json = res5_linked.get_json()
        assert res5_linked_json.get('is_linked') is True, f"Expected is_linked True, got {res5_linked_json}"
        assert res5_linked_json['user']['username'] == 'tg_test_user'

        # Unlinked user test
        res5_unlinked = client.post('/api/tma/auth', json={'telegram_id': 11111111})
        assert res5_unlinked.status_code == 200
        res5_unlinked_json = res5_unlinked.get_json()
        assert res5_unlinked_json.get('is_linked') is False, f"Expected is_linked False, got {res5_unlinked_json}"

        # Schedule personalization test
        res5_sched = client.post('/api/tma/schedule', json={'telegram_id': 99887766})
        assert res5_sched.status_code == 200
        assert res5_sched.get_json().get('is_linked') is True
        print(" -> ✅ SUCCESS: /api/tma/auth & /api/tma/schedule personalization verified!\n")

        print("============================================================")
        print("ALL TELEGRAM BOTS V2 & TMA TESTS PASSED 100% SUCCESSFULLY!")
        print("============================================================\n")

if __name__ == '__main__':
    run_telegram_bots_v2_tests()

