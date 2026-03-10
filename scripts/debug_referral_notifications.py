#!/usr/bin/env python3
"""
Отладка системы уведомлений о рефералах в Telegram.
Checks: BotAdmins, их привязка, уведомления в БД.
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
from app.models import db, BotAdmin, User, UserProfile, UserNotification

app = create_app()

with app.app_context():
    print("=" * 80)
    print("🔍 ОТЛАДКА УВЕДОМЛЕНИЙ О РЕФЕРАЛАХ")
    print("=" * 80)
    
    # 1. Проверим BotAdmins
    print("\n1️⃣  АДМИНИСТРАТОРЫ БОТА (BotAdmin)")
    print("-" * 80)
    admins = BotAdmin.query.filter_by(is_active=True).all()
    if not admins:
        print("❌ НЕТ активных BotAdmin'ов!")
    else:
        print(f"✅ Найдено {len(admins)} активных админов:")
        for admin in admins:
            print(f"\n   Admin ID: {admin.admin_id}")
            print(f"   User ID: {admin.user_id}")
            user = User.query.get(admin.user_id)
            if user:
                print(f"   Username: {user.username}")
                print(f"   Role: {user.role}")
                
                # Проверим профиль
                profile = UserProfile.query.filter_by(user_id=user.id).first()
                if profile:
                    print(f"   Profile ID: {profile.profile_id}")
                    if profile.telegram_chat_id:
                        print(f"   ✅ Telegram привязан: {profile.telegram_chat_id}")
                    else:
                        print(f"   ❌ Telegram НЕ привязан!")
                    
                    if profile.telegram_notifications_enabled:
                        print(f"   ✅ Уведомления ВКЛЮЧЕНЫ")
                    else:
                        print(f"   ❌ Уведомления ОТКЛЮЧЕНЫ")
                    
                    print(f"   tg_notify_referral_used: {profile.tg_notify_referral_used}")
                else:
                    print(f"   ❌ Профиль не найден!")
            else:
                print(f"   ❌ Пользователь не найден!")
    
    # 2. Проверим последние уведомления referral_used
    print("\n\n2️⃣  НЕДАВНИЕ УВЕДОМЛЕНИЯ (referral_used)")
    print("-" * 80)
    recent = UserNotification.query.filter_by(kind='referral_used').order_by(
        UserNotification.created_at.desc()
    ).limit(10).all()
    
    if not recent:
        print("❌ Нет уведомлений о рефералах!")
    else:
        print(f"✅ Найдено {len(recent)} уведомлений:")
        for notif in recent:
            print(f"\n   ID: {notif.notification_id}")
            print(f"   User ID: {notif.user_id}")
            user = User.query.get(notif.user_id)
            if user:
                print(f"   User: {user.username}")
            print(f"   Title: {notif.title}")
            print(f"   Body: {notif.body}")
            print(f"   Telegram sent: {notif.telegram_sent}")
            print(f"   Created: {notif.created_at}")
    
    # 3. Проверим недоставленные уведомления
    print("\n\n3️⃣  НЕДОСТАВЛЕННЫЕ УВЕДОМЛЕНИЯ (telegram_sent = FALSE)")
    print("-" * 80)
    unsent = UserNotification.query.filter(
        UserNotification.telegram_sent == False,
        UserNotification.kind == 'referral_used'
    ).all()
    
    if not unsent:
        print("✅ Нет недоставленных уведомлений о рефералах")
    else:
        print(f"❌ Найдено {len(unsent)} недоставленных уведомлений:")
        for notif in unsent:
            user = User.query.get(notif.user_id)
            profile = UserProfile.query.filter_by(user_id=notif.user_id).first()
            print(f"\n   Notif ID: {notif.notification_id}")
            print(f"   User: {user.username if user else 'N/A'}")
            print(f"   Title: {notif.title}")
            if profile:
                chat_id = profile.telegram_chat_id
                tg_enabled = profile.telegram_notifications_enabled
                ref_enabled = profile.tg_notify_referral_used
                print(f"   Telegram Chat ID: {chat_id}")
                print(f"   Notifications enabled: {tg_enabled}")
                print(f"   Referral enabled: {ref_enabled}")
                
                if not chat_id:
                    print(f"   ⚠️  ChatID is NULL - no telegram")
                elif not tg_enabled:
                    print(f"   ⚠️  Notifications disabled globally")
                elif ref_enabled is False:
                    print(f"   ⚠️  Referral notifications disabled")
                else:
                    print(f"   ✅ Should be sent by urep_bot!")
            else:
                print(f"   ❌ No profile found!")
    
    # 4. Инструкции
    print("\n\n4️⃣  РЕКОМЕНДАЦИИ")
    print("-" * 80)
    if not admins:
        print("❌ Нужно создать BotAdmin record:")
        print("   - Добавьте админа в таблицу BotAdmins через админку")
        print("   - Или используйте скрипт create_tester_user.py")
    else:
        all_linked = all(
            UserProfile.query.filter_by(user_id=admin.user_id).first() and
            UserProfile.query.filter_by(user_id=admin.user_id).first().telegram_chat_id
            for admin in admins
        )
        if not all_linked:
            print("❌ Не все админы привязали Telegram:")
            print("   1. Отправьте админу код привязки")
            print("   2. Админ должен запустить /link КОД в боте")
            print("   3. Затем уведомления начнут приходить")
        else:
            print("✅ Админы привязаны, проверьте:")
            print("   1. Запущен ли urep_bot? (должен быть фоновый процесс)")
            print("   2. Есть ли ошибки в логах urep_bot?")
            print("   3. Пришли ли уведомления в Telegram?")
    
    print("\n" + "=" * 80)
