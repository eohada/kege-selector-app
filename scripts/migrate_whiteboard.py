"""
Миграция: Создание таблицы LessonWhiteboards для интерактивных досок Miro.

Запуск:
    python scripts/migrate_whiteboard.py          # использует настройки из окружения
    python scripts/migrate_whiteboard.py --local  # принудительно SQLite
"""
import sys
import os

# Добавляем корневую директорию проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Если передан флаг --local, используем SQLite
if '--local' in sys.argv or not os.environ.get('DATABASE_URL'):
    # Убираем DATABASE_URL чтобы приложение использовало SQLite
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('DATABASE_EXTERNAL_URL', None)
    os.environ.pop('POSTGRES_URL', None)
    print("[LOCAL] Using SQLite database")

from app import create_app
from app.models import db
from sqlalchemy import text, inspect

def migrate():
    """Создаёт таблицу LessonWhiteboards если её нет."""
    app = create_app()
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        if 'LessonWhiteboards' in existing_tables:
            print("[OK] Table LessonWhiteboards already exists")
            return
        
        print("[MIGRATE] Creating table LessonWhiteboards...")
        
        # Определяем тип БД
        is_postgres = 'postgresql' in str(db.engine.url)
        
        if is_postgres:
            # PostgreSQL
            sql = """
            CREATE TABLE IF NOT EXISTS "LessonWhiteboards" (
                id SERIAL PRIMARY KEY,
                lesson_id INTEGER NOT NULL UNIQUE REFERENCES "Lessons"(lesson_id) ON DELETE CASCADE,
                miro_board_id VARCHAR(100) NOT NULL,
                miro_board_url VARCHAR(500),
                miro_view_link VARCHAR(500),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                allow_student_edit BOOLEAN NOT NULL DEFAULT TRUE,
                board_name VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS ix_lessonwhiteboards_lesson_id ON "LessonWhiteboards"(lesson_id);
            CREATE INDEX IF NOT EXISTS ix_lessonwhiteboards_miro_board_id ON "LessonWhiteboards"(miro_board_id);
            """
        else:
            # SQLite
            sql = """
            CREATE TABLE IF NOT EXISTS LessonWhiteboards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL UNIQUE REFERENCES Lessons(lesson_id) ON DELETE CASCADE,
                miro_board_id VARCHAR(100) NOT NULL,
                miro_board_url VARCHAR(500),
                miro_view_link VARCHAR(500),
                is_active BOOLEAN NOT NULL DEFAULT 1,
                allow_student_edit BOOLEAN NOT NULL DEFAULT 1,
                board_name VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS ix_lessonwhiteboards_lesson_id ON LessonWhiteboards(lesson_id);
            CREATE INDEX IF NOT EXISTS ix_lessonwhiteboards_miro_board_id ON LessonWhiteboards(miro_board_id);
            """
        
        try:
            # Выполняем SQL
            for statement in sql.strip().split(';'):
                statement = statement.strip()
                if statement:
                    db.session.execute(text(statement))
            
            db.session.commit()
            print("[OK] Table LessonWhiteboards created successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Failed to create table: {e}")
            raise


if __name__ == '__main__':
    migrate()
