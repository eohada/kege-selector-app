#!/usr/bin/env python3
"""
Скрипт предварительной проверки системы (Pre-flight Checks)
Проверяет готовность инфраструктуры перед запуском
"""
import os
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import (
    User, UserProfile, FamilyTie, Enrollment,
    Student, Lesson, Tasks, LessonTask, StudentTaskStatistics
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

app = create_app()

def check_database_connection():
    """Проверка подключения к БД"""
    print("=" * 60)
    print("1. ПРОВЕРКА ПОДКЛЮЧЕНИЯ К БД")
    print("=" * 60)
    
    try:
        with app.app_context():
            # Простой запрос для проверки подключения
            db.session.execute(text('SELECT 1'))
            db.session.commit()
            print("✅ Подключение к БД: OK")
            
            # Проверяем тип БД
            db_url = os.environ.get('DATABASE_URL', '')
            if 'postgresql' in db_url.lower() or 'postgres' in db_url.lower():
                print("✅ Тип БД: PostgreSQL")
            elif 'sqlite' in db_url.lower():
                print("✅ Тип БД: SQLite")
            else:
                print("⚠️  Тип БД: Неизвестный")
            
            return True
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False

def check_environment_variables():
    """Проверка переменных окружения"""
    print("\n" + "=" * 60)
    print("2. ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
    print("=" * 60)
    
    checks = {
        'DATABASE_URL': {
            'required': True,
            'check': lambda v: bool(v) and len(v) > 10,
            'message': 'Должна быть корректная строка подключения'
        },
        'SECRET_KEY': {
            'required': False,
            'check': lambda v: bool(v) and len(v) >= 32 if v else False,
            'message': 'Рекомендуется длинная случайная строка (>=32 символов)'
        },
        'ENVIRONMENT': {
            'required': False,
            'check': lambda v: v in ['local', 'sandbox', 'production', 'staging'] if v else True,
            'message': 'Должно быть: local, sandbox, production или staging'
        }
    }
    
    all_ok = True
    for var_name, config in checks.items():
        value = os.environ.get(var_name)
        
        if config['required'] and not value:
            print(f"❌ {var_name}: НЕ УСТАНОВЛЕНА (обязательная)")
            all_ok = False
        elif value:
            if config['check'](value):
                print(f"✅ {var_name}: OK")
            else:
                print(f"⚠️  {var_name}: {config['message']}")
                if config['required']:
                    all_ok = False
        else:
            print(f"ℹ️  {var_name}: не установлена (опциональная)")
    
    return all_ok

def check_database_schema():
    """Проверка схемы БД"""
    print("\n" + "=" * 60)
    print("3. ПРОВЕРКА СХЕМЫ БД")
    print("=" * 60)
    
    required_tables = [
        'Users',
        'UserProfiles',
        'FamilyTies',
        'Enrollments',
        'Students',
        'Lessons',
        'Tasks',
        'LessonTasks',
        'StudentTaskStatistics'
    ]
    
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            missing_tables = []
            for table in required_tables:
                if table in existing_tables:
                    print(f"✅ Таблица {table}: существует")
                else:
                    print(f"❌ Таблица {table}: НЕ НАЙДЕНА")
                    missing_tables.append(table)
            
            if missing_tables:
                print(f"\n⚠️  Отсутствуют таблицы: {', '.join(missing_tables)}")
                print("💡 Выполните: python scripts/init_staging_db.py или создайте таблицы вручную")
                return False
            
            return True
    except Exception as e:
        print(f"❌ Ошибка проверки схемы: {e}")
        return False

def check_table_columns():
    """Проверка наличия ключевых колонок"""
    print("\n" + "=" * 60)
    print("4. ПРОВЕРКА КОЛОНОК ТАБЛИЦ")
    print("=" * 60)
    
    required_columns = {
        'Users': ['id', 'username', 'email', 'role', 'is_active', 'password_hash'],
        'UserProfiles': ['profile_id', 'user_id', 'first_name', 'last_name', 'phone', 'telegram_id'],
        'FamilyTies': ['tie_id', 'parent_id', 'student_id', 'access_level', 'is_confirmed'],
        'Enrollments': ['enrollment_id', 'student_id', 'tutor_id', 'subject', 'status'],
        'Students': ['student_id', 'name', 'email', 'is_active']
    }
    
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            all_ok = True
            
            for table_name, columns in required_columns.items():
                try:
                    table_columns = [col['name'] for col in inspector.get_columns(table_name)]
                    missing = [col for col in columns if col not in table_columns]
                    
                    if missing:
                        print(f"❌ {table_name}: отсутствуют колонки {', '.join(missing)}")
                        all_ok = False
                    else:
                        print(f"✅ {table_name}: все колонки на месте")
                except Exception as e:
                    print(f"❌ {table_name}: ошибка проверки - {e}")
                    all_ok = False
            
            return all_ok
    except Exception as e:
        print(f"❌ Ошибка проверки колонок: {e}")
        return False

def check_rbac_models():
    """Проверка RBAC моделей"""
    print("\n" + "=" * 60)
    print("5. ПРОВЕРКА RBAC МОДЕЛЕЙ")
    print("=" * 60)
    
    try:
        with app.app_context():
            # Проверяем, что модели можно импортировать
            models = [User, UserProfile, FamilyTie, Enrollment]
            for model in models:
                try:
                    count = model.query.count()
                    print(f"✅ {model.__name__}: {count} записей")
                except Exception as e:
                    print(f"❌ {model.__name__}: ошибка - {e}")
                    return False
            
            # Проверяем методы User
            test_user = User.query.first()
            if test_user:
                methods = ['is_admin', 'is_tutor', 'is_student', 'is_parent']
                for method in methods:
                    if hasattr(test_user, method):
                        print(f"✅ User.{method}(): метод существует")
                    else:
                        print(f"❌ User.{method}(): метод отсутствует")
                        return False
            else:
                print("⚠️  Нет пользователей в БД для проверки методов")
            
            return True
    except Exception as e:
        print(f"❌ Ошибка проверки RBAC моделей: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_rbac_utilities():
    """Проверка RBAC утилит"""
    print("\n" + "=" * 60)
    print("6. ПРОВЕРКА RBAC УТИЛИТ")
    print("=" * 60)
    
    try:
        from app.auth.rbac_utils import get_user_scope, apply_data_scope, mask_contact_info
        
        # Проверяем функции
        functions = [
            ('get_user_scope', get_user_scope),
            ('apply_data_scope', apply_data_scope),
            ('mask_contact_info', mask_contact_info)
        ]
        
        for func_name, func in functions:
            if callable(func):
                print(f"✅ {func_name}(): функция существует")
            else:
                print(f"❌ {func_name}(): функция отсутствует")
                return False
        
        # Тестируем mask_contact_info
        test_email = "test@example.com"
        masked = mask_contact_info(test_email)
        if masked and masked != test_email:
            print(f"✅ mask_contact_info(): работает (пример: {test_email} -> {masked})")
        else:
            print(f"⚠️  mask_contact_info(): возможно не работает корректно")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка проверки RBAC утилит: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_routes():
    """Проверка маршрутов"""
    print("\n" + "=" * 60)
    print("7. ПРОВЕРКА МАРШРУТОВ")
    print("=" * 60)
    
    try:
        # Проверяем, что blueprint'ы зарегистрированы
        blueprints = [
            'auth',
            'main',
            'parents',
            'admin',
            'students'
        ]
        
        registered_blueprints = [bp.name for bp in app.blueprints.values()]
        
        for bp_name in blueprints:
            if bp_name in registered_blueprints:
                print(f"✅ Blueprint '{bp_name}': зарегистрирован")
            else:
                print(f"❌ Blueprint '{bp_name}': НЕ зарегистрирован")
                return False
        
        # Проверяем наличие ключевых маршрутов через список правил
        required_paths = [
            '/login',
            '/logout',
            '/dashboard',
            '/parents/parent/dashboard',
            '/admin',
        ]
        
        registered_paths = [str(rule) for rule in app.url_map.iter_rules()]
        
        for path in required_paths:
            found = any(path in str(rule) for rule in app.url_map.iter_rules())
            if found:
                print(f"✅ Маршрут '{path}': зарегистрирован")
            else:
                print(f"⚠️  Маршрут '{path}': не найден (может быть нормально)")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка проверки маршрутов: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_templates():
    """Проверка шаблонов"""
    print("\n" + "=" * 60)
    print("8. ПРОВЕРКА ШАБЛОНОВ")
    print("=" * 60)
    
    import os
    templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
    
    required_templates = [
        'login.html',
        'dashboard.html',
        'parent_dashboard.html',
        'student_profile.html',
        'student_stats_unified.html',
        '_primary_nav.html',
        'admin_panel.html'
    ]
    
    all_ok = True
    for template in required_templates:
        template_path = os.path.join(templates_dir, template)
        if os.path.exists(template_path):
            print(f"✅ {template}: существует")
        else:
            print(f"❌ {template}: НЕ НАЙДЕН")
            all_ok = False
    
    return all_ok

def check_test_data():
    """Проверка тестовых данных"""
    print("\n" + "=" * 60)
    print("9. ПРОВЕРКА ТЕСТОВЫХ ДАННЫХ")
    print("=" * 60)
    
    try:
        with app.app_context():
            # Проверяем наличие тестовых пользователей
            test_usernames = ['admin', 'tutor1', 'student1', 'parent1']
            found_users = []
            
            for username in test_usernames:
                user = User.query.filter_by(username=username).first()
                if user:
                    found_users.append(username)
                    # Проверяем профиль
                    profile = UserProfile.query.filter_by(user_id=user.id).first()
                    if profile:
                        print(f"✅ {username}: User + Profile")
                    else:
                        print(f"⚠️  {username}: User есть, но нет Profile")
                else:
                    print(f"ℹ️  {username}: не найден (можно создать через seed)")
            
            if found_users:
                print(f"\n✅ Найдено тестовых пользователей: {len(found_users)}")
            else:
                print("\n⚠️  Тестовые пользователи не найдены")
                print("💡 Выполните: python scripts/seed_rbac_data.py --sandbox")
            
            # Проверяем Enrollment
            enrollments_count = Enrollment.query.count()
            if enrollments_count > 0:
                print(f"✅ Enrollment: {enrollments_count} связей")
            else:
                print("ℹ️  Enrollment: нет связей (можно создать через seed)")
            
            # Проверяем FamilyTie
            family_ties_count = FamilyTie.query.count()
            if family_ties_count > 0:
                print(f"✅ FamilyTie: {family_ties_count} связей")
            else:
                print("ℹ️  FamilyTie: нет связей (можно создать через seed)")
            
            # Проверяем Student записи для учеников
            student_users = User.query.filter_by(role='student').all()
            students_with_records = 0
            for user in student_users:
                if user.email:
                    student = Student.query.filter_by(email=user.email).first()
                    if student:
                        students_with_records += 1
            
            if student_users:
                print(f"✅ Student записи: {students_with_records}/{len(student_users)} учеников имеют Student записи")
                if students_with_records < len(student_users):
                    print("⚠️  Некоторые ученики не имеют Student записей")
                    print("💡 Выполните seed скрипт заново для создания Student записей")
            
            return True
    except Exception as e:
        print(f"❌ Ошибка проверки тестовых данных: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Основная функция проверки"""
    print("\n" + "=" * 60)
    print("ПРЕДВАРИТЕЛЬНАЯ ПРОВЕРКА СИСТЕМЫ (PRE-FLIGHT CHECKS)")
    print("=" * 60)
    print()
    
    checks = [
        ("Подключение к БД", check_database_connection),
        ("Переменные окружения", check_environment_variables),
        ("Схема БД", check_database_schema),
        ("Колонки таблиц", check_table_columns),
        ("RBAC модели", check_rbac_models),
        ("RBAC утилиты", check_rbac_utilities),
        ("Маршруты", check_routes),
        ("Шаблоны", check_templates),
        ("Тестовые данные", check_test_data),
    ]
    
    results = []
    for check_name, check_func in checks:
        try:
            result = check_func()
            results.append((check_name, result))
        except Exception as e:
            print(f"\n❌ Критическая ошибка при проверке '{check_name}': {e}")
            results.append((check_name, False))
    
    # Итоговая сводка
    print("\n" + "=" * 60)
    print("ИТОГОВАЯ СВОДКА")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for check_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {check_name}")
    
    print(f"\nПройдено проверок: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! Система готова к работе.")
        return 0
    else:
        print(f"\n⚠️  НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ. Исправьте ошибки перед запуском.")
        return 1

if __name__ == '__main__':
    sys.exit(main())
