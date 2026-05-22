#!/usr/bin/env python3
"""
Четкая диагностика creator'а и Telegram привязки.
"""
from app import create_app
from app.models import db, User, UserProfile, UserRole

app = create_app()
with app.app_context():
    print("=" * 80)
    print("🎯 ДИАГНОСТИКА CREATOR'А")
    print("=" * 80)
    
    # Ищем creator в UserRoles
    creator_role = UserRole.query.filter_by(role='creator').first()
    
    if creator_role:
        creator_id = creator_role.user_id
        creator = User.query.get(creator_id)
        
        print(f"\n✅ CREATOR НАЙДЕН!")
        print(f"   Username: {creator.username}")
        print(f"   User ID: {creator.id}")
        print(f"   Основная роль: {creator.role}")
        
        # Проверим профиль и Telegram
        profile = UserProfile.query.filter_by(user_id=creator.id).first()
        
        if profile:
            print(f"\n✅ Профиль существует:")
            print(f"   Profile ID: {profile.profile_id}")
            
            if profile.telegram_chat_id:
                print(f"   ✅ Telegram: привязан ({profile.telegram_chat_id})")
            else:
                print(f"   ❌ Telegram: НЕ привязан!")
                print(f"      ⚠️  НУЖНО ПРИВЯЗАТЬ TELEGRAM!")
                print(f"      Действия:")
                print(f"      1. Зайти в профиль creator на сайте")
                print(f"      2. Нажать 'Generate Telegram Link Code'")
                print(f"      3. Скопировать КОД")
                print(f"      4. Отправить боту: /link КОД")
        else:
            print(f"\n❌ Профиль не существует!")
            print(f"   Создаем профиль...")
            
            # Создадим профиль
            new_profile = UserProfile(user_id=creator.id)
            db.session.add(new_profile)
            db.session.commit()
            
            print(f"   ✅ Профиль создан!")
            print(f"   Теперь нужно привязать Telegram (см. выше)")
    else:
        print(f"\n❌ CREATOR НЕ НАЙДЕН!")
        print(f"   Никто не имеет роль 'creator' в UserRoles")
