"""
Script to clean up user account pool and set explicit dev passwords.
Prints formatted credentials table upon completion.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from core.db_models import db, User
from werkzeug.security import generate_password_hash

def cleanup_and_seed_user_pool():
    app = create_app()
    with app.app_context():
        print("Cleaning up user pool and setting explicit dev passwords...")

        target_accounts = [
            # CREATOR
            {'username': 'creator', 'role': 'creator', 'password': 'creator123', 'email': 'creator@boostudy.ru'},
            
            # ADMINS
            {'username': 'admin_1', 'role': 'admin', 'password': 'admin123', 'email': 'admin1@boostudy.ru'},
            {'username': 'admin_2', 'role': 'admin', 'password': 'admin123', 'email': 'admin2@boostudy.ru'},
            {'username': 'admin_3', 'role': 'admin', 'password': 'admin123', 'email': 'admin3@boostudy.ru'},

            # TEACHERS
            {'username': 'teacher_1', 'role': 'teacher', 'password': 'teacher123', 'email': 'teacher1@boostudy.ru'},
            {'username': 'teacher_2', 'role': 'teacher', 'password': 'teacher123', 'email': 'teacher2@boostudy.ru'},
            {'username': 'teacher_3', 'role': 'teacher', 'password': 'teacher123', 'email': 'teacher3@boostudy.ru'},

            # STUDENTS
            {'username': 'student_1', 'role': 'student', 'password': 'student123', 'email': 'student1@boostudy.ru'},
            {'username': 'student_2', 'role': 'student', 'password': 'student123', 'email': 'student2@boostudy.ru'},
            {'username': 'student_3', 'role': 'student', 'password': 'student123', 'email': 'student3@boostudy.ru'},

            # PARENTS
            {'username': 'parent_1', 'role': 'parent', 'password': 'parent123', 'email': 'parent1@boostudy.ru'},
            {'username': 'parent_2', 'role': 'parent', 'password': 'parent123', 'email': 'parent2@boostudy.ru'},
            {'username': 'parent_3', 'role': 'parent', 'password': 'parent123', 'email': 'parent3@boostudy.ru'},

            # TESTERS
            {'username': 'tester_1', 'role': 'tester', 'password': 'tester123', 'email': 'tester1@boostudy.ru'},
            {'username': 'tester_2', 'role': 'tester', 'password': 'tester123', 'email': 'tester2@boostudy.ru'},
            {'username': 'tester_3', 'role': 'tester', 'password': 'tester123', 'email': 'tester3@boostudy.ru'},
        ]

        target_usernames = tuple(acc['username'] for acc in target_accounts)
        placeholders = ', '.join([':u' + str(i) for i in range(len(target_usernames))])
        params = {'u' + str(i): u for i, u in enumerate(target_usernames)}

        # Direct SQL cleanup of junk users (PostgreSQL & SQLite compatible)
        if db.engine.name == 'sqlite':
            db.session.execute(db.text("PRAGMA foreign_keys = OFF;"))
        try:
            db.session.execute(db.text(f'DELETE FROM "UserProfiles" WHERE user_id NOT IN (SELECT id FROM "Users" WHERE username IN ({placeholders}));'), params)
            db.session.execute(db.text(f'DELETE FROM "Users" WHERE username NOT IN ({placeholders});'), params)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"User cleanup notice: {e}")
            db.session.commit()

        if db.engine.name == 'sqlite':
            db.session.execute(db.text("PRAGMA foreign_keys = ON;"))
        db.session.commit()

        # Seed or update accounts with clean password hashes
        for acc in target_accounts:
            user = User.query.filter_by(username=acc['username']).first()
            if not user:
                user = User(
                    username=acc['username'],
                    email=acc['email'],
                    role=acc['role'],
                    password_hash=generate_password_hash(acc['password']),
                    is_active=True
                )
                db.session.add(user)
            else:
                user.role = acc['role']
                user.email = acc['email']
                user.password_hash = generate_password_hash(acc['password'])
                user.is_active = True
            db.session.commit()

        # PRINT FORMATTED CREDENTIALS TABLE
        print("\n" + "=" * 60)
        print("BOOSTUDY DEV USER POOL CREDENTIALS")
        print("=" * 60)
        print("CREATOR:  creator                   | Password: creator123")
        print("ADMINS:   admin_1, admin_2, admin_3 | Password: admin123")
        print("TEACHERS: teacher_1, teacher_2, teacher_3 | Password: teacher123")
        print("STUDENTS: student_1, student_2, student_3 | Password: student123")
        print("PARENTS:  parent_1, parent_2, parent_3  | Password: parent123")
        print("TESTERS:  tester_1, tester_2, tester_3   | Password: tester123")
        print("=" * 60 + "\n")

if __name__ == '__main__':
    cleanup_and_seed_user_pool()
