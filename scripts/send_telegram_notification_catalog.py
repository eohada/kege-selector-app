#!/usr/bin/env python3
"""
Send the complete catalog of BooStudy Telegram notifications to the Creator.

Target Recipient:
  Chat ID: 854161398 (Creator / User ID 4)
  Bot: @BooStudy_local_bot

Strict guardrails:
- Refuses to send to any chat ID other than 854161398.
- Does not modify database records or user roles.
- Renders cards using the real Telegram Next templating engine (render_telegram_notification).
- Respects Telegram API rate limits by pausing between sends.
- Leaves default safe dev mode intact.
"""
from __future__ import annotations

import os
import sys
import time
import json
import logging
from typing import Any

# Ensure project root is in sys.path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

from wsgi import app
from app.telegram.config import BOT_TOKEN, TELEGRAM_BOT_USERNAME, get_main_bot_token
from app.telegram.notifications import send_telegram_message
from app.telegram.notification_templates import render_telegram_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telegram_catalog")

ALLOWED_CHAT_ID = 854161398
TARGET_USER_ID = 4
PAUSE_BETWEEN_MESSAGES = 0.7  # seconds, ensures safe rate limits with Telegram API


def send_catalog_message(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Safe sender strictly locked to ALLOWED_CHAT_ID."""
    if int(chat_id) != ALLOWED_CHAT_ID:
        raise ValueError(f"SECURITY VIOLATION: Refusing to send to unapproved chat_id={chat_id}")
    
    resp = send_telegram_message(
        chat_id=chat_id,
        text_body=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )
    time.sleep(PAUSE_BETWEEN_MESSAGES)
    if resp and resp.get("ok"):
        return True
    logger.error("Failed to deliver message to %s: %s", chat_id, resp)
    return False


def build_catalog() -> list[dict[str, Any]]:
    """Build the exhaustive catalog of all supported notifications across all 6 roles."""
    catalog = []
    test_id = 1

    # =========================================================================
    # 1. 👑 СОЗДАТЕЛЮ (Creator) - 4 notifications
    # =========================================================================
    group_1 = [
        {
            "group": "👑 СОЗДАТЕЛЮ",
            "name": "Критический сбой платежного шлюза",
            "kind": "system_critical_error",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="system_critical_error",
                title="Сбой платежного шлюза ЮKassa",
                body=(
                    "Traceback (most recent call last):\n"
                    '  File "app/billing/routes.py", line 142, in webhook\n'
                    "ConnectionRefusedError: Connection to YooKassa API timed out after 3 retries."
                ),
                meta={"service": "billing-gateway", "recipient_role": "creator"},
            ),
        },
        {
            "group": "👑 СОЗДАТЕЛЮ",
            "name": "Высокая утилизация дискового пространства",
            "kind": "operational_alert",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="operational_alert",
                title="Утилизация диска БД превысила порог 90%",
                body="Раздел /var/lib/postgresql заполнен на 91.4%. Рекомендуется запуск вакуума и ротация журналов WAL.",
                meta={"service": "database-storage", "recipient_role": "creator"},
            ),
        },
        {
            "group": "👑 СОЗДАТЕЛЮ",
            "name": "Сбой фонового воркера Celery",
            "kind": "system_errors",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="system_errors",
                title="Воркер задач потерял heartbeat-соединение",
                body="Worker celery@node-worker-1 lost heartbeat connection after 180s idle. Auto-restart initiated.",
                meta={"service": "celery-dispatcher", "recipient_role": "creator"},
            ),
        },
        {
            "group": "👑 СОЗДАТЕЛЮ",
            "name": "Ответ ученика на напоминание об уроке",
            "kind": "lesson_reminder_response",
            "builder": lambda: (
                (
                    "⏰ <b>Ответ на напоминание об уроке</b>\n\n"
                    "👤 Ученик: <b>@alexey_student</b>\n"
                    "🆔 Платформа: <code>4</code>\n"
                    "📚 Урок: <b>#2201</b>\n"
                    "📄 Тема: <b>Информатика ЕГЭ: Задание 27</b>\n"
                    "🕐 Начало: <b>24 октября (сб) в 18:00 МСК</b>\n"
                    "✅ Ответ: <b>Буду на уроке</b>\n\n"
                    "<b>Текст уведомления:</b>\n"
                    "<pre>⏰ Напоминание: урок начнётся через 15 мин.\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "📚 Урок: Информатика ЕГЭ: Задание 27</pre>"
                ),
                None,
            ),
        },
    ]

    # =========================================================================
    # 2. 🛡️ АДМИНИСТРАТОРУ (Admin) - 3 notifications
    # =========================================================================
    group_2 = [
        {
            "group": "🛡️ АДМИНИСТРАТОРУ",
            "name": "Сбой сервиса видеоконференций",
            "kind": "system_critical_error",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="system_critical_error",
                title="Сбой создания комнаты видеосвязи Daily.co",
                body="Daily.co API returned 503 Service Unavailable during room provisioning for lesson #2201.",
                meta={"service": "video-gateway", "recipient_role": "admin"},
            ),
        },
        {
            "group": "🛡️ АДМИНИСТРАТОРУ",
            "name": "Переполнение очереди задач Outbox",
            "kind": "operational_alert",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="operational_alert",
                title="Очередь Outbox превысила лимит",
                body="Количество неотправленных доставок в очереди notifications_high превысило 500 записей. Средняя задержка: 45с.",
                meta={"service": "outbox-dispatcher", "recipient_role": "admin"},
            ),
        },
        {
            "group": "🛡️ АДМИНИСТРАТОРУ",
            "name": "Ответ техподдержки по обращению",
            "kind": "bug_report_reply",
            "builder": lambda: (
                (
                    "💬 <b>Ответ от команды BooStudy</b>\n\n"
                    "📌 По репорту <b>#1042</b>:\n\n"
                    "Мы проверили воспроизведение аудио на интерактивной доске. Проблема решена, обновите страницу занятия."
                ),
                None,
            ),
        },
    ]

    # =========================================================================
    # 3. 👨‍🏫 ПРЕПОДАВАТЕЛЮ (Teacher) - 9 notifications
    # =========================================================================
    group_3 = [
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Назначение нового занятия в расписании",
            "kind": "lesson_scheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_scheduled",
                title="Новое занятие в расписании",
                meta={
                    "student_name": "Алексей Смирнов",
                    "subject": "Информатика: Задание 27 (Динамика)",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "teacher",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Перенос занятия на другое время",
            "kind": "lesson_rescheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_rescheduled",
                title="Урок перенесён",
                meta={
                    "student_name": "Алексей Смирнов",
                    "subject": "Информатика: Задание 27",
                    "start_time": "2026-11-06T16:30:00+00:00",
                    "old_start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "teacher",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Отмена занятия",
            "kind": "lesson_cancelled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_cancelled",
                title="Урок отменён",
                meta={
                    "student_name": "Алексей Смирнов",
                    "subject": "Информатика: Графы и деревья",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "reason": "По согласованию сторон (болезнь)",
                    "recipient_role": "teacher",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Напоминание о занятии за 15 минут",
            "kind": "lesson_reminder",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_reminder",
                title="Напоминание об уроке",
                meta={
                    "student_name": "Алексей Смирнов",
                    "subject": "Информатика: Разбор пробника ЕГЭ",
                    "minutes_left": 15,
                    "start_time": "2026-11-02T19:00:00+00:00",
                    "room_url": "http://127.0.0.1:5000/room/lesson-2201",
                    "recipient_role": "teacher",
                },
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Ученик сдал домашнюю работу",
            "kind": "teacher_homework_submitted",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="teacher_homework_submitted",
                title="Сдана домашняя работа",
                meta={
                    "student_name": "Алексей Смирнов",
                    "assignment_title": "ДЗ №4: Теория графов и алгоритм Дейкстры",
                    "submitted_at": "2026-11-02T18:20:00+00:00",
                    "submission_id": 2702,
                    "recipient_role": "teacher",
                },
                link_url="http://127.0.0.1:5000/submissions/2702/grade",
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Очередь проверки домашних заданий",
            "kind": "review_queue",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="review_queue",
                title="Очередь проверки",
                body="3 ученика ожидают проверки решений более 24 часов.",
                meta={"pending_count": 5, "recipient_role": "teacher"},
                link_url="http://127.0.0.1:5000/tutor/submissions",
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Старт урока и запрос ссылки на видеосозвон",
            "kind": "lesson_started_teacher_prompt",
            "builder": lambda: (
                (
                    "▶️ <b>Урок начался</b>\n\n"
                    "👤 Ученик: Алексей Смирнов\n"
                    "📚 Тема: Задание 26: Жадные алгоритмы\n"
                    "⏱ Длительность: 60 мин\n\n"
                    "Пришли ссылку на видеосозвон одним сообщением.\n"
                    "После этого я отправлю её ученику вместе с сообщением о начале урока."
                ),
                {"inline_keyboard": [[{"text": "📎 Отправить ссылку", "callback_data": "lesson_call_link:2201"}]]},
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Завершение урока и запрос домашнего задания",
            "kind": "lesson_finished_teacher_prompt",
            "builder": lambda: (
                (
                    "✅ <b>Урок завершен</b>\n\n"
                    "👤 Ученик: <b>Алексей Смирнов</b>\n"
                    "📚 Урок: <b>Задание 26: Жадные алгоритмы</b>\n"
                    "⏱ Длительность: <b>60 мин</b>\n\n"
                    "Напиши следующим сообщением, какое ДЗ нужно оставить ученику.\n"
                    "Потом я спрошу, когда напомнить об этом."
                ),
                {"inline_keyboard": [[{"text": "📝 Оставить ДЗ", "callback_data": "lesson_hw_note:2201"}]]},
            ),
        },
        {
            "group": "👨‍🏫 ПРЕПОДАВАТЕЛЮ",
            "name": "Напоминание о сохранённой заметке по ДЗ",
            "kind": "teacher_homework_note_reminder",
            "builder": lambda: (
                (
                    "⏰ <b>Напоминание по ДЗ после урока</b>\n\n"
                    "👤 Ученик: <b>Алексей Смирнов</b>\n"
                    "📚 Урок: <b>Задание 26: Жадные алгоритмы</b>\n\n"
                    "<b>Что нужно скинуть:</b>\n"
                    "<pre>Сборник Полякова № 120-135, обрати внимание на крайние случаи n=1</pre>\n"
                    "🕐 Урок: 02.11.2026 18:00"
                ),
                None,
            ),
        },
    ]

    # =========================================================================
    # 4. 🎓 УЧЕНИКУ (Student) - 16 notifications
    # =========================================================================
    group_4 = [
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Назначение нового урока в расписании",
            "kind": "lesson_scheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_scheduled",
                title="Новый урок в расписании",
                meta={
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика ЕГЭ: Задание 24 (Строки)",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Перенос урока на другое время",
            "kind": "lesson_rescheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_rescheduled",
                title="Урок перенесён",
                meta={
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика: Строковые алгоритмы",
                    "start_time": "2026-11-06T16:30:00+00:00",
                    "old_start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Отмена запланированного урока",
            "kind": "lesson_cancelled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_cancelled",
                title="Урок отменён",
                meta={
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика: Рекурсивные структуры",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "reason": "Технические работы на сервере видеосвязи",
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Напоминание об уроке за 15 минут",
            "kind": "lesson_reminder",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_reminder",
                title="Напоминание об уроке",
                meta={
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика: Разбор тренировочного варианта",
                    "minutes_left": 15,
                    "start_time": "2026-11-02T19:00:00+00:00",
                    "room_url": "http://127.0.0.1:5000/room/lesson-2201",
                    "recipient_role": "student",
                },
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Приглашение в классную комнату (старт урока)",
            "kind": "lesson_started_student",
            "builder": lambda: (
                (
                    "▶️ <b>Урок начался</b>\n\n"
                    "Информатика: Разбор тренировочного варианта\n\n"
                    "🔗 http://127.0.0.1:5000/lesson/2201/classwork-tasks"
                ),
                {"inline_keyboard": [[{"text": "🚪 В классную комнату", "url": "http://127.0.0.1:5000/lesson/2201/classwork-tasks"}]]},
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Назначение нового домашнего задания",
            "kind": "assignment_assigned",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="assignment_assigned",
                title="Новое домашнее задание",
                meta={
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм и подотрезки",
                    "deadline": "2026-11-08T20:59:00+00:00",
                    "assignment_id": 2726,
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Подтверждение успешной сдачи домашней работы",
            "kind": "homework_submitted",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_submitted",
                title="Домашняя работа успешно отправлена",
                meta={
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "assignment_id": 2726,
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Домашняя работа проверена преподавателем",
            "kind": "homework_checked",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_checked",
                title="Домашнее задание проверено",
                meta={
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "score": 10,
                    "max_score": 10,
                    "teacher_comment": "Отличная реализация алгоритма без лишней памяти, молодец!",
                    "assignment_id": 2726,
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Домашняя работа возвращена на доработку",
            "kind": "homework_returned",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_returned",
                title="Работа возвращена на доработку",
                meta={
                    "assignment_title": "ДЗ №4: Теория графов и Дейкстра",
                    "comment": "Тест 14 падает по лимиту времени O(N^2). Примени двоичную кучу или очередь с приоритетами.",
                    "assignment_id": 2727,
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/assignments/2727",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Приближение срока сдачи задания (дедлайн)",
            "kind": "assignment_deadline",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="assignment_deadline",
                title="Скоро истекает срок сдачи задания",
                meta={
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "deadline": "2026-11-03T18:00:00+00:00",
                    "recipient_role": "student",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Новая запись в электронном журнале оценок",
            "kind": "new_gradebook_entry",
            "builder": lambda: (
                (
                    "📒 <b>Новая запись в журнале</b>\n\n"
                    "Пробный экзамен КЕГЭ №2\n"
                    "Балл: 92 из 100\n\n"
                    "🔗 http://127.0.0.1:5000/student/29/gradebook"
                ),
                {"inline_keyboard": [[{"text": "📒 Журнал", "url": "http://127.0.0.1:5000/student/29/gradebook"}]]},
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Разблокировано новое достижение",
            "kind": "achievement",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="achievement",
                title="Новое достижение!",
                body="Решено 100 задач по программированию подряд без единой ошибки компиляции.",
                meta={"achievement_title": "Мастер компиляции", "recipient_role": "student"},
                link_url="http://127.0.0.1:5000/achievements",
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Ответ службы поддержки на баг-репорт",
            "kind": "bug_report_reply_student",
            "builder": lambda: (
                (
                    "💬 <b>Ответ от команды BooStudy</b>\n\n"
                    "📌 По репорту <b>#1</b>:\n\n"
                    "Баг с отображением формул LaTeX в мобильном браузере успешно исправлен. Спасибо за обратную связь!"
                ),
                None,
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Изменение баланса уроков",
            "kind": "lesson_balance_changed",
            "builder": lambda: (
                (
                    "📚 <b>Изменение количества уроков</b>\n\n"
                    "Было: <b>8</b>\n"
                    "Стало: <b>12</b>\n"
                    "Причина: Пополнение абонемента «Интенсив ЕГЭ 2026»"
                ),
                None,
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Предупреждение о низком остатке уроков",
            "kind": "low_lessons",
            "builder": lambda: (
                ("⚠️ <b>Внимание, на балансе осталось меньше трех уроков.</b>"),
                None,
            ),
        },
        {
            "group": "🎓 УЧЕНИКУ",
            "name": "Предупреждение об истечении срока подписки",
            "kind": "subscription_expiring",
            "builder": lambda: (
                (
                    "ℹ️ <b>Подписка истекает через 3 дн.</b>\n\n"
                    "Дата окончания: 05.11.2026\n\n"
                    "🔗 http://127.0.0.1:5000/billing"
                ),
                {"inline_keyboard": [[{"text": "💳 Продлить подписку", "url": "http://127.0.0.1:5000/billing"}]]},
            ),
        },
    ]

    # =========================================================================
    # 5. 👨‍👩‍👧 РОДИТЕЛЮ (Parent) - 11 notifications
    # =========================================================================
    group_5 = [
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Новый урок у ребёнка в расписании",
            "kind": "lesson_scheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_scheduled",
                title="Новый урок у ребёнка",
                meta={
                    "student_name": "Алексей",
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика ЕГЭ: Задание 24",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Урок ребёнка перенесён на другое время",
            "kind": "lesson_rescheduled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_rescheduled",
                title="Урок перенесён",
                meta={
                    "student_name": "Алексей",
                    "subject": "Информатика ЕГЭ",
                    "start_time": "2026-11-06T16:30:00+00:00",
                    "old_start_time": "2026-11-05T15:00:00+00:00",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Урок ребёнка отменён",
            "kind": "lesson_cancelled",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_cancelled",
                title="Урок отменён",
                meta={
                    "student_name": "Алексей",
                    "subject": "Информатика ЕГЭ",
                    "start_time": "2026-11-05T15:00:00+00:00",
                    "reason": "По согласованию сторон",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/schedule",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Напоминание о предстоящем уроке ребёнка",
            "kind": "lesson_reminder",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="lesson_reminder",
                title="Напоминание об уроке",
                meta={
                    "student_name": "Алексей",
                    "teacher_name": "Виктор Николаевич",
                    "subject": "Информатика: Подготовка к КЕГЭ",
                    "minutes_left": 15,
                    "start_time": "2026-11-02T19:00:00+00:00",
                    "room_url": "http://127.0.0.1:5000/room/lesson-2201",
                    "recipient_role": "parent",
                },
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Ребёнку назначено новое домашнее задание",
            "kind": "assignment_assigned",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="assignment_assigned",
                title="Новое задание у ребёнка",
                meta={
                    "student_name": "Алексей",
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "deadline": "2026-11-08T20:59:00+00:00",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Ребёнок отправил решение ДЗ на проверку",
            "kind": "homework_submitted",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_submitted",
                title="Ребёнок сдал домашнюю работу",
                meta={
                    "student_name": "Алексей",
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Преподаватель проверил домашнюю работу ребёнка",
            "kind": "homework_checked",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_checked",
                title="Проверена домашняя работа ребёнка",
                meta={
                    "student_name": "Алексей",
                    "assignment_title": "ДЗ №5: Оптимизация префиксных сумм",
                    "score": 10,
                    "max_score": 10,
                    "teacher_comment": "Алексей отлично справился со всеми тестами!",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/assignments/2726",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Работа ребёнка возвращена учителем на доработку",
            "kind": "homework_returned",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="homework_returned",
                title="Работа ребёнка возвращена на доработку",
                meta={
                    "student_name": "Алексей",
                    "assignment_title": "ДЗ №4: Теория графов",
                    "comment": "Нужно доработать решение с учетом ограничений памяти.",
                    "recipient_role": "parent",
                },
                link_url="http://127.0.0.1:5000/assignments/2727",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Запрос на привязку семейного аккаунта",
            "kind": "family_link_created",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="family_link_created",
                title="Запрос на семейную связь",
                body="Ученик Алексей (ID: 29) отправил запрос на привязку родительского аккаунта.",
                meta={"relative_name": "Алексей", "recipient_role": "parent"},
                link_url="http://127.0.0.1:5000/family",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Семейная связь успешно подтверждена",
            "kind": "family_link_confirmed",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="family_link_confirmed",
                title="Семейная связь подтверждена",
                body="Семейная связь с аккаунтом ученика Алексея успешно подтверждена.",
                meta={"relative_name": "Алексей", "recipient_role": "parent"},
                link_url="http://127.0.0.1:5000/family",
            ),
        },
        {
            "group": "👨‍👩‍👧 РОДИТЕЛЮ",
            "name": "Семейная связь отключена",
            "kind": "family_link_revoked",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="family_link_revoked",
                title="Семейная связь отключена",
                body="Семейная связь с аккаунтом ученика Алексея была отключена.",
                meta={"recipient_role": "parent"},
                link_url="http://127.0.0.1:5000/family",
            ),
        },
    ]

    # =========================================================================
    # 6. 🌐 ОБЩИЕ УВЕДОМЛЕНИЯ (General) - 3 notifications
    # =========================================================================
    group_6 = [
        {
            "group": "🌐 ОБЩИЕ УВЕДОМЛЕНИЯ",
            "name": "Утренний дайджест дня",
            "kind": "daily_digest",
            "builder": lambda: (
                (
                    "☀️ <b>Доброе утро! Твой план на сегодня:</b>\n\n"
                    "<b>📅 Уроки:</b>\n"
                    "  • 15:00 — Информатика: Задание 27\n"
                    "  • 18:00 — Разбор пробника ЕГЭ\n\n"
                    "📋 Незавершённых заданий: <b>2</b>\n\n"
                    "🔗 http://127.0.0.1:5000"
                ),
                None,
            ),
        },
        {
            "group": "🌐 ОБЩИЕ УВЕДОМЛЕНИЯ",
            "name": "Еженедельный дайджест успеваемости",
            "kind": "child_digest",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="child_digest",
                title="Дайджест успеваемости",
                body="За прошедшую неделю Алексей выполнил 4 домашних задания со средним баллом 9.5 из 10 и посетил 2 занятия.",
                meta={"recipient_role": "parent"},
                link_url="http://127.0.0.1:5000/parent/digest",
            ),
        },
        {
            "group": "🌐 ОБЩИЕ УВЕДОМЛЕНИЯ",
            "name": "Новость и обновление платформы",
            "kind": "news",
            "builder": lambda: render_telegram_notification(
                user_id=TARGET_USER_ID,
                kind="news",
                title="Обновление платформы: Новый тренажер ЕГЭ 2026",
                body="Мы добавили более 300 актуальных задач КЕГЭ по информатике с подробными видеоразборами от ведущих экспертов.",
                link_url="http://127.0.0.1:5000/news/kege-2026",
            ),
        },
    ]

    all_groups = [group_1, group_2, group_3, group_4, group_5, group_6]
    for grp in all_groups:
        for item in grp:
            item["test_id"] = test_id
            test_id += 1
            catalog.append(item)

    return catalog


def run_catalog_demonstration() -> dict[str, Any]:
    """Execute the full notification catalog broadcast to Creator."""
    print("=" * 70)
    print("🚀 BooStudy Telegram Next — Полный Каталог Уведомлений")
    print("=" * 70)
    print(f"[*] Целевой чат ID: {ALLOWED_CHAT_ID} (Создатель)")
    print(f"[*] Активный бот: @{TELEGRAM_BOT_USERNAME or 'BooStudy_local_bot'}")
    
    with app.app_context():
        catalog = build_catalog()
        print(f"[*] Подготовлено элементов каталога: {len(catalog)}")
        
        # Group summary
        group_counts: dict[str, int] = {}
        for item in catalog:
            grp = item["group"]
            group_counts[grp] = group_counts.get(grp, 0) + 1

        print("\nРаспределение по ролям:")
        for grp, cnt in group_counts.items():
            print(f"  • {grp}: {cnt} уведомлений")
        print("-" * 70)

        # Send introductory banner
        banner_text = (
            "🚀 <b>BooStudy Telegram Next — Каталог уведомлений</b>\n\n"
            "Здравствуй, Создатель! Ниже представлена полная демонстрация всех видов "
            "уведомлений платформы BooStudy, оформленных по стандарту Telegram Next.\n\n"
            f"📊 Всего шаблонов в каталоге: <b>{len(catalog)}</b>\n"
            "Каждое сообщение содержит реальную вёрстку, форматирование дат, "
            "эмодзи-акценты и интерактивные кнопки действия.\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        print("[*] Отправка вступительного баннера...")
        send_catalog_message(ALLOWED_CHAT_ID, banner_text)

        current_group = None
        delivered_count = 0
        failed_count = 0
        role_stats: dict[str, int] = {grp: 0 for grp in group_counts}

        for item in catalog:
            grp = item["group"]
            test_id = item["test_id"]
            name = item["name"]

            # Send group header if group changed
            if grp != current_group:
                current_group = grp
                group_banner = (
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{grp} (Всего: {group_counts[grp]})\n"
                    f"━━━━━━━━━━━━━━━━━━"
                )
                print(f"\n---> Раздел: {grp}")
                send_catalog_message(ALLOWED_CHAT_ID, group_banner)

            # Render template
            try:
                rendered_text, reply_markup = item["builder"]()
            except Exception as e:
                logger.error("Error building notification %s (%s): %s", test_id, name, e)
                failed_count += 1
                continue

            # Prefix header
            full_text = f"<b>ТЕСТ {test_id:02d} — Уведомление о [{name}]</b>\n\n{rendered_text}"

            print(f"  [{test_id:02d}/{len(catalog)}] Отправка: ТЕСТ {test_id:02d} — {name}...")
            ok = send_catalog_message(ALLOWED_CHAT_ID, full_text, reply_markup)
            if ok:
                delivered_count += 1
                role_stats[grp] += 1
            else:
                failed_count += 1

        # Send concluding banner
        summary_text = (
            "━━━━━━━━━━━━━━━━━━\n"
            "🏁 <b>Каталог уведомлений успешно отправлен!</b>\n\n"
            f"✅ Доставлено сообщений: <b>{delivered_count} / {len(catalog)}</b>\n"
            f"❌ Ошибок: <b>{failed_count}</b>\n\n"
            "Все кнопки и разметка доступны для визуального и интерактивного тестирования."
        )
        send_catalog_message(ALLOWED_CHAT_ID, summary_text)

        print("\n" + "=" * 70)
        print("🏁 ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА")
        print(f"Доставлено: {delivered_count} / {len(catalog)}")
        print(f"Ошибок: {failed_count}")
        for grp, cnt in role_stats.items():
            print(f"  • {grp}: {cnt} / {group_counts[grp]}")
        print("=" * 70)

        return {
            "total_catalog": len(catalog),
            "delivered": delivered_count,
            "failed": failed_count,
            "role_stats": role_stats,
            "group_counts": group_counts,
        }


if __name__ == "__main__":
    run_catalog_demonstration()
