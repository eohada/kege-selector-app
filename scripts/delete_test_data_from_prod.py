"""
Скрипт для удаления тестовых данных RBAC из production базы
ВНИМАНИЕ: Используйте только если данные случайно попали в production!
"""
import os
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from core.db_models import User, UserProfile, FamilyTie, Enrollment

TEST_USERNAMES = ['admin', 'tutor1', 'tutor2', 'student1', 'student2', 'student3', 'parent1', 'parent2']

app = create_app()

def delete_test_data():
    """Удаляет тестовые данные из текущей базы"""
    with app.app_context():
        environment = os.environ.get('ENVIRONMENT', 'local')
        database_url = os.environ.get('DATABASE_URL', '')
        
        if 'production' in database_url.lower() or environment == 'production':
            print("⚠️  ВНИМАНИЕ: Похоже, вы подключены к PRODUCTION базе!")
            print(f"   DATABASE_URL: {database_url.split('@')[-1] if '@' in database_url else 'N/A'}")
            response = input("Вы УВЕРЕНЫ, что хотите удалить данные из PRODUCTION? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Отменено")
                return False
        else:
            print(f"🌍 Окружение: {environment}")
            print(f"🔌 БД: {database_url.split('@')[-1] if '@' in database_url else 'N/A'}")
        
        print("\n🗑️  Удаление тестовых данных...")
        
        test_users = User.query.filter(User.username.in_(TEST_USERNAMES)).all()
        test_user_ids = [u.id for u in test_users]
        
        if not test_user_ids:
            print("✅ Тестовые пользователи не найдены, нечего удалять")
            return True
        
        print(f"   Найдено пользователей: {len(test_user_ids)}")
        
        from sqlalchemy import or_
        
        deleted_enrollments = Enrollment.query.filter(Enrollment.student_id.in_(test_user_ids)).delete(synchronize_session=False)
        print(f"   Удалено Enrollment: {deleted_enrollments}")
        
        deleted_ties = FamilyTie.query.filter(
            or_(
                FamilyTie.parent_id.in_(test_user_ids),
                FamilyTie.student_id.in_(test_user_ids)
            )
        ).delete(synchronize_session=False)
        print(f"   Удалено FamilyTie: {deleted_ties}")
        
        deleted_profiles = UserProfile.query.filter(UserProfile.user_id.in_(test_user_ids)).delete(synchronize_session=False)
        print(f"   Удалено UserProfile: {deleted_profiles}")
        
        deleted_users = User.query.filter(User.username.in_(TEST_USERNAMES)).delete(synchronize_session=False)
        print(f"   Удалено User: {deleted_users}")
        
        db.session.commit()
        print("\n✅ Тестовые данные удалены из базы")
        return True

if __name__ == '__main__':
    success = delete_test_data()
    sys.exit(0 if success else 1)
