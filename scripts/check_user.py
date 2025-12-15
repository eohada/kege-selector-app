#!/usr/bin/env python3
"""
Скрипт для проверки пользователя в базе данных
Использование: python scripts/check_user.py <username>
"""
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User

def check_user(username):
    """Проверяет существование пользователя и выводит информацию"""
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        
        if not user:
            print(f"[X] Пользователь '{username}' не найден в базе данных")
            return False
        
        print(f"[OK] Пользователь '{username}' найден!")
        print("=" * 50)
        print(f"Логин: {user.username}")
        print(f"Роль: {user.get_role_display()} ({user.role})")
        print(f"Активен: {'Да' if user.is_active else 'Нет'}")
        print(f"Создан: {user.created_at}")
        print(f"Последний вход: {user.last_login or 'Никогда'}")
        print(f"Хеш пароля: {user.password_hash[:50]}...")
        print("\n[!] ВАЖНО: Пароль хранится в хешированном виде.")
        print("   Оригинальный пароль восстановить невозможно.")
        print("   Для сброса пароля используйте:")
        print(f"   python scripts/create_tester_user.py {username} <новый_пароль>")
        
        return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python scripts/check_user.py <username>")
        print("Пример: python scripts/check_user.py misha")
        sys.exit(1)
    
    username = sys.argv[1]
    success = check_user(username)
    sys.exit(0 if success else 1)

