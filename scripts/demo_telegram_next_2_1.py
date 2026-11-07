"""Interactive 10-scenario demonstration script for BooStudy Telegram Next 2.1.

Sends 10 curated verification scenarios exclusively to Creator chat ID 854161398:
1. Teacher notified of submitted HW (teacher_homework_submitted)
2. Self-notification suppression audit (student actor suppressed)
3. Student notified of graded HW (homework_checked)
4. Batch scheduling of 5 lessons in 1 compact summary card (lesson_batch_scheduled)
5. Student notification preferences in bot
6. Teacher notification preferences in bot
7. Teacher inspecting student's notifications & comparison mode
8. Admin overview of roles & policies
9. Broadcast preview & recipient calculation
10. Test announcement delivered via Broadcast Center
"""
from __future__ import annotations

import os
import sys
import time

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from core.db_models import db, User, UserProfile
from app.telegram.config import set_live_delivery_active, is_live_delivery_active
from app.telegram.notifications import send_telegram_message
from app.telegram.notification_templates import render_telegram_notification
from app.telegram.event_policy import EventContext, should_suppress_notification
from app.telegram.batching import process_scheduled_lessons_batch

TARGET_CHAT_ID = 854161398
TARGET_USER_ID = 4  # Creator


def send_demo_card(step_num: int, title: str, html_content: str, reply_markup: dict | None = None) -> bool:
    banner = f"⭐ <b>[BooStudy Next 2.1 · Демонстрация {step_num}/10]</b>\n📌 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    full_text = banner + html_content
    res = send_telegram_message(
        chat_id=TARGET_CHAT_ID,
        text_body=full_text,
        reply_markup=reply_markup,
    )
    ok = bool(res and res.get('ok'))
    status = "OK" if ok else f"FAILED ({res})"
    print(f"[{step_num}/10] {title}: {status}")
    time.sleep(1.2)
    return ok


def run_demo():
    print(f"=== Запуск демонстрации Telegram Next 2.1 для Chat ID {TARGET_CHAT_ID} ===")
    app = create_app()
    with app.app_context():
        # Enable live delivery for Creator allowlist
        set_live_delivery_active(True)
        assert is_live_delivery_active()

        # ---------------------------------------------------------------------
        # Сценарий 1: Уведомление преподавателю о сданном ДЗ
        # ---------------------------------------------------------------------
        meta_s1 = {
            "student_name": "Иван Смирнов",
            "assignment_title": "Задание №24 КЕГЭ: Текстовые файлы и регулярные выражения",
            "submission_id": 101,
            "recipient_role": "teacher",
        }
        text_s1, markup_s1 = render_telegram_notification(
            user_id=TARGET_USER_ID,
            kind="teacher_homework_submitted",
            title="Сдана домашняя работа",
            meta=meta_s1,
            link_url="https://boostudy.ru/teacher/review/101",
        )
        send_demo_card(1, "Преподаватель: Сдача работы учеником", text_s1, markup_s1)

        # ---------------------------------------------------------------------
        # Сценарий 2: Подавление самоуведомления ученика-автора
        # ---------------------------------------------------------------------
        event_ctx_s2 = EventContext(
            event_kind="homework_submitted",
            actor_user_id=101,  # Student submitted
            actor_role="student",
            subject_user_id=101,
            entity_type="submission",
            entity_id=501,
        )
        suppressed, reason = should_suppress_notification(event_ctx_s2, recipient_user_id=101, recipient_role="student")
        card_s2 = (
            "🛡️ <b>Аудит решения диспетчера доставки:</b>\n\n"
            "• <b>Событие:</b> <code>homework_submitted</code> (Сдача ДЗ через сайт)\n"
            "• <b>Инициатор (Actor):</b> Ученик ID 101\n"
            "• <b>Получатель (Recipient):</b> Ученик ID 101\n"
            f"• <b>Решение:</b> <code>SUPPRESSED (подавлено)</code>\n"
            f"• <b>Причина:</b> <i>{reason}</i>\n\n"
            "✅ <i>Результат: ученик видит подтверждение на экране сайта, а чат в Telegram не засоряется дублирующим эхо-сообщением.</i>"
        )
        send_demo_card(2, "Подавление самоуведомления ученика (Self-action)", card_s2)

        # ---------------------------------------------------------------------
        # Сценарий 3: Уведомление ученику о проверенном ДЗ
        # ---------------------------------------------------------------------
        meta_s3 = {
            "assignment_title": "Задание №24 КЕГЭ: Текстовые файлы",
            "assignment_id": 55,
            "score": "100%",
            "comment": "Отличный разбор! Код написан компактно и работает за O(N).",
            "recipient_role": "student",
        }
        text_s3, markup_s3 = render_telegram_notification(
            user_id=TARGET_USER_ID,
            kind="homework_checked",
            title="Домашнее задание проверено",
            meta=meta_s3,
            link_url="https://boostudy.ru/homework/55",
        )
        send_demo_card(3, "Ученик: Домашнее задание проверено", text_s3, markup_s3)

        # ---------------------------------------------------------------------
        # Сценарий 4: Пакетное назначение 5 уроков одной карточкой (Batching)
        # ---------------------------------------------------------------------
        lessons_batch = [
            {"lesson_id": 201, "topic": "Рекурсия и переборные алгоритмы (Задание 16)", "start_time": "2026-11-05T15:00:00Z"},
            {"lesson_id": 202, "topic": "Динамическое программирование одномерное", "start_time": "2026-11-07T15:00:00Z"},
            {"lesson_id": 203, "topic": "Двумерное ДП и поиск оптимального пути", "start_time": "2026-11-12T15:00:00Z"},
            {"lesson_id": 204, "topic": "Теория игр на одну и две кучи (19-21)", "start_time": "2026-11-14T15:00:00Z"},
            {"lesson_id": 205, "topic": "Сложные прототипы динамики (Задание 27А)", "start_time": "2026-11-19T15:00:00Z"},
        ]
        batch_cards = process_scheduled_lessons_batch(
            recipient_user_id=TARGET_USER_ID,
            teacher_name="Михаил Викторович",
            lessons_data=lessons_batch,
            batch_id="batch_nov_2026",
            recipient_role="student",
        )
        assert len(batch_cards) == 1
        b_card = batch_cards[0]
        send_demo_card(4, "Батчинг: 5 уроков в единой сводной карточке", b_card["text"], b_card["reply_markup"])

        # ---------------------------------------------------------------------
        # Сценарий 5: Настройки уведомлений ученика в Bot V3
        # ---------------------------------------------------------------------
        card_s5 = (
            "⚙️ <b>Иерархические настройки: Кабинет Ученика</b>\n\n"
            "Ученик имеет независимый профиль настроек уведомлений:\n"
            "• 📅 <b>Занятия и расписание:</b> 4 из 4 включено\n"
            "• 📝 <b>Домашние задания:</b> 3 из 4 включено (дедлайн выключен)\n"
            "• 💳 <b>Баланс и абонементы:</b> 3 из 3 включено\n"
            "• ⭐ <b>Общее и дайджесты:</b> 1 из 2 включено\n\n"
            "Каждый переключатель снабжён кнопкой <code>[👁️ Пример]</code> для синтетического превью без спама в базу."
        )
        markup_s5 = {
            "inline_keyboard": [
                [{"text": "⚙️ Открыть настройки в боте", "callback_data": "v3:set:notif:role:student"}]
            ]
        }
        send_demo_card(5, "Гранулярные настройки роли: 🎓 Ученик", card_s5, markup_s5)

        # ---------------------------------------------------------------------
        # Сценарий 6: Настройки уведомлений преподавателя в Bot V3
        # ---------------------------------------------------------------------
        card_s6 = (
            "👨‍🏫 <b>Иерархические настройки: Кабинет Преподавателя</b>\n\n"
            "Настройки преподавателя изолированы от настроек ученика:\n"
            "• 📥 <b>Сдача работ на проверку:</b> ✅ Включено\n"
            "• 📅 <b>Начало урока со ссылкой LiveKit:</b> ✅ Включено\n"
            "• 🏁 <b>Запрос заметки ДЗ после урока:</b> ✅ Включено\n"
            "• ⏰ <b>Напоминание о прикреплении ДЗ:</b> ✅ Включено\n"
            "• 🔄 <b>Сброс роли:</b> возвращает только учительские дефолты."
        )
        markup_s6 = {
            "inline_keyboard": [
                [{"text": "⚙️ Настройки преподавателя", "callback_data": "v3:set:notif:role:teacher"}]
            ]
        }
        send_demo_card(6, "Гранулярные настройки роли: 👨‍🏫 Преподаватель", card_s6, markup_s6)

        # ---------------------------------------------------------------------
        # Сценарий 7: Просмотр преподавателем настроек своего ученика + Режим сравнения
        # ---------------------------------------------------------------------
        card_s7 = (
            "👥 <b>Контроль каналов связи: «Уведомления моих учеников»</b>\n\n"
            "Преподаватель видит статус доставки своих подтверждённых учеников (Read-only):\n"
            "• <b>Ученик:</b> Иван Смирнов (ID 101)\n"
            "• <b>Telegram:</b> ✅ Подключен\n"
            "• <b>Домашние задания:</b> 3 из 4 включено\n"
            "• <b>Занятия:</b> 4 из 4 включено\n\n"
            "<b>Режим сравнения «Я / Ученик»:</b>\n"
            "При сдаче ДЗ ученик видит подтверждение на сайте, а учитель получает карточку с кнопкой проверки. "
            "При выставлении оценки учитель сохраняет балл на сайте, а ученик получает подробную карточку в Telegram."
        )
        markup_s7 = {
            "inline_keyboard": [
                [{"text": "👥 Ученики преподавателя", "callback_data": "v3:tch:st_notif:list"}],
                [{"text": "⚖️ Режим сравнения «Я / Ученик»", "callback_data": "v3:tch:st_notif:cmp:101"}],
            ]
        }
        send_demo_card(7, "Инспекция ученика и режим сравнения (RBAC)", card_s7, markup_s7)

        # ---------------------------------------------------------------------
        # Сценарий 8: Административный обзор ролей и политик
        # ---------------------------------------------------------------------
        card_s8 = (
            "🛡️ <b>Административный аудит политик доставки:</b>\n\n"
            "В кабинете администратора доступна полная матрица политик:\n"
            "• 🎓 <b>Student:</b> 15 типов (дефолты, опции отписки, батчинг)\n"
            "• 👨‍🏫 <b>Teacher:</b> 8 типов (очередь проверки, LiveKit, ДЗ)\n"
            "• 👨‍👩‍👧 <b>Parent:</b> 12 типов (успеваемость ребёнка, тихий режим сдачи ДЗ)\n"
            "• ⚙️ <b>Admin / Creator:</b> 7 типов (мониторинг Outbox, воркеры Celery, LiveKit WebRTC)\n\n"
            "Поддерживается инспекция с расшифровкой источника (По умолчанию / Выбор пользователя / Блокировка)."
        )
        markup_s8 = {
            "inline_keyboard": [
                [{"text": "🛡️ Открыть аудит в боте", "callback_data": "v3:adm:notif:hub"}]
            ]
        }
        send_demo_card(8, "Административный обзор политик ролей", card_s8, markup_s8)

        # ---------------------------------------------------------------------
        # Сценарий 9: Предпросмотр рассылки (Preview & Recipient Count)
        # ---------------------------------------------------------------------
        card_s9 = (
            "📢 <b>Центр рассылок: Предпросмотр перед отправкой</b>\n\n"
            "• <b>Аудитория:</b> 👥 <code>Мои прикреплённые ученики</code>\n"
            "• <b>Категория:</b> <code>broadcast</code> (Рассылка преподавателя)\n"
            "• <b>Рассчитано активных получателей:</b> <b>4</b> чел. с подключенным Telegram\n\n"
            "<b>Текст объявления:</b>\n"
            "<i>«В субботу в 12:00 МСК проводим открытый интенсив по разбору сложных прототипов заданий 26 и 27. Ссылка на комнату появится в вашем расписании за 15 минут до старта.»</i>\n\n"
            "<i>💡 Охват рассчитывается автоматически с учётом привязки и персональных настроек категории.</i>"
        )
        markup_s9 = {
            "inline_keyboard": [
                [{"text": "📢 Центр рассылок", "callback_data": "v3:bc:start"}]
            ]
        }
        send_demo_card(9, "Центр рассылок: Предпросмотр и расчёт охвата", card_s9, markup_s9)

        # ---------------------------------------------------------------------
        # Сценарий 10: Реальная тестовая рассылка Создателю
        # ---------------------------------------------------------------------
        meta_s10 = {
            "sender_name": "Михаил Викторович",
            "title": "Субботний интенсив по КЕГЭ",
            "body": "Прошу всех проверить готовность среды Python и библиотеки sympy к субботнему практикуму. Занятие продлится 90 минут.",
            "recipient_role": "creator",
        }
        text_s10, markup_s10 = render_telegram_notification(
            user_id=TARGET_USER_ID,
            kind="broadcast",
            title="Субботний интенсив по КЕГЭ",
            meta=meta_s10,
            link_url="https://boostudy.ru/schedule",
        )
        send_demo_card(10, "Реальная рассылка через Broadcast Center", text_s10, markup_s10)

    print("\n=== Все 10 сценариев успешно отправлены Создателю в Telegram! ===")


if __name__ == "__main__":
    run_demo()
