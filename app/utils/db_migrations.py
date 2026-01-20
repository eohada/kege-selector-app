"""
Функции для миграций базы данных
"""
import logging
import os
import json
from sqlalchemy import inspect, text
from app.models import db
from core.db_models import (
    Tester, AuditLog, RolePermission, User,
    UserNotification,
    LessonMessage,
    InviteLink,
    LessonTaskTeacherComment, TaskReview,
    Course, CourseModule,
    StudentLearningPlanItem,
    StudentDiagnosticCheckpoint,
    GradebookEntry,
    SchoolGroup,
    GroupStudent,
    LessonTaskAttempt,
    SubmissionAttempt,
    MaterialAsset, LessonMaterialLink, LessonRoomTemplate, RubricTemplate,
    RecurringLessonSlot,
    TariffPlan, TariffGroup, UserSubscription, UserConsent
)
from app.auth.permissions import DEFAULT_ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

def _backfill_lesson_materials_to_protected_urls(app, inspector, table_names, limit: int = 1000):
    """
    Best-effort backfill:
    - старые lesson.materials со ссылками вида /static/uploads/lessons/<lesson_id>/<file>
      переводим на /files/lessons/<lesson_id>/<stored_name>
    - делаем только если файл реально существует на диске
    """
    try:
        lessons_table = _resolve_table_name(table_names, 'Lessons')
        if not lessons_table:
            return
        cols = {c['name'] for c in inspector.get_columns(lessons_table)}
        if 'materials' not in cols:
            return

        from app.models import Lesson  # локальный импорт чтобы не ловить циклы

        # Быстрый отбор: только где materials не пустой
        q = Lesson.query.filter(Lesson.materials.isnot(None)).order_by(Lesson.lesson_id.desc()).limit(int(limit))
        lessons = q.all()
        if not lessons:
            return

        changed = 0
        for lesson in lessons:
            mats = lesson.materials or []
            if isinstance(mats, str):
                try:
                    mats = json.loads(mats) or []
                except Exception:
                    mats = []
            if not isinstance(mats, list) or not mats:
                continue

            updated_any = False
            new_mats = []
            for m in mats:
                if not isinstance(m, dict):
                    new_mats.append(m)
                    continue
                url = (m.get('url') or '').strip()
                if not url:
                    new_mats.append(m)
                    continue
                if '/files/lessons/' in url:
                    new_mats.append(m)
                    continue

                marker = '/static/uploads/lessons/'
                if marker in url:
                    stored_name = os.path.basename((url.split('?')[0] or '').strip())
                    if stored_name:
                        abs_path = os.path.join(app.root_path, 'static', 'uploads', 'lessons', str(lesson.lesson_id), stored_name)
                        if os.path.exists(abs_path):
                            m = dict(m)
                            m['url'] = f"/files/lessons/{lesson.lesson_id}/{stored_name}"
                            m['storage_path'] = f"static/uploads/lessons/{lesson.lesson_id}/{stored_name}"
                            updated_any = True
                new_mats.append(m)

            if updated_any:
                lesson.materials = new_mats
                try:
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(lesson, 'materials')
                except Exception:
                    pass
                changed += 1

        if changed:
            try:
                db.session.commit()
                logger.info(f"Backfilled protected lesson material URLs for {changed} lessons")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Could not commit lesson materials backfill: {e}")
    except Exception as e:
        logger.warning(f"Lesson materials backfill skipped due to error: {e}")

def _is_postgres(app):
    try:
        db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        return ('postgresql' in db_url) or ('postgres' in db_url)
    except Exception:
        return False

def _resolve_table_name(table_names, preferred):
    if preferred in table_names:
        return preferred
    lower = preferred.lower()
    if lower in table_names:
        return lower
    return None

def _fix_postgres_sequences(app, inspector):
    if not _is_postgres(app):
        return
    try:
        table_names = inspector.get_table_names()
        sequences_map = {
            'Students': 'student_id',
            'Lessons': 'lesson_id',
            'LessonTasks': 'lesson_task_id',
            'Tasks': 'task_id',
            'UsageHistory': 'usage_id',
            'SkippedTasks': 'skipped_id',
            'BlacklistTasks': 'blacklist_id',
            'AuditLog': 'id',
            'MaintenanceMode': 'id',
            'StudentTaskStatistics': 'stat_id',
            'TaskTemplate': 'template_id',
            'TemplateTask': 'id',
            'Users': 'id',
            'Topics': 'topic_id',
            'UserProfiles': 'profile_id',
            'FamilyTies': 'tie_id',
            'Enrollments': 'enrollment_id',
            'RolePermissions': 'id',
        }

        for preferred_table, pk_column in sequences_map.items():
            real_table = _resolve_table_name(table_names, preferred_table)
            if not real_table:
                continue
            try:
                cols = {col['name'] for col in inspector.get_columns(real_table)}
                if pk_column not in cols:
                    continue
                
                # Проверяем MAX ID
                try:
                    max_id_result = db.session.execute(text(f'SELECT MAX("{pk_column}") FROM "{real_table}"'))
                    max_id = max_id_result.scalar()
                    
                    if max_id and max_id > 0:
                        db.session.execute(
                            text(
                                f"SELECT setval("
                                f"pg_get_serial_sequence('\"{real_table}\"', '{pk_column}'), "
                                f":max_id, "
                                f"true"
                                f")"
                            ), {'max_id': max_id}
                        )
                        db.session.commit()
                except Exception as seq_err:
                    logger.warning(f"Error checking/fixing sequence for {real_table}: {seq_err}")
                    db.session.rollback()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Could not fix sequence for {real_table}.{pk_column}: {e}")
        logger.info("PostgreSQL sequences synchronization completed")
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Sequence synchronization skipped due to error: {e}")

def check_and_fix_rbac_schema(app):
    """
    Check and fix RBAC related schema issues.
    This function is designed to be safe to run on every request or startup.
    """
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            
            # 1. Ensure RolePermissions table exists
            role_perms_table = _resolve_table_name(table_names, 'RolePermissions')
            if not role_perms_table:
                logger.info("RolePermissions table missing. Creating...")
                RolePermission.__table__.create(db.engine)
                logger.info("RolePermissions table created.")
                
                # Fill defaults immediately
                count = 0
                for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                    for perm_name in perms:
                        rp = RolePermission(role=role, permission_name=perm_name, is_enabled=True)
                        db.session.add(rp)
                        count += 1
                db.session.commit()
                logger.info(f"Filled default permissions ({count} records)")
            else:
                # Таблица существует, проверяем, есть ли в ней права
                existing_count = RolePermission.query.count()
                if existing_count == 0:
                    logger.info("RolePermissions table exists but is empty. Initializing default permissions...")
                    try:
                        count = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
                                # Проверяем, что право существует в ALL_PERMISSIONS
                                from app.auth.permissions import ALL_PERMISSIONS
                                if perm_name not in ALL_PERMISSIONS:
                                    logger.warning(f"Permission '{perm_name}' not found in ALL_PERMISSIONS, skipping")
                                    continue
                                
                                # Проверяем, нет ли уже такой записи (на случай параллельных запросов)
                                exists = RolePermission.query.filter_by(
                                    role=role, 
                                    permission_name=perm_name
                                ).first()
                                if not exists:
                                    rp = RolePermission(role=role, permission_name=perm_name, is_enabled=True)
                                    db.session.add(rp)
                                    count += 1
                        
                        db.session.commit()
                        logger.info(f"Initialized {count} default permission records")
                    except Exception as init_error:
                        db.session.rollback()
                        logger.error(f"Error initializing default permissions: {init_error}", exc_info=True)
                else:
                    # Таблица не пустая: докидываем новые права так, чтобы RBAC был полностью консистентен:
                    # - для каждой роли из DEFAULT_ROLE_PERMISSIONS должны существовать записи по ВСЕМ permission'ам
                    # - если записи не было, ставим is_enabled как в DEFAULT_ROLE_PERMISSIONS
                    # Это убирает "скрытые дефолты" (fallback) и делает управление правами через админку/remote admin детерминированным.
                    try:
                        from app.auth.permissions import ALL_PERMISSIONS
                        all_perm_keys = list(ALL_PERMISSIONS.keys())
                        # Собираем существующие пары (role, permission_name) одним запросом
                        try:
                            existing_pairs = set(
                                (rp.role, rp.permission_name)
                                for rp in RolePermission.query.with_entities(RolePermission.role, RolePermission.permission_name).all()
                            )
                        except Exception:
                            existing_pairs = set()

                        added = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            defaults = set(perms or [])
                            for perm_name in all_perm_keys:
                                if (role, perm_name) in existing_pairs:
                                    continue
                                db.session.add(RolePermission(role=role, permission_name=perm_name, is_enabled=(perm_name in defaults)))
                                added += 1
                        if added:
                            db.session.commit()
                            logger.info(f"Backfilled {added} missing RolePermission records (full matrix)")
                    except Exception as backfill_err:
                        db.session.rollback()
                        logger.warning(f"Could not backfill RolePermissions: {backfill_err}")
            
            # 2. Ensure custom_permissions column in Users
            users_table = _resolve_table_name(table_names, 'Users')
            if users_table:
                cols = {col['name'] for col in inspector.get_columns(users_table)}
                if 'custom_permissions' not in cols:
                    logger.info("Adding custom_permissions column to Users...")
                    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                    if 'postgresql' in db_url or 'postgres' in db_url:
                        db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN custom_permissions JSON'))
                    else:
                        db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN custom_permissions JSON'))
                    db.session.commit()
                    logger.info("custom_permissions column added.")

    except Exception as e:
        logger.error(f"Error in check_and_fix_rbac_schema: {e}")
        db.session.rollback()

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

            # Run targeted RBAC fix
            check_and_fix_rbac_schema(app)

            inspector = inspect(db.engine)
            
            # Получаем реальное имя таблицы (может быть в нижнем регистре)
            table_names = inspector.get_table_names()
            if 'LessonTaskTeacherComments' not in table_names and 'lessontaskteachercomments' not in table_names:  # comment
                try:  # comment
                    LessonTaskTeacherComment.__table__.create(db.engine)  # comment
                    logger.info("LessonTaskTeacherComments table created")  # comment
                except Exception as e:  # comment
                    logger.warning(f"Could not create LessonTaskTeacherComments table: {e}")  # comment
                    db.session.rollback()  # comment

            # Фундамент: таблица ревью заданий банка (Formator)
            if 'TaskReviews' not in table_names and 'taskreviews' not in table_names:
                try:
                    TaskReview.__table__.create(db.engine)
                    logger.info("TaskReviews table created")
                except Exception as e:
                    logger.warning(f"Could not create TaskReviews table: {e}")
                    db.session.rollback()

            # Фундамент: курсы и модули (курс → модуль → урок)
            if 'Courses' not in table_names and 'courses' not in table_names:
                try:
                    Course.__table__.create(db.engine)
                    logger.info("Courses table created")
                except Exception as e:
                    logger.warning(f"Could not create Courses table: {e}")
                    db.session.rollback()

            if 'CourseModules' not in table_names and 'coursemodules' not in table_names:
                try:
                    CourseModule.__table__.create(db.engine)
                    logger.info("CourseModules table created")
                except Exception as e:
                    logger.warning(f"Could not create CourseModules table: {e}")
                    db.session.rollback()

            # Фундамент: учебная траектория (план) ученика
            if 'StudentLearningPlanItems' not in table_names and 'studentlearningplanitems' not in table_names:
                try:
                    StudentLearningPlanItem.__table__.create(db.engine)
                    logger.info("StudentLearningPlanItems table created")
                except Exception as e:
                    logger.warning(f"Could not create StudentLearningPlanItems table: {e}")
                    db.session.rollback()

            # Фундамент: диагностические контрольные точки
            if 'StudentDiagnosticCheckpoints' not in table_names and 'studentdiagnosticcheckpoints' not in table_names:
                try:
                    StudentDiagnosticCheckpoint.__table__.create(db.engine)
                    logger.info("StudentDiagnosticCheckpoints table created")
                except Exception as e:
                    logger.warning(f"Could not create StudentDiagnosticCheckpoints table: {e}")
                    db.session.rollback()

            # Фундамент: журнал оценок
            if 'GradebookEntries' not in table_names and 'gradebookentries' not in table_names:
                try:
                    GradebookEntry.__table__.create(db.engine)
                    logger.info("GradebookEntries table created")
                except Exception as e:
                    logger.warning(f"Could not create GradebookEntries table: {e}")
                    db.session.rollback()

            # Фундамент: попытки сдачи (пересдачи)
            if 'LessonTaskAttempts' not in table_names and 'lessontaskattempts' not in table_names:
                try:
                    LessonTaskAttempt.__table__.create(db.engine)
                    logger.info("LessonTaskAttempts table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonTaskAttempts table: {e}")
                    db.session.rollback()

            if 'SubmissionAttempts' not in table_names and 'submissionattempts' not in table_names:
                try:
                    SubmissionAttempt.__table__.create(db.engine)
                    logger.info("SubmissionAttempts table created")
                except Exception as e:
                    logger.warning(f"Could not create SubmissionAttempts table: {e}")
                    db.session.rollback()

            # Фундамент: группы/классы
            if 'SchoolGroups' not in table_names and 'schoolgroups' not in table_names:
                try:
                    SchoolGroup.__table__.create(db.engine)
                    logger.info("SchoolGroups table created")
                except Exception as e:
                    logger.warning(f"Could not create SchoolGroups table: {e}")
                    db.session.rollback()

            if 'GroupStudents' not in table_names and 'groupstudents' not in table_names:
                try:
                    GroupStudent.__table__.create(db.engine)
                    logger.info("GroupStudents table created")
                except Exception as e:
                    logger.warning(f"Could not create GroupStudents table: {e}")
                    db.session.rollback()

            # Фундамент: внутренние уведомления
            if 'UserNotifications' not in table_names and 'usernotifications' not in table_names:
                try:
                    UserNotification.__table__.create(db.engine)
                    logger.info("UserNotifications table created")
                except Exception as e:
                    logger.warning(f"Could not create UserNotifications table: {e}")
                    db.session.rollback()

            # Фундамент: диалоги по уроку
            if 'LessonMessages' not in table_names and 'lessonmessages' not in table_names:
                try:
                    LessonMessage.__table__.create(db.engine)
                    logger.info("LessonMessages table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonMessages table: {e}")
                    db.session.rollback()

            # Фундамент: приглашения (онбординг)
            if 'InviteLinks' not in table_names and 'invitelinks' not in table_names:
                try:
                    InviteLink.__table__.create(db.engine)
                    logger.info("InviteLinks table created")
                except Exception as e:
                    logger.warning(f"Could not create InviteLinks table: {e}")
                    db.session.rollback()

            # Фундамент: библиотека материалов и шаблоны комнат/уроков
            if 'MaterialAssets' not in table_names and 'materialassets' not in table_names:
                try:
                    MaterialAsset.__table__.create(db.engine)
                    logger.info("MaterialAssets table created")
                except Exception as e:
                    logger.warning(f"Could not create MaterialAssets table: {e}")
                    db.session.rollback()
            else:
                # добавляем storage_path, если таблица уже есть
                try:
                    assets_table = _resolve_table_name(table_names, 'MaterialAssets')
                    if assets_table:
                        cols = {c['name'] for c in inspector.get_columns(assets_table)}
                        if 'storage_path' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{assets_table}" ADD COLUMN storage_path TEXT'))
                                logger.info(f"Added storage_path to {assets_table}")
                            except Exception as e:
                                logger.warning(f"Could not add storage_path to {assets_table}: {e}")
                                db.session.rollback()
                except Exception:
                    pass

            if 'LessonMaterialLinks' not in table_names and 'lessonmateriallinks' not in table_names:
                try:
                    LessonMaterialLink.__table__.create(db.engine)
                    logger.info("LessonMaterialLinks table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonMaterialLinks table: {e}")
                    db.session.rollback()

            if 'LessonRoomTemplates' not in table_names and 'lessonroomtemplates' not in table_names:
                try:
                    LessonRoomTemplate.__table__.create(db.engine)
                    logger.info("LessonRoomTemplates table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonRoomTemplates table: {e}")
                    db.session.rollback()

            # Фундамент: автоплан расписания (RecurringLessonSlots)
            if 'RecurringLessonSlots' not in table_names and 'recurringlessonslots' not in table_names:
                try:
                    RecurringLessonSlot.__table__.create(db.engine)
                    logger.info("RecurringLessonSlots table created")
                except Exception as e:
                    logger.warning(f"Could not create RecurringLessonSlots table: {e}")
                    db.session.rollback()

            # Фундамент: биллинг/юридический слой
            if 'TariffGroups' not in table_names and 'tariffgroups' not in table_names:
                try:
                    TariffGroup.__table__.create(db.engine)
                    logger.info("TariffGroups table created")
                except Exception as e:
                    logger.warning(f"Could not create TariffGroups table: {e}")
                    db.session.rollback()

            if 'TariffPlans' not in table_names and 'tariffplans' not in table_names:
                try:
                    TariffPlan.__table__.create(db.engine)
                    logger.info("TariffPlans table created")
                except Exception as e:
                    logger.warning(f"Could not create TariffPlans table: {e}")
                    db.session.rollback()
            else:
                # добавляем колонки группировки/сортировки тарифов, если таблица уже есть
                try:
                    tp_table = _resolve_table_name(table_names, 'TariffPlans')
                    if tp_table:
                        cols = {c['name'] for c in inspector.get_columns(tp_table)}
                        if 'group_id' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN group_id INTEGER'))
                                logger.info(f"Added group_id to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add group_id to {tp_table}: {e}")
                                db.session.rollback()
                        if 'order_index' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN order_index INTEGER DEFAULT 0'))
                                logger.info(f"Added order_index to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add order_index to {tp_table}: {e}")
                                db.session.rollback()
                except Exception:
                    pass

            if 'UserSubscriptions' not in table_names and 'usersubscriptions' not in table_names:
                try:
                    UserSubscription.__table__.create(db.engine)
                    logger.info("UserSubscriptions table created")
                except Exception as e:
                    logger.warning(f"Could not create UserSubscriptions table: {e}")
                    db.session.rollback()

            if 'UserConsents' not in table_names and 'userconsents' not in table_names:
                try:
                    UserConsent.__table__.create(db.engine)
                    logger.info("UserConsents table created")
                except Exception as e:
                    logger.warning(f"Could not create UserConsents table: {e}")
                    db.session.rollback()
            lessons_table = 'Lessons' if 'Lessons' in table_names else ('lessons' if 'lessons' in table_names else None)
            students_table = 'Students' if 'Students' in table_names else ('students' if 'students' in table_names else None)
            lesson_tasks_table = 'LessonTasks' if 'LessonTasks' in table_names else ('lessontasks' if 'lessontasks' in table_names else None)
            
            if not lessons_table:
                logger.warning("Lessons table not found, skipping schema migration")
                return

            lesson_columns = {col['name'] for col in inspector.get_columns(lessons_table)}
            db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
            is_postgres = 'postgresql' in db_url or 'postgres' in db_url
            
            # Функция для безопасного добавления колонки
            def safe_add_column(col_name, col_type):
                if col_name not in lesson_columns:
                    try:
                        if is_postgres:
                            db.session.execute(text(f'ALTER TABLE "{lessons_table}" ADD COLUMN {col_name} {col_type}'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {lessons_table} ADD COLUMN {col_name} {col_type}'))
                        logger.info(f"Added column {col_name} to {lessons_table}")
                    except Exception as e:
                        logger.warning(f"Could not add column {col_name} to {lessons_table}: {e}")
                        db.session.rollback()
            
            safe_add_column('homework_result_percent', 'INTEGER')
            safe_add_column('homework_result_notes', 'TEXT')
            safe_add_column('review_summaries', 'JSON')
            
            # Новые поля для полноценного урока
            safe_add_column('content', 'TEXT')
            safe_add_column('content_blocks', 'JSON')
            safe_add_column('student_notes', 'TEXT')
            safe_add_column('materials', 'JSON')
            safe_add_column('course_module_id', 'INTEGER')

            # Backfill: старые материалы уроков -> защищенные ссылки
            _backfill_lesson_materials_to_protected_urls(app, inspector, table_names, limit=2000)

            if lesson_tasks_table:
                lesson_task_columns = {col['name'] for col in inspector.get_columns(lesson_tasks_table)}
                def safe_add_lesson_task_column(col_name, col_type):  # comment
                    if col_name in lesson_task_columns:  # comment
                        return  # comment
                    try:  # comment
                        if is_postgres:  # comment
                            db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN {col_name} {col_type}'))  # comment
                        else:  # comment
                            db.session.execute(text(f'ALTER TABLE {lesson_tasks_table} ADD COLUMN {col_name} {col_type}'))  # comment
                        logger.info(f"Added column {col_name} to {lesson_tasks_table}")  # comment
                    except Exception as e:  # comment
                        logger.warning(f"Could not add column {col_name} to {lesson_tasks_table}: {e}")  # comment
                        db.session.rollback()  # comment

                if 'assignment_type' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN assignment_type TEXT DEFAULT \'homework\''))
                if 'student_submission' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN student_submission TEXT'))
                if 'submission_correct' not in lesson_task_columns:
                    db.session.execute(text(f'ALTER TABLE "{lesson_tasks_table}" ADD COLUMN submission_correct INTEGER'))
                safe_add_lesson_task_column('status', 'TEXT DEFAULT \'pending\'')  # comment
                safe_add_lesson_task_column('submission_files', 'JSON')  # comment
                safe_add_lesson_task_column('teacher_comment', 'TEXT')  # comment
                try:  # comment
                    # Убираем устаревший статус in_progress, если он где-то появился
                    if is_postgres:  # comment
                        db.session.execute(text(f'UPDATE "{lesson_tasks_table}" SET status = \'pending\' WHERE status = \'in_progress\''))  # comment
                    else:  # comment
                        db.session.execute(text(f"UPDATE {lesson_tasks_table} SET status = 'pending' WHERE status = 'in_progress'"))  # comment
                except Exception as e:  # comment
                    logger.warning(f"Could not normalize LessonTasks.status values: {e}")  # comment
                    db.session.rollback()  # comment

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
            try:
                db.session.commit()
                logger.info("Database migrations committed successfully")
            except Exception as commit_error:
                db.session.rollback()
                logger.error(f"Error committing migrations: {commit_error}", exc_info=True)
            
            # ========================================================================
            # МИГРАЦИИ ДЛЯ НОВОЙ СИСТЕМЫ АВТОРИЗАЦИИ (RBAC) - ОСТАЛЬНЫЕ ТАБЛИЦЫ
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

                # schedule_ics_token для приватного экспорта календаря
                if 'schedule_ics_token' not in users_columns:
                    try:
                        if _is_postgres(app):
                            db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN schedule_ics_token VARCHAR(120)'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN schedule_ics_token VARCHAR(120)'))
                        logger.info("Added schedule_ics_token column to Users table")
                    except Exception as e:
                        logger.warning(f"Could not add schedule_ics_token to Users: {e}")
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
            
            # 5. Создаем таблицы системы заданий (Assignments, AssignmentTasks, Submissions, Answers)
            assignments_table = _resolve_table_name(table_names, 'Assignments')
            if not assignments_table:
                try:
                    db.create_all()  # Создаст все таблицы системы заданий если их нет
                    logger.info("Created Assignments system tables (Assignments, AssignmentTasks, Submissions, Answers)")
                except Exception as e:
                    logger.warning(f"Could not create Assignments system tables: {e}")

            # 5.1 Создаем таблицу RubricTemplates (если её нет)
            rubric_templates_table = _resolve_table_name(table_names, 'RubricTemplates')
            if not rubric_templates_table:
                try:
                    db.create_all()
                    logger.info("Created RubricTemplates table")
                except Exception as e:
                    logger.warning(f"Could not create RubricTemplates table: {e}")

            # 5.2 Добавляем недостающие колонки для Rubrics в Assignments/Submissions
            try:
                assignments_table = _resolve_table_name(table_names, 'Assignments')
                submissions_table = _resolve_table_name(table_names, 'Submissions')
                if assignments_table:
                    cols = {c['name'] for c in inspector.get_columns(assignments_table)}
                    if 'rubric_template_id' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN rubric_template_id INTEGER'))
                            logger.info(f"Added rubric_template_id to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add rubric_template_id to {assignments_table}: {e}")
                            db.session.rollback()
                if submissions_table:
                    cols = {c['name'] for c in inspector.get_columns(submissions_table)}
                    if 'rubric_template_id' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN rubric_template_id INTEGER'))
                            logger.info(f"Added rubric_template_id to {submissions_table}")
                        except Exception as e:
                            logger.warning(f"Could not add rubric_template_id to {submissions_table}: {e}")
                            db.session.rollback()
                    if 'rubric_scores' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN rubric_scores JSON'))
                            logger.info(f"Added rubric_scores to {submissions_table}")
                        except Exception as e:
                            # sqlite может не поддержать JSON тип — пробуем TEXT
                            try:
                                db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN rubric_scores TEXT'))
                                logger.info(f"Added rubric_scores (TEXT) to {submissions_table}")
                            except Exception as e2:
                                logger.warning(f"Could not add rubric_scores to {submissions_table}: {e} / {e2}")
                                db.session.rollback()
            except Exception as e:
                logger.warning(f"Could not ensure rubric columns: {e}")
            
            # 6. Создаем таблицу комментариев к заданиям (SubmissionComments)
            comments_table = _resolve_table_name(table_names, 'SubmissionComments')
            if not comments_table:
                try:
                    db.create_all() # Создаст таблицу SubmissionComments если её нет
                    logger.info("Created SubmissionComments table")
                except Exception as e:
                    logger.warning(f"Could not create SubmissionComments table: {e}")
            
            # Коммитим миграции RBAC и Assignments
            try:
                db.session.commit()
                logger.info("RBAC and Assignments migrations committed successfully")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Error committing RBAC/Assignments migrations: {e}")
            
            # Исправляем sequences ПОСЛЕ коммита миграций
            # Это не критично, если не получится - просто будет warning
            _fix_postgres_sequences(app, inspector)  # После миграций синхронизируем sequences (чинит 500 duplicate key на SERIAL)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)
        # НЕ пробрасываем ошибку дальше, чтобы не блокировать запуск приложения
