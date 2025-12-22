"""
Функции для миграций базы данных
"""
import logging
from sqlalchemy import inspect, text
from app.models import db
from core.db_models import Tester, AuditLog

logger = logging.getLogger(__name__)

def _is_postgres(app):  # Проверяем, что подключена PostgreSQL (в ней есть sequences/serial)
    try:  # Пытаемся безопасно прочитать строку подключения
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')  # Берём URI из конфига Flask
        return ('postgresql' in db_url) or ('postgres' in db_url)  # True, если похоже на Postgres
    except Exception:  # На всякий случай не ломаем миграции
        return False  # Если не удалось определить — считаем, что не Postgres

def _resolve_table_name(table_names, preferred):  # Находим реальное имя таблицы (учитываем возможный lower-case)
    if preferred in table_names:  # Если таблица есть в точном регистре
        return preferred  # Возвращаем её как есть
    lower = preferred.lower()  # Готовим lower-case вариант имени
    if lower in table_names:  # Если таблица есть в нижнем регистре
        return lower  # Возвращаем lower-case имя
    return None  # Таблица не найдена

def _fix_postgres_sequences(app, inspector):  # Выравниваем sequences, чтобы nextval() не выдавал занятые PK после импорта
    if not _is_postgres(app):  # Если это не Postgres — выходим (SQLite не нуждается)
        return  # Ничего не делаем
    try:  # Защищаемся от падений при попытке setval
        table_names = inspector.get_table_names()  # Список таблиц в БД
        sequences_map = {  # Таблица -> pk-колонка (как в scripts/fix_sequences.py)
            'Students': 'student_id',  # PK учеников
            'Lessons': 'lesson_id',  # PK уроков
            'LessonTasks': 'lesson_task_id',  # PK связки урок-задание
            'Tasks': 'task_id',  # PK задач (важно для ручного создания)
            'UsageHistory': 'usage_id',  # PK истории принятия
            'SkippedTasks': 'skipped_id',  # PK пропусков
            'BlacklistTasks': 'blacklist_id',  # PK черного списка
            'Testers': 'tester_id',  # PK тестировщиков
            'AuditLog': 'id',  # PK логов
            'MaintenanceMode': 'id',  # PK режима техработ
            'StudentTaskStatistics': 'stat_id',  # PK ручной статистики
            'TaskTemplate': 'template_id',  # PK шаблонов
            'TemplateTask': 'id',  # PK связки шаблон-задание (если есть)
            'Users': 'id',  # PK пользователей
        }  # Конец mapping

        for preferred_table, pk_column in sequences_map.items():  # Проходим по всем таблицам, где есть SERIAL/IDENTITY
            real_table = _resolve_table_name(table_names, preferred_table)  # Определяем реальное имя таблицы
            if not real_table:  # Если таблицы нет — пропускаем
                continue  # Переходим к следующей
            try:  # Пытаемся починить sequence для конкретной таблицы
                cols = {col['name'] for col in inspector.get_columns(real_table)}  # Список колонок таблицы
                if pk_column not in cols:  # Если PK колонки нет — пропускаем
                    continue  # Переходим к следующей
                # Важно: используем pg_get_serial_sequence, чтобы не гадать имя sequence
                db.session.execute(  # Выполняем SQL-команду setval
                    text(  # Оборачиваем в text()
                        f"SELECT setval("  # Начинаем setval
                        f"pg_get_serial_sequence('\"{real_table}\"', '{pk_column}'), "  # Получаем имя sequence по таблице+PK
                        f"COALESCE((SELECT MAX(\"{pk_column}\") FROM \"{real_table}\"), 0), "  # Берём текущий max(pk)
                        f"true"  # is_called=true => следующий nextval будет max+1
                        f")"  # Закрываем setval
                    )  # Конец SQL
                )  # Конец execute
            except Exception as e:  # Если не удалось (например, таблица без sequence)
                logger.warning(f"Could not fix sequence for {real_table}.{pk_column}: {e}")  # Логируем и продолжаем
        try:  # Коммитим изменения setval одной транзакцией
            db.session.commit()  # Фиксируем обновления sequences
            logger.info("PostgreSQL sequences synchronized successfully")  # Пишем в лог об успехе
        except Exception as e:  # Если коммит не прошёл
            db.session.rollback()  # Откатываем
            logger.warning(f"Could not commit sequence synchronization: {e}")  # Логируем проблему
    except Exception as e:  # Если общий процесс упал
        db.session.rollback()  # Откатываем на всякий случай
        logger.warning(f"Sequence synchronization skipped due to error: {e}")  # Не блокируем запуск приложения

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
            
            # Проверяем и создаем таблицу MaintenanceMode
            maintenance_table = 'MaintenanceMode' if 'MaintenanceMode' in table_names else ('maintenancemode' if 'maintenancemode' in table_names else None)
            if not maintenance_table:
                # Создаем таблицу для управления режимом тех работ
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
                    # PostgreSQL синтаксис
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS "MaintenanceMode" (
                            id SERIAL PRIMARY KEY,
                            is_enabled BOOLEAN DEFAULT FALSE NOT NULL,
                            message TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_by INTEGER REFERENCES "Users"(id)
                        )
                    """))
                else:
                    # SQLite синтаксис
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS MaintenanceMode (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            is_enabled INTEGER DEFAULT 0 NOT NULL,
                            message TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_by INTEGER REFERENCES Users(id)
                        )
                    """))
                logger.info("Created MaintenanceMode table")
                if 'created_at' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
                if 'updated_at' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))

            # Проверяем и обновляем AuditLog таблицу
            audit_log_table = 'AuditLog' if 'AuditLog' in table_names else ('auditlog' if 'auditlog' in table_names else None)
            if audit_log_table:
                audit_log_columns = {col['name'] for col in inspector.get_columns(audit_log_table)}
                
                # Добавляем колонку user_id если её нет
                if 'user_id' not in audit_log_columns:
                    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                    if 'postgresql' in db_url or 'postgres' in db_url:
                        # PostgreSQL синтаксис
                        try:
                            db.session.execute(text("""
                                ALTER TABLE "AuditLog" 
                                ADD COLUMN user_id INTEGER 
                                REFERENCES "Users"(id) 
                                ON DELETE SET NULL
                            """))
                            # Создаем индекс для user_id
                            db.session.execute(text("""
                                CREATE INDEX IF NOT EXISTS idx_audit_user_id 
                                ON "AuditLog"(user_id)
                            """))
                            logger.info(f"Added user_id column to {audit_log_table}")
                        except Exception as e:
                            logger.warning(f"Could not add user_id column: {e}")
                    else:
                        # SQLite синтаксис
                        try:
                            db.session.execute(text("""
                                ALTER TABLE AuditLog 
                                ADD COLUMN user_id INTEGER 
                                REFERENCES Users(id)
                            """))
                            logger.info(f"Added user_id column to {audit_log_table}")
                        except Exception as e:
                            logger.warning(f"Could not add user_id column: {e}")
                
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

            # Проверяем и обновляем таблицу Reminders
            reminders_table = 'Reminders' if 'Reminders' in table_names else ('reminders' if 'reminders' in table_names else None)
            if reminders_table:
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
                    # Для PostgreSQL проверяем через information_schema
                    try:
                        result = db.session.execute(text("""
                            SELECT is_nullable 
                            FROM information_schema.columns 
                            WHERE table_name = :table_name AND column_name = 'reminder_time'
                        """), {'table_name': reminders_table})
                        row = result.fetchone()
                        if row and row[0] == 'NO':
                            # Колонка NOT NULL, делаем её nullable
                            db.session.execute(text(f'ALTER TABLE "{reminders_table}" ALTER COLUMN reminder_time DROP NOT NULL'))
                            logger.info(f"Made reminder_time nullable in {reminders_table}")
                    except Exception as e:
                        logger.warning(f"Could not check/update reminder_time nullable: {e}")
                else:
                    # SQLite не поддерживает ALTER COLUMN, но это не критично
                    logger.warning("SQLite does not support ALTER COLUMN, reminder_time will remain NOT NULL")
            
            _fix_postgres_sequences(app, inspector)  # После миграций синхронизируем sequences (чинит 500 duplicate key на SERIAL)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)
        raise  # Пробрасываем ошибку дальше

