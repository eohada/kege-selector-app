"""
Функции для миграций базы данных
"""
import logging
from sqlalchemy import inspect, text
from app.models import db
from core.db_models import Tester, AuditLog

logger = logging.getLogger(__name__)

def ensure_schema_columns(app):
    """
    Обеспечивает наличие всех необходимых колонок в таблицах БД
    Выполняет миграции схемы при необходимости
    """
    try:
        with app.app_context():
            db.create_all()
            db.session.commit()

            inspector = inspect(db.engine)
            
            # Получаем реальное имя таблицы (может быть в нижнем регистре)
            table_names = inspector.get_table_names()
            lessons_table = 'Lessons' if 'Lessons' in table_names else ('lessons' if 'lessons' in table_names else None)
            students_table = 'Students' if 'Students' in table_names else ('students' if 'students' in table_names else None)
            lesson_tasks_table = 'LessonTasks' if 'LessonTasks' in table_names else ('lessontasks' if 'lessontasks' in table_names else None)
            
            if not lessons_table:
                logger.warning("Lessons table not found, skipping schema migration")
                return

            lesson_columns = {col['name'] for col in inspector.get_columns(lessons_table)}
            if 'homework_result_percent' not in lesson_columns:
                db.session.execute(text('ALTER TABLE Lessons ADD COLUMN homework_result_percent INTEGER'))
            if 'homework_result_notes' not in lesson_columns:
                db.session.execute(text('ALTER TABLE Lessons ADD COLUMN homework_result_notes TEXT'))

            if lesson_tasks_table:
                lesson_task_columns = {col['name'] for col in inspector.get_columns(lesson_tasks_table)}
                if 'assignment_type' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN assignment_type TEXT DEFAULT \'homework\''))
                if 'student_submission' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN student_submission TEXT'))
                if 'submission_correct' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN submission_correct INTEGER'))

            if students_table:
                student_columns = {col['name'] for col in inspector.get_columns(students_table)}
                if 'category' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN category TEXT'))
                if 'school_class' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN school_class INTEGER'))  # Добавляем колонку для хранения класса
                if 'goal_text' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN goal_text TEXT'))  # Храним текстовую формулировку цели
                if 'programming_language' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN programming_language VARCHAR(100)'))  # Храним выбранный язык программирования

                indexes = {idx['name'] for idx in inspector.get_indexes(students_table)}
                if 'idx_students_category' not in indexes:
                    db.session.execute(text(f'CREATE INDEX idx_students_category ON "{students_table}"(category)'))

            lesson_indexes = {idx['name'] for idx in inspector.get_indexes(lessons_table)}
            if 'idx_lessons_status' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_status ON "{lessons_table}"(status)'))
            if 'idx_lessons_lesson_date' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_lesson_date ON "{lessons_table}"(lesson_date)'))

            # Обновляем старые статусы ДЗ на новые значения, если таблица уже существовала
            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_done\' WHERE homework_status = \'completed\''))  # Старый completed -> assigned_done
            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_not_done\' WHERE homework_status IN (\'pending\', \'not_done\')'))  # pending/not_done -> assigned_not_done

            # Проверяем и создаем таблицу StudentTaskStatistics
            stats_table = 'StudentTaskStatistics' if 'StudentTaskStatistics' in table_names else ('studenttaskstatistics' if 'studenttaskstatistics' in table_names else None)
            if not stats_table:
                # Создаем таблицу для ручных изменений статистики
                db.session.execute(text("""
                    CREATE TABLE IF NOT EXISTS "StudentTaskStatistics" (
                        stat_id SERIAL PRIMARY KEY,
                        student_id INTEGER NOT NULL REFERENCES "Students"(student_id) ON DELETE CASCADE,
                        task_number INTEGER NOT NULL,
                        manual_correct INTEGER DEFAULT 0 NOT NULL,
                        manual_incorrect INTEGER DEFAULT 0 NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(student_id, task_number)
                    )
                """))
                db.session.execute(text("""
                    CREATE INDEX IF NOT EXISTS ix_student_task_statistics 
                    ON "StudentTaskStatistics"(student_id, task_number)
                """))
                logger.info("Created StudentTaskStatistics table")
            else:
                # Проверяем наличие всех колонок
                stats_columns = {col['name'] for col in inspector.get_columns(stats_table)}
                if 'manual_correct' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN manual_correct INTEGER DEFAULT 0 NOT NULL'))
                if 'manual_incorrect' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN manual_incorrect INTEGER DEFAULT 0 NOT NULL'))
                if 'created_at' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
                if 'updated_at' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))

            # Проверяем и обновляем AuditLog таблицу
            audit_log_table = 'AuditLog' if 'AuditLog' in table_names else ('auditlog' if 'auditlog' in table_names else None)
            if audit_log_table:
                audit_log_columns = {col['name'] for col in inspector.get_columns(audit_log_table)}
                # Изменяем session_id на TEXT если он VARCHAR(100)
                try:
                    pg_cursor = db.session.connection().connection.cursor()
                    pg_cursor.execute("""
                        SELECT data_type, character_maximum_length 
                        FROM information_schema.columns 
                        WHERE table_name = %s AND column_name = 'session_id'
                    """, (audit_log_table,))
                    col_info = pg_cursor.fetchone()
                    if col_info and col_info[0] == 'character varying' and col_info[1] == 100:
                        db.session.execute(text(f'ALTER TABLE "{audit_log_table}" ALTER COLUMN session_id TYPE TEXT'))
                        logger.info(f"Updated session_id column in {audit_log_table} to TEXT")
                except Exception as e:
                    logger.warning(f"Could not update session_id column: {e}")

            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)
        raise  # Пробрасываем ошибку дальше

