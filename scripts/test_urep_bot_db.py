#!/usr/bin/env python3
"""
Проверка, что urep_bot может читать уведомления из БД.
Запустите этот скрипт вместо полного urep_bot для тестирования.
"""
import os
import sys
import asyncio
from datetime import datetime

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, root)
os.chdir(root)

try:
    from dotenv import load_dotenv
    env_path = os.path.join(root, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)
except ImportError:
    pass

# Импортируем из urep_bot
from urep_bot.config import DATABASE_URL
from urep_bot.db import init_db, get_session, close_session
from urep_bot.notifications import process_pending_notifications

# Импортируем Telegram Bot (фейковый для теста)
class FakeBot:
    async def send_message(self, chat_id, text, **kwargs):
        print(f"📤 [FAKE] Отправка в chat_id={chat_id}: {text[:100]}...")
        return True

async def test_urep_bot_db():
    """Тестируем подключение urep_bot к БД и чтение уведомлений."""
    print("=" * 80)
    print("🔍 ТЕСТИРОВАНИЕ ПОДКЛЮЧЕНИЯ UREP_BOT К БД")
    print("=" * 80)

    # 1. Проверим конфигурацию
    print(f"\n1️⃣  КОНФИГУРАЦИЯ:")
    print(f"   DATABASE_URL: {DATABASE_URL[:50]}..." if DATABASE_URL else "❌ DATABASE_URL не задан")

    if not DATABASE_URL:
        print("❌ urep_bot не может подключиться к БД!")
        return False

    # 2. Инициализируем БД
    print(f"\n2️⃣  ПОДКЛЮЧЕНИЕ К БД:")
    try:
        init_db()
        print("✅ Подключение к БД успешно")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False

    # 3. Проверим чтение уведомлений
    print(f"\n3️⃣  ЧТЕНИЕ УВЕДОМЛЕНИЙ:")
    session = get_session()
    try:
        from sqlalchemy import text
        result = session.execute(text("""
            SELECT COUNT(*) FROM "UserNotifications"
            WHERE kind = 'referral_used' AND telegram_sent = FALSE
        """))
        count = result.fetchone()[0]
        print(f"✅ Найдено {count} неотправленных уведомлений о рефералах")

        if count > 0:
            # Покажем последние 3
            result = session.execute(text("""
                SELECT notification_id, user_id, title, created_at
                FROM "UserNotifications"
                WHERE kind = 'referral_used' AND telegram_sent = FALSE
                ORDER BY created_at DESC
                LIMIT 3
            """))
            rows = result.fetchall()
            print("   Последние неотправленные:")
            for row in rows:
                print(f"     ID {row[0]}: {row[2]} (user {row[1]})")

        # 4. Проверим наличие профилей с привязанным Telegram
        result = session.execute(text("""
            SELECT COUNT(DISTINCT up.user_id)
            FROM "UserProfiles" up
            WHERE up.telegram_chat_id IS NOT NULL
              AND (up.telegram_notifications_enabled = TRUE OR up.telegram_notifications_enabled IS NULL)
              AND COALESCE(up.tg_notify_referral_used, TRUE) = TRUE
        """))
        profile_count = result.fetchone()[0]
        print(f"✅ Найдено {profile_count} профилей с привязанным Telegram и включенными уведомлениями о рефералах")

        if profile_count == 0:
            print("❌ НЕТ профилей с привязанным Telegram!")
            print("   Администраторы должны привязать Telegram через /link КОД")

    except Exception as e:
        print(f"❌ Ошибка чтения из БД: {e}")
        return False
    finally:
        close_session(session)

    # 5. Тестируем отправку уведомлений
    print(f"\n4️⃣  ТЕСТИРОВАНИЕ ОТПРАВКИ:")
    try:
        fake_bot = FakeBot()
        sent_count = await process_pending_notifications(fake_bot)
        print(f"✅ process_pending_notifications вернул: {sent_count}")
        print("   (Это количество отправленных уведомлений)")
    except Exception as e:
        print(f"❌ Ошибка при тестировании отправки: {e}")
        return False

    print(f"\n🎉 ВСЕ ПРОВЕРКИ ПРОШЛИ УСПЕШНО!")
    print("Если уведомления не приходят в реальном Telegram:")
    print("1. Убедитесь, что urep_bot запущен с правильным BOT_TOKEN")
    print("2. Проверьте логи urep_bot на ошибки")
    print("3. Убедитесь, что BOT_TOKEN имеет доступ к отправке сообщений")

    return True

if __name__ == '__main__':
    asyncio.run(test_urep_bot_db())
