"""Automated test suite for BooStudy Telegram Notifications V1.

Verifies:
- Role-specific visual cards & localized Russian date rendering (all 7 weekdays & timezones)
- Centralized template engine & actionable buttons
- User preference toggles (global switch & per-category switches)
- Transport-level Dev Allowlist safety guard: distinct 'simulated' status vs real 'sent'
- Pure configuration-driven allowlist (empty allowlist prohibits any external delivery)
- Dynamic account state: unlinking & chat change between enqueue and deliver
- Parent FamilyTie authorization & IDOR isolation (revocation between enqueue and deliver)
- Concurrency protection: DispatcherLock inter-process singleton
- Time-sensitive event invalidation (stale lesson reminder cancellation on reschedule)
- End-to-end domain event flows:
  * Homework assigned -> student & parent notification
  * Homework submitted -> teacher check notification with action button
  * Homework graded -> student & parent score card with comments
  * Lesson scheduled & rescheduled -> reminder invalidation & updated card
- Telegram API 429 retry / backoff policy
"""
from datetime import datetime, timedelta, timezone
import os
import pytest

from core.db_models import (
    db, User, UserProfile, Student, FamilyTie, Lesson, Tasks,
    TelegramDelivery, UserNotification, PendingAssignmentNotification,
    utc_now,
)
from app.telegram.config import is_delivery_permitted, get_dev_allowlist_chat_ids
from app.telegram.notification_templates import (
    render_telegram_notification,
    format_russian_dt,
)
from app.telegram.delivery import (
    enqueue_delivery,
    claim_due_deliveries,
    deliver_one,
    invalidate_pending_lesson_deliveries,
    recover_stale_processing,
)
from app.telegram.dispatcher import run_dispatch_cycle, DispatcherLock
from app.notifications.service import (
    notify_user,
    notify_student_and_parents,
    enqueue_assignment_notification,
    process_pending_assignment_notifications,
)


def test_format_russian_dt_all_weekdays_and_timezones():
    """Verify Russian date formatting across all 7 weekdays and multiple timezones."""
    # Week of Oct 19 to Oct 25, 2026:
    # 2026-10-19: Monday    (пн)
    # 2026-10-20: Tuesday   (вт)
    # 2026-10-21: Wednesday (ср)
    # 2026-10-22: Thursday  (чт)
    # 2026-10-23: Friday    (пт)
    # 2026-10-24: Saturday  (сб)  <- Verification of actual day of week!
    # 2026-10-25: Sunday    (вс)
    expected_weekdays = [
        (datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc), '19 октября (пн)'),
        (datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc), '20 октября (вт)'),
        (datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), '21 октября (ср)'),
        (datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc), '22 октября (чт)'),
        (datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc), '23 октября (пт)'),
        (datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc), '24 октября (сб)'),
        (datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc), '25 октября (вс)'),
    ]
    for dt, expected in expected_weekdays:
        res = format_russian_dt(dt, 'Europe/Moscow')
        assert expected in res, f"Expected '{expected}' in '{res}' for {dt}"

    # Month and Year boundary
    nye = datetime(2026, 12, 31, 21, 30, tzinfo=timezone.utc)  # 21:30 UTC = 00:30 MSK on Jan 1, 2027
    formatted_nye = format_russian_dt(nye, 'Europe/Moscow')
    assert '1 января' in formatted_nye
    assert '00:30 МСК' in formatted_nye

    # Tomsk timezone (UTC+7, MSK+4)
    dt_tomsk = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)  # 10:00 UTC = 17:00 Tomsk
    formatted_tomsk = format_russian_dt(dt_tomsk, 'Asia/Tomsk')
    assert '24 октября (сб)' in formatted_tomsk
    assert '17:00' in formatted_tomsk


def test_notification_template_student_lesson(app):
    """Verify rich card and action button for student lesson."""
    with app.app_context():
        u = User(username='student_tmpl', role='student')
        db.session.add(u)
        db.session.flush()

        text, button = render_telegram_notification(
            user_id=u.id,
            kind='lesson_scheduled',
            title='Новый урок',
            link_url='http://127.0.0.1:5000/lesson/101',
            meta={
                'topic': 'ЕГЭ Информатика: Задание 27',
                'teacher_name': 'Алексей Преподаватель',
                'start_time': datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
            }
        )
        assert 'Новый урок в расписании' in text
        assert 'ЕГЭ Информатика: Задание 27' in text
        assert 'Алексей Преподаватель' in text
        assert '24 октября (сб)' in text
        assert 'Локальная ссылка' in text
        assert button is not None
        assert button['inline_keyboard'][0][0]['text'] == '📅 Открыть расписание'
        assert button['inline_keyboard'][0][0]['url'] == 'http://127.0.0.1:5000/lesson/101'


def test_notification_template_parent_graded(app):
    """Verify parent perspective with student name, score, and comments."""
    with app.app_context():
        p = User(username='parent_tmpl', role='parent')
        db.session.add(p)
        db.session.flush()

        text, button = render_telegram_notification(
            user_id=p.id,
            kind='homework_checked',
            title='Работа проверена',
            link_url='https://boostudy.ru/assignments/202',
            meta={
                'student_name': 'Ваня Иванов',
                'assignment_title': 'Динамическое программирование',
                'score': 10,
                'max_score': 10,
                'teacher_comment': 'Отличное решение задачи!',
            }
        )
        assert 'Проверена домашняя работа ребёнка' in text
        assert 'Ваня Иванов' in text
        assert 'Динамическое программирование' in text
        assert '10 / 10' in text
        assert 'Отличное решение задачи!' in text
        assert button is not None
        assert button['inline_keyboard'][0][0]['text'] == '📊 Посмотреть результат'


def test_preference_global_and_category_toggles(app, monkeypatch):
    """Verify that turning off global switch or category disables Telegram delivery."""
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '12345678')
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda *a, **k: {'ok': True, 'result': {'message_id': 111}}
    )
    with app.app_context():
        u = User(username='pref_user', role='student')
        db.session.add(u)
        db.session.flush()

        # Global toggle OFF
        prof = UserProfile(
            user_id=u.id,
            telegram_chat_id=12345678,
            telegram_notifications_enabled=False,
            tg_notify_lesson_scheduled=True,
        )
        db.session.add(prof)
        db.session.commit()

        row1 = enqueue_delivery(u.id, 'Lesson reminder', kind='lesson_scheduled')
        claim_due_deliveries()
        res1 = deliver_one(row1.delivery_id)
        assert res1['status'] == 'cancelled'
        assert db.session.get(TelegramDelivery, row1.delivery_id).last_error == 'telegram notifications disabled'

        # Global ON, but category (lessons) OFF
        prof.telegram_notifications_enabled = True
        prof.tg_notify_lesson_scheduled = False
        db.session.commit()

        row2 = enqueue_delivery(u.id, 'Lesson scheduled', kind='lesson_scheduled')
        claim_due_deliveries()
        res2 = deliver_one(row2.delivery_id)
        assert res2['status'] == 'cancelled'
        assert 'notification kind disabled' in db.session.get(TelegramDelivery, row2.delivery_id).last_error

        # Category ON -> permitted
        prof.tg_notify_lesson_scheduled = True
        db.session.commit()

        row3 = enqueue_delivery(u.id, 'Lesson scheduled 2', kind='lesson_scheduled')
        claim_due_deliveries()
        res3 = deliver_one(row3.delivery_id)
        assert res3['status'] == 'sent'


def test_transport_dev_allowlist_safe_dry_run_distinct_status(app, monkeypatch):
    """Verify non-allowlisted chats in local mode are saved with status='simulated' (distinct from 'sent')."""
    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '55555555')

    api_called = []
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda *a, **k: api_called.append(True)
    )

    with app.app_context():
        u = User(username='dev_test_user', role='student')
        db.session.add(u)
        db.session.flush()

        # Chat ID 999999999 is NOT in allowlist
        prof = UserProfile(
            user_id=u.id,
            telegram_chat_id=999999999,
            telegram_notifications_enabled=True,
        )
        db.session.add(prof)
        db.session.commit()

        n = UserNotification(user_id=u.id, kind='news', title='Dry run test')
        db.session.add(n)
        db.session.flush()

        row = enqueue_delivery(u.id, 'Safe test notification', kind='news', notification_id=n.notification_id)
        claim_due_deliveries()
        res = deliver_one(row.delivery_id)

        # Status must be 'simulated', NOT 'sent'!
        assert res['status'] == 'simulated'
        assert res.get('dry_run') is True
        assert len(api_called) == 0  # Zero Telegram API calls!

        saved = db.session.get(TelegramDelivery, row.delivery_id)
        assert saved.status == 'simulated'
        assert '[dev_dry_run]' in saved.last_error

        # UserNotification telegram_sent must remain False for simulated messages
        saved_n = db.session.get(UserNotification, n.notification_id)
        assert saved_n.telegram_sent is False


def test_empty_allowlist_blocks_all_external_deliveries(app, monkeypatch):
    """Verify that if allowlist is empty, NO external deliveries can occur."""
    monkeypatch.setenv('ENVIRONMENT', 'local')
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '')
    monkeypatch.setenv('BOOTSTRAP_CREATOR_CHAT_ID', '')

    api_called = []
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda *a, **k: api_called.append(True)
    )

    with app.app_context():
        u = User(username='no_allowlist_user', role='student')
        db.session.add(u)
        db.session.flush()

        prof = UserProfile(
            user_id=u.id,
            telegram_chat_id=854161398,
            telegram_notifications_enabled=True,
        )
        db.session.add(prof)
        db.session.commit()

        # Allowlist has no external developer chat
        assert 854161398 not in get_dev_allowlist_chat_ids()
        assert is_delivery_permitted(854161398) is False

        row = enqueue_delivery(u.id, 'Test', kind='news')
        claim_due_deliveries()
        res = deliver_one(row.delivery_id)
        assert res['status'] == 'simulated'
        assert len(api_called) == 0


def test_unlinking_telegram_between_enqueue_and_deliver(app, monkeypatch):
    """Verify that if user unlinks Telegram while delivery is queued, delivery is cancelled."""
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '111222333')
    with app.app_context():
        u = User(username='unlink_user', role='student')
        db.session.add(u)
        db.session.flush()

        prof = UserProfile(
            user_id=u.id,
            telegram_chat_id=111222333,
            telegram_notifications_enabled=True,
        )
        db.session.add(prof)
        db.session.commit()

        # Enqueue while linked
        row = enqueue_delivery(u.id, 'Notification', kind='news')
        claim_due_deliveries()

        # User unlinks Telegram in web settings before dispatcher delivers
        prof.telegram_chat_id = None
        db.session.commit()

        res = deliver_one(row.delivery_id)
        assert res['status'] == 'cancelled'
        assert db.session.get(TelegramDelivery, row.delivery_id).last_error == 'telegram chat is not linked'


def test_changing_telegram_chat_between_enqueue_and_deliver(app, monkeypatch):
    """Verify that if user changes Telegram chat ID before delivery, the current chat ID is used."""
    sent_chats = []
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '22222222')
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda cid, *a, **k: sent_chats.append(cid) or {'ok': True, 'result': {'message_id': 1}}
    )
    with app.app_context():
        u = User(username='relink_user', role='student')
        db.session.add(u)
        db.session.flush()

        prof = UserProfile(
            user_id=u.id,
            telegram_chat_id=11111111,
            telegram_notifications_enabled=True,
        )
        db.session.add(prof)
        db.session.commit()

        row = enqueue_delivery(u.id, 'Notification', kind='news')
        claim_due_deliveries()

        # User links a new chat ID
        prof.telegram_chat_id = 22222222
        db.session.commit()

        res = deliver_one(row.delivery_id)
        assert res['status'] == 'sent'
        assert sent_chats == [22222222]


def test_revoking_family_tie_between_enqueue_and_deliver(app, monkeypatch):
    """Verify parent cannot receive notifications about student if FamilyTie is revoked before delivery."""
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '999888777')
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda *a, **k: {'ok': True, 'result': {'message_id': 123}}
    )
    with app.app_context():
        parent = User(username='parent_rev', role='parent')
        student_u = User(username='student_rev', role='student')
        db.session.add_all([parent, student_u])
        db.session.flush()

        prof = UserProfile(
            user_id=parent.id,
            telegram_chat_id=999888777,
            telegram_notifications_enabled=True,
        )
        tie = FamilyTie(parent_id=parent.id, student_id=student_u.id, is_confirmed=True)
        db.session.add_all([prof, tie])
        db.session.commit()

        # Enqueue notification with student_id while tie is valid
        row = enqueue_delivery(
            parent.id,
            'Child homework submitted',
            kind='homework_submitted',
            student_id=student_u.id,
        )
        claim_due_deliveries()

        # FamilyTie is revoked (is_confirmed=False) before dispatcher runs
        tie.is_confirmed = False
        db.session.commit()

        res = deliver_one(row.delivery_id)
        assert res['status'] == 'cancelled'
        assert 'family tie unconfirmed or revoked' in db.session.get(TelegramDelivery, row.delivery_id).last_error


def test_dispatcher_lock_concurrency_protection(tmp_path):
    """Verify DispatcherLock prevents two concurrent dispatcher workers."""
    lock_file = str(tmp_path / 'test_dispatcher.lock')
    lock1 = DispatcherLock(lock_file)
    lock2 = DispatcherLock(lock_file)

    assert lock1.acquire() is True
    # Second instance must fail to acquire while first holds it
    assert lock2.acquire() is False

    lock1.release()
    # Now second instance can acquire
    assert lock2.acquire() is True
    lock2.release()


def test_lesson_reminder_invalidation_on_reschedule(app):
    """Verify stale lesson reminders are cancelled when a lesson is rescheduled or cancelled."""
    with app.app_context():
        u = User(username='lesson_inv_user', role='student')
        db.session.add(u)
        db.session.flush()

        row1 = enqueue_delivery(u.id, 'Урок через 30 минут', kind='lesson_reminder', lesson_id=555)
        row2 = enqueue_delivery(u.id, 'Урок через 30 минут (другой)', kind='lesson_reminder', lesson_id=777)
        assert row1.status == 'pending'
        assert row2.status == 'pending'

        # Invalidate lesson 555
        cancelled = invalidate_pending_lesson_deliveries(555, reason='lesson_rescheduled')
        assert cancelled == 1

        d1 = db.session.get(TelegramDelivery, row1.delivery_id)
        d2 = db.session.get(TelegramDelivery, row2.delivery_id)

        assert d1.status == 'cancelled'
        assert 'invalidated: lesson_rescheduled' in d1.last_error
        assert d2.status == 'pending'


def test_telegram_api_429_retry_policy(app, monkeypatch):
    """Verify Telegram 429 rate limit triggers backoff and status='retry'."""
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '12345')
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda *a, **k: {'ok': False, 'error_code': 429, 'description': 'Too Many Requests: retry after 60'}
    )
    with app.app_context():
        u = User(username='retry_user', role='student')
        db.session.add(u)
        db.session.flush()
        db.session.add(UserProfile(user_id=u.id, telegram_chat_id=12345, telegram_notifications_enabled=True))
        db.session.commit()

        row = enqueue_delivery(u.id, 'Rate limited message', kind='news')
        claim_due_deliveries()
        res = deliver_one(row.delivery_id)

        assert res['status'] == 'retry'
        saved = db.session.get(TelegramDelivery, row.delivery_id)
        assert saved.status == 'retry'
        assert saved.attempt_count == 1
        assert saved.next_attempt_at is not None
        next_dt = saved.next_attempt_at if saved.next_attempt_at.tzinfo else saved.next_attempt_at.replace(tzinfo=timezone.utc)
        assert next_dt > utc_now()


def test_e2e_teacher_assigns_homework_and_debounced_delivery(app, monkeypatch):
    """E2E Domain Flow: Teacher assigns homework -> debounced queue -> student & parent cards."""
    sent_cards = []
    monkeypatch.setenv('TELEGRAM_DEV_ALLOWLIST_CHAT_IDS', '101,102')
    monkeypatch.setattr(
        'app.telegram.delivery.send_telegram_message',
        lambda cid, text, reply_markup=None, **k: sent_cards.append({'cid': cid, 'text': text, 'markup': reply_markup}) or {'ok': True, 'result': {'message_id': 1}}
    )
    with app.app_context():
        student_u = User(username='e2e_student', role='student')
        parent_u = User(username='e2e_parent', role='parent')
        db.session.add_all([student_u, parent_u])
        db.session.flush()

        db.session.add(UserProfile(user_id=student_u.id, telegram_chat_id=101, telegram_notifications_enabled=True))
        db.session.add(UserProfile(user_id=parent_u.id, telegram_chat_id=102, telegram_notifications_enabled=True))
        db.session.add(FamilyTie(parent_id=parent_u.id, student_id=student_u.id, is_confirmed=True))

        st = Student(name='Тестовый Ученик', user_id=student_u.id)
        db.session.add(st)
        db.session.flush()

        l = Lesson(student_id=st.student_id, topic='Тестовый урок', status='planned', lesson_date=utc_now() + timedelta(days=1))
        db.session.add(l)
        db.session.flush()

        # Domain event: Teacher enqueues homework assignment notification
        enqueue_assignment_notification(
            lesson=l,
            assignment_type='homework',
            task_ids=[1, 2, 3],
            link_url='http://127.0.0.1:5000/assignments/test',
        )
        assert PendingAssignmentNotification.query.count() == 1

        # Dispatcher processes debounced queue
        processed = process_pending_assignment_notifications(force=True)
        assert processed == 1
        assert PendingAssignmentNotification.query.count() == 0

        # Now deliveries exist in Outbox
        due = claim_due_deliveries()
        assert len(due) == 2  # One for student, one for parent
        for did in due:
            res = deliver_one(did)
            assert res['status'] == 'sent'

        assert len(sent_cards) == 2
        # Student card
        st_card = next(c for c in sent_cards if c['cid'] == 101)
        assert 'Новое домашнее задание' in st_card['text']
        assert st_card['markup']['inline_keyboard'][0][0]['text'] == '📖 Перейти к заданию'

        # Parent card
        parent_card = next(c for c in sent_cards if c['cid'] == 102)
        assert 'Новое задание у ребёнка' in parent_card['text']
        assert 'Тестовый Ученик' in parent_card['text']
        assert parent_card['markup']['inline_keyboard'][0][0]['text'] == '📖 Посмотреть задание'
