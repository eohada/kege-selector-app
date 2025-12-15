#!/usr/bin/env python3
"""
Скрипт для вывода списка всех пользователей
Использование: python scripts/list_users.py
"""
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User

def list_users():
    """Выводит список всех пользователей"""
    app = create_app()
    with app.app_context():
        users = User.query.order_by(User.username).all()
        
        if not users:
            print("[!] Пользователи не найдены в базе данных")
            return
        
        print(f"[OK] Найдено пользователей: {len(users)}")
        print("=" * 70)
        print(f"{'Логин':<20} {'Роль':<15} {'Активен':<10} {'Создан':<20}")
        print("-" * 70)
        
        for user in users:
            role_display = user.get_role_display()
            active = "Да" if user.is_active else "Нет"
            created = user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else "N/A"
            print(f"{user.username:<20} {role_display:<15} {active:<10} {created:<20}")

if __name__ == '__main__':
    list_users()

