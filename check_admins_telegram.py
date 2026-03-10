#!/usr/bin/env python3
"""
Проверяет всех админов и их Telegram привязку.
"""
import sys
from app import create_app
from app.models import db, User, UserProfile

app = create_app()
with app.app_context():
    print("=" * 80)
    print("👥 ВСЕ АДМИНЫ СИСТЕМЫ И ИХ TELEGRAM ПРИВЯЗКА")
    print("=" * 80)
    
    # Найдем всех админов
    admins = User.query.filter(User.role.in_(['creator', 'chief_admin', 'admin'])).all()
    
    if not admins:
        print("❌ Админов не найдено!")
        sys.exit(1)
    
    print(f"\n✅ Найдено {len(admins)} админов:\n")
    
    for admin in admins:
        print(f"{'─' * 80}")
        print(f"👤 Имя: {admin.username}")
        print(f"   User ID: {admin.id}")
        print(f"   Роль: {admin.role}")
        
        profile = UserProfile.query.filter_by(user_id=admin.id).first()
        if not profile:
            print(f"   ❌ Профиль НЕ найден!")
            continue
        
        print(f"   Profile ID: {profile.profile_id}")
        
        if profile.telegram_chat_id:
            print(f"   ✅ Telegram привязан: {profile.telegram_chat_id}")
        else:
            print(f"   ❌ Telegram НЕ привязан")
        
        if profile.telegram_notifications_enabled:
            print(f"   ✅ Уведомления включены")
        else:
            print(f"   ❌ Уведомления ОТКЛЮЧЕНЫ")
        
        if profile.tg_notify_referral_used:
            print(f"   ✅ Уведомления о рефералах включены")
        else:
            print(f"   ❌ Уведомления о рефералах ОТКЛЮЧЕНЫ")
    
    print(f"\n{'=' * 80}")
    print("📊 ИТОГО:")
    
    valid_admins = []
    for admin in admins:
        profile = UserProfile.query.filter_by(user_id=admin.id).first()
        if profile and profile.telegram_chat_id and profile.telegram_notifications_enabled and profile.tg_notify_referral_used:
            valid_admins.append(admin)
    
    if valid_admins:
        print(f"✅ {len(valid_admins)} админов полностью настроены для получения уведомлений:")
        for admin in valid_admins:
            print(f"   - {admin.username} (ID {admin.id})")
    else:
        print(f"❌ НИ ОДИН админ не настроен для получения уведомлений!")
        print("\nВозможные проблемы:")
        for admin in admins:
            profile = UserProfile.query.filter_by(user_id=admin.id).first()
            issues = []
            if not profile:
                issues.append("нет профиля")
            else:
                if not profile.telegram_chat_id:
                    issues.append("Telegram не привязан")
                if not profile.telegram_notifications_enabled:
                    issues.append("уведомления отключены")
                if profile.tg_notify_referral_used is False:
                    issues.append("уведомления о рефералах отключены")
            
            if issues:
                print(f"   {admin.username}: {', '.join(issues)}")
