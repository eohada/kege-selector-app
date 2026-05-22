#!/usr/bin/env python3
"""
Проверяет роли пользователей через UserRole таблицу.
"""
import sys
from app import create_app
from app.models import db, User, UserRole, UserProfile

app = create_app()
with app.app_context():
    print("=" * 80)
    print("👥 ВСЕ ПОЛЬЗОВАТЕЛИ И ИХ РОЛИ (включая множественные)")
    print("=" * 80)
    
    # Найдем всех пользователей
    users = User.query.all()
    
    print(f"\nВсего пользователей: {len(users)}\n")
    
    for user in users:
        print(f"{'─' * 60}")
        print(f"👤 {user.username} (ID {user.id})")
        print(f"   Основная роль: {user.role}")
        
        # Найдем все роли пользователя
        user_roles = UserRole.query.filter_by(user_id=user.id).all()
        if user_roles:
            print(f"   Дополнительные роли: {[ur.role for ur in user_roles]}")
        
        # Все роли вместе
        all_roles = [user.role] if user.role else []
        all_roles.extend([ur.role for ur in user_roles])
        all_roles = list(set(all_roles))  # убрать дубликаты
        
        print(f"   Все роли: {all_roles}")
        
        # Проверим, является ли админом
        is_admin = any(role in ['creator', 'chief_admin', 'admin'] for role in all_roles)
        print(f"   Админ системы: {'✅ ДА' if is_admin else '❌ НЕТ'}")
        
        # Telegram статус
        profile = UserProfile.query.filter_by(user_id=user.id).first()
        if profile and profile.telegram_chat_id:
            print(f"   Telegram: ✅ привязан ({profile.telegram_chat_id})")
        else:
            print(f"   Telegram: ❌ не привязан")
    
    print(f"\n{'=' * 80}")
    print("🎯 АДМИНЫ СИСТЕМЫ (все роли):")
    
    admin_users = []
    for user in users:
        user_roles = UserRole.query.filter_by(user_id=user.id).all()
        all_roles = [user.role] if user.role else []
        all_roles.extend([ur.role for ur in user_roles])
        
        if any(role in ['creator', 'chief_admin', 'admin'] for role in all_roles):
            admin_users.append(user)
    
    if admin_users:
        print(f"✅ Найдено {len(admin_users)} админов:")
        for user in admin_users:
            profile = UserProfile.query.filter_by(user_id=user.id).first()
            tg_status = "✅ TG" if profile and profile.telegram_chat_id else "❌ нет TG"
            print(f"   - {user.username} (ID {user.id}) {tg_status}")
    else:
        print("❌ Админов не найдено!")
    
    # Проверим реферальные коды
    print(f"\n🔗 РЕФЕРАЛЬНЫЕ КОДЫ:")
    from app.models import ReferralCode
    codes = ReferralCode.query.all()
    if codes:
        for code in codes:
            creator = User.query.get(code.creator_id)
            creator_name = creator.username if creator else f"ID {code.creator_id}"
            print(f"   Код '{code.code}' создан: {creator_name}")
    else:
        print("   Нет реферальных кодов")
