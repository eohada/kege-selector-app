#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания или сброса пароля пользователя в admin окружении
Работает через прямое подключение к базе данных

Использование:
    # Локально (если есть доступ к БД)
    python scripts/reset_admin_user.py admin newpassword123 creator
    
    # Через Railway shell
    railway run python scripts/reset_admin_user.py admin newpassword123 creator
"""
import os
import sys

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, moscow_now
from werkzeug.security import generate_password_hash

def reset_or_create_user(username, password, role='creator'):
    """
    Создает пользователя или сбрасывает пароль существующего
    """
    app = create_app()
    with app.app_context():
        try:
            # Проверяем окружение
            environment = os.environ.get('ENVIRONMENT', 'local')
            print("=" * 60)
            print("СБРОС/СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ В ADMIN ОКРУЖЕНИИ")
            print("=" * 60)
            print(f"Окружение: {environment}")
            print(f"Username: {username}")
            print(f"Role: {role}")
            print()
            
            # Проверяем, существует ли пользователь
            user = User.query.filter_by(username=username).first()
            
            if user:
                # Обновляем пароль и роль
                old_role = user.role
                user.password_hash = generate_password_hash(password)
                user.role = role
                user.is_active = True
                db.session.commit()
                print(f"✅ Пользователь '{username}' обновлен")
                if old_role != role:
                    print(f"   Роль изменена: {old_role} → {role}")
                print(f"   Пароль сброшен")
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
                print(f"✅ Пользователь '{username}' создан")
            
            print()
            print("=" * 60)
            print("УЧЕТНЫЕ ДАННЫЕ:")
            print("=" * 60)
            print(f"Логин: {username}")
            print(f"Пароль: {password}")
            print(f"Роль: {role}")
            print()
            print("Теперь вы можете войти в систему!")
            print("=" * 60)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print("=" * 60)
            print("ОШИБКА")
            print("=" * 60)
            print(f"Не удалось создать/обновить пользователя: {e}")
            print()
            print("Проверьте:")
            print("  1. Правильность DATABASE_URL")
            print("  2. Что база данных доступна")
            print("  3. Что вы запускаете скрипт в правильном окружении")
            print("=" * 60)
            return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Использование: python scripts/reset_admin_user.py <username> <password> [role]")
        print()
        print("Примеры:")
        print("  python scripts/reset_admin_user.py admin mypassword123 creator")
        print("  python scripts/reset_admin_user.py admin newpass456")
        print()
        print("Для запуска через Railway:")
        print("  railway run python scripts/reset_admin_user.py admin mypassword123 creator")
        print()
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else 'creator'
    
    if len(password) < 8:
        print("⚠️  ВНИМАНИЕ: Пароль должен быть не менее 8 символов!")
        print()
    
    success = reset_or_create_user(username, password, role)
    sys.exit(0 if success else 1)
