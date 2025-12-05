#!/usr/bin/env python3
"""
Скрипт для создания пользователей
Использование: 
  python scripts/create_tester_user.py <username> <password> [role]
  python scripts/create_tester_user.py <username> <password>  # роль по умолчанию: tester
  python scripts/create_tester_user.py creator <password> creator  # создать создателя

Роли: 'tester' (тестировщик) или 'creator' (создатель)
"""
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from core.db_models import User, moscow_now
from werkzeug.security import generate_password_hash

def create_user(username, password, role='tester'):
    """Создает или обновляет пользователя"""
    with app.app_context():
        if role not in ['tester', 'creator']:
            print(f"❌ Ошибка: роль должна быть 'tester' или 'creator'")
            return
        
        # Проверяем, существует ли пользователь
        user = User.query.filter_by(username=username).first()
        
        if user:
            # Обновляем пароль и роль
            user.password_hash = generate_password_hash(password)
            user.role = role
            user.is_active = True
            db.session.commit()
            print(f"✅ Пользователь '{username}' обновлен.")
        else:
            # Создаем нового пользователя
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=True,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.commit()
            print(f"✅ Пользователь '{username}' создан успешно.")
        
        role_display = 'Создатель' if role == 'creator' else 'Тестировщик'
        print(f"📝 Имя пользователя: {username}")
        print(f"🔑 Пароль: {password}")
        print(f"👤 Роль: {role_display} ({role})")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Использование: python scripts/create_tester_user.py <username> <password> [role]")
        print("Примеры:")
        print("  python scripts/create_tester_user.py tester test123")
        print("  python scripts/create_tester_user.py creator mypassword creator")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else 'tester'
    
    create_user(username, password, role)

