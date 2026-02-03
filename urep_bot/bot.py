"""
Основной файл бота - обработчики команд и callback-запросов.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from sqlalchemy import text

from config import BOT_TOKEN, APP_URL
from db import get_session, close_session
from messages import (
    WELCOME_MESSAGE, HELP_MESSAGE, LINK_SUCCESS, LINK_INVALID_CODE,
    LINK_CODE_EXPIRED, LINK_ALREADY_LINKED, LINK_USAGE,
    UNLINK_SUCCESS, UNLINK_NOT_LINKED, PROFILE_NOT_LINKED,
    NO_UPCOMING_LESSONS, NO_STATS, SETTINGS_TEMPLATE,
    NOTIFICATIONS_ENABLED, NOTIFICATIONS_DISABLED, ERROR_GENERIC
)
from keyboards import (
    get_main_keyboard, get_settings_keyboard, get_back_keyboard,
    get_unlink_confirm_keyboard, get_open_link_keyboard
)

logger = logging.getLogger(__name__)


# ============================================
# УТИЛИТЫ
# ============================================

def get_user_by_chat_id(session, chat_id: int) -> Optional[dict]:
    """Получить пользователя по chat_id Telegram."""
    result = session.execute(text("""
        SELECT u.id, u.username, u.role, up.first_name, up.last_name,
               up.telegram_notifications_enabled
        FROM "Users" u
        JOIN "UserProfiles" up ON up.user_id = u.id
        WHERE up.telegram_chat_id = :chat_id
    """), {"chat_id": chat_id})
    row = result.fetchone()
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "role": row[2],
            "first_name": row[3],
            "last_name": row[4],
            "notifications_enabled": row[5] if row[5] is not None else True
        }
    return None


def get_linked_student(session, user_id: int) -> Optional[dict]:
    """Получить связанного студента через Enrollment."""
    result = session.execute(text("""
        SELECT s.student_id, s.name, s.target_score, s.school_class
        FROM "Students" s
        JOIN "Enrollments" e ON e.student_id = s.student_id
        WHERE e.tutor_id IN (
            SELECT tutor_id FROM "Enrollments" WHERE student_id = :user_id
        ) OR EXISTS (
            SELECT 1 FROM "Enrollments" WHERE student_id = s.student_id 
            AND tutor_id = (SELECT id FROM "Users" WHERE id = :user_id AND role = 'tutor')
        )
        LIMIT 1
    """), {"user_id": user_id})
    row = result.fetchone()
    if row:
        return {
            "student_id": row[0],
            "name": row[1],
            "target_score": row[2],
            "school_class": row[3]
        }
    return None


def get_subscription_info(session, user_id: int) -> Optional[dict]:
    """Получить информацию о подписке."""
    result = session.execute(text("""
        SELECT us.lessons_remaining, us.ends_at, us.status, tp.title
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
            "plan_title": row[3]
        }
    return None


# ============================================
# КОМАНДЫ
# ============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start."""
    await update.message.reply_text(
        WELCOME_MESSAGE,
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help."""
    await update.message.reply_text(HELP_MESSAGE)


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /link КОД — привязка аккаунта."""
    if not context.args:
        await update.message.reply_text(LINK_USAGE)
        return
    
    code = context.args[0].upper().strip()
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        # Проверяем, не привязан ли уже этот chat_id
        existing = session.execute(text("""
            SELECT user_id FROM "UserProfiles" WHERE telegram_chat_id = :chat_id
        """), {"chat_id": chat_id}).fetchone()
        
        if existing:
            await update.message.reply_text(LINK_ALREADY_LINKED)
            return
        
        # Ищем профиль с этим кодом
        result = session.execute(text("""
            SELECT up.profile_id, up.user_id, up.telegram_link_code_expires, u.username
            FROM "UserProfiles" up
            JOIN "Users" u ON u.id = up.user_id
            WHERE up.telegram_link_code = :code
        """), {"code": code})
        row = result.fetchone()
        
        if not row:
            await update.message.reply_text(LINK_INVALID_CODE)
            return
        
        profile_id, user_id, expires_at, username = row
        
        # Проверяем срок действия
        if expires_at and expires_at < datetime.utcnow():
            await update.message.reply_text(LINK_CODE_EXPIRED)
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
        
        await update.message.reply_text(
            LINK_SUCCESS,
            reply_markup=get_main_keyboard()
        )
        logger.info(f"User {username} (id={user_id}) linked Telegram chat_id={chat_id}")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in link_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unlink — отвязка аккаунта."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(UNLINK_NOT_LINKED)
            return
        
        # Отвязываем
        session.execute(text("""
            UPDATE "UserProfiles"
            SET telegram_chat_id = NULL
            WHERE telegram_chat_id = :chat_id
        """), {"chat_id": chat_id})
        session.commit()
        
        await update.message.reply_text(UNLINK_SUCCESS)
        logger.info(f"User {user['username']} unlinked Telegram")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in unlink_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /me — информация о профиле."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED)
            return
        
        # Формируем профиль
        name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
        
        text_parts = [f"👤 *{name}*\n"]
        
        # Подписка
        sub = get_subscription_info(session, user['id'])
        if sub:
            if sub['lessons_remaining'] is not None:
                text_parts.append(f"📚 Осталось уроков: *{sub['lessons_remaining']}*")
            if sub['plan_title']:
                text_parts.append(f"📋 Тариф: {sub['plan_title']}")
            if sub['ends_at']:
                text_parts.append(f"📅 До: {sub['ends_at'].strftime('%d.%m.%Y')}")
        else:
            text_parts.append("📚 Подписка не активна")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_open_link_keyboard(f"{APP_URL}/profile", "🌐 Открыть профиль")
        )
        
    except Exception as e:
        logger.error(f"Error in me_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /lessons — ближайшие уроки."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED)
            return
        
        # Получаем уроки для студента
        # Через Enrollment находим student_id связанный с user_id
        result = session.execute(text("""
            SELECT l.lesson_id, l.lesson_date, l.topic, l.status, l.duration, s.name as student_name
            FROM "Lessons" l
            JOIN "Students" s ON s.student_id = l.student_id
            WHERE s.user_id = :user_id
              AND l.lesson_date >= NOW()
              AND l.status IN ('planned', 'in_progress')
            ORDER BY l.lesson_date ASC
            LIMIT 5
        """), {"user_id": user['id']})
        lessons = result.fetchall()
        
        if not lessons:
            await update.message.reply_text(NO_UPCOMING_LESSONS)
            return
        
        text_parts = ["📅 *Ближайшие уроки:*\n"]
        
        for lesson in lessons:
            lesson_id, date, topic, status, duration, student_name = lesson
            date_str = date.strftime('%d.%m %H:%M') if date else "?"
            topic_str = topic or "Без темы"
            status_emoji = "🟢" if status == 'in_progress' else "📅"
            text_parts.append(f"{status_emoji} *{date_str}* ({duration} мин)\n   {topic_str}")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in lessons_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — статистика."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED)
            return
        
        # Получаем статистику уроков
        result = session.execute(text("""
            SELECT 
                COUNT(*) FILTER (WHERE l.status = 'completed') as completed,
                COUNT(*) FILTER (WHERE l.status = 'planned') as planned
            FROM "Lessons" l
            JOIN "Students" s ON s.student_id = l.student_id
            WHERE s.user_id = :user_id
        """), {"user_id": user['id']})
        stats = result.fetchone()
        
        if not stats or (stats[0] == 0 and stats[1] == 0):
            await update.message.reply_text(NO_STATS)
            return
        
        completed, planned = stats
        
        text_parts = [
            "📊 *Твоя статистика:*\n",
            f"✅ Проведено уроков: *{completed}*",
            f"📅 Запланировано: *{planned}*",
        ]
        
        # Подписка
        sub = get_subscription_info(session, user['id'])
        if sub and sub['lessons_remaining'] is not None:
            text_parts.append(f"\n📚 Осталось уроков: *{sub['lessons_remaining']}*")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in stats_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /settings — настройки уведомлений."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED)
            return
        
        enabled = user['notifications_enabled']
        status = NOTIFICATIONS_ENABLED if enabled else NOTIFICATIONS_DISABLED
        
        await update.message.reply_text(
            SETTINGS_TEMPLATE.format(status=status),
            reply_markup=get_settings_keyboard(enabled)
        )
        
    except Exception as e:
        logger.error(f"Error in settings_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC)
    finally:
        close_session(session)


# ============================================
# CALLBACK HANDLERS
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
        
        if data == "main_menu":
            await query.edit_message_text(
                "🏠 Главное меню",
                reply_markup=get_main_keyboard()
            )
        
        elif data == "profile":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED)
                return
            # Аналог /me
            name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
            sub = get_subscription_info(session, user['id'])
            
            text_parts = [f"👤 *{name}*\n"]
            if sub:
                if sub['lessons_remaining'] is not None:
                    text_parts.append(f"📚 Осталось уроков: *{sub['lessons_remaining']}*")
                if sub['plan_title']:
                    text_parts.append(f"📋 Тариф: {sub['plan_title']}")
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "lessons":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED)
                return
            
            result = session.execute(text("""
                SELECT l.lesson_date, l.topic, l.status, l.duration
                FROM "Lessons" l
                JOIN "Students" s ON s.student_id = l.student_id
                WHERE s.user_id = :user_id
                  AND l.lesson_date >= NOW()
                  AND l.status IN ('planned', 'in_progress')
                ORDER BY l.lesson_date ASC
                LIMIT 5
            """), {"user_id": user['id']})
            lessons = result.fetchall()
            
            if not lessons:
                await query.edit_message_text(NO_UPCOMING_LESSONS, reply_markup=get_back_keyboard())
                return
            
            text_parts = ["📅 *Ближайшие уроки:*\n"]
            for lesson in lessons:
                date, topic, status, duration = lesson
                date_str = date.strftime('%d.%m %H:%M') if date else "?"
                topic_str = topic or "Без темы"
                status_emoji = "🟢" if status == 'in_progress' else "📅"
                text_parts.append(f"{status_emoji} *{date_str}* ({duration} мин)\n   {topic_str}")
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "stats":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED)
                return
            
            result = session.execute(text("""
                SELECT 
                    COUNT(*) FILTER (WHERE l.status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE l.status = 'planned') as planned
                FROM "Lessons" l
                JOIN "Students" s ON s.student_id = l.student_id
                WHERE s.user_id = :user_id
            """), {"user_id": user['id']})
            stats = result.fetchone()
            
            if not stats or (stats[0] == 0 and stats[1] == 0):
                await query.edit_message_text(NO_STATS, reply_markup=get_back_keyboard())
                return
            
            text_parts = [
                "📊 *Твоя статистика:*\n",
                f"✅ Проведено: *{stats[0]}*",
                f"📅 Запланировано: *{stats[1]}*",
            ]
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "settings":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED)
                return
            
            enabled = user['notifications_enabled']
            status = NOTIFICATIONS_ENABLED if enabled else NOTIFICATIONS_DISABLED
            
            await query.edit_message_text(
                SETTINGS_TEMPLATE.format(status=status),
                reply_markup=get_settings_keyboard(enabled)
            )
        
        elif data == "toggle_notifications":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED)
                return
            
            new_state = not user['notifications_enabled']
            session.execute(text("""
                UPDATE "UserProfiles"
                SET telegram_notifications_enabled = :enabled
                WHERE telegram_chat_id = :chat_id
            """), {"enabled": new_state, "chat_id": chat_id})
            session.commit()
            
            status = NOTIFICATIONS_ENABLED if new_state else NOTIFICATIONS_DISABLED
            await query.edit_message_text(
                SETTINGS_TEMPLATE.format(status=status),
                reply_markup=get_settings_keyboard(new_state)
            )
        
        elif data == "confirm_unlink":
            session.execute(text("""
                UPDATE "UserProfiles"
                SET telegram_chat_id = NULL
                WHERE telegram_chat_id = :chat_id
            """), {"chat_id": chat_id})
            session.commit()
            
            await query.edit_message_text(UNLINK_SUCCESS)
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in callback_handler: {e}", exc_info=True)
        await query.edit_message_text(ERROR_GENERIC)
    finally:
        close_session(session)


# ============================================
# СОЗДАНИЕ ПРИЛОЖЕНИЯ
# ============================================

def create_bot_application() -> Application:
    """Создание и настройка приложения бота."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("link", link_command))
    application.add_handler(CommandHandler("unlink", unlink_command))
    application.add_handler(CommandHandler("me", me_command))
    application.add_handler(CommandHandler("lessons", lessons_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("settings", settings_command))
    
    # Callback-запросы
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    return application
