"""
Основной файл бота - обработчики команд и callback-запросов.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from sqlalchemy import text

from urep_bot.config import BOT_TOKEN, APP_URL
from urep_bot.db import get_session, close_session

logger = logging.getLogger(__name__)


# ============================================
# ТЕКСТЫ СООБЩЕНИЙ
# ============================================

WELCOME_MESSAGE = """
👋 <b>Привет! Я бот платформы URep.</b>

Я буду присылать тебе уведомления:
• 📅 Напоминания об уроках
• ✅ Проверка домашних заданий
• 💬 Сообщения от преподавателя
• ⚠️ Когда уроки заканчиваются

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

⚙️ Настроить уведомления: /settings
"""

PROFILE_NOT_LINKED = """
❌ <b>Telegram не привязан к аккаунту</b>

Чтобы привязать:
1. Зайди в профиль на сайте
2. Нажми "Привязать Telegram"
3. Отправь мне команду /link КОД
"""

NO_LESSONS = "📅 Уроков пока нет. Как только урок будет запланирован — я сообщу!"

ERROR_MESSAGE = "❌ Произошла ошибка. Попробуй ещё раз или обратись к преподавателю."


# ============================================
# КЛАВИАТУРЫ
# ============================================

def get_main_keyboard():
    """Главное меню."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("📅 Уроки", callback_data="lessons"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("🌐 Открыть сайт", url=APP_URL),
        ],
    ])


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
        [InlineKeyboardButton("« Главное меню", callback_data="main")],
    ])


# ============================================
# УТИЛИТЫ
# ============================================

def esc(text) -> str:
    """Экранирование HTML."""
    if not text:
        return ""
    return html.escape(str(text))


def get_user_by_chat_id(session, chat_id: int) -> Optional[dict]:
    """Получить пользователя по chat_id Telegram."""
    # Базовый запрос без новых колонок (для совместимости)
    result = session.execute(text("""
        SELECT u.id, u.username, u.email, u.role, up.first_name, up.last_name,
               up.telegram_notifications_enabled
        FROM "Users" u
        JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE up.telegram_chat_id = :chat_id
    """), {"chat_id": chat_id})
    row = result.fetchone()
    if not row:
        return None
    
    user = {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "role": row[3],
        "first_name": row[4],
        "last_name": row[5],
        "notifications_enabled": row[6] if row[6] is not None else True,
        # Значения по умолчанию для настроек уведомлений
        "tg_notify_lesson_reminder": True,
        "tg_notify_homework_checked": True,
        "tg_notify_homework_returned": True,
        "tg_notify_new_message": True,
        "tg_notify_lesson_scheduled": True,
        "tg_notify_low_lessons": True,
        "tg_notify_news": False,
    }
    
    # Пробуем получить детальные настройки (если колонки существуют)
    try:
        settings_result = session.execute(text("""
            SELECT 
                COALESCE(tg_notify_lesson_reminder, TRUE),
                COALESCE(tg_notify_homework_checked, TRUE),
                COALESCE(tg_notify_homework_returned, TRUE),
                COALESCE(tg_notify_new_message, TRUE),
                COALESCE(tg_notify_lesson_scheduled, TRUE),
                COALESCE(tg_notify_low_lessons, TRUE),
                COALESCE(tg_notify_news, FALSE)
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
    except Exception:
        # Колонки ещё не созданы - используем значения по умолчанию
        pass
    
    return user


def get_student_by_email(session, email: str) -> Optional[dict]:
    """Получить студента по email."""
    if not email:
        return None
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
               tp.title, tp.lessons_count, tp.price
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
            "price": row[6],
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
    # Статистика уроков
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
    
    # Статистика ДЗ
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
    
    # Последний урок
    last_lesson = session.execute(text("""
        SELECT lesson_date, topic FROM "Lessons"
        WHERE student_id = :student_id AND status = 'completed'
        ORDER BY lesson_date DESC LIMIT 1
    """), {"student_id": student_id}).fetchone()
    
    # Следующий урок
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


# ============================================
# КОМАНДЫ
# ============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
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
    
    session = get_session()
    try:
        # Проверяем, не привязан ли уже
        existing = session.execute(text(
            'SELECT user_id FROM "UserProfiles" WHERE telegram_chat_id = :chat_id'
        ), {"chat_id": chat_id}).fetchone()
        
        if existing:
            await update.message.reply_text(
                "ℹ️ Этот Telegram уже привязан к аккаунту.\n\nИспользуй /unlink для отвязки.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Ищем код
        result = session.execute(text("""
            SELECT up.profile_id, up.user_id, up.telegram_link_code_expires, u.username
            FROM "UserProfiles" up
            JOIN "Users" u ON u.id = up.user_id
            WHERE up.telegram_link_code = :code
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
        
        if expires_at and expires_at < datetime.utcnow():
            await update.message.reply_text(
                "⏰ Код истёк. Получи новый код в личном кабинете.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Привязываем
        session.execute(text("""
            UPDATE "UserProfiles"
            SET telegram_chat_id = :chat_id,
                telegram_link_code = NULL,
                telegram_link_code_expires = NULL
            WHERE profile_id = :profile_id
        """), {"chat_id": chat_id, "profile_id": profile_id})
        session.commit()
        
        await update.message.reply_text(LINK_SUCCESS, parse_mode="HTML", reply_markup=get_main_keyboard())
        logger.info(f"User {username} linked Telegram chat_id={chat_id}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in link_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_MESSAGE, parse_mode="HTML", reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unlink."""
    chat_id = update.effective_chat.id
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(
                "ℹ️ Telegram не привязан к аккаунту.",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return
        
        session.execute(text(
            'UPDATE "UserProfiles" SET telegram_chat_id = NULL WHERE telegram_chat_id = :chat_id'
        ), {"chat_id": chat_id})
        session.commit()
        
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
        
        student = get_student_by_email(session, user['email'])
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


# ============================================
# ПОСТРОИТЕЛИ ТЕКСТА
# ============================================

async def build_profile_text(session, user: dict) -> str:
    """Построить текст профиля."""
    name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
    student = get_student_by_email(session, user['email'])
    sub = get_subscription_info(session, user['id'])
    
    lines = [f"👤 <b>{esc(name)}</b>"]
    lines.append(f"📧 {esc(user['email']) if user['email'] else 'Email не указан'}")
    lines.append("")
    
    # Информация о студенте
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
    
    # Подписка
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
    student = get_student_by_email(session, user['email'])
    if not student:
        return "📊 Профиль ученика не найден."
    
    stats = get_detailed_stats(session, student['student_id'])
    sub = get_subscription_info(session, user['id'])
    
    lines = ["📊 <b>Твоя статистика</b>", ""]
    
    # Уроки
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
    
    # Следующий/последний урок
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
    
    # ДЗ
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
    
    # Баланс
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


# ============================================
# CALLBACK HANDLER
# ============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback-запросов."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        
        if data == "main":
            await query.edit_message_text(
                "🏠 <b>Главное меню</b>\n\nВыбери действие:",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
        
        elif data == "profile":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            text = await build_profile_text(session, user)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
        
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
            student = get_student_by_email(session, user['email'])
            if not student:
                await query.edit_message_text("Профиль ученика не найден.", parse_mode="HTML", reply_markup=get_back_keyboard())
                return
            lessons = get_lessons(session, student['student_id'], upcoming=True)
            text = build_lessons_text(lessons, upcoming=True)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_lessons_keyboard())
        
        elif data == "lessons_history":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            student = get_student_by_email(session, user['email'])
            if not student:
                await query.edit_message_text("Профиль ученика не найден.", parse_mode="HTML", reply_markup=get_back_keyboard())
                return
            lessons = get_lessons(session, student['student_id'], upcoming=False)
            text = build_lessons_text(lessons, upcoming=False)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_lessons_keyboard())
        
        elif data == "stats":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            text = await build_stats_text(session, user)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_back_keyboard())
        
        elif data == "settings":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            text = build_settings_text(user)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_settings_keyboard(user))
        
        elif data.startswith("toggle_"):
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, parse_mode="HTML", reply_markup=get_main_keyboard())
                return
            
            field = data[7:]  # Убираем "toggle_"
            allowed_fields = [
                'tg_notify_lesson_reminder', 'tg_notify_homework_checked',
                'tg_notify_homework_returned', 'tg_notify_new_message',
                'tg_notify_lesson_scheduled', 'tg_notify_low_lessons', 'tg_notify_news'
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


# ============================================
# СОЗДАНИЕ ПРИЛОЖЕНИЯ
# ============================================

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
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    return application
