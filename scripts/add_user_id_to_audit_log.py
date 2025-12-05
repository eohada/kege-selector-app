#!/usr/bin/env python3
"""
Скрипт для добавления поля user_id в таблицу AuditLog
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from core.db_models import db
from sqlalchemy import text

def add_user_id_column():
    """Добавляет поле user_id в таблицу AuditLog"""
    with app.app_context():
        try:
            # Проверяем, существует ли уже колонка user_id
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('AuditLog')]
            
            if 'user_id' in columns:
                print("Колонка user_id уже существует в таблице AuditLog")
                return
            
            # Добавляем колонку user_id
            print("Добавление колонки user_id в таблицу AuditLog...")
            db.session.execute(text("""
                ALTER TABLE "AuditLog" 
                ADD COLUMN user_id INTEGER 
                REFERENCES "Users"(id) 
                ON DELETE SET NULL
            """))
            
            # Создаем индекс для user_id
            print("Создание индекса для user_id...")
            db.session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_audit_user_id 
                ON "AuditLog"(user_id)
            """))
            
            db.session.commit()
            print("✓ Колонка user_id успешно добавлена в таблицу AuditLog")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Ошибка при добавлении колонки user_id: {e}")
            raise

if __name__ == '__main__':
    add_user_id_column()


