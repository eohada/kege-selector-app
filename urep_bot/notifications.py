"""
Фоновые задачи: отправка уведомлений и напоминаний.
"""
import logging
import json
from datetime import datetime, timedelta
from typing import Optional

from telegram import Bot
from telegram.error import TelegramError
from sqlalchemy import text

from urep_bot.config import APP_URL
from urep_bot.db import get_session, close_session
from urep_bot.messages import NOTIFICATION_TEMPLATES

logger = logging.getLogger(__name__)

KIND_SETTINGS_MAP = {
    'lesson_reminder_1h': 'tg_notify_lesson_reminder',
    'lesson_reminder_15m': 'tg_notify_lesson_reminder',
    'lesson_scheduled': 'tg_notify_lesson_scheduled',
    'lesson_review_graded': 'tg_notify_homework_checked',
    'lesson_task_graded': 'tg_notify_homework_checked',
    'assignment_graded': 'tg_notify_homework_checked',
    'lesson_review_returned': 'tg_notify_homework_returned',
    'lesson_task_returned': 'tg_notify_homework_returned',
    'assignment_returned': 'tg_notify_homework_returned',
    'lesson_message': 'tg_notify_new_message',
    'assignment_assigned': 'tg_notify_new_message',
    'lessons_low': 'tg_notify_low_lessons',
    'platform_news': 'tg_notify_news',
    'news': 'tg_notify_news',
    'generic': 'tg_notify_news',
}


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
                un.user_id,
                un.kind,
                un.title,
                un.body,
                un.link_url,
                un.meta,
                up.telegram_chat_id,
                COALESCE(up.tg_notify_lesson_reminder, TRUE) AS tg_notify_lesson_reminder,
                COALESCE(up.tg_notify_homework_checked, TRUE) AS tg_notify_homework_checked,
                COALESCE(up.tg_notify_homework_returned, TRUE) AS tg_notify_homework_returned,
                COALESCE(up.tg_notify_new_message, TRUE) AS tg_notify_new_message,
                COALESCE(up.tg_notify_lesson_scheduled, TRUE) AS tg_notify_lesson_scheduled,
                COALESCE(up.tg_notify_low_lessons, TRUE) AS tg_notify_low_lessons,
                COALESCE(up.tg_notify_news, TRUE) AS tg_notify_news
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
        processed_ids: set[int] = set()
        
        for notif in notifications:
            (
                notif_id, user_id, kind, title, body, link_url, meta, chat_id,
                tg_notify_lesson_reminder, tg_notify_homework_checked, tg_notify_homework_returned,
                tg_notify_new_message, tg_notify_lesson_scheduled, tg_notify_low_lessons, tg_notify_news
            ) = notif
            if notif_id in processed_ids:
                continue
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = None
            settings = {
                'tg_notify_lesson_reminder': tg_notify_lesson_reminder,
                'tg_notify_homework_checked': tg_notify_homework_checked,
                'tg_notify_homework_returned': tg_notify_homework_returned,
                'tg_notify_new_message': tg_notify_new_message,
                'tg_notify_lesson_scheduled': tg_notify_lesson_scheduled,
                'tg_notify_low_lessons': tg_notify_low_lessons,
                'tg_notify_news': tg_notify_news,
            }
            
            setting_key = KIND_SETTINGS_MAP.get(kind)
            if setting_key and not settings.get(setting_key, True):
                session.execute(text("""
                    UPDATE "UserNotifications"
                    SET telegram_sent = TRUE
                    WHERE notification_id = :notif_id
                """), {"notif_id": notif_id})
                continue
            
            # Агрегация уведомлений о заданиях по уроку/типу
            if kind == 'assignment_assigned':
                lesson_id = (meta or {}).get('lesson_id')
                assignment_type = (meta or {}).get('assignment_type')
                task_numbers = (meta or {}).get('task_numbers') or {}
                pending = [{
                    'notif_id': notif_id,
                    'user_id': user_id,
                    'chat_id': chat_id,
                    'title': title,
                    'body': body,
                    'link_url': link_url,
                    'lesson_id': lesson_id,
                    'assignment_type': assignment_type,
                    'task_numbers': task_numbers,
                }]
                for n in notifications:
                    if n is notif:
                        continue
                    n_id, n_user_id, n_kind, n_title, n_body, n_link_url, n_meta, n_chat_id, *_ = n
                    if n_kind != 'assignment_assigned':
                        continue
                    if n_user_id != user_id:
                        continue
                    if n_chat_id != chat_id:
                        continue
                    n_meta_obj = None
                    if isinstance(n_meta, str):
                        try:
                            n_meta_obj = json.loads(n_meta)
                        except Exception:
                            n_meta_obj = None
                    else:
                        n_meta_obj = n_meta
                    if (n_meta_obj or {}).get('lesson_id') != lesson_id:
                        continue
                    if (n_meta_obj or {}).get('assignment_type') != assignment_type:
                        continue
                    pending.append({
                        'notif_id': n_id,
                        'user_id': n_user_id,
                        'chat_id': n_chat_id,
                        'title': n_title,
                        'body': n_body,
                        'link_url': n_link_url,
                        'lesson_id': lesson_id,
                        'assignment_type': assignment_type,
                        'task_numbers': (n_meta_obj or {}).get('task_numbers') or {},
                    })

                # Собираем суммарные количества
                merged_counts: dict[int, int] = {}
                for p in pending:
                    for k, v in (p.get('task_numbers') or {}).items():
                        try:
                            num = int(k)
                            merged_counts[num] = merged_counts.get(num, 0) + int(v)
                        except Exception:
                            continue

                def _plural(count: int) -> str:
                    if count % 10 == 1 and count % 100 != 11:
                        return 'задание'
                    if 2 <= count % 10 <= 4 and not (12 <= count % 100 <= 14):
                        return 'задания'
                    return 'заданий'

                if merged_counts:
                    parts = [f"{cnt} {_plural(cnt)} №{num}" for num, cnt in sorted(merged_counts.items())]
                    summary = ", ".join(parts)
                else:
                    summary = "нет заданий"

                label_map = {'homework': 'Домашняя работа', 'classwork': 'Классная работа', 'exam': 'Проверочная работа'}
                label = label_map.get(assignment_type, 'Задания')
                agg_title = f"Новые задания — {label}"
                agg_body = f"{label}: {summary}"
                agg_link = pending[0].get('link_url')
                agg_meta = {'lesson_id': lesson_id, 'assignment_type': assignment_type}

                message_text = format_notification('assignment_assigned', agg_title, agg_body, agg_link, agg_meta)
                success = await send_telegram_notification(bot, chat_id, message_text)

                for p in pending:
                    session.execute(text("""
                        UPDATE "UserNotifications"
                        SET telegram_sent = TRUE
                        WHERE notification_id = :notif_id
                    """), {"notif_id": p['notif_id']})
                    processed_ids.add(int(p['notif_id']))
                if success:
                    sent_count += 1
                continue

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
              AND COALESCE(up.tg_notify_lesson_reminder, TRUE) = TRUE
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
              AND COALESCE(up.tg_notify_low_lessons, TRUE) = TRUE
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


async def process_error_report_replies(bot: Bot):
    """Отправка ответов админа на сообщения об ошибках."""
    session = get_session()
    try:
        result = session.execute(text("""
            SELECT report_id, telegram_chat_id, admin_reply, status
            FROM "BotErrorReports"
            WHERE admin_reply IS NOT NULL
              AND reply_sent_at IS NULL
              AND telegram_chat_id IS NOT NULL
            ORDER BY report_id ASC
            LIMIT 50
        """))
        rows = result.fetchall()
        if not rows:
            return 0
        
        sent_count = 0
        for report_id, chat_id, admin_reply, status in rows:
            message = f"✅ <b>Ответ по вашему обращению</b>\n\n{admin_reply}"
            success = await send_telegram_notification(bot, chat_id, message)
            if success:
                session.execute(text("""
                    UPDATE "BotErrorReports"
                    SET reply_sent_at = NOW(),
                        replied_at = NOW(),
                        status = CASE WHEN status = 'closed' THEN status ELSE 'answered' END
                    WHERE report_id = :report_id
                """), {"report_id": report_id})
                sent_count += 1
        
        session.commit()
        return sent_count
    except Exception as e:
        session.rollback()
        logger.error(f"Error sending error report replies: {e}", exc_info=True)
        return 0
    finally:
        close_session(session)
