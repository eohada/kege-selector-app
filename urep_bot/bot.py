"""
Основной файл бота - обработчики команд и callback-запросов.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import html
import json
import urllib.request
import urllib.error

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import text

from urep_bot.config import BOT_TOKEN, APP_URL, APP_OPEN_URL, BOT_INTERNAL_TOKEN
from urep_bot.db import get_session, close_session

logger = logging.getLogger(__name__)



WELCOME_MESSAGE = """
👋 <b>Привет! Я бот платформы URep.</b>

Я буду присылать тебе уведомления:
• 📅 Напоминания об уроках
• ✅ Проверка домашних заданий
• 💬 Сообщения от преподавателя
• ⚠️ Когда уроки заканчиваются
• 📢 Новости платформы

🔗 <b>Чтобы начать:</b>
1. Зайди в личный кабинет на сайте
2. Открой свой профиль  
3. Нажми "Привязать Telegram"
4. Скопируй команду с кодом и отправь мне

Или введи: /link КОД
"""

HELP_MESSAGE = """
📚 <b>Команды бота:</b>

/start — Начало работы
/me — Мой профиль и подписка
/lessons — Мои уроки (ближайшие + история)
/stats — Подробная статистика
/settings — Настройки уведомлений
/error — Сообщить об ошибке
/help — Эта справка

/link КОД — Привязать аккаунт
/unlink — Отвязать аккаунт

💡 Также можно использовать кнопки меню внизу.
"""

LINK_SUCCESS = """
✅ <b>Аккаунт успешно привязан!</b>

Теперь ты будешь получать уведомления:
• Напоминания об уроках (за 1 час и 15 минут)
• Результаты проверки ДЗ
• Сообщения от преподавателя
• Предупреждения о заканчивающихся уроках
• Новости платформы

⚙️ Настроить уведомления: /settings
"""

PROFILE_NOT_LINKED = """
❌ <b>Telegram не привязан к аккаунту</b>

Чтобы привязать:
1. Зайди в профиль на сайте
2. Нажми "Привязать Telegram"
3. Отправь мне команду /link КОД
"""


def _profile_not_linked_with_chat_id(chat_id) -> str:
    """Текст «не привязан» с подсказкой по chat_id для диагностики."""
    return (
        PROFILE_NOT_LINKED
        + f"\n\n🔢 <b>Твой chat_id:</b> <code>{chat_id}</code>\n"
        "Если ты уже привязывал аккаунт на сайте — получи новый код в профиле и отправь /link КОД."
    )

NO_LESSONS = "📅 Уроков пока нет. Как только урок будет запланирован — я сообщу!"

ERROR_MESSAGE = "❌ Произошла ошибка. Попробуй ещё раз или обратись к преподавателю."
ERROR_REPORT_PROMPT = (
    "🛠 <b>Сообщение об ошибке</b>\n\n"
    "Опиши проблему одним сообщением:\n"
    "• где именно возникла ошибка\n"
    "• что ты делал(а) перед этим\n"
    "• какой результат ожидал(а)\n"
)
ERROR_REPORT_RECEIVED = "✅ Сообщение об ошибке отправлено. Спасибо! Мы разберёмся и ответим."



def get_main_keyboard(user_role: str = None):
    """Главное меню."""
    buttons = [
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("📅 Уроки", callback_data="lessons"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("🛠 Сообщение об ошибке", callback_data="error_report"),
        ],
        [
            InlineKeyboardButton("🌐 Открыть сайт", url=APP_OPEN_URL),
        ],
    ]
    
    if user_role in ('admin', 'creator', 'chief_admin', 'tutor'):
        buttons.insert(2, [InlineKeyboardButton("👨‍💼 Админ-панель", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(buttons)


def get_admin_keyboard(user_role: str):
    """Меню администратора."""
    buttons = [
        [
            InlineKeyboardButton("👥 Поиск ученика", callback_data="admin_search_student"),
            InlineKeyboardButton("🎫 Реферальные коды", callback_data="admin_referrals"),
        ],
        [
            InlineKeyboardButton("🐞 Ошибки", callback_data="admin_errors"),
            InlineKeyboardButton("📊 Общая статистика", callback_data="admin_stats"),
        ],
    ]
    
    if user_role in ('creator', 'chief_admin'):
        buttons.append([InlineKeyboardButton("➕ Создать ученика", callback_data="admin_create_student")])
        
    buttons.append([InlineKeyboardButton("« Главное меню", callback_data="main")])
    return InlineKeyboardMarkup(buttons)


def get_back_keyboard():
    """Кнопка назад."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« Главное меню", callback_data="main")],
    ])


def get_lessons_keyboard():
    """Меню уроков."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Ближайшие", callback_data="lessons_upcoming"),
            InlineKeyboardButton("📜 История", callback_data="lessons_history"),
        ],
        [InlineKeyboardButton("« Главное меню", callback_data="main")],
    ])


def get_settings_keyboard(settings: dict):
    """Меню настроек."""
    def toggle(key, label):
        status = "✅" if settings.get(key, True) else "❌"
        return InlineKeyboardButton(f"{status} {label}", callback_data=f"toggle_{key}")
    
    return InlineKeyboardMarkup([
        [toggle("tg_notify_lesson_reminder", "Напоминания об уроках")],
        [toggle("tg_notify_lesson_scheduled", "Новый урок запланирован")],
        [toggle("tg_notify_homework_checked", "ДЗ проверено")],
        [toggle("tg_notify_homework_returned", "ДЗ на доработку")],
        [toggle("tg_notify_new_message", "Сообщения преподавателя")],
        [toggle("tg_notify_low_lessons", "Уроки заканчиваются")],
        [toggle("tg_notify_news", "Новости платформы")],
        [toggle("tg_notify_referral_used", "Уведомления о рефералах")],
        [toggle("tg_notify_homework_submitted", "Сдача ДЗ учениками")],
        [toggle("tg_notify_system_errors", "Системные ошибки")],
        [InlineKeyboardButton("🔌 Отвязать Telegram", callback_data="unlink")],
        [InlineKeyboardButton("« Главное меню", callback_data="main")],
    ])


def get_unlink_confirm_keyboard():
    """Кнопки подтверждения отвязки Telegram."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отвязать", callback_data="unlink_confirm"),
            InlineKeyboardButton("↩️ Отмена", callback_data="settings"),
        ],
    ])



def esc(text) -> str:
    """Экранирование HTML."""
    if not text:
        return ""
    return html.escape(str(text))


def get_bot_admin_chat_ids(session) -> list[int]:
    """Получить список chat_id администраторов бота."""
    try:
        result = session.execute(text("""
            SELECT up.telegram_chat_id
            FROM "BotAdmins" ba
            JOIN "UserProfiles" up ON up.user_id = ba.user_id
            WHERE ba.is_active = TRUE
              AND up.telegram_chat_id IS NOT NULL
        """))
        return [row[0] for row in result.fetchall() if row and row[0]]
    except Exception:
        return []


NOTIFY_LABELS = {
    "tg_notify_lesson_reminder": "напоминания об уроках",
    "tg_notify_lesson_scheduled": "новый урок",
    "tg_notify_homework_checked": "ДЗ проверено",
    "tg_notify_homework_returned": "ДЗ на доработку",
    "tg_notify_new_message": "сообщения преподавателя",
    "tg_notify_low_lessons": "уроки заканчиваются",
    "tg_notify_news": "новости платформы",
    "tg_notify_referral_used": "рефералы",
    "tg_notify_homework_submitted": "сдача ДЗ",
    "tg_notify_system_errors": "системные ошибки",
}


def get_bot_connected_users(session) -> list[dict]:
    """Список пользователей, подключённых к боту: логин, numeric_id, включённые уведомления."""
    try:
        result = session.execute(text("""
            SELECT u.username, u.numeric_id,
                   COALESCE(up.telegram_notifications_enabled, TRUE),
                   COALESCE(up.tg_notify_lesson_reminder, TRUE),
                   COALESCE(up.tg_notify_lesson_scheduled, TRUE),
                   COALESCE(up.tg_notify_homework_checked, TRUE),
                   COALESCE(up.tg_notify_homework_returned, TRUE),
                   COALESCE(up.tg_notify_new_message, TRUE),
                   COALESCE(up.tg_notify_low_lessons, TRUE),
                   COALESCE(up.tg_notify_news, TRUE),
                   COALESCE(up.tg_notify_referral_used, TRUE),
                   COALESCE(up.tg_notify_homework_submitted, TRUE),
                   COALESCE(up.tg_notify_system_errors, TRUE)
            FROM "Users" u
            JOIN "UserProfiles" up ON up.user_id = u.id
            WHERE up.telegram_chat_id IS NOT NULL
            ORDER BY u.username ASC
        """))
        rows = result.fetchall()
    except Exception as e:
        logger.warning(f"get_bot_connected_users: {e}", exc_info=True)
        return []

    keys = [
        "tg_notify_lesson_reminder", "tg_notify_lesson_scheduled", "tg_notify_homework_checked",
        "tg_notify_homework_returned", "tg_notify_new_message", "tg_notify_low_lessons", "tg_notify_news",
        "tg_notify_referral_used", "tg_notify_homework_submitted", "tg_notify_system_errors",
    ]
    out = []
    for row in rows:
        username = (row[0] or "").strip() or "—"
        numeric_id = row[1] if row[1] is not None else "—"
        notifications_enabled = row[2]
        enabled_list = []
        if notifications_enabled:
            for i, key in enumerate(keys):
                if row[3 + i]:
                    enabled_list.append(NOTIFY_LABELS.get(key, key))
        out.append({
            "username": username,
            "numeric_id": numeric_id,
            "notifications_enabled": notifications_enabled,
            "enabled_list": enabled_list,
        })
    return out


def format_connected_users_message(users: list[dict]) -> str:
    """Форматирует список подключённых пользователей в сообщение (логин — #ID — уведомления)."""
    if not users:
        return "👥 <b>Пользователи, подключённые к боту</b>\n\nНет подключённых пользователей."
    lines = ["👥 <b>Пользователи, подключённые к боту</b>\n"]
    for u in users:
        login = esc(u["username"])
        num_id = u["numeric_id"] if u["numeric_id"] == "—" else f"#{u['numeric_id']}"
        if u["notifications_enabled"] and u["enabled_list"]:
            notif = ", ".join(u["enabled_list"])
        elif u["notifications_enabled"]:
            notif = "все по умолчанию"
        else:
            notif = "выкл"
        lines.append(f"• <b>{login}</b> — {num_id} — {esc(notif)}")
    return "\n".join(lines)


async def start_error_report_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, *, from_callback: bool = False):
    """Запускает сценарий отправки ошибки."""
    context.user_data["awaiting_error_report"] = True
    if from_callback and update.callback_query:
        await update.callback_query.edit_message_text(
            ERROR_REPORT_PROMPT,
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )
    else:
        await update.message.reply_text(
            ERROR_REPORT_PROMPT,
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )


def get_user_by_chat_id(session, chat_id) -> Optional[dict]:
    """Получить пользователя по chat_id Telegram. chat_id приводится к int."""
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return None
    result = session.execute(text("""
        SELECT u.id, u.username, u.email, u.role, up.first_name, up.last_name,
               up.telegram_notifications_enabled
        FROM "Users" u
        JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE up.telegram_chat_id = :chat_id
    """), {"chat_id": chat_id})
    row = result.fetchone()
    if not row:
        logger.info("get_user_by_chat_id: no user for chat_id=%s (check DB UserProfiles.telegram_chat_id)", chat_id)
        return None

    user_id = row[0]
    base_role = (row[3] or "").strip().lower() if row[3] else None

    # Загружаем дополнительные роли пользователя из UserRoles и вычисляем «сильнейшую» роль,
    # чтобы поведение совпадало с бекендом (см. ROLE_STRENGTH_ORDER в core/db_models.py).
    extra_roles: list[str] = []
    try:
        roles_result = session.execute(text("""
            SELECT role
            FROM "UserRoles"
            WHERE user_id = :user_id
        """), {"user_id": user_id})
        extra_roles = [(r[0] or "").strip().lower() for r in roles_result.fetchall() if r and r[0]]
    except Exception as e:
        logger.warning("get_user_by_chat_id: failed to load extra roles for user_id=%s: %s", user_id, e)

    all_roles = set()
    if base_role:
        all_roles.add(base_role)
    for r in extra_roles:
        if r:
            all_roles.add(r)

    ROLE_STRENGTH_ORDER = (
        "creator",
        "chief_admin",
        "admin",
        "chief_tester",
        "content_maker",
        "tutor",
        "designer",
        "tester",
        "student",
        "parent",
    )

    effective_role = None
    for slug in ROLE_STRENGTH_ORDER:
        if slug in all_roles:
            effective_role = slug
            break
    if not effective_role:
        if base_role:
            effective_role = base_role
        elif extra_roles:
            effective_role = extra_roles[0]

    # Админ бота (BotAdmins) получает полный доступ, даже если роль в User/UserRoles не совпадает
    if effective_role not in ("creator", "chief_admin", "admin", "tutor"):
        try:
            admin_ids = get_bot_admin_chat_ids(session)
            if chat_id in admin_ids:
                effective_role = "chief_admin"
        except Exception:
            pass

    user = {
        "id": user_id,
        "username": row[1],
        "email": row[2],
        "role": effective_role,
        "first_name": row[4],
        "last_name": row[5],
        "notifications_enabled": row[6] if row[6] is not None else True,
        "tg_notify_lesson_reminder": True,
        "tg_notify_homework_checked": True,
        "tg_notify_homework_returned": True,
        "tg_notify_new_message": True,
        "tg_notify_lesson_scheduled": True,
        "tg_notify_low_lessons": True,
        "tg_notify_news": True,
        "tg_notify_referral_used": True,
        "tg_notify_homework_submitted": True,
        "tg_notify_system_errors": True,
    }
    
    try:
        settings_result = session.execute(text("""
            SELECT 
                COALESCE(tg_notify_lesson_reminder, TRUE),
                COALESCE(tg_notify_homework_checked, TRUE),
                COALESCE(tg_notify_homework_returned, TRUE),
                COALESCE(tg_notify_new_message, TRUE),
                COALESCE(tg_notify_lesson_scheduled, TRUE),
                COALESCE(tg_notify_low_lessons, TRUE),
                COALESCE(tg_notify_news, TRUE),
                COALESCE(tg_notify_referral_used, TRUE),
                COALESCE(tg_notify_homework_submitted, TRUE),
                COALESCE(tg_notify_system_errors, TRUE)
            FROM "UserProfiles"
            WHERE telegram_chat_id = :chat_id
        """), {"chat_id": chat_id})
        settings = settings_result.fetchone()
        if settings:
            user["tg_notify_lesson_reminder"] = settings[0]
            user["tg_notify_homework_checked"] = settings[1]
            user["tg_notify_homework_returned"] = settings[2]
            user["tg_notify_new_message"] = settings[3]
            user["tg_notify_lesson_scheduled"] = settings[4]
            user["tg_notify_low_lessons"] = settings[5]
            user["tg_notify_news"] = settings[6]
            user["tg_notify_referral_used"] = settings[7]
            user["tg_notify_homework_submitted"] = settings[8]
            user["tg_notify_system_errors"] = settings[9]
    except Exception:
        pass
    
    return user


def get_student_by_email(session, email: Optional[str], user_id: Optional[int] = None) -> Optional[dict]:
    """Получить студента по user_id (приоритет) или email."""
    row = None
    if user_id:
        result = session.execute(text("""
            SELECT s.student_id, s.name, s.target_score, s.school_class, 
                   s.category, s.programming_language, s.goal_text,
                   s.diagnostic_level, s.strengths, s.weaknesses
            FROM "Students" s
            WHERE s.user_id = :user_id AND s.is_active = TRUE
            LIMIT 1
        """), {"user_id": user_id})
        row = result.fetchone()
    if not row and email:
        result = session.execute(text("""
            SELECT s.student_id, s.name, s.target_score, s.school_class, 
                   s.category, s.programming_language, s.goal_text,
                   s.diagnostic_level, s.strengths, s.weaknesses
            FROM "Students" s
            WHERE LOWER(s.email) = LOWER(:email) AND s.is_active = TRUE
            LIMIT 1
        """), {"email": email})
        row = result.fetchone()
    if row:
        return {
            "student_id": row[0],
            "name": row[1],
            "target_score": row[2],
            "school_class": row[3],
            "category": row[4],
            "programming_language": row[5],
            "goal_text": row[6],
            "diagnostic_level": row[7],
            "strengths": row[8],
            "weaknesses": row[9],
        }
    return None


def get_subscription_info(session, user_id: int) -> Optional[dict]:
    """Получить информацию о подписке."""
    result = session.execute(text("""
        SELECT us.lessons_remaining, us.ends_at, us.status, us.started_at,
               tp.title, tp.lessons_count
        FROM "UserSubscriptions" us
        LEFT JOIN "TariffPlans" tp ON tp.plan_id = us.plan_id
        WHERE us.user_id = :user_id AND us.status = 'active'
        ORDER BY us.ends_at DESC NULLS LAST
        LIMIT 1
    """), {"user_id": user_id})
    row = result.fetchone()
    if row:
        return {
            "lessons_remaining": row[0],
            "ends_at": row[1],
            "status": row[2],
            "started_at": row[3],
            "plan_title": row[4],
            "lessons_total": row[5],
        }
    return None


def get_lessons(session, student_id: int, upcoming: bool = True, limit: int = 10) -> list:
    """Получить уроки."""
    if upcoming:
        query = """
            SELECT l.lesson_id, l.lesson_date, l.topic, l.status, l.duration, 
                   l.lesson_type, l.homework_status
            FROM "Lessons" l
            WHERE l.student_id = :student_id
              AND l.lesson_date >= NOW() - INTERVAL '2 hours'
              AND l.status IN ('planned', 'in_progress')
            ORDER BY l.lesson_date ASC
            LIMIT :limit
        """
    else:
        query = """
            SELECT l.lesson_id, l.lesson_date, l.topic, l.status, l.duration,
                   l.lesson_type, l.homework_status
            FROM "Lessons" l
            WHERE l.student_id = :student_id
              AND l.status = 'completed'
            ORDER BY l.lesson_date DESC
            LIMIT :limit
        """
    
    result = session.execute(text(query), {"student_id": student_id, "limit": limit})
    lessons = []
    for row in result.fetchall():
        lessons.append({
            "lesson_id": row[0],
            "date": row[1],
            "topic": row[2],
            "status": row[3],
            "duration": row[4],
            "type": row[5],
            "homework_status": row[6],
        })
    return lessons


def get_detailed_stats(session, student_id: int) -> dict:
    """Получить подробную статистику."""
    lessons_result = session.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'completed') as completed,
            COUNT(*) FILTER (WHERE status = 'planned') as planned,
            COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
            SUM(duration) FILTER (WHERE status = 'completed') as total_hours
        FROM "Lessons"
        WHERE student_id = :student_id
    """), {"student_id": student_id})
    lr = lessons_result.fetchone()
    
    hw_result = session.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE lt.status = 'graded') as checked,
            COUNT(*) FILTER (WHERE lt.status = 'submitted') as pending,
            COUNT(*) FILTER (WHERE lt.status = 'returned') as returned,
            COUNT(*) FILTER (WHERE lt.submission_correct = TRUE) as correct
        FROM "LessonTasks" lt
        JOIN "Lessons" l ON l.lesson_id = lt.lesson_id
        WHERE l.student_id = :student_id AND lt.assignment_type = 'homework'
    """), {"student_id": student_id})
    hr = hw_result.fetchone()
    
    last_lesson = session.execute(text("""
        SELECT lesson_date, topic FROM "Lessons"
        WHERE student_id = :student_id AND status = 'completed'
        ORDER BY lesson_date DESC LIMIT 1
    """), {"student_id": student_id}).fetchone()
    
    next_lesson = session.execute(text("""
        SELECT lesson_date, topic FROM "Lessons"
        WHERE student_id = :student_id AND status = 'planned' AND lesson_date >= NOW()
        ORDER BY lesson_date ASC LIMIT 1
    """), {"student_id": student_id}).fetchone()
    
    return {
        "lessons_total": lr[0] if lr else 0,
        "lessons_completed": lr[1] if lr else 0,
        "lessons_planned": lr[2] if lr else 0,
        "lessons_cancelled": lr[3] if lr else 0,
        "total_minutes": lr[4] if lr and lr[4] else 0,
        "hw_total": hr[0] if hr else 0,
        "hw_checked": hr[1] if hr else 0,
        "hw_pending": hr[2] if hr else 0,
        "hw_returned": hr[3] if hr else 0,
        "hw_correct": hr[4] if hr else 0,
        "last_lesson_date": last_lesson[0] if last_lesson else None,
        "last_lesson_topic": last_lesson[1] if last_lesson else None,
        "next_lesson_date": next_lesson[0] if next_lesson else None,
        "next_lesson_topic": next_lesson[1] if next_lesson else None,
    }


def format_lesson_type(t: str) -> str:
    """Тип урока."""
    types = {
        'regular': 'Обычный',
        'introductory': 'Вводный',
        'diagnostic': 'Диагностика',
        'exam': 'Проверочная',
        'consultation': 'Консультация',
    }
    return types.get(t, t or 'Урок')


def format_hw_status(s: str) -> str:
    """Статус ДЗ."""
    statuses = {
        'not_assigned': '—',
        'assigned': '📝',
        'submitted': '📤',
        'checked': '✅',
        'returned': '↩️',
    }
    return statuses.get(s, '')



def _call_link_api(url: str, code: str, chat_id: int, telegram_id: Optional[str]):
    """Вызов API привязки по указанному URL."""
    payload = {
        "code": code,
        "chat_id": chat_id,
        "telegram_id": telegram_id,
    }
    request_data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if BOT_INTERNAL_TOKEN:
        request_headers["X-Bot-Token"] = BOT_INTERNAL_TOKEN

    req = urllib.request.Request(
        url,
        data=request_data,
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body) if body else {}
            return {"status": resp.status, "data": data}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        return {"status": e.code, "data": data}
    except Exception as e:
        logger.warning(f"Link via app API failed: {e}", exc_info=True)
        return None


def _link_via_app_api(code: str, chat_id: int, telegram_id: Optional[str]):
    """Привязка через API приложения (с fallback на основной домен)."""
    if not APP_URL:
        return None

    base_urls = []
    for base in (APP_URL, "https://boostudy.ru/"):
        if base and base not in base_urls:
            base_urls.append(base)

    last_result = None
    for base in base_urls:
        url = f"{base.rstrip('/')}/api/telegram/link-bot"
        result = _call_link_api(url, code, chat_id, telegram_id)
        if not result:
            continue

        status = result.get("status")
        data = result.get("data") or {}
        error = data.get("error")

        if status == 200 and data.get("success"):
            return result

        if error != "invalid_code":
            return result

        last_result = result

    return last_result


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    chat_id = update.effective_chat.id
    session = get_session()
    user_role = None
    try:
        user = get_user_by_chat_id(session, chat_id)
        if user:
            user_role = user.get('role')
    finally:
        close_session(session)

    if user_role is None:
        text = (
            WELCOME_MESSAGE
            + f"\n\n🔢 <b>Твой chat_id:</b> <code>{chat_id}</code>\n"
            "Если уже привязывал аккаунт на сайте — получи новый код в профиле и отправь /link КОД."
        )
    else:
        text = WELCOME_MESSAGE
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=get_main_keyboard(user_role)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    chat_id = update.effective_chat.id
    session = get_session()
    user_role = None
    try:
        user = get_user_by_chat_id(session, chat_id)
        if user:
            user_role = user.get('role')
    finally:
        close_session(session)

    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_main_keyboard(user_role)
    )


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /link КОД."""
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Использование:</b> /link КОД\n\nПолучи код в настройках профиля на сайте.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return
    
    code = context.args[0].upper().strip()
    chat_id = update.effective_chat.id
    tg_username = (update.effective_user.username or '').strip()
    tg_identifier = f"@{tg_username}" if tg_username else None
    
    api_result = _link_via_app_api(code, chat_id, tg_identifier)
    if api_result:
        status = api_result.get("status")
        data = api_result.get("data") or {}
        error = data.get("error")

        if status == 200 and data.get("success"):
            # Сразу перезапросить пользователя и показать меню с учётом роли (на случай кэша/реплики)
            role = None
            reply_markup = get_main_keyboard()
            session = get_session()
            try:
                user = get_user_by_chat_id(session, chat_id)
                role = user.get("role") if user else None
                reply_markup = get_main_keyboard(role)
            finally:
                close_session(session)
            await update.message.reply_text(
                LINK_SUCCESS + "\n\n💡 Если меню внизу не обновилось — отправь /start.",
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            logger.info("User linked via API chat_id=%s role=%s", chat_id, role)
            return

        if error == "already_linked":
            await update.message.reply_text(
                "ℹ️ Этот Telegram уже привязан к аккаунту.\n\nИспользуй /unlink для отвязки.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return

        if error == "expired_code":
            await update.message.reply_text(
                "⏰ Код истёк (действует 15 минут). Получи новый код в личном кабинете на сайте.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return

        # invalid_code от API — не выходим: пробуем привязать через БД (та же БД у бота и сайта)
        if error == "invalid_code":
            logger.info("Link API returned invalid_code for code=%s, trying DB fallback", code[:3] + "***")
        elif status and 400 <= status < 500:
            await update.message.reply_text(
                ERROR_MESSAGE,
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return

        if status and status >= 500:
            logger.warning(f"Link API returned {status} for chat_id={chat_id}, trying DB fallback")

    session = get_session()
    try:
        cid = int(chat_id)
        existing = session.execute(text(
            'SELECT user_id FROM "UserProfiles" WHERE telegram_chat_id = :chat_id'
        ), {"chat_id": cid}).fetchone()
        
        if existing:
            await update.message.reply_text(
                "ℹ️ Этот Telegram уже привязан к аккаунту.\n\nИспользуй /unlink для отвязки.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        result = session.execute(text("""
            SELECT up.profile_id, up.user_id, up.telegram_link_code_expires, u.username
            FROM "UserProfiles" up
            JOIN "Users" u ON u.id = up.user_id
            WHERE UPPER(TRIM(COALESCE(up.telegram_link_code, ''))) = :code
        """), {"code": code})
        row = result.fetchone()
        
        if not row:
            await update.message.reply_text(
                "❌ Неверный код. Проверь правильность или получи новый в личном кабинете.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        profile_id, user_id, expires_at, username = row
        
        now_utc = datetime.now(timezone.utc)
        if expires_at is not None:
            exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
            if exp < now_utc:
                await update.message.reply_text(
                    "⏰ Код истёк (действует 15 минут). Получи новый код в профиле на сайте.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
        
        session.execute(text("""
            UPDATE "UserProfiles"
            SET telegram_chat_id = :chat_id,
                telegram_link_code = NULL,
                telegram_link_code_expires = NULL,
                telegram_id = CASE
                    WHEN telegram_id IS NULL OR telegram_id = '' THEN :telegram_id
                    ELSE telegram_id
                END
            WHERE profile_id = :profile_id
        """), {"chat_id": cid, "profile_id": profile_id, "telegram_id": tg_identifier})
        session.commit()

        session2 = get_session()
        try:
            user = get_user_by_chat_id(session2, cid)
            role = user.get("role") if user else None
            reply_markup = get_main_keyboard(role)
        finally:
            close_session(session2)
        await update.message.reply_text(
            LINK_SUCCESS + "\n\n💡 Если меню внизу не обновилось — отправь /start.",
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        logger.info("User %s linked Telegram chat_id=%s role=%s", username, chat_id, role if user else None)
        
    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        logger.error(f"Error in link_command chat_id={chat_id} code={code!r}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Не удалось привязать (временная ошибка). Запроси новый код в профиле на сайте и попробуй снова через минуту.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    finally:
        close_session(session)


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unlink."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        if not _unlink_telegram(session, chat_id):
            await update.message.reply_text(
                "ℹ️ Telegram не привязан к аккаунту.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await update.message.reply_text(
            "✅ Telegram отвязан. Ты больше не будешь получать уведомления.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        session.rollback()
        logger.error(f"Error in unlink_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


def _unlink_telegram(session, chat_id: int) -> bool:
    """Отвязать Telegram по chat_id."""
    exists = session.execute(text(
        'SELECT profile_id FROM "UserProfiles" WHERE telegram_chat_id = :chat_id'
    ), {"chat_id": chat_id}).fetchone()
    if not exists:
        return False

    session.execute(text("""
        UPDATE "UserProfiles"
        SET telegram_chat_id = NULL,
            telegram_link_code = NULL,
            telegram_link_code_expires = NULL,
            telegram_id = NULL
        WHERE telegram_chat_id = :chat_id
    """), {"chat_id": chat_id})
    session.commit()
    return True


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /me — профиль."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        text = await build_profile_text(session, user)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_main_keyboard())
    except Exception as e:
        logger.error(f"Error in me_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /lessons."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        student = get_student_by_email(session, user.get('email'), user.get('id'))
        if not student:
            await update.message.reply_text(
                "📚 Профиль ученика не найден. Обратись к преподавателю.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        await update.message.reply_text(
            "📅 <b>Мои уроки</b>\n\nВыбери что показать:",
            parse_mode="HTML",
            reply_markup=get_lessons_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in lessons_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        text = await build_stats_text(session, user)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
    except Exception as e:
        logger.error(f"Error in stats_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /settings."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        text = build_settings_text(user)
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_settings_keyboard(user))
    except Exception as e:
        logger.error(f"Error in settings_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def error_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /error — отправка ошибки."""
    session = get_session()
    try:
        user = get_user_by_chat_id(session, update.effective_chat.id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
    finally:
        close_session(session)
    await start_error_report_flow(update, context, from_callback=False)


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /users — список пользователей, подключённых к боту (только для админов бота)."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        admin_chat_ids = get_bot_admin_chat_ids(session)
        if chat_id not in admin_chat_ids:
            await update.message.reply_text(
                "⛔ Доступ запрещён. Команда только для администраторов бота.",
                parse_mode="HTML",
            )
            return
        users = get_bot_connected_users(session)
        msg = format_connected_users_message(users)
        max_len = 4000
        if len(msg) <= max_len:
            await update.message.reply_text(msg, parse_mode="HTML")
        else:
            parts = [msg[i : i + max_len] for i in range(0, len(msg), max_len)]
            for part in parts:
                await update.message.reply_text(part, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in users_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML")
    finally:
        close_session(session)


async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Центральный обработчик входящих текстовых сообщений (не команд)."""
    if not update.message or update.message.chat.type != "private":
        return
    
    message_text = (update.message.text or "").strip()
    if not message_text:
        return

    # Проверяем состояние пользователя
    if context.user_data.get("awaiting_error_report"):
        await handle_error_report_submission(update, context, message_text)
    elif context.user_data.get("awaiting_student_search"):
        await handle_student_search(update, context, message_text)
    elif context.user_data.get("awaiting_user_creation"):
        await handle_user_creation_step(update, context, message_text)


async def handle_error_report_submission(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
    """Обработка отправки сообщения об ошибке."""
    session = get_session()
    try:
        user = get_user_by_chat_id(session, update.effective_chat.id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
            return
        
        chat_id = update.effective_chat.id
        now = datetime.now(timezone.utc)
        report_id = None
        try:
            result = session.execute(text("""
                INSERT INTO "BotErrorReports" (user_id, telegram_chat_id, message, status, created_at, updated_at)
                VALUES (:user_id, :chat_id, :message, 'new', :created_at, :updated_at)
                RETURNING report_id
            """), {
                "user_id": user["id"],
                "chat_id": chat_id,
                "message": message_text,
                "created_at": now,
                "updated_at": now,
            })
            row = result.fetchone()
            report_id = row[0] if row else None
        except Exception:
            session.rollback()
            session.execute(text("""
                INSERT INTO "BotErrorReports" (user_id, telegram_chat_id, message, status, created_at, updated_at)
                VALUES (:user_id, :chat_id, :message, 'new', :created_at, :updated_at)
            """), {
                "user_id": user["id"],
                "chat_id": chat_id,
                "message": message_text,
                "created_at": now,
                "updated_at": now,
            })
        session.commit()
        
        admin_chat_ids = get_bot_admin_chat_ids(session)
        admin_text = (
            f"🛠 <b>Сообщение об ошибке</b>\n\n"
            f"👤 {esc(user.get('first_name') or user.get('username') or 'Пользователь')}\n"
            f"🆔 User ID: {user.get('id')}\n"
            f"📝 {esc(message_text)}\n"
            f"{f'📌 ID: {report_id}' if report_id else ''}\n"
            f"🔗 {APP_URL}/admin/bot/errors"
        )
        for admin_chat_id in admin_chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_chat_id,
                    text=admin_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                pass
        
        context.user_data["awaiting_error_report"] = False
        await update.message.reply_text(ERROR_REPORT_RECEIVED, reply_markup=get_main_keyboard(user.get('role')))
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving bot error report: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def handle_student_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query_text: str):
    """Поиск ученика в базе."""
    session = get_session()
    try:
        user = get_user_by_chat_id(session, update.effective_chat.id)
        if not user or user.get('role') not in ('admin', 'creator', 'chief_admin', 'tutor'):
            await update.message.reply_text("⛔ Доступ запрещён.")
            return

        result = session.execute(text("""
            SELECT s.student_id, s.name, s.email, s.platform_id
            FROM "Students" s
            WHERE (s.name ILIKE :q OR s.email ILIKE :q OR s.platform_id ILIKE :q)
              AND s.is_active = TRUE
            LIMIT 5
        """), {"q": f"%{query_text}%"})
        students = result.fetchall()

        if not students:
            await update.message.reply_text(f"❌ Ученик по запросу '{esc(query_text)}' не найден. Попробуйте другое имя или email.")
        else:
            lines = [f"🔍 <b>Результаты поиска ({len(students)}):</b>", ""]
            for sid, name, email, pid in students:
                lines.append(f"👤 <b>{esc(name)}</b>")
                lines.append(f"📧 {esc(email) or '—'} | ID: #{pid or sid}")
                lines.append(f"🔗 {APP_URL}/student/{sid}")
                lines.append("")
            
            context.user_data["awaiting_student_search"] = False
            await update.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=get_admin_keyboard(user.get('role')))
    finally:
        close_session(session)


async def handle_user_creation_step(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Пошаговое создание ученика: имя → email → создание User + Student + UserProfile."""
    import re
    import secrets
    from werkzeug.security import generate_password_hash

    step = context.user_data.get("create_student_step", "name")
    session = get_session()
    try:
        user = get_user_by_chat_id(session, update.effective_chat.id)
        if not user or user.get('role') not in ('creator', 'chief_admin'):
            context.user_data.pop("awaiting_user_creation", None)
            context.user_data.pop("create_student_step", None)
            context.user_data.pop("create_student_name", None)
            await update.message.reply_text("⛔ Доступ запрещён.")
            return

        if step == "name":
            name = (text or "").strip()[:200]
            if not name:
                await update.message.reply_text("Введите непустое имя.")
                return
            context.user_data["create_student_name"] = name
            context.user_data["create_student_step"] = "email"
            await update.message.reply_text("📧 Теперь введите <b>email</b> ученика:", parse_mode="HTML")
            return

        if step == "email":
            email = (text or "").strip().lower()[:200]
            if not email or "@" not in email:
                await update.message.reply_text("Введите корректный email.")
                return
            name = context.user_data.get("create_student_name") or "Ученик"
            student_id = None
            base_username = re.sub(r'[^a-z0-9]', '', email.split("@")[0]) or "user"
            base_username = base_username[:20]
            password_plain = secrets.token_urlsafe(8)
            password_hash = generate_password_hash(password_plain)

            for _ in range(5):
                suffix = secrets.token_hex(2)
                username = f"{base_username}_{suffix}"
                existing = session.execute(text('SELECT id FROM "Users" WHERE username = :u'), {"u": username}).fetchone()
                if not existing:
                    break
            else:
                username = f"student_{secrets.token_hex(4)}"

            try:
                session.execute(text("""
                    INSERT INTO "Users" (username, email, password_hash, role, is_active, created_at)
                    VALUES (:username, :email, :password_hash, 'student', TRUE, NOW())
                """), {"username": username, "email": email, "password_hash": password_hash})
                session.commit()
                row = session.execute(text('SELECT id FROM "Users" WHERE username = :u'), {"u": username}).fetchone()
                user_id = row[0] if row else None
                if not user_id:
                    session.rollback()
                    await update.message.reply_text("❌ Не удалось создать пользователя.")
                    return
                session.execute(text('INSERT INTO "UserRoles" (user_id, role) VALUES (:uid, \'student\')'), {"uid": user_id})
                session.execute(text("""
                    INSERT INTO "Students" (user_id, name, email, is_active, created_at, updated_at)
                    VALUES (:uid, :name, :email, TRUE, NOW(), NOW())
                """), {"uid": user_id, "name": name, "email": email})
                session.execute(text("""
                    INSERT INTO "UserProfiles" (user_id, timezone, created_at, updated_at)
                    VALUES (:uid, 'Europe/Moscow', NOW(), NOW())
                """), {"uid": user_id})
                session.commit()
                student_row = session.execute(text('SELECT student_id FROM "Students" WHERE user_id = :uid'), {"uid": user_id}).fetchone()
                student_id = student_row[0] if student_row else user_id
            except Exception as e:
                session.rollback()
                logger.exception("Create student failed: %s", e)
                await update.message.reply_text(f"❌ Ошибка при создании: {str(e)[:200]}")
            else:
                context.user_data.pop("awaiting_user_creation", None)
                context.user_data.pop("create_student_step", None)
                context.user_data.pop("create_student_name", None)
                admin_link = f"{APP_URL}/student/{student_id}" if APP_URL and student_id else ""
                msg = (
                    f"✅ <b>Ученик создан</b>\n\n"
                    f"👤 {esc(name)}\n"
                    f"📧 {esc(email)}\n"
                    f"🔑 Логин: <code>{esc(username)}</code>\n"
                    f"🔒 Пароль: <code>{password_plain}</code>\n\n"
                    f"Передай пароль ученику/родителю безопасным способом.\n"
                )
                if admin_link:
                    msg += f"\n🔗 {admin_link}"
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_admin_keyboard(user.get('role')))
            return
    finally:
        close_session(session)




async def build_profile_text(session, user: dict) -> str:
    """Построить текст профиля."""
    name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
    student = get_student_by_email(session, user.get('email'), user.get('id'))
    sub = get_subscription_info(session, user['id'])
    
    lines = [f"👤 <b>{esc(name)}</b>"]
    lines.append(f"📧 {esc(user['email']) if user['email'] else 'Email не указан'}")
    lines.append("")
    
    if student:
        lines.append("📚 <b>Учебный профиль:</b>")
        if student['school_class']:
            lines.append(f"   🎓 Класс: {student['school_class']}")
        if student['target_score']:
            lines.append(f"   🎯 Цель: {student['target_score']} баллов")
        if student['programming_language']:
            lines.append(f"   💻 Язык: {esc(student['programming_language'])}")
        if student['category']:
            lines.append(f"   📂 Направление: {esc(student['category'])}")
        if student['goal_text']:
            lines.append(f"   📝 Цель: {esc(student['goal_text'][:100])}")
        if student['diagnostic_level']:
            lines.append(f"   📊 Уровень: {esc(student['diagnostic_level'])}")
        lines.append("")
    
    lines.append("💳 <b>Подписка:</b>")
    if sub:
        if sub['plan_title']:
            lines.append(f"   📋 Тариф: {esc(sub['plan_title'])}")
        if sub['lessons_remaining'] is not None:
            total = sub['lessons_total'] or '∞'
            remaining = sub['lessons_remaining']
            emoji = "🟢" if remaining > 5 else ("🟡" if remaining > 2 else "🔴")
            lines.append(f"   {emoji} Уроков: {remaining} из {total}")
        if sub['ends_at']:
            lines.append(f"   📅 Действует до: {sub['ends_at'].strftime('%d.%m.%Y')}")
        if sub['started_at']:
            lines.append(f"   🗓 Активна с: {sub['started_at'].strftime('%d.%m.%Y')}")
    else:
        lines.append("   ❌ Подписка не активна")
    
    return "\n".join(lines)


async def build_stats_text(session, user: dict) -> str:
    """Построить текст статистики."""
    student = get_student_by_email(session, user.get('email'), user.get('id'))
    if not student:
        return "📊 Профиль ученика не найден."
    
    stats = get_detailed_stats(session, student['student_id'])
    sub = get_subscription_info(session, user['id'])
    
    lines = ["📊 <b>Твоя статистика</b>", ""]
    
    lines.append("📚 <b>Уроки:</b>")
    lines.append(f"   ✅ Проведено: {stats['lessons_completed']}")
    lines.append(f"   📅 Запланировано: {stats['lessons_planned']}")
    if stats['lessons_cancelled']:
        lines.append(f"   ❌ Отменено: {stats['lessons_cancelled']}")
    if stats['total_minutes']:
        hours = stats['total_minutes'] // 60
        mins = stats['total_minutes'] % 60
        lines.append(f"   ⏱ Всего времени: {hours}ч {mins}м")
    lines.append("")
    
    if stats['next_lesson_date']:
        lines.append(f"⏰ <b>Следующий урок:</b>")
        lines.append(f"   {stats['next_lesson_date'].strftime('%d.%m в %H:%M')}")
        if stats['next_lesson_topic']:
            lines.append(f"   {esc(stats['next_lesson_topic'][:50])}")
        lines.append("")
    
    if stats['last_lesson_date']:
        lines.append(f"📜 <b>Последний урок:</b>")
        lines.append(f"   {stats['last_lesson_date'].strftime('%d.%m.%Y')}")
        if stats['last_lesson_topic']:
            lines.append(f"   {esc(stats['last_lesson_topic'][:50])}")
        lines.append("")
    
    if stats['hw_total']:
        lines.append("📝 <b>Домашние задания:</b>")
        lines.append(f"   ✅ Проверено: {stats['hw_checked']}")
        if stats['hw_pending']:
            lines.append(f"   ⏳ Ожидает проверки: {stats['hw_pending']}")
        if stats['hw_returned']:
            lines.append(f"   ↩️ На доработке: {stats['hw_returned']}")
        if stats['hw_correct'] and stats['hw_checked']:
            accuracy = round(stats['hw_correct'] / stats['hw_checked'] * 100)
            lines.append(f"   🎯 Точность: {accuracy}%")
        lines.append("")
    
    if sub and sub['lessons_remaining'] is not None:
        emoji = "🟢" if sub['lessons_remaining'] > 5 else ("🟡" if sub['lessons_remaining'] > 2 else "🔴")
        lines.append(f"{emoji} <b>Баланс:</b> {sub['lessons_remaining']} уроков")
        if sub['lessons_remaining'] <= 2:
            lines.append("⚠️ <i>Уроки заканчиваются!</i>")
    
    return "\n".join(lines)


def build_settings_text(user: dict) -> str:
    """Построить текст настроек."""
    lines = [
        "⚙️ <b>Настройки уведомлений</b>",
        "",
        "Нажми на пункт чтобы включить/выключить:",
        ""
    ]
    return "\n".join(lines)


def build_lessons_text(lessons: list, upcoming: bool) -> str:
    """Построить текст списка уроков."""
    if not lessons:
        if upcoming:
            return NO_LESSONS
        return "📜 История уроков пуста."
    
    title = "📅 <b>Ближайшие уроки:</b>" if upcoming else "📜 <b>История уроков:</b>"
    lines = [title, ""]
    
    for lesson in lessons:
        date = lesson['date']
        date_str = date.strftime('%d.%m %H:%M') if date else "—"
        topic = esc(lesson['topic'][:50]) if lesson['topic'] else "Тема не указана"
        duration = lesson['duration'] or 60
        ltype = format_lesson_type(lesson['type'])
        hw = format_hw_status(lesson['homework_status'])
        
        if upcoming:
            emoji = "🟢" if lesson['status'] == 'in_progress' else "📅"
            lines.append(f"{emoji} <b>{date_str}</b> ({duration} мин)")
        else:
            lines.append(f"✅ <b>{date_str}</b> ({duration} мин)")
        
        lines.append(f"   {topic}")
        extra = []
        if ltype != 'Урок':
            extra.append(ltype)
        if hw:
            extra.append(f"ДЗ {hw}")
        if extra:
            lines.append(f"   <i>{' • '.join(extra)}</i>")
        lines.append("")
    
    return "\n".join(lines)



async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    if data != "error_report":
        context.user_data.pop("awaiting_error_report", None)
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        
        if data == "main":
            await query.edit_message_text(
                "🏠 <b>Главное меню</b>\n\nВыбери действие:",
                parse_mode="HTML",
                reply_markup=get_main_keyboard(user.get('role') if user else None)
            )
        
        elif data == "admin_panel":
            if not user or user.get('role') not in ('admin', 'creator', 'chief_admin', 'tutor'):
                await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
                return
            await query.edit_message_text(
                "👨‍💼 <b>Панель управления</b>\n\nЗдесь вы можете управлять платформой и отслеживать активность.",
                parse_mode="HTML",
                reply_markup=get_admin_keyboard(user.get('role'))
            )

        elif data == "admin_referrals":
            if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
                await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
                return
            
            result = session.execute(text("""
                SELECT code, usage_count, usage_limit, is_active
                FROM "ReferralCodes"
                WHERE creator_id = :user_id
                ORDER BY created_at DESC
            """), {"user_id": user['id']})
            codes = result.fetchall()
            
            if not codes:
                text_msg = "🎫 <b>Ваши реферальные коды</b>\n\nУ вас пока нет созданных кодов.\nИспользуйте команду /gen_ref КОД [лимит] для создания."
            else:
                lines = ["🎫 <b>Ваши реферальные коды:</b>", ""]
                for c_code, usage, limit, active in codes:
                    status = "✅" if active else "❌"
                    limit_str = f"/{limit}" if limit else ""
                    lines.append(f"• <code>{c_code}</code> — {usage}{limit_str} исп. {status}")
                text_msg = "\n".join(lines)
            
            await query.edit_message_text(text_msg, parse_mode="HTML", reply_markup=get_admin_keyboard(user.get('role')))

        elif data == "admin_errors":
            if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
                await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
                return
            
            result = session.execute(text("""
                SELECT report_id, message, created_at, status
                FROM "BotErrorReports"
                WHERE status = 'new'
                ORDER BY created_at DESC
                LIMIT 5
            """))
            errors = result.fetchall()
            
            if not errors:
                text_msg = "🐞 <b>Новых ошибок нет</b>\n\nВсе сообщения обработаны."
            else:
                lines = ["🐞 <b>Последние новые ошибки:</b>", ""]
                for rid, msg, dt, status in errors:
                    lines.append(f"<b>#{rid}</b> ({dt.strftime('%d.%m %H:%M')}):")
                    lines.append(f"<i>{esc(msg[:100])}...</i>")
                    lines.append("")
                text_msg = "\n".join(lines)
            
            await query.edit_message_text(text_msg, parse_mode="HTML", reply_markup=get_admin_keyboard(user.get('role')))

        elif data == "admin_search_student":
            if not user or user.get('role') not in ('admin', 'creator', 'chief_admin', 'tutor'):
                await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
                return
            context.user_data["awaiting_student_search"] = True
            await query.edit_message_text(
                "🔍 <b>Поиск ученика</b>\n\nВведите имя или email ученика:",
                parse_mode="HTML",
                reply_markup=get_admin_keyboard(user.get('role'))
            )

        elif data == "admin_stats":
            if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
                await query.edit_message_text("⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
                return
            
            stats = {}
            stats['total_users'] = session.execute(text('SELECT COUNT(*) FROM "Users"')).scalar()
            stats['active_students'] = session.execute(text('SELECT COUNT(*) FROM "Students" WHERE is_active = TRUE')).scalar()
            stats['lessons_today'] = session.execute(text("SELECT COUNT(*) FROM \"Lessons\" WHERE lesson_date::date = CURRENT_DATE")).scalar()
            stats['referrals_total'] = session.execute(text('SELECT COUNT(*) FROM "ReferralUsage"')).scalar()
            
            text_msg = (
                f"📊 <b>Статистика платформы</b>\n\n"
                f"👤 Всего пользователей: {stats['total_users']}\n"
                f"🎓 Активных учеников: {stats['active_students']}\n"
                f"📅 Уроков сегодня: {stats['lessons_today']}\n"
                f"🚀 Использований рефералов: {stats['referrals_total']}"
            )
            
            await query.edit_message_text(text_msg, parse_mode="HTML", reply_markup=get_admin_keyboard(user.get('role')))

        elif data == "admin_create_student":
            if not user or user.get('role') not in ('creator', 'chief_admin'):
                await query.edit_message_text("⛔ Доступ запрещён. Только создатель или главный админ.", reply_markup=get_main_keyboard())
                return
            context.user_data["awaiting_user_creation"] = True
            context.user_data["create_student_step"] = "name"
            await query.edit_message_text(
                "➕ <b>Создание ученика</b>\n\nВведите <b>имя ученика</b> (ФИО или как в журнале):",
                parse_mode="HTML",
                reply_markup=get_admin_keyboard(user.get('role'))
            )

        elif data == "profile":
            if not user:
                await query.edit_message_text(
                    _profile_not_linked_with_chat_id(chat_id),
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
            profile_text = await build_profile_text(session, user)
            await query.edit_message_text(profile_text, parse_mode="HTML", reply_markup=get_back_keyboard())
        
        elif data == "lessons":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            await query.edit_message_text(
                "📅 <b>Мои уроки</b>\n\nВыбери что показать:",
                parse_mode="HTML",
                reply_markup=get_lessons_keyboard()
            )
        
        elif data == "lessons_upcoming":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            student = get_student_by_email(session, user.get('email'), user.get('id'))
            if not student:
                await query.edit_message_text("Профиль ученика не найден.", parse_mode="HTML", reply_markup=get_back_keyboard())
                return
            lessons = get_lessons(session, student['student_id'], upcoming=True)
            lessons_text = build_lessons_text(lessons, upcoming=True)
            await query.edit_message_text(lessons_text, parse_mode="HTML", reply_markup=get_lessons_keyboard())
        
        elif data == "lessons_history":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            student = get_student_by_email(session, user.get('email'), user.get('id'))
            if not student:
                await query.edit_message_text("Профиль ученика не найден.", parse_mode="HTML", reply_markup=get_back_keyboard())
                return
            lessons = get_lessons(session, student['student_id'], upcoming=False)
            history_text = build_lessons_text(lessons, upcoming=False)
            await query.edit_message_text(history_text, parse_mode="HTML", reply_markup=get_lessons_keyboard())
        
        elif data == "stats":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            stats_text = await build_stats_text(session, user)
            await query.edit_message_text(stats_text, parse_mode="HTML", reply_markup=get_back_keyboard())
        
        elif data == "settings":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            settings_text = build_settings_text(user)
            await query.edit_message_text(settings_text, parse_mode="HTML", reply_markup=get_settings_keyboard(user))
        
        elif data == "unlink":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            await query.edit_message_text(
                "⚠️ <b>Отвязать Telegram?</b>\n\n"
                "Ты перестанешь получать уведомления, пока снова не привяжешь аккаунт.",
                parse_mode="HTML",
                reply_markup=get_unlink_confirm_keyboard()
            )

        elif data == "unlink_confirm":
            if not _unlink_telegram(session, chat_id):
                await query.edit_message_text(
                    "ℹ️ Telegram не привязан к аккаунту.",
                    parse_mode="HTML",
                    reply_markup=get_main_keyboard()
                )
                return
            await query.edit_message_text(
                "✅ Telegram отвязан. Чтобы вернуть уведомления, привяжи аккаунт снова.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )

        elif data == "error_report":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            await start_error_report_flow(update, context, from_callback=True)
        
        elif data.startswith("toggle_"):
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            
            field = data[7:]  # Убираем "toggle_"
            allowed_fields = [
                'tg_notify_lesson_reminder', 'tg_notify_homework_checked',
                'tg_notify_homework_returned', 'tg_notify_new_message',
                'tg_notify_lesson_scheduled', 'tg_notify_low_lessons', 'tg_notify_news',
                'tg_notify_referral_used', 'tg_notify_homework_submitted', 'tg_notify_system_errors'
            ]
            
            if field in allowed_fields:
                current = user.get(field, True)
                new_value = not current
                
                try:
                    session.execute(text(f"""
                        UPDATE "UserProfiles"
                        SET {field} = :value
                        WHERE telegram_chat_id = :chat_id
                    """), {"value": new_value, "chat_id": chat_id})
                    session.commit()
                    user[field] = new_value
                except Exception as e:
                    session.rollback()
                    logger.warning(f"Could not update {field}: {e}")
                    await query.edit_message_text(
                        "⚙️ <b>Настройки</b>\n\n⚠️ Настройки временно недоступны. Попробуй позже.",
                        parse_mode="HTML",
                        reply_markup=get_back_keyboard()
                    )
                    return
            
            text = build_settings_text(user)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_settings_keyboard(user))
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in callback_handler: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                ERROR_MESSAGE,
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        except Exception:
            pass
    finally:
        close_session(session)



async def gen_ref_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /gen_ref <code> [limit] — генерация реферального кода (для админов)."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user or user.get('role') not in ('admin', 'creator', 'chief_admin'):
            await update.message.reply_text("⛔ Доступ запрещён.")
            return

        if not context.args:
            await update.message.reply_text("ℹ️ <b>Использование:</b> /gen_ref КОД [лимит]\n\nПример: /gen_ref SUMMER2024 50")
            return

        code = context.args[0].upper().strip()
        limit = None
        if len(context.args) > 1:
            try:
                limit = int(context.args[1])
            except ValueError:
                pass

        # Проверяем не занят ли код
        existing = session.execute(text('SELECT id FROM "ReferralCodes" WHERE code = :code'), {"code": code}).fetchone()
        if existing:
            await update.message.reply_text(f"❌ Код <b>{code}</b> уже существует.")
            return

        session.execute(text("""
            INSERT INTO "ReferralCodes" (code, creator_id, usage_limit, usage_count, is_active, created_at)
            VALUES (:code, :creator_id, :limit, 0, TRUE, NOW())
        """), {
            "code": code,
            "creator_id": user["id"],
            "limit": limit
        })
        session.commit()

        limit_text = f"с лимитом {limit}" if limit else "без лимита"
        await update.message.reply_text(f"✅ Реферальный код <b>{code}</b> успешно создан {limit_text}!")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in gen_ref_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE)
    finally:
        close_session(session)


def create_bot_application() -> Application:
    """Создание приложения бота."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CommandHandler("unlink", unlink_command))
    application.add_handler(CommandHandler("me", me_command))
    application.add_handler(CommandHandler("lessons", lessons_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("error", error_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("gen_ref", gen_ref_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, handle_private_text))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    return application
