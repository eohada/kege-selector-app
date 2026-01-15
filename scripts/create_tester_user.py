#!/usr/bin/env python3
"""
Скрипт для создания пользователей
Использование: 
  python scripts/create_tester_user.py <username> <password> [role] [--force-production]
  python scripts/create_tester_user.py <username> <password>  # роль по умолчанию: tester
  python scripts/create_tester_user.py creator <password> creator  # создать создателя

Роли: 'tester' (тестировщик) или 'creator' (создатель)

ВАЖНО: Тестеры создаются только в sandbox окружении!
       Для создания в production используйте --force-production (только для creator!)
"""
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, moscow_now
from werkzeug.security import generate_password_hash

def create_user(username, password, role='tester', force_production=False):
    """Создает или обновляет пользователя"""
    app = create_app()
    with app.app_context():
        # Проверяем окружение
        environment = os.environ.get('ENVIRONMENT', 'local')
        
        # Если пытаемся создать тестера в production - блокируем
        if role == 'tester' and environment == 'production' and not force_production:
            print("❌ ОШИБКА: Тестеры могут создаваться только в sandbox окружении!")
            print(f"   Текущее окружение: {environment}")
            print("\n💡 Решения:")
            print("   1. Переключитесь на sandbox окружение (ENVIRONMENT=sandbox)")
            print("   2. Или используйте скрипт move_testers_to_sandbox.py для переноса")
            return False
        
        if role not in ['tester', 'creator']:
            print(f"❌ Ошибка: роль должна быть 'tester' или 'creator'")
            return False
        
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
        print(f"🌍 Окружение: {environment}")
        
        return True

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Использование: python scripts/create_tester_user.py <username> <password> [role] [--force-production]")
        print("Примеры:")
        print("  python scripts/create_tester_user.py tester test123")
        print("  python scripts/create_tester_user.py creator mypassword creator")
        print("\n⚠️  ВАЖНО: Тестеры создаются только в sandbox окружении!")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith('--') else 'tester'
    force_production = '--force-production' in sys.argv
    
    success = create_user(username, password, role, force_production)
    sys.exit(0 if success else 1)

