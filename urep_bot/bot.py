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

from urep_bot.config import BOT_TOKEN, APP_URL
from urep_bot.db import get_session, close_session
from urep_bot.messages import (
    WELCOME_MESSAGE, HELP_MESSAGE, LINK_SUCCESS, LINK_INVALID_CODE,
    LINK_CODE_EXPIRED, LINK_ALREADY_LINKED, LINK_USAGE,
    UNLINK_SUCCESS, UNLINK_NOT_LINKED, PROFILE_NOT_LINKED,
    NO_UPCOMING_LESSONS, NO_STATS, SETTINGS_TEMPLATE,
    NOTIFICATIONS_ENABLED, NOTIFICATIONS_DISABLED, ERROR_GENERIC
)
from urep_bot.keyboards import (
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
        SELECT u.id, u.username, u.email, u.role, up.first_name, up.last_name,
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
            "email": row[2],
            "role": row[3],
            "first_name": row[4],
            "last_name": row[5],
            "notifications_enabled": row[6] if row[6] is not None else True
        }
    return None


def get_student_by_email(session, email: str) -> Optional[dict]:
    """Получить студента по email (связь User.email = Student.email)."""
    if not email:
        return None
    result = session.execute(text("""
        SELECT s.student_id, s.name, s.target_score, s.school_class, 
               s.category, s.programming_language, s.goal_text
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
            "goal_text": row[6]
        }
    return None


def get_subscription_info(session, user_id: int) -> Optional[dict]:
    """Получить информацию о подписке."""
    result = session.execute(text("""
        SELECT us.lessons_remaining, us.ends_at, us.status, tp.title, tp.lessons_count
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
            "plan_title": row[3],
            "lessons_total": row[4]
        }
    return None


def get_lessons_for_student(session, student_id: int, limit: int = 5, upcoming_only: bool = True) -> list:
    """Получить уроки для студента."""
    if upcoming_only:
        result = session.execute(text("""
            SELECT l.lesson_id, l.lesson_date, l.topic, l.status, l.duration, l.lesson_type
            FROM "Lessons" l
            WHERE l.student_id = :student_id
              AND l.lesson_date >= NOW() - INTERVAL '1 hour'
              AND l.status IN ('planned', 'in_progress')
            ORDER BY l.lesson_date ASC
            LIMIT :limit
        """), {"student_id": student_id, "limit": limit})
    else:
        result = session.execute(text("""
            SELECT l.lesson_id, l.lesson_date, l.topic, l.status, l.duration, l.lesson_type
            FROM "Lessons" l
            WHERE l.student_id = :student_id
            ORDER BY l.lesson_date DESC
            LIMIT :limit
        """), {"student_id": student_id, "limit": limit})
    
    lessons = []
    for row in result.fetchall():
        lessons.append({
            "lesson_id": row[0],
            "lesson_date": row[1],
            "topic": row[2],
            "status": row[3],
            "duration": row[4],
            "lesson_type": row[5]
        })
    return lessons


def get_student_stats(session, student_id: int) -> dict:
    """Получить статистику студента."""
    result = session.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE l.status = 'completed') as completed,
            COUNT(*) FILTER (WHERE l.status = 'planned') as planned,
            COUNT(*) FILTER (WHERE l.status = 'cancelled') as cancelled,
            COUNT(*) as total
        FROM "Lessons" l
        WHERE l.student_id = :student_id
    """), {"student_id": student_id})
    row = result.fetchone()
    
    # Получаем статистику по ДЗ
    hw_result = session.execute(text("""
        SELECT 
            COUNT(*) FILTER (WHERE lt.submission_status = 'checked') as hw_checked,
            COUNT(*) FILTER (WHERE lt.submission_status = 'submitted') as hw_pending,
            COUNT(*) FILTER (WHERE lt.submission_correct = TRUE) as hw_correct,
            COUNT(*) as hw_total
        FROM "LessonTasks" lt
        JOIN "Lessons" l ON l.lesson_id = lt.lesson_id
        WHERE l.student_id = :student_id AND lt.assignment_type = 'homework'
    """), {"student_id": student_id})
    hw_row = hw_result.fetchone()
    
    return {
        "lessons_completed": row[0] if row else 0,
        "lessons_planned": row[1] if row else 0,
        "lessons_cancelled": row[2] if row else 0,
        "lessons_total": row[3] if row else 0,
        "hw_checked": hw_row[0] if hw_row else 0,
        "hw_pending": hw_row[1] if hw_row else 0,
        "hw_correct": hw_row[2] if hw_row else 0,
        "hw_total": hw_row[3] if hw_row else 0
    }


def format_lesson_type(lesson_type: str) -> str:
    """Форматирование типа урока."""
    types = {
        'regular': '📚 Обычный',
        'introductory': '👋 Вводный',
        'diagnostic': '🔍 Диагностика',
        'exam': '📝 Проверочная',
        'consultation': '💬 Консультация'
    }
    return types.get(lesson_type, '📚 Урок')


def format_lesson_status(status: str) -> str:
    """Форматирование статуса урока."""
    statuses = {
        'planned': '📅 Запланирован',
        'in_progress': '🟢 Идёт сейчас',
        'completed': '✅ Проведён',
        'cancelled': '❌ Отменён'
    }
    return statuses.get(status, status)


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
    await update.message.reply_text(
        HELP_MESSAGE,
        reply_markup=get_main_keyboard()
    )


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /link КОД — привязка аккаунта."""
    if not context.args:
        await update.message.reply_text(LINK_USAGE, reply_markup=get_main_keyboard())
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
            await update.message.reply_text(LINK_ALREADY_LINKED, reply_markup=get_main_keyboard())
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
            await update.message.reply_text(LINK_INVALID_CODE, reply_markup=get_main_keyboard())
            return
        
        profile_id, user_id, expires_at, username = row
        
        # Проверяем срок действия
        if expires_at and expires_at < datetime.utcnow():
            await update.message.reply_text(LINK_CODE_EXPIRED, reply_markup=get_main_keyboard())
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
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /unlink — отвязка аккаунта."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(UNLINK_NOT_LINKED, reply_markup=get_main_keyboard())
            return
        
        # Отвязываем
        session.execute(text("""
            UPDATE "UserProfiles"
            SET telegram_chat_id = NULL
            WHERE telegram_chat_id = :chat_id
        """), {"chat_id": chat_id})
        session.commit()
        
        await update.message.reply_text(UNLINK_SUCCESS, reply_markup=get_main_keyboard())
        logger.info(f"User {user['username']} unlinked Telegram")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in unlink_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /me — информация о профиле."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
            return
        
        # Формируем профиль
        name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
        student = get_student_by_email(session, user['email'])
        sub = get_subscription_info(session, user['id'])
        
        text_parts = [f"👤 *{name}*"]
        text_parts.append(f"📧 {user['email'] or 'Email не указан'}")
        text_parts.append("")
        
        # Информация о студенте
        if student:
            if student['school_class']:
                text_parts.append(f"🎓 {student['school_class']} класс")
            if student['target_score']:
                text_parts.append(f"🎯 Цель: {student['target_score']} баллов")
            if student['programming_language']:
                text_parts.append(f"💻 Язык: {student['programming_language']}")
            if student['category']:
                text_parts.append(f"📂 Категория: {student['category']}")
        
        text_parts.append("")
        
        # Подписка
        text_parts.append("*💳 Подписка:*")
        if sub:
            if sub['plan_title']:
                text_parts.append(f"📋 Тариф: {sub['plan_title']}")
            if sub['lessons_remaining'] is not None:
                total = sub['lessons_total'] or '∞'
                text_parts.append(f"📚 Уроков: {sub['lessons_remaining']} из {total}")
            if sub['ends_at']:
                text_parts.append(f"📅 Действует до: {sub['ends_at'].strftime('%d.%m.%Y')}")
        else:
            text_parts.append("_Подписка не активна_")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in me_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def lessons_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /lessons — ближайшие уроки."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
            return
        
        student = get_student_by_email(session, user['email'])
        if not student:
            await update.message.reply_text(
                "📚 Профиль ученика не найден.\n\nОбратитесь к преподавателю для настройки.",
                reply_markup=get_main_keyboard()
            )
            return
        
        lessons = get_lessons_for_student(session, student['student_id'], limit=7)
        
        if not lessons:
            await update.message.reply_text(
                NO_UPCOMING_LESSONS + "\n\nКак только урок будет запланирован, я пришлю уведомление! 📩",
                reply_markup=get_main_keyboard()
            )
            return
        
        text_parts = ["📅 *Ближайшие уроки:*\n"]
        
        for i, lesson in enumerate(lessons, 1):
            date = lesson['lesson_date']
            date_str = date.strftime('%d.%m %H:%M') if date else "Дата не указана"
            topic_str = lesson['topic'] or "Тема не указана"
            duration = lesson['duration'] or 60
            
            status_emoji = "🟢" if lesson['status'] == 'in_progress' else "📅"
            if lesson['status'] == 'completed':
                status_emoji = "✅"
            
            text_parts.append(f"{status_emoji} *{date_str}* ({duration} мин)")
            text_parts.append(f"   📝 {topic_str}")
            text_parts.append("")
        
        text_parts.append(f"_Всего запланировано: {len(lessons)}_")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in lessons_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — статистика."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
            return
        
        student = get_student_by_email(session, user['email'])
        if not student:
            await update.message.reply_text(
                "📊 Профиль ученика не найден.\n\nОбратитесь к преподавателю для настройки.",
                reply_markup=get_main_keyboard()
            )
            return
        
        stats = get_student_stats(session, student['student_id'])
        sub = get_subscription_info(session, user['id'])
        
        text_parts = ["📊 *Твоя статистика:*\n"]
        
        # Уроки
        text_parts.append("*📚 Уроки:*")
        text_parts.append(f"✅ Проведено: {stats['lessons_completed']}")
        text_parts.append(f"📅 Запланировано: {stats['lessons_planned']}")
        if stats['lessons_cancelled'] > 0:
            text_parts.append(f"❌ Отменено: {stats['lessons_cancelled']}")
        text_parts.append("")
        
        # Домашние задания
        if stats['hw_total'] > 0:
            text_parts.append("*📝 Домашние задания:*")
            text_parts.append(f"✅ Проверено: {stats['hw_checked']}")
            if stats['hw_pending'] > 0:
                text_parts.append(f"⏳ Ожидает проверки: {stats['hw_pending']}")
            if stats['hw_correct'] > 0:
                accuracy = round(stats['hw_correct'] / max(stats['hw_checked'], 1) * 100)
                text_parts.append(f"🎯 Точность: {accuracy}%")
            text_parts.append("")
        
        # Подписка
        if sub and sub['lessons_remaining'] is not None:
            text_parts.append("*💳 Баланс:*")
            text_parts.append(f"📚 Осталось уроков: {sub['lessons_remaining']}")
            if sub['lessons_remaining'] <= 2:
                text_parts.append("⚠️ _Уроки заканчиваются!_")
        
        await update.message.reply_text(
            "\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in stats_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
    finally:
        close_session(session)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /settings — настройки уведомлений."""
    chat_id = update.effective_chat.id
    
    session = get_session()
    try:
        user = get_user_by_chat_id(session, chat_id)
        if not user:
            await update.message.reply_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
            return
        
        enabled = user['notifications_enabled']
        status = NOTIFICATIONS_ENABLED if enabled else NOTIFICATIONS_DISABLED
        
        await update.message.reply_text(
            SETTINGS_TEMPLATE.format(status=status),
            reply_markup=get_settings_keyboard(enabled)
        )
        
    except Exception as e:
        logger.error(f"Error in settings_command: {e}", exc_info=True)
        await update.message.reply_text(ERROR_GENERIC, reply_markup=get_main_keyboard())
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
                "🏠 *Главное меню*\n\nВыберите действие:",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        
        elif data == "profile":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
                return
            
            name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
            student = get_student_by_email(session, user['email'])
            sub = get_subscription_info(session, user['id'])
            
            text_parts = [f"👤 *{name}*"]
            text_parts.append(f"📧 {user['email'] or 'Email не указан'}")
            text_parts.append("")
            
            if student:
                if student['school_class']:
                    text_parts.append(f"🎓 {student['school_class']} класс")
                if student['target_score']:
                    text_parts.append(f"🎯 Цель: {student['target_score']} баллов")
            
            text_parts.append("")
            text_parts.append("*💳 Подписка:*")
            if sub:
                if sub['plan_title']:
                    text_parts.append(f"📋 {sub['plan_title']}")
                if sub['lessons_remaining'] is not None:
                    text_parts.append(f"📚 Осталось уроков: {sub['lessons_remaining']}")
            else:
                text_parts.append("_Не активна_")
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "lessons":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
                return
            
            student = get_student_by_email(session, user['email'])
            if not student:
                await query.edit_message_text(
                    "📚 Профиль ученика не найден.",
                    reply_markup=get_back_keyboard()
                )
                return
            
            lessons = get_lessons_for_student(session, student['student_id'], limit=7)
            
            if not lessons:
                await query.edit_message_text(
                    NO_UPCOMING_LESSONS,
                    reply_markup=get_back_keyboard()
                )
                return
            
            text_parts = ["📅 *Ближайшие уроки:*\n"]
            for lesson in lessons:
                date = lesson['lesson_date']
                date_str = date.strftime('%d.%m %H:%M') if date else "?"
                topic_str = lesson['topic'] or "Без темы"
                status_emoji = "🟢" if lesson['status'] == 'in_progress' else "📅"
                text_parts.append(f"{status_emoji} *{date_str}* ({lesson['duration']} мин)")
                text_parts.append(f"   {topic_str}")
                text_parts.append("")
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "stats":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
                return
            
            student = get_student_by_email(session, user['email'])
            if not student:
                await query.edit_message_text(
                    "📊 Профиль ученика не найден.",
                    reply_markup=get_back_keyboard()
                )
                return
            
            stats = get_student_stats(session, student['student_id'])
            sub = get_subscription_info(session, user['id'])
            
            text_parts = ["📊 *Статистика:*\n"]
            text_parts.append(f"✅ Проведено уроков: {stats['lessons_completed']}")
            text_parts.append(f"📅 Запланировано: {stats['lessons_planned']}")
            
            if stats['hw_total'] > 0:
                text_parts.append("")
                text_parts.append(f"📝 ДЗ проверено: {stats['hw_checked']}")
                if stats['hw_pending'] > 0:
                    text_parts.append(f"⏳ Ожидает: {stats['hw_pending']}")
            
            if sub and sub['lessons_remaining'] is not None:
                text_parts.append("")
                text_parts.append(f"📚 Осталось уроков: {sub['lessons_remaining']}")
            
            await query.edit_message_text(
                "\n".join(text_parts),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )
        
        elif data == "settings":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
                return
            
            enabled = user['notifications_enabled']
            status = NOTIFICATIONS_ENABLED if enabled else NOTIFICATIONS_DISABLED
            
            await query.edit_message_text(
                SETTINGS_TEMPLATE.format(status=status),
                reply_markup=get_settings_keyboard(enabled)
            )
        
        elif data == "toggle_notifications":
            if not user:
                await query.edit_message_text(PROFILE_NOT_LINKED, reply_markup=get_main_keyboard())
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
            
            await query.edit_message_text(UNLINK_SUCCESS, reply_markup=get_main_keyboard())
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error in callback_handler: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                ERROR_GENERIC + "\n\nПопробуйте ещё раз.",
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
