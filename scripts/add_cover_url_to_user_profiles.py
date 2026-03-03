"""Добавляет колонку cover_url в таблицу UserProfiles (баннер профиля креатора)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from sqlalchemy import text

def add_cover_url_column():
    app = create_app()
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            table_name = 'UserProfiles'
            if table_name not in inspector.get_table_names():
                print(f"Таблица {table_name} не найдена, пропуск.")
                return
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            if 'cover_url' in columns:
                print("Колонка cover_url уже есть в UserProfiles.")
                return
            db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'postgresql' in db_url or 'postgres' in db_url:
                db.session.execute(text('ALTER TABLE "UserProfiles" ADD COLUMN cover_url VARCHAR(500)'))
            else:
                db.session.execute(text('ALTER TABLE UserProfiles ADD COLUMN cover_url VARCHAR(500)'))
            db.session.commit()
            print("Колонка cover_url добавлена в UserProfiles.")
        except Exception as e:
            db.session.rollback()
            print(f"Ошибка: {e}")
            raise

if __name__ == '__main__':
    add_cover_url_column()
 


 