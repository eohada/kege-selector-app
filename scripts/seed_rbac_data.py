#!/usr/bin/env python3
"""
Скрипт для наполнения БД тестовыми данными RBAC системы
Аналог Prisma db seed для Flask/SQLAlchemy

Использование:
  python scripts/seed_rbac_data.py [--reset] [--sandbox] [--force-production] [--yes]

Опции:
  --reset              Удалить все существующие тестовые данные перед созданием
  --sandbox            Явно указать, что работаем с sandbox базой
  --force-production    Разрешить выполнение в production (не рекомендуется)
  --yes                 Автоматически подтвердить удаление данных (для --reset)

Примеры:
  # Наполнить sandbox базу
  ENVIRONMENT=sandbox python scripts/seed_rbac_data.py
  # или
  python scripts/seed_rbac_data.py --sandbox
  
  # Наполнить sandbox с удалением старых данных
  python scripts/seed_rbac_data.py --sandbox --reset --yes

Создает:
  - Пользователей с ролями: admin, tutor, student, parent
  - UserProfile для каждого пользователя
  - FamilyTie связи (родитель-ученик)
  - Enrollment связи (ученик-тьютор)
"""
import os
import sys
import io

# Обработка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, UserProfile, FamilyTie, Enrollment, moscow_now
from app.models import Student
from werkzeug.security import generate_password_hash

# Создаем приложение (будет пересоздано в seed_database если нужно)
app = None


# Тестовые данные
TEST_USERS = [
    # Администратор
    {
        'username': 'admin',
        'email': 'admin@example.com',
        'password': 'admin123',
        'role': 'admin',
        'profile': {
            'first_name': 'Администратор',
            'last_name': 'Системы',
            'phone': '+7 900 000 00 01',
            'telegram_id': '@admin_support'
        }
    },
    # Тьюторы
    {
        'username': 'tutor1',
        'email': 'tutor1@example.com',
        'password': 'tutor123',
        'role': 'tutor',
        'profile': {
            'first_name': 'Анна',
            'last_name': 'Преподаватель',
            'phone': '+7 900 000 00 02',
            'telegram_id': '@tutor_anna'
        }
    },
    {
        'username': 'tutor2',
        'email': 'tutor2@example.com',
        'password': 'tutor123',
        'role': 'tutor',
        'profile': {
            'first_name': 'Иван',
            'last_name': 'Учитель',
            'phone': '+7 900 000 00 03',
            'telegram_id': '@tutor_ivan'
        }
    },
    # Ученики
    {
        'username': 'student1',
        'email': 'student1@example.com',
        'password': 'student123',
        'role': 'student',
        'profile': {
            'first_name': 'Петр',
            'last_name': 'Учеников',
            'phone': '+7 900 000 00 04',
            'telegram_id': '@student_petr'
        }
    },
    {
        'username': 'student2',
        'email': 'student2@example.com',
        'password': 'student123',
        'role': 'student',
        'profile': {
            'first_name': 'Мария',
            'last_name': 'Студентова',
            'phone': '+7 900 000 00 05',
            'telegram_id': '@student_maria'
        }
    },
    {
        'username': 'student3',
        'email': 'student3@example.com',
        'password': 'student123',
        'role': 'student',
        'profile': {
            'first_name': 'Алексей',
            'last_name': 'Учеников',
            'phone': '+7 900 000 00 06',
            'telegram_id': '@student_alex'
        }
    },
    # Родители
    {
        'username': 'parent1',
        'email': 'parent1@example.com',
        'password': 'parent123',
        'role': 'parent',
        'profile': {
            'first_name': 'Ольга',
            'last_name': 'Родительская',
            'phone': '+7 900 000 00 07',
            'telegram_id': '@parent_olga'
        }
    },
    {
        'username': 'parent2',
        'email': 'parent2@example.com',
        'password': 'parent123',
        'role': 'parent',
        'profile': {
            'first_name': 'Сергей',
            'last_name': 'Родительский',
            'phone': '+7 900 000 00 08',
            'telegram_id': '@parent_sergey'
        }
    }
]

# Связи FamilyTie (родитель -> ученик)
FAMILY_TIES = [
    {'parent_username': 'parent1', 'student_username': 'student1', 'access_level': 'full'},
    {'parent_username': 'parent1', 'student_username': 'student2', 'access_level': 'full'},
    {'parent_username': 'parent2', 'student_username': 'student3', 'access_level': 'full'},
]

# Связи Enrollment (ученик -> тьютор -> предмет)
ENROLLMENTS = [
    {'student_username': 'student1', 'tutor_username': 'tutor1', 'subject': 'INFORMATICS_EGE_2025'},
    {'student_username': 'student2', 'tutor_username': 'tutor1', 'subject': 'INFORMATICS_EGE_2025'},
    {'student_username': 'student3', 'tutor_username': 'tutor2', 'subject': 'INFORMATICS_EGE_2025'},
]


def reset_test_data():
    """Удаляет все тестовые данные"""
    print("🗑️  Удаление существующих тестовых данных...")
    
    test_usernames = [u['username'] for u in TEST_USERS]
    
    # Получаем ID тестовых пользователей
    test_user_ids = db.session.query(User.id).filter(User.username.in_(test_usernames)).all()
    test_user_ids = [uid[0] for uid in test_user_ids]
    
    if not test_user_ids:
        print("  ℹ️  Тестовые пользователи не найдены, пропускаем удаление")
        return
    
    # Удаляем в правильном порядке (сначала зависимые таблицы)
    from sqlalchemy import or_
    
    Enrollment.query.filter(Enrollment.student_id.in_(test_user_ids)).delete(synchronize_session=False)
    
    FamilyTie.query.filter(
        or_(
            FamilyTie.parent_id.in_(test_user_ids),
            FamilyTie.student_id.in_(test_user_ids)
        )
    ).delete(synchronize_session=False)
    
    UserProfile.query.filter(UserProfile.user_id.in_(test_user_ids)).delete(synchronize_session=False)
    
    User.query.filter(User.username.in_(test_usernames)).delete(synchronize_session=False)
    
    db.session.commit()
    print("✅ Тестовые данные удалены")


def create_users():
    """Создает пользователей и их профили"""
    print("\n👥 Создание пользователей...")
    users_dict = {}
    
    for user_data in TEST_USERS:
        username = user_data['username']
        
        # Проверяем, существует ли пользователь
        user = User.query.filter_by(username=username).first()
        
        if user:
            # Обновляем существующего пользователя
            user.email = user_data['email']
            user.password_hash = generate_password_hash(user_data['password'])
            user.role = user_data['role']
            user.is_active = True
            print(f"  ✅ Обновлен: {username} ({user_data['role']})")
        else:
            # Создаем нового пользователя
            user = User(
                username=username,
                email=user_data['email'],
                password_hash=generate_password_hash(user_data['password']),
                role=user_data['role'],
                is_active=True,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.flush()  # Получаем ID
            print(f"  ✅ Создан: {username} ({user_data['role']})")
        
        # Создаем или обновляем профиль
        profile_data = user_data.get('profile', {})
        if not profile_data:
            print(f"  ⚠️  Нет данных профиля для {username}, пропускаем")
            users_dict[username] = user
            continue
        
        profile = UserProfile.query.filter_by(user_id=user.id).first()
        
        if profile:
            profile.first_name = profile_data.get('first_name')
            profile.last_name = profile_data.get('last_name')
            profile.phone = profile_data.get('phone')
            profile.telegram_id = profile_data.get('telegram_id')
            print(f"    📝 Профиль обновлен для {username}")
        else:
            profile = UserProfile(
                user_id=user.id,
                first_name=profile_data.get('first_name'),
                last_name=profile_data.get('last_name'),
                phone=profile_data.get('phone'),
                telegram_id=profile_data.get('telegram_id'),
                timezone=profile_data.get('timezone', 'Europe/Moscow')
            )
            db.session.add(profile)
            print(f"    📝 Профиль создан для {username}")
        
        # Для учеников создаем соответствующую запись Student
        if user_data['role'] == 'student' and user.email:
            student = Student.query.filter_by(email=user.email).first()
            if not student:
                # Создаем Student запись для ученика
                profile_name = f"{profile_data.get('first_name', '')} {profile_data.get('last_name', '')}".strip()
                if not profile_name:
                    profile_name = user.username
                
                student = Student(
                    name=profile_name,
                    email=user.email,
                    phone=profile_data.get('phone'),
                    telegram=profile_data.get('telegram_id'),
                    is_active=True
                )
                db.session.add(student)
                print(f"    👨‍🎓 Student запись создана для {username}")
            else:
                # Обновляем существующую запись
                profile_name = f"{profile_data.get('first_name', '')} {profile_data.get('last_name', '')}".strip()
                if profile_name:
                    student.name = profile_name
                if profile_data.get('phone'):
                    student.phone = profile_data.get('phone')
                if profile_data.get('telegram_id'):
                    student.telegram = profile_data.get('telegram_id')
                student.is_active = True
                print(f"    👨‍🎓 Student запись обновлена для {username}")
        
        users_dict[username] = user
    
    db.session.commit()
    print(f"✅ Создано/обновлено пользователей: {len(users_dict)}")
    return users_dict


def create_family_ties(users_dict):
    """Создает связи родитель-ученик"""
    print("\n👨‍👩‍👧 Создание семейных связей...")
    
    for tie_data in FAMILY_TIES:
        parent = users_dict.get(tie_data['parent_username'])
        student = users_dict.get(tie_data['student_username'])
        
        if not parent or not student:
            print(f"  ⚠️  Пропущено: {tie_data['parent_username']} -> {tie_data['student_username']} (пользователь не найден)")
            continue
        
        # Проверяем, существует ли связь
        family_tie = FamilyTie.query.filter_by(
            parent_id=parent.id,
            student_id=student.id
        ).first()
        
        # Получаем имена для вывода
        def get_user_name(user):
            """Безопасно получает имя пользователя из профиля"""
            try:
                # Загружаем профиль через запрос
                profile = UserProfile.query.filter_by(user_id=user.id).first()
                if profile and profile.first_name:
                    return f"{profile.first_name} {profile.last_name or ''}".strip()
            except:
                pass
            return user.username
        
        parent_name = get_user_name(parent)
        student_name = get_user_name(student)
        
        if family_tie:
            family_tie.access_level = tie_data['access_level']
            family_tie.is_confirmed = True
            print(f"  ✅ Обновлена связь: {parent_name} -> {student_name}")
        else:
            family_tie = FamilyTie(
                parent_id=parent.id,
                student_id=student.id,
                access_level=tie_data['access_level'],
                is_confirmed=True,
                created_at=moscow_now()
            )
            db.session.add(family_tie)
            print(f"  ✅ Создана связь: {parent_name} -> {student_name}")
    
    db.session.commit()
    print(f"✅ Создано/обновлено семейных связей: {len(FAMILY_TIES)}")


def create_enrollments(users_dict):
    """Создает связи ученик-тьютор-предмет"""
    print("\n📚 Создание учебных контрактов...")
    
    for enrollment_data in ENROLLMENTS:
        student = users_dict.get(enrollment_data['student_username'])
        tutor = users_dict.get(enrollment_data['tutor_username'])
        
        if not student or not tutor:
            print(f"  ⚠️  Пропущено: {enrollment_data['student_username']} -> {enrollment_data['tutor_username']} (пользователь не найден)")
            continue
        
        # Проверяем, существует ли контракт
        enrollment = Enrollment.query.filter_by(
            student_id=student.id,
            tutor_id=tutor.id,
            subject=enrollment_data['subject']
        ).first()
        
        # Получаем имена для вывода
        def get_user_name(user):
            """Безопасно получает имя пользователя из профиля"""
            try:
                # Загружаем профиль через запрос
                profile = UserProfile.query.filter_by(user_id=user.id).first()
                if profile and profile.first_name:
                    return f"{profile.first_name} {profile.last_name or ''}".strip()
            except:
                pass
            return user.username
        
        student_name = get_user_name(student)
        tutor_name = get_user_name(tutor)
        
        if enrollment:
            enrollment.status = 'active'
            print(f"  ✅ Обновлен контракт: {student_name} -> {tutor_name} ({enrollment_data['subject']})")
        else:
            enrollment = Enrollment(
                student_id=student.id,
                tutor_id=tutor.id,
                subject=enrollment_data['subject'],
                status='active',
                created_at=moscow_now()
            )
            db.session.add(enrollment)
            print(f"  ✅ Создан контракт: {student_name} -> {tutor_name} ({enrollment_data['subject']})")
    
    db.session.commit()
    print(f"✅ Создано/обновлено учебных контрактов: {len(ENROLLMENTS)}")


def print_summary(users_dict):
    """Выводит сводку созданных данных"""
    print("\n" + "="*60)
    print("📊 СВОДКА СОЗДАННЫХ ДАННЫХ")
    print("="*60)
    
    print("\n👥 Пользователи:")
    for role in ['admin', 'tutor', 'student', 'parent']:
        users_by_role = [u for u in users_dict.values() if u.role == role]
        if users_by_role:
            print(f"  {role.upper()}: {len(users_by_role)}")
            for user in users_by_role:
                # Безопасно получаем имя из профиля
                profile = UserProfile.query.filter_by(user_id=user.id).first()
                if profile and profile.first_name:
                    profile_name = f"{profile.first_name} {profile.last_name or ''}".strip()
                else:
                    profile_name = user.username
                print(f"    - {user.username} ({user.email}) - {profile_name}")
    
    print("\n👨‍👩‍👧 Семейные связи:")
    family_ties = FamilyTie.query.join(User, FamilyTie.parent_id == User.id).filter(
        User.username.in_([u['username'] for u in TEST_USERS if u['role'] == 'parent'])
    ).all()
    for tie in family_ties:
        parent = User.query.get(tie.parent_id)
        student = User.query.get(tie.student_id)
        # Безопасно получаем имена из профилей
        parent_profile = UserProfile.query.filter_by(user_id=parent.id).first() if parent else None
        student_profile = UserProfile.query.filter_by(user_id=student.id).first() if student else None
        parent_name = f"{parent_profile.first_name} {parent_profile.last_name or ''}".strip() if parent_profile and parent_profile.first_name else (parent.username if parent else 'N/A')
        student_name = f"{student_profile.first_name} {student_profile.last_name or ''}".strip() if student_profile and student_profile.first_name else (student.username if student else 'N/A')
        print(f"  - {parent_name} -> {student_name} ({tie.access_level})")
    
    print("\n📚 Учебные контракты:")
    enrollments = Enrollment.query.join(User, Enrollment.student_id == User.id).filter(
        User.username.in_([u['username'] for u in TEST_USERS if u['role'] == 'student'])
    ).all()
    for enrollment in enrollments:
        student = User.query.get(enrollment.student_id)
        tutor = User.query.get(enrollment.tutor_id)
        # Безопасно получаем имена из профилей
        student_profile = UserProfile.query.filter_by(user_id=student.id).first() if student else None
        tutor_profile = UserProfile.query.filter_by(user_id=tutor.id).first() if tutor else None
        student_name = f"{student_profile.first_name} {student_profile.last_name or ''}".strip() if student_profile and student_profile.first_name else (student.username if student else 'N/A')
        tutor_name = f"{tutor_profile.first_name} {tutor_profile.last_name or ''}".strip() if tutor_profile and tutor_profile.first_name else (tutor.username if tutor else 'N/A')
        print(f"  - {student_name} -> {tutor_name} ({enrollment.subject})")
    
    print("\n" + "="*60)
    print("✅ Наполнение БД завершено успешно!")
    print("="*60)


def seed_database(reset=False, force_production=False, target_environment=None, use_sandbox=False):
    """Основная функция наполнения БД"""
    global app
    
    # Если нужно использовать sandbox, переключаем DATABASE_URL
    if use_sandbox:
        sandbox_url = os.environ.get('SANDBOX_DATABASE_URL')
        if not sandbox_url:
            print("❌ ОШИБКА: SANDBOX_DATABASE_URL не установлен!")
            print("\n💡 Как получить URL sandbox базы:")
            print("   1. Railway → Ваш проект → Переключитесь на окружение 'sandbox'")
            print("   2. PostgreSQL → Connect → Public Network URL")
            print("   3. Скопируйте URL и установите:")
            print("      $env:SANDBOX_DATABASE_URL='postgresql://...'")
            return False
        
        # Сохраняем оригинальный DATABASE_URL
        original_db_url = os.environ.get('DATABASE_URL')
        os.environ['DATABASE_URL'] = sandbox_url
        print(f"🔄 Переключено на SANDBOX базу данных")
        
        # Пересоздаем app с новым DATABASE_URL
        app = create_app()
        os.environ['ENVIRONMENT'] = 'sandbox'
    
    if not app:
        app = create_app()
    
    with app.app_context():
        # Проверяем окружение
        environment = target_environment or os.environ.get('ENVIRONMENT', 'local')
        
        # Показываем информацию о подключении
        database_url = os.environ.get('DATABASE_URL', '')
        if database_url:
            # Маскируем пароль в URL для безопасности
            masked_url = database_url.split('@')[-1] if '@' in database_url else database_url[:50] + '...'
            print(f"🔌 Подключение к БД: {masked_url}")
        print(f"🌍 Окружение: {environment}")
        
        if environment == 'production' and not force_production:
            print("❌ ОШИБКА: Наполнение БД тестовыми данными в production запрещено!")
            print(f"   Текущее окружение: {environment}")
            print("\n💡 Решения:")
            print("   1. Установите ENVIRONMENT=sandbox")
            print("   2. Или используйте --force-production (НЕ рекомендуется!)")
            return False
        
        try:
            if reset:
                reset_test_data()
            
            users_dict = create_users()
            create_family_ties(users_dict)
            create_enrollments(users_dict)
            print_summary(users_dict)
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"\n❌ ОШИБКА при наполнении БД: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    reset = '--reset' in sys.argv
    force_production = '--force-production' in sys.argv
    auto_yes = '--yes' in sys.argv
    
    # Если указан --sandbox, используем sandbox базу
    use_sandbox = '--sandbox' in sys.argv
    if use_sandbox:
        print("🌍 Режим: SANDBOX")
        if not os.environ.get('SANDBOX_DATABASE_URL'):
            print("⚠️  ВНИМАНИЕ: SANDBOX_DATABASE_URL не установлен!")
            print("   Скрипт попытается использовать DATABASE_URL, но это может быть production!")
            print("\n💡 Для работы с sandbox установите:")
            print("   $env:SANDBOX_DATABASE_URL='postgresql://user:pass@host:port/db'")
            print("   (Получите URL из Railway → Sandbox → PostgreSQL → Connect → Public Network URL)")
            response = input("\nПродолжить без SANDBOX_DATABASE_URL? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Отменено")
                sys.exit(0)
    
    if reset:
        print("⚠️  ВНИМАНИЕ: Будет удалена вся существующая тестовая информация!")
        if auto_yes:
            print("  (подтверждено через --yes)")
        else:
            try:
                response = input("Продолжить? (yes/no): ")
                if response.lower() != 'yes':
                    print("❌ Отменено")
                    sys.exit(0)
            except EOFError:
                # Если нет интерактивного ввода (например, в CI/CD)
                print("⚠️  Нет интерактивного ввода. Используйте --yes для автоматического подтверждения.")
                sys.exit(1)
    
    success = seed_database(reset=reset, force_production=force_production, use_sandbox=use_sandbox)
    sys.exit(0 if success else 1)
