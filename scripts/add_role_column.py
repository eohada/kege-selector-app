#!/usr/bin/env python3
"""Скрипт для добавления поля role в таблицу Users"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db
from sqlalchemy import text

def add_role_column():
    """Добавляет поле role в таблицу Users"""
    with app.app_context():
        try:
            # Проверяем, существует ли уже поле role
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('Users')]
            
            if 'role' in columns:
                print("✅ Поле 'role' уже существует в таблице Users")
                return
            
            # Добавляем поле role
            db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'postgresql' in db_url or 'postgres' in db_url:
                # PostgreSQL
                db.session.execute(text('ALTER TABLE "Users" ADD COLUMN role VARCHAR(50) DEFAULT \'tester\' NOT NULL'))
                # Обновляем существующие записи
                db.session.execute(text('UPDATE "Users" SET role = \'tester\' WHERE role IS NULL'))
            else:
                # SQLite
                db.session.execute(text('ALTER TABLE Users ADD COLUMN role VARCHAR(50) DEFAULT \'tester\' NOT NULL'))
                db.session.execute(text('UPDATE Users SET role = \'tester\' WHERE role IS NULL'))
            
            db.session.commit()
            print("✅ Поле 'role' успешно добавлено в таблицу Users")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Ошибка при добавлении поля role: {e}")
            raise

if __name__ == '__main__':
    add_role_column()
























