#!/usr/bin/env python3
"""
Диагностика уведомлений о рефералах на production сервере.
Запустите на сервере где работает приложение.
"""
import os
import sys
from datetime import datetime

# Добавим путь к приложению
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
from app.models import db, User, UserRole, UserProfile, UserNotification
from app.notifications.service import notify_user

app = create_app()

def diagnose_referral_notifications():
    """Полная диагностика системы уведомлений о рефералах."""
    with app.app_context():
        print("=" * 100)
        print("🔍 ДИАГНОСТИКА УВЕДОМЛЕНИЙ О РЕФЕРАЛАХ (PRODUCTION)")
        print("=" * 100)

        # 1. Проверим creator'а
        print("\n1️⃣  ПРОВЕРКА CREATOR'А:")
        creator = User.query.filter_by(username='creator').first()
        if not creator:
            print("❌ CREATOR НЕ НАЙДЕН В БД!")
            return False

        print(f"✅ Creator найден: ID {creator.id}")
        print(f"   Users.role: '{creator.role}'")

        # Проверим роли в UserRoles
        roles = UserRole.query.filter_by(user_id=creator.id).all()
        print(f"   Дополнительных ролей: {len(roles)}")
        for role in roles:
            print(f"   - '{role.role}'")

        # Проверим профиль
        profile = UserProfile.query.filter_by(user_id=creator.id).first()
        if profile:
            print(f"   Профиль: ✅ найден")
            print(f"   Telegram chat_id: {profile.telegram_chat_id}")
            if hasattr(profile, 'telegram_notifications_enabled'):
                print(f"   Telegram notifications: {profile.telegram_notifications_enabled}")
            if hasattr(profile, 'tg_notify_referral_used'):
                print(f"   Referral notifications: {profile.tg_notify_referral_used}")
        else:
            print(f"   Профиль: ❌ НЕ НАЙДЕН")
            return False

        # 2. Проверим логику поиска админов
        print("\n2️⃣  ПРОВЕРКА ЛОГИКИ ПОИСКА АДМИНОВ:")
        admin_roles = ['creator', 'chief_admin', 'admin', 'chief_tester']
        admin_users_set = set()

        # Основная роль
        basic_admins = User.query.filter(User.role.in_(admin_roles)).all()
        print(f"Админы по основной роли: {len(basic_admins)}")
        for admin in basic_admins:
            admin_users_set.add(admin.id)
            print(f"  - {admin.username} (ID {admin.id}, role='{admin.role}')")

        # Дополнительные роли
        role_admins = db.session.query(User).join(UserRole).filter(
            UserRole.role.in_(admin_roles)
        ).all()
        print(f"Админы по дополнительным ролям: {len(role_admins)}")
        for admin in role_admins:
            admin_users_set.add(admin.id)
            print(f"  - {admin.username} (ID {admin.id})")

        print(f"Итого уникальных админов: {len(admin_users_set)}")

        if creator.id in admin_users_set:
            print(f"✅ CREATOR ПОПАДАЕТ В СПИСОК АДМИНОВ")
        else:
            print(f"❌ CREATOR НЕ ПОПАДАЕТ В СПИСОК АДМИНОВ!")
            return False

        # 3. Создадим тестовое уведомление
        print("\n3️⃣  СОЗДАНИЕ ТЕСТОВОГО УВЕДОМЛЕНИЯ:")
        try:
            notify_user(
                creator.id,
                kind='referral_used',
                title='🧪 Тест уведомления о реферале',
                body='Это тестовая проверка работы системы уведомлений.',
                meta={'test': True, 'timestamp': datetime.now().isoformat()}
            )
            db.session.commit()
            print("✅ Уведомление создано в БД")
        except Exception as e:
            print(f"❌ Ошибка создания уведомления: {e}")
            return False

        # 4. Проверим уведомление в БД
        print("\n4️⃣  ПРОВЕРКА УВЕДОМЛЕНИЯ В БД:")
        recent = UserNotification.query.filter_by(
            user_id=creator.id,
            kind='referral_used'
        ).order_by(UserNotification.created_at.desc()).first()

        if not recent:
            print("❌ Уведомление не найдено в БД!")
            return False

        print(f"✅ Уведомление найдено:")
        print(f"   ID: {recent.notification_id}")
        print(f"   User: {creator.username} (ID {creator.id})")
        print(f"   Kind: {recent.kind}")
        print(f"   Title: {recent.title}")
        print(f"   Telegram sent: {recent.telegram_sent}")
        print(f"   Created: {recent.created_at}")

        # 5. Проверим статус отправки через 30 секунд
        print("\n5️⃣  СТАТУС ОТПРАВКИ:")
        print("Подождите 30-60 секунд и проверьте Telegram...")
        print("Затем запустите этот скрипт повторно или проверьте в БД:")
        print(f"SELECT telegram_sent, telegram_sent_at FROM \"UserNotifications\" WHERE notification_id = {recent.notification_id};")

        return True

if __name__ == '__main__':
    success = diagnose_referral_notifications()
    if success:
        print("\n🎉 ДИАГНОСТИКА ПРОШЛА УСПЕШНО!")
        print("Если уведомление не пришло в Telegram, проблема в urep_bot.")
    else:
        print("\n❌ ДИАГНОСТИКА ОБНАРУЖИЛА ПРОБЛЕМЫ!")
        print("Исправьте проблемы выше.")