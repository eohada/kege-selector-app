"""
Trigger realistic educational test notifications for Creator (User 4, Chat ID 854161398)
or specified user to verify Telegram delivery in @BooStudy_local_bot.

Supports:
- Safe dry-run mode (default): simulates delivery and logs outbox state without contacting Telegram.
- Live delivery mode (--live): temporarily enables live delivery for this test, sends to Telegram,
  and automatically reverts to safe dry-run mode immediately.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

from wsgi import app
from app.models import db, User, Lesson, Submission
from app.notifications.service import notify_user
from app.telegram.config import set_live_delivery_active, is_live_delivery_active
from app.telegram.delivery import claim_due_deliveries, deliver_one, TelegramDelivery


def parse_args():
    parser = argparse.ArgumentParser(description="Trigger Telegram test notification")
    parser.add_argument("--user-id", type=int, default=4, help="Target user ID (default: 4)")
    parser.add_argument(
        "--kind",
        type=str,
        default="lesson_scheduled",
        choices=["lesson_scheduled", "lesson_reminder", "submission_submitted", "submission_checked", "daily_digest"],
        help="Notification kind to trigger"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform real delivery to Telegram (reverts to safe mode immediately after)"
    )
    return parser.parse_args()


def trigger_notification(user_id: int, kind: str, live: bool):
    with app.app_context():
        user = User.query.get(user_id)
        if not user:
            print(f"[!] User {user_id} not found!")
            return

        chat_id = user.profile.telegram_chat_id if user.profile else None
        print(f"[*] Target User {user_id} (Chat ID: {chat_id}), Kind: {kind}, Mode: {'LIVE' if live else 'SIMULATED (Dry-Run)'}")

        now = datetime.now(timezone.utc)
        lesson_time = now + timedelta(hours=2)

        # Find or use existing realistic IDs for richer templates
        sample_lesson = Lesson.query.filter_by(teacher_id=user_id).first() or Lesson.query.first()
        sample_sub = Submission.query.first()

        meta = {}
        title = ""
        body = ""
        link_url = ""

        if kind == "lesson_scheduled":
            title = "Новое занятие в расписании"
            body = "Запланирован урок по подготовке к ЕГЭ: Графы и поиск в глубину (Задание 27)"
            link_url = "http://127.0.0.1:5000/lessons"
            meta = {
                "subject": "ЕГЭ Информатика: Задание 27 (Графы)",
                "student_name": "Алексей Смирнов",
                "teacher_name": "Создатель платформы",
                "start_time": lesson_time.isoformat(),
                "duration": 90,
                "lesson_id": sample_lesson.lesson_id if sample_lesson else 101,
            }
        elif kind == "lesson_reminder":
            title = "Напоминание о занятии"
            body = "Урок начнется через 2 часа: Графы и поиск в глубину"
            link_url = "http://127.0.0.1:5000/lessons"
            meta = {
                "subject": "ЕГЭ Информатика",
                "start_time": lesson_time.isoformat(),
                "lesson_id": sample_lesson.lesson_id if sample_lesson else 101,
            }
        elif kind == "submission_submitted":
            title = "Новая работа на проверку"
            body = "Ученик Алексей Смирнов сдал ДЗ: Вариант №102 КЕГЭ 2026"
            link_url = "http://127.0.0.1:5000/tutor/submissions"
            meta = {
                "assignment_title": "Решение варианта №102 КЕГЭ 2026",
                "student_name": "Алексей Смирнов",
                "submission_id": sample_sub.submission_id if sample_sub else 1,
            }
        elif kind == "submission_checked":
            title = "Домашнее задание проверено"
            body = "Преподаватель проверил работу 'Динамическое программирование'. Оценка: 24/25 (96%)"
            link_url = "http://127.0.0.1:5000/student/homework"
            meta = {
                "assignment_title": "Контрольная работа №2: Динамическое программирование",
                "score": 24,
                "max_score": 25,
                "percentage": 96,
                "submission_id": sample_sub.submission_id if sample_sub else 1,
            }
        else: # daily_digest
            title = "Дайджест на сегодня"
            body = "У вас запланировано 2 занятия и 1 работа ожидает проверки."
            link_url = "http://127.0.0.1:5000/dashboard"
            meta = {
                "lessons_count": 2,
                "reviews_count": 1,
            }

        if live:
            print("[+] Activating live delivery mode temporarily...")
            set_live_delivery_active(True)

        try:
            notify_user(
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                link_url=link_url,
                meta=meta
            )
            db.session.commit()
            print("[✓] Notification queued in database & Outbox delivery created.")

            # Deliver immediately
            claimed_ids = claim_due_deliveries(limit=10)
            print(f"[*] Claimed delivery IDs: {claimed_ids}")
            for d_id in claimed_ids:
                res = deliver_one(d_id)
                print(f"    - Delivery #{d_id}: status={res.get('status')} ok={res.get('ok')}")

        finally:
            if live:
                set_live_delivery_active(False)
                print("[✓] Reverted live delivery mode. Safe dry-run mode restored.")

if __name__ == '__main__':
    args = parse_args()
    trigger_notification(args.user_id, args.kind, args.live)
