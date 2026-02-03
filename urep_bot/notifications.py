"""
Фоновые задачи: отправка уведомлений и напоминаний.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError
from sqlalchemy import text

from urep_bot.config import APP_URL
from urep_bot.db import get_session, close_session
from urep_bot.messages import NOTIFICATION_TEMPLATES

logger = logging.getLogger(__name__)


def format_notification(kind: str, title: str, body: Optional[str], link_url: Optional[str], meta: Optional[dict] = None) -> str:
    """Форматирование уведомления для отправки."""
    template = NOTIFICATION_TEMPLATES.get(kind, NOTIFICATION_TEMPLATES['generic'])
    
    # Формируем текст
    text_parts = []
    
    try:
        formatted = template.format(
            title=title or "",
            body=body or "",
            date=meta.get('date', '') if meta else '',
            topic=meta.get('topic', '') if meta else '',
            link=link_url or '',
            count=meta.get('count', 0) if meta else 0
        )
        text_parts.append(formatted)
    except Exception:
        # Fallback
        if title:
            text_parts.append(title)
        if body:
            text_parts.append(body)
    
    # Добавляем ссылку если есть
    if link_url:
        full_url = link_url if link_url.startswith('http') else f"{APP_URL}{link_url}"
        text_parts.append(f"\n🔗 {full_url}")
    
    return "\n".join(text_parts)


async def send_telegram_notification(bot: Bot, chat_id: int, text: str) -> bool:
    """Отправка уведомления в Telegram."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return True
    except TelegramError as e:
        logger.warning(f"Failed to send notification to {chat_id}: {e}")
        # Если пользователь заблокировал бота - отвязываем
        if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
            session = get_session()
            try:
                session.execute(text("""
                    UPDATE "UserProfiles"
                    SET telegram_chat_id = NULL
                    WHERE telegram_chat_id = :chat_id
                """), {"chat_id": chat_id})
                session.commit()
                logger.info(f"Unlinked blocked user chat_id={chat_id}")
            except Exception:
                session.rollback()
            finally:
                close_session(session)
        return False
    except Exception as e:
        logger.error(f"Error sending notification: {e}", exc_info=True)
        return False


async def process_pending_notifications(bot: Bot):
    """Обработка ожидающих уведомлений из UserNotification."""
    session = get_session()
    try:
        # Получаем непрочитанные уведомления для пользователей с привязанным Telegram
        # Используем COALESCE для совместимости с БД без новых колонок
        result = session.execute(text("""
            SELECT 
                un.notification_id,
                un.kind,
                un.title,
                un.body,
                un.link_url,
                un.meta,
                up.telegram_chat_id
            FROM "UserNotifications" un
            JOIN "UserProfiles" up ON up.user_id = un.user_id
            WHERE un.telegram_sent = FALSE
              AND up.telegram_chat_id IS NOT NULL
              AND (up.telegram_notifications_enabled = TRUE OR up.telegram_notifications_enabled IS NULL)
              AND un.created_at > NOW() - INTERVAL '24 hours'
            ORDER BY un.created_at ASC
            LIMIT 50
        """))
        
        notifications = result.fetchall()
        
        if not notifications:
            return 0
        
        sent_count = 0
        
        for notif in notifications:
            notif_id, kind, title, body, link_url, meta, chat_id = notif
            
            # Форматируем и отправляем
            message_text = format_notification(kind, title, body, link_url, meta)
            
            success = await send_telegram_notification(bot, chat_id, message_text)
            
            if success:
                # Помечаем как отправленное
                session.execute(text("""
                    UPDATE "UserNotifications"
                    SET telegram_sent = TRUE
                    WHERE notification_id = :notif_id
                """), {"notif_id": notif_id})
                sent_count += 1
            else:
                # При ошибке тоже помечаем, чтобы не спамить
                session.execute(text("""
                    UPDATE "UserNotifications"
                    SET telegram_sent = TRUE
                    WHERE notification_id = :notif_id
                """), {"notif_id": notif_id})
        
        session.commit()
        
        if sent_count > 0:
            logger.info(f"Sent {sent_count} notifications to Telegram")
        
        return sent_count
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error processing notifications: {e}", exc_info=True)
        return 0
    finally:
        close_session(session)


async def process_lesson_reminders(bot: Bot):
    """Отправка напоминаний об уроках."""
    session = get_session()
    try:
        now = datetime.utcnow()
        
        # Уроки через ~1 час (55-65 минут)
        hour_from = now + timedelta(minutes=55)
        hour_to = now + timedelta(minutes=65)
        
        # Уроки через ~15 минут (10-20 минут)
        fifteen_from = now + timedelta(minutes=10)
        fifteen_to = now + timedelta(minutes=20)
        
        # Получаем уроки для напоминаний
        result = session.execute(text("""
            SELECT 
                l.lesson_id,
                l.lesson_date,
                l.topic,
                s.name as student_name,
                up.telegram_chat_id,
                CASE 
                    WHEN l.lesson_date BETWEEN :hour_from AND :hour_to THEN '1h'
                    WHEN l.lesson_date BETWEEN :fifteen_from AND :fifteen_to THEN '15m'
                END as reminder_type
            FROM "Lessons" l
            JOIN "Students" s ON s.student_id = l.student_id
            JOIN "UserProfiles" up ON up.user_id = s.user_id
            WHERE l.status = 'planned'
              AND up.telegram_chat_id IS NOT NULL
              AND (up.telegram_notifications_enabled = TRUE OR up.telegram_notifications_enabled IS NULL)
              AND (
                  (l.lesson_date BETWEEN :hour_from AND :hour_to)
                  OR (l.lesson_date BETWEEN :fifteen_from AND :fifteen_to)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM "UserNotifications" un
                  WHERE un.user_id = s.user_id
                    AND un.kind IN ('lesson_reminder_1h', 'lesson_reminder_15m')
                    AND un.meta->>'lesson_id' = l.lesson_id::text
                    AND un.created_at > NOW() - INTERVAL '2 hours'
              )
        """), {
            "hour_from": hour_from,
            "hour_to": hour_to,
            "fifteen_from": fifteen_from,
            "fifteen_to": fifteen_to
        })
        
        lessons = result.fetchall()
        
        if not lessons:
            return 0
        
        sent_count = 0
        
        for lesson in lessons:
            lesson_id, date, topic, student_name, chat_id, reminder_type = lesson
            
            if reminder_type == '1h':
                kind = 'lesson_reminder_1h'
                time_text = "через 1 час"
            else:
                kind = 'lesson_reminder_15m'
                time_text = "через 15 минут"
            
            date_str = date.strftime('%H:%M') if date else ""
            topic_str = topic or "Без темы"
            
            message = f"⏰ Урок {time_text}!\n\n📅 {date_str}\n📝 {topic_str}\n\n🔗 {APP_URL}/lessons"
            
            success = await send_telegram_notification(bot, chat_id, message)
            
            if success:
                # Создаём запись в UserNotifications чтобы не отправлять повторно
                session.execute(text("""
                    INSERT INTO "UserNotifications" (user_id, kind, title, body, meta, telegram_sent, created_at)
                    SELECT s.user_id, :kind, :title, :body, :meta, TRUE, NOW()
                    FROM "Students" s
                    JOIN "Lessons" l ON l.student_id = s.student_id
                    WHERE l.lesson_id = :lesson_id
                """), {
                    "kind": kind,
                    "title": f"Напоминание об уроке",
                    "body": topic_str,
                    "meta": f'{{"lesson_id": {lesson_id}}}',
                    "lesson_id": lesson_id
                })
                sent_count += 1
        
        session.commit()
        
        if sent_count > 0:
            logger.info(f"Sent {sent_count} lesson reminders")
        
        return sent_count
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error processing reminders: {e}", exc_info=True)
        return 0
    finally:
        close_session(session)


async def check_low_lessons(bot: Bot):
    """Проверка пользователей с малым количеством оставшихся уроков."""
    session = get_session()
    try:
        # Пользователи с 2 или менее уроками
        result = session.execute(text("""
            SELECT 
                u.id as user_id,
                up.telegram_chat_id,
                us.lessons_remaining
            FROM "Users" u
            JOIN "UserProfiles" up ON up.user_id = u.id
            JOIN "UserSubscriptions" us ON us.user_id = u.id
            WHERE up.telegram_chat_id IS NOT NULL
              AND (up.telegram_notifications_enabled = TRUE OR up.telegram_notifications_enabled IS NULL)
              AND us.status = 'active'
              AND us.lessons_remaining IS NOT NULL
              AND us.lessons_remaining <= 2
              AND us.lessons_remaining > 0
              AND NOT EXISTS (
                  SELECT 1 FROM "UserNotifications" un
                  WHERE un.user_id = u.id
                    AND un.kind = 'lessons_low'
                    AND un.created_at > NOW() - INTERVAL '7 days'
              )
        """))
        
        users = result.fetchall()
        
        if not users:
            return 0
        
        sent_count = 0
        
        for user in users:
            user_id, chat_id, lessons_remaining = user
            
            message = f"⚠️ Осталось уроков: {lessons_remaining}\n\nПополните баланс для продолжения занятий.\n\n🔗 {APP_URL}/profile"
            
            success = await send_telegram_notification(bot, chat_id, message)
            
            if success:
                session.execute(text("""
                    INSERT INTO "UserNotifications" (user_id, kind, title, body, telegram_sent, created_at)
                    VALUES (:user_id, 'lessons_low', 'Уроки заканчиваются', :body, TRUE, NOW())
                """), {
                    "user_id": user_id,
                    "body": f"Осталось уроков: {lessons_remaining}"
                })
                sent_count += 1
        
        session.commit()
        
        if sent_count > 0:
            logger.info(f"Sent {sent_count} low lessons warnings")
        
        return sent_count
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error checking low lessons: {e}", exc_info=True)
        return 0
    finally:
        close_session(session)
