#!/usr/bin/env python3
"""
Тестовый скрипт для проверки всей цепочки уведомлений о рефералах.
Создает тестовое уведомление и проверяет, что оно отправляется.
"""
import os
import sys
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

from app import create_app
from app.models import db, User, UserProfile, UserNotification, BotAdmin, ReferralCode, ReferralUsage
from app.notifications.service import notify_user

app = create_app()

def test_referral_notification():
    """Тестируем создание и отправку уведомления о реферале."""
    with app.app_context():
        print("=" * 80)
        print("🧪 ТЕСТИРОВАНИЕ УВЕДОМЛЕНИЙ О РЕФЕРАЛАХ")
        print("=" * 80)

        # 1. Проверим BotAdmin'ов
        print("\n1️⃣  ПРОВЕРКА BotAdmin'ов:")
        admins = BotAdmin.query.filter_by(is_active=True).all()
        if not admins:
            print("❌ НЕТ активных BotAdmin'ов!")
            print("   Создайте: python scripts/setup_bot_admin.py")
            return False

        print(f"✅ Найдено {len(admins)} активных BotAdmin'ов:")
        valid_admins = []
        for admin in admins:
            user = User.query.get(admin.user_id)
            profile = UserProfile.query.filter_by(user_id=admin.user_id).first()

            if not user:
                print(f"   ❌ Admin {admin.admin_id}: пользователь {admin.user_id} не найден")
                continue

            if not profile:
                print(f"   ❌ Admin {admin.admin_id}: профиль не найден для {user.username}")
                continue

            if not profile.telegram_chat_id:
                print(f"   ❌ Admin {admin.admin_id}: Telegram не привязан для {user.username}")
                continue

            if not profile.telegram_notifications_enabled:
                print(f"   ❌ Admin {admin.admin_id}: уведомления отключены для {user.username}")
                continue

            if profile.tg_notify_referral_used is False:
                print(f"   ❌ Admin {admin.admin_id}: уведомления о рефералах отключены для {user.username}")
                continue

            print(f"   ✅ Admin {admin.admin_id}: {user.username} (chat_id: {profile.telegram_chat_id})")
            valid_admins.append((admin, user, profile))

        if not valid_admins:
            print("❌ НЕТ валидных админов для отправки уведомлений!")
            return False

        # 2. Создадим тестовое уведомление
        print("\n2️⃣  СОЗДАНИЕ ТЕСТОВОГО УВЕДОМЛЕНИЯ:")
        test_admin = valid_admins[0][0]  # Первый валидный админ

        try:
            notify_user(
                test_admin.user_id,
                kind='referral_used',
                title='🧪 Тестовое уведомление о реферале',
                body='Это тестовое уведомление для проверки работы системы.',
                meta={'test': True, 'timestamp': datetime.now().isoformat()}
            )
            db.session.commit()
            print("✅ Тестовое уведомление создано в БД")
        except Exception as e:
            print(f"❌ Ошибка при создании уведомления: {e}")
            return False

        # 3. Проверим, что уведомление появилось в БД
        print("\n3️⃣  ПРОВЕРКА В БД:")
        recent = UserNotification.query.filter_by(
            user_id=test_admin.user_id,
            kind='referral_used'
        ).order_by(UserNotification.created_at.desc()).first()

        if not recent:
            print("❌ Уведомление не найдено в БД!")
            return False

        print(f"✅ Уведомление найдено:")
        print(f"   ID: {recent.notification_id}")
        print(f"   User ID: {recent.user_id}")
        print(f"   Kind: {recent.kind}")
        print(f"   Title: {recent.title}")
        print(f"   Telegram sent: {recent.telegram_sent}")
        print(f"   Created: {recent.created_at}")

        # 4. Инструкции по проверке
        print("\n4️⃣  СЛЕДУЮЩИЕ ШАГИ:")
        print("   1. Убедитесь, что urep_bot запущен:")
        print("      python urep_bot/run_bot.py")
        print("   2. Подождите 30-60 секунд")
        print("   3. Проверьте Telegram на наличие сообщения")
        print("   4. Если не пришло, проверьте логи urep_bot")
        print("   5. Проверьте статус в БД:")
        print(f"      SELECT telegram_sent FROM \"UserNotifications\" WHERE notification_id = {recent.notification_id};")

        return True

if __name__ == '__main__':
    success = test_referral_notification()
    if success:
        print("\n🎉 ТЕСТ ПРОШЕЛ УСПЕШНО!")
        print("Если уведомление не пришло в Telegram, проблема в urep_bot.")
    else:
        print("\n❌ ТЕСТ НЕ ПРОШЕЛ!")
        print("Исправьте проблемы выше и повторите.")
