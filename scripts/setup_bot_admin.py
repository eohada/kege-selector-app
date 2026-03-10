#!/usr/bin/env python3
"""
Быстрый скрипт для создания/активации BotAdmin записи для текущего пользователя.

Использование:
  python scripts/setup_bot_admin.py [user_id]

Если user_id не передан, попробует найти первого админа (chief_admin or admin).
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
from app.models import db, User, BotAdmin

app = create_app()

def main():
    user_id = None
    if len(sys.argv) > 1:
        try:
            user_id = int(sys.argv[1])
        except ValueError:
            print(f"❌ Неверный user_id: {sys.argv[1]}")
            sys.exit(1)
    
    with app.app_context():
        if not user_id:
            # Ищем первого админа
            admin_user = User.query.filter(
                User.role.in_(['chief_admin', 'admin'])
            ).first()
            if admin_user:
                user_id = admin_user.id
                print(f"📍 Найден администратор: {admin_user.username} (ID: {user_id})")
            else:
                print("❌ Админов не найдено. Передайте user_id вручную:")
                print("   python scripts/setup_bot_admin.py <user_id>")
                sys.exit(1)
        
        user = User.query.get(user_id)
        if not user:
            print(f"❌ Пользователь с ID {user_id} не найден!")
            sys.exit(1)
        
        print(f"👤 Пользователь: {user.username} (role: {user.role})")
        
        # Проверяем, уже ли он BotAdmin
        existing = BotAdmin.query.filter_by(user_id=user_id).first()
        if existing:
            if existing.is_active:
                print(f"✅ Уже BotAdmin (активен)")
            else:
                existing.is_active = True
                db.session.commit()
                print(f"✅ BotAdmin активирован!")
        else:
            # Создаем новый BotAdmin
            new_admin = BotAdmin(user_id=user_id, is_active=True)
            db.session.add(new_admin)
            db.session.commit()
            print(f"✅ BotAdmin создан!")
        
        # Информация о следующем шаге
        print("\n📌 СЛЕДУЮЩИЙ ШАГ:")
        print("   Администратор должен привязать Telegram:")
        print("   1. Зайти в личный кабинет на сайте")
        print("   2. Открыть профиль")
        print("   3. Нажать 'Generate Telegram Link Code'")
        print("   4. Копировать КОД")
        print("   5. Отправить боту: /link КОД")
        print("\n   После этого уведомления начнут приходить!")

if __name__ == '__main__':
    main()
