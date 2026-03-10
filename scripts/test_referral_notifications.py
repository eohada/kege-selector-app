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
from app.models import db, User, UserRole, UserProfile, UserNotification, ReferralCode, ReferralUsage
from app.notifications.service import notify_user

app = create_app()

def test_referral_notification():
    """Тестируем создание и отправку уведомления о реферале."""
    with app.app_context():
        print("=" * 80)
        print("🧪 ТЕСТИРОВАНИЕ УВЕДОМЛЕНИЙ О РЕФЕРАЛАХ")
        print("=" * 80)

        # 1. Найдем всех админов (как в routes.py)
        print("\n1️⃣  ПОИСК АДМИНОВ:")
        admin_roles = ['creator', 'chief_admin', 'admin', 'chief_tester']
        admin_users_set = set()
        
        # Проверим основную роль
        basic_admins = User.query.filter(User.role.in_(admin_roles)).all()
        for admin in basic_admins:
            admin_users_set.add(admin.id)
        
        # Проверим дополнительные роли
        role_admins = db.session.query(User).join(UserRole).filter(
            UserRole.role.in_(admin_roles)
        ).all()
        for admin in role_admins:
            admin_users_set.add(admin.id)
        
        if not admin_users_set:
            print("❌ НЕТ пользователей с админ-ролями!")
            return False
        
        print(f"✅ Найдено {len(admin_users_set)} админов(ы)")
        
        # 2. Проверим, у кого есть Telegram и уведомления включены
        print("\n2️⃣  ПРОВЕРКА TELEGRAM:")
        valid_admins = []
        for user_id in admin_users_set:
            try:
                user = User.query.get(user_id) if hasattr(User.query, 'get') else db.session.get(User, user_id)
                
                if not user:
                    print(f"   ❌ User {user_id}: не найден в БД")
                    continue
                
                # Попытаемся загрузить профиль с обработкой ошибок
                try:
                    profile = UserProfile.query.filter_by(user_id=user_id).first()
                except Exception as profile_err:
                    print(f"   ⚠️  {user.username}: ошибка при загрузке профиля - {str(profile_err)[:50]}...")
                    profile = None
                
                # Для локальной БД profile может быть None или не иметь всех колонок
                if not profile:
                    print(f"   ⚠️  {user.username}: нет профиля")
                    continue
                
                # Проверяем только критичное - есть ли Telegram
                if not hasattr(profile, 'telegram_chat_id') or not profile.telegram_chat_id:
                    print(f"   ⚠️  {user.username}: Telegram не привязан")
                    continue
                
                print(f"   ✅ {user.username} (ID {user.id}, chat_id: {profile.telegram_chat_id})")
                valid_admins.append((user, profile))
                
            except Exception as e:
                print(f"   ❌ User {user_id}: ошибка - {e}")
        
        if not valid_admins:
            print("❌ НЕТ валидных админов с Telegram для отправки!")
            return False
        
        # 3. Создаем тестовое уведомление для первого админа
        print("\n3️⃣  СОЗДАНИЕ ТЕСТОВОГО УВЕДОМЛЕНИЯ:")
        test_user = valid_admins[0][0]  # Первый валидный админ
        
        try:
            notify_user(
                test_user.id,
                kind='referral_used',
                title='🧪 Тестовое уведомление о реферале',
                body='Это тестовое уведомление для проверки работы системы.',
                meta={'test': True, 'timestamp': datetime.now().isoformat()}
            )
            db.session.commit()
            print(f"✅ Тестовое уведомление создано для: {test_user.username}")
        except Exception as e:
            print(f"❌ Ошибка при создании уведомления: {e}")
            return False
        
        # 4. Проверим, что уведомление появилось в БД
        print("\n4️⃣  ПРОВЕРКА В БД:")
        recent = UserNotification.query.filter_by(
            user_id=test_user.id,
            kind='referral_used'
        ).order_by(UserNotification.created_at.desc()).first()
        
        if not recent:
            print("❌ Уведомление не найдено в БД!")
            return False
        
        print(f"✅ Уведомление найдено:")
        print(f"   ID: {recent.notification_id}")
        print(f"   User: {test_user.username} (ID {test_user.id})")
        print(f"   Kind: {recent.kind}")
        print(f"   Title: {recent.title}")
        print(f"   Telegram sent: {recent.telegram_sent}")
        print(f"   Created: {recent.created_at}")
        
        # 5. Инструкции по проверке
        print("\n5️⃣  СЛЕДУЮЩИЕ ШАГИ:")
        print("   1. Убедитесь, что urep_bot запущен:")
        print("      python urep_bot/run_bot.py")
        print("   2. Подождите 30-60 секунд для отправки")
        print("   3. Проверьте Telegram на наличие сообщения")
        print("   4. Если не пришло, проверьте логи urep_bot")
        print(f"   5. Статус уведомления в БД:")
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
