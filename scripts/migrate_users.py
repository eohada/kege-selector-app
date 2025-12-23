
import sys
import os

# Добавляем корневую директорию в путь импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text, inspect

app = create_app()

def migrate_users():
    with app.app_context():
        print("Starting manual migration for Users table...")
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        
        users_table = 'Users' if 'Users' in table_names else ('users' if 'users' in table_names else None)
        
        if not users_table:
            print("Error: Users table not found!")
            return

        print(f"Found table: {users_table}")
        users_columns = {col['name'] for col in inspector.get_columns(users_table)}
        print(f"Existing columns: {users_columns}")

        columns_to_add = [
            ('avatar_url', 'VARCHAR(500)'),
            ('about_me', 'TEXT'),
            ('custom_status', 'VARCHAR(100)'),
            ('telegram_link', 'VARCHAR(200)'),
            ('github_link', 'VARCHAR(200)')
        ]

        for col_name, col_type in columns_to_add:
            if col_name not in users_columns:
                print(f"Adding column {col_name}...")
                try:
                    db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN {col_name} {col_type}'))
                    print(f"Added {col_name}")
                except Exception as e:
                    print(f"Failed to add {col_name}: {e}")
                    db.session.rollback()
            else:
                print(f"Column {col_name} already exists.")

        try:
            db.session.commit()
            print("Migration committed successfully.")
        except Exception as e:
            print(f"Error during commit: {e}")
            db.session.rollback()

if __name__ == "__main__":
    migrate_users()
