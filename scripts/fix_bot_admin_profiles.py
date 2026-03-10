#!/usr/bin/env python3
"""
Проверка и создание UserProfile для BotAdmin'ов.
Без UserProfile уведомления не будут отправляться.
"""
import os
import sys

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
from app.models import db, User, UserProfile, BotAdmin

app = create_app()

def fix_bot_admin_profiles():
    """Проверяет и создает UserProfile для всех BotAdmin'ов."""
    with app.app_context():
        print("=" * 80)
        print("🔧 ИСПРАВЛЕНИЕ ПРОФИЛЕЙ BotAdmin'ов")
        print("=" * 80)

        admins = BotAdmin.query.filter_by(is_active=True).all()
        if not admins:
            print("❌ Нет активных BotAdmin'ов!")
            return False

        fixed_count = 0
        for admin in admins:
            user = User.query.get(admin.user_id)
            if not user:
                print(f"❌ BotAdmin {admin.admin_id}: пользователь {admin.user_id} не найден!")
                continue

            profile = UserProfile.query.filter_by(user_id=user.id).first()
            if profile:
                print(f"✅ BotAdmin {admin.admin_id} ({user.username}): профиль существует")
                if profile.telegram_chat_id:
                    print(f"   Telegram привязан: {profile.telegram_chat_id}")
                else:
                    print(f"   ⚠️  Telegram НЕ привязан")
                continue

            # Создаем профиль
            try:
                new_profile = UserProfile(user_id=user.id)
                db.session.add(new_profile)
                db.session.commit()
                print(f"✅ BotAdmin {admin.admin_id} ({user.username}): профиль СОЗДАН")
                fixed_count += 1
            except Exception as e:
                db.session.rollback()
                print(f"❌ Ошибка создания профиля для {user.username}: {e}")

        if fixed_count > 0:
            print(f"\n🎉 Создано {fixed_count} профилей!")
            print("Теперь уведомления должны работать.")
        else:
            print("\nℹ️  Все профили уже существуют.")

        # Финальная проверка
        print("\n📊 ФИНАЛЬНАЯ ПРОВЕРКА:")
        for admin in admins:
            user = User.query.get(admin.user_id)
            profile = UserProfile.query.filter_by(user_id=user.id).first()
            status = "✅" if profile and profile.telegram_chat_id else "❌"
            tg_status = f" (TG: {profile.telegram_chat_id})" if profile and profile.telegram_chat_id else " (TG не привязан)"
            print(f"   {status} {user.username}{tg_status}")

        return True

if __name__ == '__main__':
    fix_bot_admin_profiles()
