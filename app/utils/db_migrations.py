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
            # 'Testers': 'tester_id',  # PK тестировщиков - ПРОПУСКАЕМ, т.к. может быть text тип
            'AuditLog': 'id',  # PK логов
            'MaintenanceMode': 'id',  # PK режима техработ
            'StudentTaskStatistics': 'stat_id',  # PK ручной статистики
            'TaskTemplate': 'template_id',  # PK шаблонов
            'TemplateTask': 'id',  # PK связки шаблон-задание (если есть)
            'Users': 'id',  # PK пользователей
            'Topics': 'topic_id',  # PK тем/навыков
            'UserProfiles': 'profile_id',  # PK профилей пользователей
            'FamilyTies': 'tie_id',  # PK семейных связей
            'Enrollments': 'enrollment_id',  # PK учебных контрактов
        }  # Конец mapping

        # Исправляем sequences в отдельных транзакциях, чтобы ошибка одной не влияла на другие
        for preferred_table, pk_column in sequences_map.items():  # Проходим по всем таблицам, где есть SERIAL/IDENTITY
            real_table = _resolve_table_name(table_names, preferred_table)  # Определяем реальное имя таблицы
            if not real_table:  # Если таблицы нет — пропускаем
                continue  # Переходим к следующей
            try:  # Пытаемся починить sequence для конкретной таблицы
                cols = {col['name'] for col in inspector.get_columns(real_table)}  # Список колонок таблицы
                if pk_column not in cols:  # Если PK колонки нет — пропускаем
                    continue  # Переходим к следующей
                # Важно: используем pg_get_serial_sequence, чтобы не гадать имя sequence
                # Каждая попытка в отдельной транзакции
                db.session.execute(  # Выполняем SQL-команду setval
                    text(  # Оборачиваем в text()
                        f"SELECT setval("  # Начинаем setval
                        f"pg_get_serial_sequence('\"{real_table}\"', '{pk_column}'), "  # Получаем имя sequence по таблице+PK
                        f"COALESCE((SELECT MAX(\"{pk_column}\") FROM \"{real_table}\"), 0), "  # Берём текущий max(pk)
                        f"true"  # is_called=true => следующий nextval будет max+1
                        f")"  # Закрываем setval
                    )  # Конец SQL
                )  # Конец execute
                db.session.commit()  # Коммитим каждую sequence отдельно
            except Exception as e:  # Если не удалось (например, таблица без sequence или неправильный тип)
                db.session.rollback()  # Откатываем только эту попытку
                logger.warning(f"Could not fix sequence for {real_table}.{pk_column}: {e}")  # Логируем и продолжаем
        logger.info("PostgreSQL sequences synchronization completed")  # Пишем в лог об успехе
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
            # Создаем таблицы, если их нет
            db.create_all()
            try:
                db.session.commit()
            except Exception as e:
                logger.warning(f"Error committing db.create_all(): {e}")
                db.session.rollback()

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
            
            # Проверяем и создаем таблицу Topics (темы/навыки)
            topics_table = 'Topics' if 'Topics' in table_names else ('topics' if 'topics' in table_names else None)
            if not topics_table:
                if _is_postgres(app):
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS "Topics" (
                            topic_id SERIAL PRIMARY KEY,
                            name VARCHAR(100) NOT NULL UNIQUE,
                            description TEXT,
                            subject_id INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_topics_name ON "Topics"(name)
                    """))
                else:
                    # SQLite синтаксис
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS Topics (
                            topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name VARCHAR(100) NOT NULL UNIQUE,
                            description TEXT,
                            subject_id INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_topics_name ON Topics(name)
                    """))
                logger.info("Created Topics table")
            
            # Проверяем и создаем связующую таблицу task_topics
            task_topics_table = 'task_topics' if 'task_topics' in table_names else ('TaskTopics' if 'TaskTopics' in table_names else None)
            if not task_topics_table:
                if _is_postgres(app):
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS task_topics (
                            task_id INTEGER NOT NULL REFERENCES "Tasks"(task_id) ON DELETE CASCADE,
                            topic_id INTEGER NOT NULL REFERENCES "Topics"(topic_id) ON DELETE CASCADE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (task_id, topic_id)
                        )
                    """))
                else:
                    # SQLite синтаксис
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS task_topics (
                            task_id INTEGER NOT NULL REFERENCES Tasks(task_id) ON DELETE CASCADE,
                            topic_id INTEGER NOT NULL REFERENCES Topics(topic_id) ON DELETE CASCADE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (task_id, topic_id)
                        )
                    """))
                logger.info("Created task_topics table")
            
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
            
            # Проверяем и обновляем таблицу Users
            users_table = _resolve_table_name(table_names, 'Users')
            if users_table:
                try:
                    users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                    
                    # Поля профиля - добавляем только если их нет, с обработкой ошибок
                    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                    is_postgres = 'postgresql' in db_url or 'postgres' in db_url
                    
                    if 'avatar_url' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN avatar_url VARCHAR(500)'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN avatar_url VARCHAR(500)'))
                            logger.info(f"Added column avatar_url to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add avatar_url column (may already exist): {e}")
                    
                    if 'about_me' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN about_me TEXT'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN about_me TEXT'))
                            logger.info(f"Added column about_me to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add about_me column (may already exist): {e}")
                    
                    if 'custom_status' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN custom_status VARCHAR(100)'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN custom_status VARCHAR(100)'))
                            logger.info(f"Added column custom_status to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add custom_status column (may already exist): {e}")
                    
                    if 'telegram_link' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN telegram_link VARCHAR(200)'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN telegram_link VARCHAR(200)'))
                            logger.info(f"Added column telegram_link to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add telegram_link column (may already exist): {e}")
                    
                    if 'github_link' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN github_link VARCHAR(200)'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN github_link VARCHAR(200)'))
                            logger.info(f"Added column github_link to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add github_link column (may already exist): {e}")
                except Exception as e:
                    logger.warning(f"Error checking/updating Users table columns: {e}")
                    # Не пробрасываем ошибку дальше, чтобы не блокировать запуск приложения

            # КРИТИЧЕСКИ ВАЖНО: коммитим миграции ДО исправления sequences
            # Иначе ошибки в sequences могут откатить все миграции
            try:
                db.session.commit()
                logger.info("Database migrations committed successfully")
                
                # Проверяем, что миграции действительно применились
                # Перечитываем колонки Users после коммита
                if users_table:
                    try:
                        users_columns_after = {col['name'] for col in inspector.get_columns(users_table)}
                        missing_columns = []
                        for col_name in ['avatar_url', 'about_me', 'custom_status', 'telegram_link', 'github_link']:
                            if col_name not in users_columns_after:
                                missing_columns.append(col_name)
                        if missing_columns:
                            logger.warning(f"After commit, these columns are still missing from Users: {missing_columns}")
                        else:
                            logger.info("All User profile columns verified after commit")
                    except Exception as verify_error:
                        logger.warning(f"Could not verify migrations: {verify_error}")
            except Exception as commit_error:
                db.session.rollback()
                logger.error(f"Error committing migrations: {commit_error}", exc_info=True)
                # Не пробрасываем ошибку дальше, но логируем как ошибку
            
            # ========================================================================
            # МИГРАЦИИ ДЛЯ НОВОЙ СИСТЕМЫ АВТОРИЗАЦИИ (RBAC)
            # ========================================================================
            
            # 1. Добавляем email в Users (если его нет)
            if users_table:
                users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                if 'email' not in users_columns:
                    try:
                        db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN email VARCHAR(200)'))
                        logger.info("Added email column to Users table")
                    except Exception as e:
                        logger.warning(f"Could not add email to Users: {e}")
                        db.session.rollback()
            
            # 2. Создаем таблицу UserProfiles (если её нет)
            profiles_table = _resolve_table_name(table_names, 'UserProfiles')
            if not profiles_table:
                try:
                    db.create_all()  # Создаст таблицу UserProfiles если её нет
                    logger.info("Created UserProfiles table")
                except Exception as e:
                    logger.warning(f"Could not create UserProfiles table: {e}")
            
            # 3. Создаем таблицу FamilyTies (если её нет)
            family_ties_table = _resolve_table_name(table_names, 'FamilyTies')
            if not family_ties_table:
                try:
                    db.create_all()  # Создаст таблицу FamilyTies если её нет
                    logger.info("Created FamilyTies table")
                except Exception as e:
                    logger.warning(f"Could not create FamilyTies table: {e}")
            
            # 4. Создаем таблицу Enrollments (если её нет)
            enrollments_table = _resolve_table_name(table_names, 'Enrollments')
            if not enrollments_table:
                try:
                    db.create_all()  # Создаст таблицу Enrollments если её нет
                    logger.info("Created Enrollments table")
                except Exception as e:
                    logger.warning(f"Could not create Enrollments table: {e}")
            
            # 5. Создаем таблицу RolePermissions (если её нет) и заполняем дефолты
            role_perms_table = _resolve_table_name(table_names, 'RolePermissions')
            if not role_perms_table:
                try:
                    # Импортируем модель ДО создания таблиц, чтобы SQLAlchemy знала о ней
                    from app.models import RolePermission
                    from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS
                    
                    db.create_all()  # Создаст таблицу RolePermissions
                    logger.info("Created RolePermissions table")
                    
                    # Заполняем дефолтные права
                    count = 0
                    for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                        for perm_name in perms:
                            rp = RolePermission(role=role, permission_name=perm_name, is_enabled=True)
                            db.session.add(rp)
                            count += 1
                    
                    db.session.commit()
                    logger.info(f"Filled default permissions ({count} records)")
                except Exception as e:
                    logger.warning(f"Could not create/fill RolePermissions table: {e}")
                    db.session.rollback()

            # 6. Добавляем custom_permissions в Users (если его нет)
            if users_table:
                users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                if 'custom_permissions' not in users_columns:
                    try:
                        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                        if 'postgresql' in db_url or 'postgres' in db_url:
                            db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN custom_permissions JSON'))
                        else:
                            # SQLite
                            db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN custom_permissions JSON'))
                        
                        db.session.commit()
                        logger.info("Added custom_permissions column to Users table")
                    except Exception as e:
                        logger.warning(f"Could not add custom_permissions to Users: {e}")
                        db.session.rollback()

            # Коммитим миграции RBAC
            try:
                db.session.commit()
                logger.info("RBAC migrations committed successfully")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Error committing RBAC migrations: {e}")
            
            # Исправляем sequences ПОСЛЕ коммита миграций
            # Это не критично, если не получится - просто будет warning
            _fix_postgres_sequences(app, inspector)  # После миграций синхронизируем sequences (чинит 500 duplicate key на SERIAL)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)
        # НЕ пробрасываем ошибку дальше, чтобы не блокировать запуск приложения
        # Миграции могут быть применены вручную позже

