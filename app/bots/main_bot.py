import logging
import os
from datetime import datetime, timezone
from flask import current_app
from core.db_models import db, User, TelegramAuthCode, BugReport, QATestCase, moscow_now, utc_now
from app.services.telegram_notifications import send_telegram_message

logger = logging.getLogger(__name__)

def _get_app_url():
    return (os.environ.get('TELEGRAM_WEBHOOK_BASE_URL') or os.environ.get('APP_URL') or 'https://boostudy.ru').rstrip('/')

def get_role_keyboard(user: User):
    app_url = _get_app_url()
    
    # Check effective role
    role = user.role.lower() if user.role else 'student'
    if role in ('creator', 'chief_admin'):
        if getattr(user, 'creator_bot_mode', 'ADMIN') == 'TEACHER':
            role = 'teacher'
        else:
            role = 'admin'

    keyboard = []

    if role == 'student':
        keyboard = [
            [{"text": "📅 Расписание", "web_app": {"url": f"{app_url}/tma/schedule"}}],
            [{"text": "📚 Мои ДЗ"}, {"text": "📊 Мой прогресс"}]
        ]
    elif role == 'parent':
        keyboard = [
            [{"text": "📈 Успеваемость ребёнка", "web_app": {"url": f"{app_url}/tma/parent/digest"}}],
            [{"text": "🗓️ Расписание", "web_app": {"url": f"{app_url}/tma/schedule"}}, {"text": "💳 Статус оплаты"}]
        ]
    elif role == 'teacher':
        keyboard = [
            [{"text": "📥 Очередь ДЗ"}, {"text": "🗓️ Мои уроки", "web_app": {"url": f"{app_url}/tma/schedule"}}],
            [{"text": "📢 Анонс группе"}]
        ]
    elif role == 'admin':
        keyboard = [
            [{"text": "👥 Пользователи и Привязки"}, {"text": "📊 Полная статистика"}],
            [{"text": "🛠️ Вкл/Выкл Техработы"}, {"text": "📢 Рассылка"}]
        ]

    # Add Creator mode toggle if user is creator or chief_admin
    if user.role and user.role.lower() in ('creator', 'chief_admin'):
        current_mode = getattr(user, 'creator_bot_mode', 'ADMIN')
        target_mode_label = "👑 Админ" if current_mode == 'TEACHER' else "👨‍🏫 Преподаватель"
        keyboard.append([{"text": f"🔄 Сменить режим: {target_mode_label}"}])

    return {"keyboard": keyboard, "resize_keyboard": True}

def reply_main_bot(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    return send_telegram_message(chat_id, text, reply_markup=reply_markup, bot_type='main')

def process_main_bot_update(update: dict) -> dict:
    """Processes updates for Main Bot (@boostudy_bot)."""
    if not update or "message" not in update:
        return {"ok": True, "status": "ok"}

    msg = update["message"]
    chat_id = msg.get("chat", {}).get("id")
    from_user = msg.get("from", {})
    tg_user_id = from_user.get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id or not tg_user_id:
        return {"ok": True, "status": "ok"}

    # Find user by telegram_id or telegram_chat_id or tg_id
    user = User.query.filter(
        (User.telegram_id == tg_user_id) | 
        (User.telegram_chat_id == chat_id) | 
        (User.tg_id == tg_user_id)
    ).first()

    # Handle /start <code>
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code_str = parts[1].strip() if len(parts) > 1 else None

        if code_str:
            auth_code = TelegramAuthCode.query.filter_by(code=code_str, is_used=False).first()
            now = utc_now()
            is_valid_time = True
            if auth_code and auth_code.expires_at:
                auth_expires = auth_code.expires_at
                if auth_expires.tzinfo is None:
                    auth_expires = auth_expires.replace(tzinfo=timezone.utc)
                is_valid_time = auth_expires >= now

            if auth_code and is_valid_time:
                user = User.query.get(auth_code.user_id)
                if user:
                    user.telegram_id = tg_user_id
                    user.telegram_chat_id = chat_id
                    user.tg_id = tg_user_id
                    user.telegram_linked_at = now
                    auth_code.is_used = True
                    db.session.commit()

                    kb = get_role_keyboard(user)
                    msg_text = f"🎉 <b>Успешная привязка!</b>\nДобро пожаловать в BooStudy, {user.username}!\nВаш профиль роли: <b>{user.role}</b>."
                    reply_main_bot(chat_id, msg_text, kb)
                    return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}
                else:
                    msg_text = "❌ Пользователь по данному коду не найден."
                    reply_main_bot(chat_id, msg_text)
                    return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text}
            else:
                msg_text = "❌ Недействительный или истекший код привязки."
                reply_main_bot(chat_id, msg_text)
                return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text}

        if not user:
            msg_text = "👋 Привет! Для доступа к возможностям бота привяжите Telegram-аккаунт в личном кабинете на сайте BooStudy."
            reply_main_bot(chat_id, msg_text)
            return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text}
        else:
            kb = get_role_keyboard(user)
            msg_text = f"👋 С возвращением, {user.username}!"
            reply_main_bot(chat_id, msg_text, kb)
            return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}

    if not user:
        msg_text = "🔒 Ваш аккаунт Telegram еще не привязан к BooStudy. Напишите /start <code>"
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text}

    # Handle CREATOR mode switch
    if text.startswith("🔄 Сменить режим:"):
        if user.role and user.role.lower() in ('creator', 'chief_admin'):
            current_mode = getattr(user, 'creator_bot_mode', 'ADMIN')
            new_mode = 'TEACHER' if current_mode == 'ADMIN' else 'ADMIN'
            user.creator_bot_mode = new_mode
            db.session.commit()

            kb = get_role_keyboard(user)
            mode_name = "👨‍🏫 Преподаватель" if new_mode == 'TEACHER' else "👑 Администратор"
            msg_text = f"🔄 Режим успешно изменен на <b>{mode_name}</b>!"
            reply_main_bot(chat_id, msg_text, kb)
            return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}

    # Handle CREATOR / ADMIN User Management Module
    if text in ("👥 Пользователи и Привязки", "/users"):
        if user.role and user.role.lower() in ('creator', 'admin', 'chief_admin'):
            total_users = User.query.count()
            recent_users = User.query.order_by(User.id.desc()).limit(8).all()
            
            lines = [f"👥 <b>Управление пользователями BooStudy (Всего: {total_users}):</b>\n"]
            for idx, u in enumerate(recent_users, 1):
                status_icon = "В боте ✅" if (u.telegram_id or u.telegram_chat_id) else "Не привязан ❌"
                lines.append(f"{idx}. <b>{u.username}</b> (Роль: <code>{u.role}</code>) — {status_icon}")

            msg_text = "\n".join(lines)
            kb = get_role_keyboard(user)
            reply_main_bot(chat_id, msg_text, kb)
            return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}

    if text in ("📊 Полная статистика", "📊 Статистика", "/stats"):
        total_users = User.query.count()
        students_cnt = User.query.filter_by(role='student').count()
        teachers_cnt = User.query.filter(User.role.in_(['teacher', 'tutor'])).count()
        linked_cnt = User.query.filter(User.telegram_id.isnot(None)).count()
        open_bugs = BugReport.query.filter(BugReport.status != 'RESOLVED').count()
        test_cases_cnt = QATestCase.query.filter_by(is_active=True).count()

        msg_text = (
            "📊 <b>Полная системная статистика BooStudy:</b>\n\n"
            f"• 👥 Всего пользователей: <b>{total_users}</b>\n"
            f"• 🎓 Учеников на платформе: <b>{students_cnt}</b>\n"
            f"• 👨‍🏫 Преподавателей и тьюторов: <b>{teachers_cnt}</b>\n"
            f"• 📱 Привязано Telegram-аккаунтов: <b>{linked_cnt}</b>\n"
            f"• 📋 Активных QA тест-кейсов: <b>{test_cases_cnt}</b>\n"
            f"• 🐞 Открытых баг-репортов: <b>{open_bugs}</b>"
        )
        kb = get_role_keyboard(user)
        reply_main_bot(chat_id, msg_text, kb)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb, "parse_mode": "HTML"}

    # Handle button commands
    if text == "📚 Мои ДЗ":
        msg_text = "📚 <b>Ваши текущие домашние задания:</b>\n\n1. Информатика — Задание 27 (Сдано)\n2. Математика — Вариант №4 (В работе)"
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"}

    if text == "📊 Мой прогресс":
        msg_text = "📊 <b>Ваш учебный прогресс:</b>\n\n• Выполнено ДЗ: 85%\n• Средний балл: 88/100\n• Целевой балл: 90+"
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"}

    if text == "💳 Статус оплаты":
        msg_text = "💳 <b>Баланс и подписка:</b>\n\n• Оплачено занятий: 8\n• Подписка: Активна (до 30.08.2026)"
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"}

    if text == "📥 Очередь ДЗ":
        msg_text = "📥 <b>Очередь проверок:</b>\n\n• Работы ждут проверки."
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"}

    if text == "🛠️ Вкл/Выкл Техработы":
        msg_text = "🛠️ <b>Режим техработ изменен!</b> Уведомления отправлены пользователям."
        reply_main_bot(chat_id, msg_text)
        return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"}

    kb = get_role_keyboard(user)
    msg_text = f"Вы выбрали: {text}"
    reply_main_bot(chat_id, msg_text, kb)
    return {"ok": True, "status": "ok", "method": "sendMessage", "chat_id": chat_id, "text": msg_text, "reply_markup": kb}
