import logging
import os
import requests
from flask import current_app
from core.db_models import User, db, moscow_now

logger = logging.getLogger(__name__)

def _get_main_bot_token():
    return os.environ.get('MAIN_BOT_TOKEN') or os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN') or ''

def _get_qa_bot_token():
    return os.environ.get('QA_BOT_TOKEN') or '8933706317:AAFeN6fww_-EjVqM0okB8N1vrDaPM5dA7ws'

def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None, bot_type: str = 'main') -> bool:
    token = _get_qa_bot_token() if bot_type == 'qa' else _get_main_bot_token()
    if not token or not chat_id:
        logger.warning(f"send_telegram_message ({bot_type}): Missing token or chat_id (chat_id={chat_id})")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"send_telegram_message error: {e}")
        return False

def notify_upcoming_lesson(user_id: int, lesson_topic: str, lesson_time_str: str, room_url: str = None) -> bool:
    user = User.query.get(user_id)
    if not user or not user.telegram_chat_id:
        return False
    msg = (
        f"⏰ <b>Напоминание о занятии!</b>\n\n"
        f"📚 <b>Тема:</b> {lesson_topic}\n"
        f"🕒 <b>Время:</b> {lesson_time_str}\n"
    )
    reply_markup = None
    if room_url:
        reply_markup = {
            "inline_keyboard": [[{"text": "🚀 Войти в урок", "url": room_url}]]
        }
    return send_telegram_message(user.telegram_chat_id, msg, reply_markup)

def notify_homework_submitted(teacher_user_id: int, student_name: str, assignment_title: str) -> bool:
    teacher = User.query.get(teacher_user_id)
    if not teacher or not teacher.telegram_chat_id:
        return False
    msg = (
        f"📥 <b>Новое ДЗ на проверку!</b>\n\n"
        f"👤 <b>Ученик:</b> {student_name}\n"
        f"📝 <b>Задание:</b> {assignment_title}\n"
    )
    return send_telegram_message(teacher.telegram_chat_id, msg)

def notify_homework_graded(student_user_id: int, assignment_title: str, score_percent: float) -> bool:
    student = User.query.get(student_user_id)
    if not student or not student.telegram_chat_id:
        return False
    msg = (
        f"🎉 <b>ДЗ проверено!</b>\n\n"
        f"📝 <b>Задание:</b> {assignment_title}\n"
        f"📊 <b>Оценка:</b> {score_percent}%\n"
    )
    return send_telegram_message(student.telegram_chat_id, msg)

def notify_maintenance_toggle(is_maintenance_on: bool) -> int:
    status_str = "🛑 <b>Включен режим технического обслуживания.</b> Доступ к платформе ограничен." if is_maintenance_on else "✅ <b>Технические работы завершены.</b> Платформа снова доступна!"
    users = User.query.filter(User.telegram_chat_id.isnot(None)).all()
    count = 0
    for u in users:
        if send_telegram_message(u.telegram_chat_id, status_str):
            count += 1
    return count

def notify_qa_status_change(user_id: int, report_title: str, old_status: str, new_status: str) -> bool:
    user = User.query.get(user_id)
    chat_id = user.telegram_chat_id or getattr(user, 'telegram_id', None) if user else None
    if not chat_id:
        return False
    status_map = {'pending': '🔴 Ожидает проверки', 'in_progress': '🟡 В работе', 'retest': '🔄 Отправлен на ретест', 'resolved': '🟢 Исправлен', 'rejected': '🚫 Отклонен'}
    old_ru = status_map.get(old_status, old_status)
    new_ru = status_map.get(new_status, new_status)
    msg = (
        f"🔔 <b>Изменение статуса баг-репорта!</b>\n\n"
        f"📌 <b>Репорт:</b> {report_title}\n"
        f"📊 <b>Старый статус:</b> {old_ru}\n"
        f"➡️ <b>Новый статус:</b> {new_ru}\n"
    )
    return send_telegram_message(chat_id, msg, bot_type='qa')

def notify_qa_test_assigned(user_id: int, test_title: str, category: str, action: str = 'assigned') -> bool:
    user = User.query.get(user_id)
    chat_id = user.telegram_chat_id or getattr(user, 'telegram_id', None) if user else None
    if not chat_id:
        return False
    actions_map = {'assigned': '📋 Вам назначен новый тест-кейс!', 'updated': '✏️ Обновлен тест-кейс!', 'deleted': '🗑️ Удален тест-кейс'}
    msg = (
        f"{actions_map.get(action, '📋 Обновление тест-кейса')}\n\n"
        f"📂 <b>Категория:</b> {category}\n"
        f"📌 <b>Название:</b> {test_title}\n"
    )
    return send_telegram_message(chat_id, msg, bot_type='qa')
