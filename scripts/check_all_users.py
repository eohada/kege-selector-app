#!/usr/bin/env python3
"""
Проверяет ВСЕХ пользователей и их роли.
"""
import sys
from app import create_app
from app.models import db, User, UserProfile

app = create_app()
with app.app_context():
    print("=" * 80)
    print("👥 ВСЕ ПОЛЬЗОВАТЕЛИ И ИХ РОЛИ")
    print("=" * 80)
    
    # Найдем всех пользователей
    users = User.query.all()
    
    print(f"\nВсего пользователей: {len(users)}\n")
    
    roles = {}
    for user in users:
        role = user.role or 'no_role'
        if role not in roles:
            roles[role] = []
        roles[role].append(user)
    
    for role, user_list in roles.items():
        print(f"\n🎭 Роль '{role}' ({len(user_list)} пользователей):")
        for user in user_list:
            profile = UserProfile.query.filter_by(user_id=user.id).first()
            tg_status = "✅ TG привязан" if profile and profile.telegram_chat_id else "❌ TG не привязан"
            print(f"   - {user.username} (ID {user.id}) {tg_status}")
    
    print(f"\n{'=' * 80}")
    print("🔍 СПЕЦИАЛЬНЫЙ ПОИСК:")
    
    # Ищем creator
    creator = User.query.filter_by(role='creator').first()
    if creator:
        print(f"✅ Creator найден: {creator.username} (ID {creator.id})")
        profile = UserProfile.query.filter_by(user_id=creator.id).first()
        if profile:
            tg_status = "✅ TG привязан" if profile.telegram_chat_id else "❌ TG не привязан"
            print(f"   Профиль: {tg_status}")
        else:
            print(f"   ❌ Профиль НЕ найден")
    else:
        print("❌ Creator НЕ найден!")
        
        # Ищем по username
        possible_creators = User.query.filter(User.username.like('%creator%')).all()
        if possible_creators:
            print("Возможные creator'ы по username:")
            for u in possible_creators:
                print(f"   - {u.username} (role: {u.role})")
        
        # Ищем по email
        possible_creators = User.query.filter(User.email.like('%creator%')).all()
        if possible_creators:
            print("Возможные creator'ы по email:")
            for u in possible_creators:
                print(f"   - {u.email} (role: {u.role})")
    
    # Проверим, кто создал реферальные коды
    from app.models import ReferralCode
    print(f"\n🔗 РЕФЕРАЛЬНЫЕ КОДЫ:")
    codes = ReferralCode.query.all()
    if codes:
        for code in codes:
            creator = User.query.get(code.creator_id)
            creator_name = creator.username if creator else f"ID {code.creator_id}"
            print(f"   Код '{code.code}' создан: {creator_name}")
    else:
        print("   Нет реферальных кодов")
