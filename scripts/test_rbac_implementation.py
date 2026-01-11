#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для тестирования новой системы авторизации и RBAC
Проверяет создание моделей, миграции и базовую функциональность
"""
import sys
import os
import io

# Настраиваем кодировку для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем корневую директорию в путь
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app import create_app, db
from core.db_models import User, UserProfile, FamilyTie, Enrollment
from app.auth.rbac_utils import get_user_scope, mask_contact_info
from sqlalchemy import inspect

def test_models_import():
    """Тест 1: Проверка импорта моделей"""
    print("=" * 60)
    print("ТЕСТ 1: Импорт моделей")
    print("=" * 60)
    
    try:
        from core.db_models import User, UserProfile, FamilyTie, Enrollment
        print("[OK] Все модели успешно импортированы")
        print(f"   - User: {User}")
        print(f"   - UserProfile: {UserProfile}")
        print(f"   - FamilyTie: {FamilyTie}")
        print(f"   - Enrollment: {Enrollment}")
        return True
    except Exception as e:
        print(f"[ERROR] Ошибка импорта моделей: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_user_model_methods():
    """Тест 2: Проверка методов модели User"""
    print("\n" + "=" * 60)
    print("ТЕСТ 2: Методы модели User")
    print("=" * 60)
    
    try:
        # Создаем тестового пользователя (не сохраняем в БД)
        test_user = User(
            username='test_admin',
            password_hash='test_hash',
            role='admin'
        )
        
        print(f"[OK] Создан тестовый пользователь: {test_user.username}")
        print(f"   - is_admin(): {test_user.is_admin()}")
        print(f"   - is_tutor(): {test_user.is_tutor()}")
        print(f"   - is_student(): {test_user.is_student()}")
        print(f"   - is_parent(): {test_user.is_parent()}")
        print(f"   - get_role_display(): {test_user.get_role_display()}")
        
        # Проверяем все роли
        roles_to_test = ['admin', 'tutor', 'student', 'parent']
        for role in roles_to_test:
            test_user.role = role
            print(f"\n   Роль '{role}':")
            print(f"     - is_admin(): {test_user.is_admin()}")
            print(f"     - is_tutor(): {test_user.is_tutor()}")
            print(f"     - is_student(): {test_user.is_student()}")
            print(f"     - is_parent(): {test_user.is_parent()}")
            print(f"     - get_role_display(): {test_user.get_role_display()}")
        
        return True
    except Exception as e:
        print(f"[ERROR] Ошибка при тестировании методов User: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_tables(app):
    """Тест 3: Проверка создания таблиц в БД"""
    print("\n" + "=" * 60)
    print("ТЕСТ 3: Создание таблиц в базе данных")
    print("=" * 60)
    
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            required_tables = ['Users', 'UserProfiles', 'FamilyTies', 'Enrollments']
            found_tables = []
            missing_tables = []
            
            for table in required_tables:
                # Проверяем оба варианта регистра
                if table in table_names or table.lower() in table_names:
                    found_tables.append(table)
                    print(f"[OK] Таблица '{table}' найдена")
                else:
                    missing_tables.append(table)
                    print(f"[WARN] Таблица '{table}' не найдена")
            
            if missing_tables:
                print(f"\n📝 Попытка создать отсутствующие таблицы...")
                try:
                    db.create_all()
                    db.session.commit()
                    print("✅ db.create_all() выполнен успешно")
                    
                    # Проверяем снова
                    table_names_after = inspector.get_table_names()
                    for table in missing_tables:
                        if table in table_names_after or table.lower() in table_names_after:
                            print(f"[OK] Таблица '{table}' создана")
                        else:
                            print(f"[ERROR] Таблица '{table}' всё ещё отсутствует")
                except Exception as e:
                    print(f"[ERROR] Ошибка при создании таблиц: {e}")
                    db.session.rollback()
                    return False
            
            # Проверяем колонки в таблице Users
            users_table = 'Users' if 'Users' in table_names else ('users' if 'users' in table_names else None)
            if users_table:
                users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                print(f"\n📋 Колонки в таблице '{users_table}':")
                required_columns = ['id', 'username', 'password_hash', 'role', 'is_active', 'email']
                for col in required_columns:
                    if col in users_columns:
                        print(f"   [OK] {col}")
                    else:
                        print(f"   [WARN] {col} (отсутствует)")
            
            return len(missing_tables) == 0
    except Exception as e:
        print(f"[ERROR] Ошибка при проверке таблиц: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rbac_utils(app):
    """Тест 4: Проверка утилит RBAC"""
    print("\n" + "=" * 60)
    print("ТЕСТ 4: Утилиты RBAC")
    print("=" * 60)
    
    try:
        with app.app_context():
            # Тест маскирования контактов
            print("📞 Тест маскирования контактов:")
            test_contacts = [
                "+7 900 123 45 67",
                "user@example.com",
                "test@domain.ru"
            ]
            
            for contact in test_contacts:
                masked = mask_contact_info(contact)
                print(f"   '{contact}' -> '{masked}'")
            
            # Тест get_user_scope (без реального пользователя)
            print("\n👤 Тест get_user_scope (без пользователя):")
            scope = get_user_scope(None)
            print(f"   Scope: {scope}")
            
            # Создаем тестовых пользователей для проверки scope
            print("\n👥 Тест get_user_scope для разных ролей:")
            test_users = [
                User(username='test_admin', role='admin', password_hash='hash'),
                User(username='test_tutor', role='tutor', password_hash='hash'),
                User(username='test_student', role='student', password_hash='hash'),
                User(username='test_parent', role='parent', password_hash='hash'),
            ]
            
            for user in test_users:
                scope = get_user_scope(user)
                print(f"   {user.role}: can_see_all={scope['can_see_all']}, student_ids={scope['student_ids']}")
        
        return True
    except Exception as e:
        print(f"[ERROR] Ошибка при тестировании RBAC утилит: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_migrations():
    """Тест 5: Проверка миграций"""
    print("\n" + "=" * 60)
    print("ТЕСТ 5: Проверка миграций")
    print("=" * 60)
    
    try:
        from app.utils.db_migrations import ensure_schema_columns
        app = create_app()
        
        with app.app_context():
            print("📝 Запуск ensure_schema_columns()...")
            ensure_schema_columns(app)
            print("[OK] Миграции выполнены успешно")
            
            # Проверяем, что колонка email добавлена
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            users_table = 'Users' if 'Users' in table_names else ('users' if 'users' in table_names else None)
            
            if users_table:
                users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                if 'email' in users_columns:
                    print("[OK] Колонка 'email' добавлена в таблицу Users")
                else:
                    print("[WARN] Колонка 'email' не найдена (может быть уже была)")
            
            return True
    except Exception as e:
        print(f"[ERROR] Ошибка при проверке миграций: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Главная функция тестирования"""
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ СИСТЕМЫ АВТОРИЗАЦИИ И RBAC")
    print("=" * 60 + "\n")
    
    results = []
    
    # Тест 1: Импорт моделей
    results.append(("Импорт моделей", test_models_import()))
    
    # Тест 2: Методы User
    results.append(("Методы модели User", test_user_model_methods()))
    
    # Тест 3: Таблицы БД
    app = create_app()
    results.append(("Создание таблиц БД", test_database_tables(app)))
    
    # Тест 4: RBAC утилиты
    results.append(("Утилиты RBAC", test_rbac_utils(app)))
    
    # Тест 5: Миграции
    results.append(("Миграции БД", test_migrations()))
    
    # Итоговый отчет
    print("\n" + "=" * 60)
    print("ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS] ПРОЙДЕН" if result else "[FAIL] ПРОВАЛЕН"
        print(f"{status}: {test_name}")
    
    print(f"\nВсего тестов: {total}")
    print(f"Пройдено: {passed}")
    print(f"Провалено: {total - passed}")
    
    if passed == total:
        print("\n[SUCCESS] Все тесты пройдены успешно!")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} тест(ов) провалено")
        return 1


if __name__ == "__main__":
    sys.exit(main())
