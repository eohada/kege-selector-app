"""
Функции для миграций базы данных
"""
import logging
import os
import json
from sqlalchemy import inspect, text
from app.models import db
from core.db_models import (
    Tester, AuditLog, RolePermission, User, UserRole,
    UserNotification,
    LessonMessage,
    LessonWhiteboard,
    InviteLink,
    LessonTaskTeacherComment, TaskReview, TaskSolution,
    LearningTrajectory, TrajectoryModule,
    Course as ExamCourse, CourseTaskTemplate,
    StudentCourseEnrollment, GradingScale,
    StudentLearningPlanItem,
    StudentDiagnosticCheckpoint,
    GradebookEntry,
    SchoolGroup,
    GroupStudent,
    LessonTaskAttempt,
    SubmissionAttempt,
    MaterialAsset, LessonMaterialLink, LessonRoomTemplate, RubricTemplate,
    RecurringLessonSlot,
    TariffPlan, TariffGroup, UserSubscription, TrainerSession, TrainerLlmLog, UserConsent,
    Subject, KnowledgeNode, UserMastery, AnalyticsEvent,
    ReferralCode, ReferralUsage,
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
            'TrainerSessions': 'session_id',
            'TrainerLlmLogs': 'log_id',
            'ReferralCodes': 'id',
            'ReferralUsage': 'id',
        }

        for preferred_table, pk_column in sequences_map.items():
            real_table = _resolve_table_name(table_names, preferred_table)
            if not real_table:
                continue
            try:
                cols = {col['name'] for col in inspector.get_columns(real_table)}
                if pk_column not in cols:
                    continue
                
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
            
            role_perms_table = _resolve_table_name(table_names, 'RolePermissions')
            if not role_perms_table:
                logger.info("RolePermissions table missing. Creating...")
                RolePermission.__table__.create(db.engine)
                logger.info("RolePermissions table created.")
                
                count = 0
                for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                    for perm_name in perms:
                        rp = RolePermission(role=role, permission_name=perm_name, is_enabled=True)
                        db.session.add(rp)
                        count += 1
                db.session.commit()
                logger.info(f"Filled default permissions ({count} records)")
            else:
                existing_count = RolePermission.query.count()
                if existing_count == 0:
                    logger.info("RolePermissions table exists but is empty. Initializing default permissions...")
                    try:
                        count = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
                                from app.auth.permissions import ALL_PERMISSIONS
                                if perm_name not in ALL_PERMISSIONS:
                                    logger.warning(f"Permission '{perm_name}' not found in ALL_PERMISSIONS, skipping")
                                    continue
                                
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
                    try:
                        from app.auth.permissions import ALL_PERMISSIONS
                        all_perm_keys = list(ALL_PERMISSIONS.keys())
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
            db.create_all()
            try:
                db.session.commit()
            except Exception as e:
                logger.warning(f"Error committing db.create_all(): {e}")
                db.session.rollback()

            check_and_fix_rbac_schema(app)

            inspector = inspect(db.engine)
            
            table_names = inspector.get_table_names()
            if 'LessonTaskTeacherComments' not in table_names and 'lessontaskteachercomments' not in table_names:  # comment
                try:  # comment
                    LessonTaskTeacherComment.__table__.create(db.engine)  # comment
                    logger.info("LessonTaskTeacherComments table created")  # comment
                except Exception as e:  # comment
                    logger.warning(f"Could not create LessonTaskTeacherComments table: {e}")  # comment
                    db.session.rollback()  # comment

            if 'TaskReviews' not in table_names and 'taskreviews' not in table_names:
                try:
                    TaskReview.__table__.create(db.engine)
                    logger.info("TaskReviews table created")
                except Exception as e:
                    logger.warning(f"Could not create TaskReviews table: {e}")
                    db.session.rollback()

            if 'TaskSolutions' not in table_names and 'tasksolutions' not in table_names:
                try:
                    TaskSolution.__table__.create(db.engine)
                    logger.info("TaskSolutions table created")
                except Exception as e:
                    logger.warning(f"Could not create TaskSolutions table: {e}")
                    db.session.rollback()
            else:
                ts_table = _resolve_table_name(table_names, 'TaskSolutions')
                if ts_table:
                    ts_cols = {c['name'] for c in inspector.get_columns(ts_table)}
                    if 'needs_manual_review' not in ts_cols:
                        try:
                            is_pg = _is_postgres(app)
                            add_sql = 'ALTER TABLE "TaskSolutions" ADD COLUMN needs_manual_review BOOLEAN DEFAULT FALSE NOT NULL' if is_pg else 'ALTER TABLE TaskSolutions ADD COLUMN needs_manual_review INTEGER DEFAULT 0 NOT NULL'
                            db.session.execute(text(add_sql))
                            db.session.commit()
                            logger.info("TaskSolutions.needs_manual_review column added")
                        except Exception as e:
                            logger.warning(f"Could not add needs_manual_review to TaskSolutions: {e}")
                            db.session.rollback()

            if 'Courses' not in table_names and 'courses' not in table_names:
                try:
                    LearningTrajectory.__table__.create(db.engine)
                    logger.info("Courses (LearningTrajectory) table created")
                except Exception as e:
                    logger.warning(f"Could not create Courses table: {e}")
                    db.session.rollback()

            if 'CourseModules' not in table_names and 'coursemodules' not in table_names:
                try:
                    TrajectoryModule.__table__.create(db.engine)
                    logger.info("CourseModules (TrajectoryModule) table created")
                except Exception as e:
                    logger.warning(f"Could not create CourseModules table: {e}")
                    db.session.rollback()

            if 'StudentLearningPlanItems' not in table_names and 'studentlearningplanitems' not in table_names:
                try:
                    StudentLearningPlanItem.__table__.create(db.engine)
                    logger.info("StudentLearningPlanItems table created")
                except Exception as e:
                    logger.warning(f"Could not create StudentLearningPlanItems table: {e}")
                    db.session.rollback()

            if 'StudentDiagnosticCheckpoints' not in table_names and 'studentdiagnosticcheckpoints' not in table_names:
                try:
                    StudentDiagnosticCheckpoint.__table__.create(db.engine)
                    logger.info("StudentDiagnosticCheckpoints table created")
                except Exception as e:
                    logger.warning(f"Could not create StudentDiagnosticCheckpoints table: {e}")
                    db.session.rollback()

            if 'GradebookEntries' not in table_names and 'gradebookentries' not in table_names:
                try:
                    GradebookEntry.__table__.create(db.engine)
                    logger.info("GradebookEntries table created")
                except Exception as e:
                    logger.warning(f"Could not create GradebookEntries table: {e}")
                    db.session.rollback()

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

            if 'UserNotifications' not in table_names and 'usernotifications' not in table_names:
                try:
                    UserNotification.__table__.create(db.engine)
                    logger.info("UserNotifications table created")
                except Exception as e:
                    logger.warning(f"Could not create UserNotifications table: {e}")
                    db.session.rollback()
            else:
                try:
                    un_table = _resolve_table_name(table_names, 'UserNotifications')
                    if un_table:
                        cols = {c['name'] for c in inspector.get_columns(un_table)}
                        if 'telegram_sent' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{un_table}" ADD COLUMN telegram_sent BOOLEAN DEFAULT FALSE'))
                                logger.info(f"Added telegram_sent to {un_table}")
                            except Exception as e:
                                logger.warning(f"Could not add telegram_sent to {un_table}: {e}")
                                db.session.rollback()
                except Exception:
                    pass

            if 'LessonMessages' not in table_names and 'lessonmessages' not in table_names:
                try:
                    LessonMessage.__table__.create(db.engine)
                    logger.info("LessonMessages table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonMessages table: {e}")
                    db.session.rollback()

            if 'LessonWhiteboards' not in table_names and 'lessonwhiteboards' not in table_names:
                try:
                    LessonWhiteboard.__table__.create(db.engine)
                    logger.info("LessonWhiteboards table created")
                except Exception as e:
                    logger.warning(f"Could not create LessonWhiteboards table: {e}")
                    db.session.rollback()

            if 'MiroUserTokens' not in table_names and 'mirousertokens' not in table_names:
                try:
                    from app.models import MiroUserToken
                    MiroUserToken.__table__.create(db.engine)
                    logger.info("MiroUserTokens table created")
                except Exception as e:
                    logger.warning(f"Could not create MiroUserTokens table: {e}")
                    db.session.rollback()

            if 'ReferralCodes' not in table_names and 'referralcodes' not in table_names:
                try:
                    ReferralCode.__table__.create(db.engine)
                    logger.info("ReferralCodes table created")
                except Exception as e:
                    logger.warning(f"Could not create ReferralCodes table: {e}")
                    db.session.rollback()

            if 'ReferralUsage' not in table_names and 'referralusage' not in table_names:
                try:
                    ReferralUsage.__table__.create(db.engine)
                    logger.info("ReferralUsage table created")
                except Exception as e:
                    logger.warning(f"Could not create ReferralUsage table: {e}")
                    db.session.rollback()

            if 'InviteLinks' not in table_names and 'invitelinks' not in table_names:
                try:
                    InviteLink.__table__.create(db.engine)
                    logger.info("InviteLinks table created")
                except Exception as e:
                    logger.warning(f"Could not create InviteLinks table: {e}")
                    db.session.rollback()

            if 'MaterialAssets' not in table_names and 'materialassets' not in table_names:
                try:
                    MaterialAsset.__table__.create(db.engine)
                    logger.info("MaterialAssets table created")
                except Exception as e:
                    logger.warning(f"Could not create MaterialAssets table: {e}")
                    db.session.rollback()
            else:
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

            if 'RecurringLessonSlots' not in table_names and 'recurringlessonslots' not in table_names:
                try:
                    RecurringLessonSlot.__table__.create(db.engine)
                    logger.info("RecurringLessonSlots table created")
                except Exception as e:
                    logger.warning(f"Could not create RecurringLessonSlots table: {e}")
                    db.session.rollback()

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
                        if 'price_per_lesson_rub' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN price_per_lesson_rub INTEGER'))
                                logger.info(f"Added price_per_lesson_rub to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add price_per_lesson_rub to {tp_table}: {e}")
                                db.session.rollback()
                        if 'allow_lessons' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN allow_lessons BOOLEAN'))
                                logger.info(f"Added allow_lessons to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add allow_lessons to {tp_table}: {e}")
                                db.session.rollback()
                        if 'allow_trainer' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN allow_trainer BOOLEAN'))
                                logger.info(f"Added allow_trainer to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add allow_trainer to {tp_table}: {e}")
                                db.session.rollback()
                        if 'lessons_count' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{tp_table}" ADD COLUMN lessons_count INTEGER'))
                                logger.info(f"Added lessons_count to {tp_table}")
                            except Exception as e:
                                logger.warning(f"Could not add lessons_count to {tp_table}: {e}")
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
            else:
                try:
                    us_table = _resolve_table_name(table_names, 'UserSubscriptions')
                    if us_table:
                        cols = {c['name'] for c in inspector.get_columns(us_table)}
                        if 'lessons_remaining' not in cols:
                            try:
                                db.session.execute(text(f'ALTER TABLE "{us_table}" ADD COLUMN lessons_remaining INTEGER'))
                                logger.info(f"Added lessons_remaining to {us_table}")
                            except Exception as e:
                                logger.warning(f"Could not add lessons_remaining to {us_table}: {e}")
                                db.session.rollback()
                except Exception:
                    pass

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
            
            safe_add_column('content', 'TEXT')
            safe_add_column('content_blocks', 'JSON')
            safe_add_column('student_notes', 'TEXT')
            safe_add_column('materials', 'JSON')
            safe_add_column('course_module_id', 'INTEGER')
            safe_add_column('published_at', 'TIMESTAMP' if is_postgres else 'DATETIME')
            safe_add_column('student_late', 'BOOLEAN DEFAULT FALSE')
            safe_add_column('started_at', 'TIMESTAMP' if is_postgres else 'DATETIME')
            safe_add_column('homework_max_attempts_default', 'INTEGER')
            safe_add_column('classwork_max_attempts_default', 'INTEGER')
            safe_add_column('exam_max_attempts_default', 'INTEGER')
            safe_add_column('allow_task_submit_homework', 'BOOLEAN DEFAULT FALSE')
            safe_add_column('allow_task_submit_classwork', 'BOOLEAN DEFAULT FALSE')
            safe_add_column('allow_task_submit_exam', 'BOOLEAN DEFAULT FALSE')

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
                safe_add_lesson_task_column('difficulty_level', 'INTEGER')  # рейтинг: 1–3 лёгкий, 4–7 средний, 8–10 сложный
                safe_add_lesson_task_column('time_spent_sec', 'INTEGER')  # время на задание (сек)
                safe_add_lesson_task_column('max_attempts', 'INTEGER')  # лимит попыток на задание (override)
                try:  # comment
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
                if 'telegram_username' not in student_columns:
                    try:
                        if is_postgres:
                            db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN telegram_username VARCHAR(100)'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {students_table} ADD COLUMN telegram_username VARCHAR(100)'))
                        logger.info(f"Added telegram_username to {students_table}")
                    except Exception as e:
                        logger.warning(f"Could not add telegram_username to {students_table}: {e}")
                        db.session.rollback()
                if 'discord_id' not in student_columns:
                    try:
                        if is_postgres:
                            db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN discord_id VARCHAR(100)'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {students_table} ADD COLUMN discord_id VARCHAR(100)'))
                        logger.info(f"Added discord_id to {students_table}")
                    except Exception as e:
                        logger.warning(f"Could not add discord_id to {students_table}: {e}")
                        db.session.rollback()
                if 'user_id' not in student_columns:
                    db.session.execute(text(f'ALTER TABLE "{students_table}" ADD COLUMN user_id INTEGER REFERENCES "Users"(id)'))
                    logger.info(f"Added user_id column to {students_table}")

                indexes = {idx['name'] for idx in inspector.get_indexes(students_table)}
                if 'idx_students_category' not in indexes:
                    db.session.execute(text(f'CREATE INDEX idx_students_category ON "{students_table}"(category)'))

            lesson_indexes = {idx['name'] for idx in inspector.get_indexes(lessons_table)}
            if 'idx_lessons_status' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_status ON "{lessons_table}"(status)'))
            if 'idx_lessons_lesson_date' not in lesson_indexes:
                db.session.execute(text(f'CREATE INDEX idx_lessons_lesson_date ON "{lessons_table}"(lesson_date)'))

            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_done\' WHERE homework_status = \'completed\''))  # Старый completed -> assigned_done
            db.session.execute(text(f'UPDATE "{lessons_table}" SET homework_status = \'assigned_not_done\' WHERE homework_status IN (\'pending\', \'not_done\')'))  # pending/not_done -> assigned_not_done

            stats_table = 'StudentTaskStatistics' if 'StudentTaskStatistics' in table_names else ('studenttaskstatistics' if 'studenttaskstatistics' in table_names else None)
            if not stats_table:
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
                stats_columns = {col['name'] for col in inspector.get_columns(stats_table)}
                if 'manual_correct' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN manual_correct INTEGER DEFAULT 0 NOT NULL'))
                if 'manual_incorrect' not in stats_columns:
                    db.session.execute(text(f'ALTER TABLE "{stats_table}" ADD COLUMN manual_incorrect INTEGER DEFAULT 0 NOT NULL'))
            
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
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS task_topics (
                            task_id INTEGER NOT NULL REFERENCES Tasks(task_id) ON DELETE CASCADE,
                            topic_id INTEGER NOT NULL REFERENCES Topics(topic_id) ON DELETE CASCADE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (task_id, topic_id)
                        )
                    """))
                logger.info("Created task_topics table")
            
            maintenance_table = 'MaintenanceMode' if 'MaintenanceMode' in table_names else ('maintenancemode' if 'maintenancemode' in table_names else None)
            if not maintenance_table:
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
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

            pending_table = 'PendingAssignmentNotifications' if 'PendingAssignmentNotifications' in table_names else ('pendingassignmentnotifications' if 'pendingassignmentnotifications' in table_names else None)
            if not pending_table:
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS "PendingAssignmentNotifications" (
                            pending_id SERIAL PRIMARY KEY,
                            lesson_id INTEGER NOT NULL REFERENCES "Lessons"(lesson_id) ON DELETE CASCADE,
                            student_id INTEGER NOT NULL REFERENCES "Students"(student_id) ON DELETE CASCADE,
                            assignment_type VARCHAR(50) NOT NULL,
                            task_ids JSON,
                            link_url TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(lesson_id, assignment_type)
                        )
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_lesson
                        ON "PendingAssignmentNotifications"(lesson_id)
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_student
                        ON "PendingAssignmentNotifications"(student_id)
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_activity
                        ON "PendingAssignmentNotifications"(last_activity_at)
                    """))
                else:
                    db.session.execute(text("""
                        CREATE TABLE IF NOT EXISTS PendingAssignmentNotifications (
                            pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            lesson_id INTEGER NOT NULL REFERENCES Lessons(lesson_id) ON DELETE CASCADE,
                            student_id INTEGER NOT NULL REFERENCES Students(student_id) ON DELETE CASCADE,
                            assignment_type VARCHAR(50) NOT NULL,
                            task_ids TEXT,
                            link_url TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(lesson_id, assignment_type)
                        )
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_lesson
                        ON PendingAssignmentNotifications(lesson_id)
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_student
                        ON PendingAssignmentNotifications(student_id)
                    """))
                    db.session.execute(text("""
                        CREATE INDEX IF NOT EXISTS ix_pending_assignment_activity
                        ON PendingAssignmentNotifications(last_activity_at)
                    """))
                logger.info("Created PendingAssignmentNotifications table")

            audit_log_table = 'AuditLog' if 'AuditLog' in table_names else ('auditlog' if 'auditlog' in table_names else None)
            if audit_log_table:
                audit_log_columns = {col['name'] for col in inspector.get_columns(audit_log_table)}
                
                if 'user_id' not in audit_log_columns:
                    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                    if 'postgresql' in db_url or 'postgres' in db_url:
                        try:
                            db.session.execute(text("""
                                ALTER TABLE "AuditLog" 
                                ADD COLUMN user_id INTEGER 
                                REFERENCES "Users"(id) 
                                ON DELETE SET NULL
                            """))
                            db.session.execute(text("""
                                CREATE INDEX IF NOT EXISTS idx_audit_user_id 
                                ON "AuditLog"(user_id)
                            """))
                            logger.info(f"Added user_id column to {audit_log_table}")
                        except Exception as e:
                            logger.warning(f"Could not add user_id column: {e}")
                    else:
                        try:
                            db.session.execute(text("""
                                ALTER TABLE AuditLog 
                                ADD COLUMN user_id INTEGER 
                                REFERENCES Users(id)
                            """))
                            logger.info(f"Added user_id column to {audit_log_table}")
                        except Exception as e:
                            logger.warning(f"Could not add user_id column: {e}")
                
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

            reminders_table = 'Reminders' if 'Reminders' in table_names else ('reminders' if 'reminders' in table_names else None)
            if reminders_table:
                db_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
                    try:
                        result = db.session.execute(text("""
                            SELECT is_nullable 
                            FROM information_schema.columns 
                            WHERE table_name = :table_name AND column_name = 'reminder_time'
                        """), {'table_name': reminders_table})
                        row = result.fetchone()
                        if row and row[0] == 'NO':
                            db.session.execute(text(f'ALTER TABLE "{reminders_table}" ALTER COLUMN reminder_time DROP NOT NULL'))
                            logger.info(f"Made reminder_time nullable in {reminders_table}")
                    except Exception as e:
                        logger.warning(f"Could not check/update reminder_time nullable: {e}")
                else:
                    logger.warning("SQLite does not support ALTER COLUMN, reminder_time will remain NOT NULL")
            
            users_table = _resolve_table_name(table_names, 'Users')
            if users_table:
                try:
                    users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                    
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
                    if 'is_qa_pool' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN is_qa_pool BOOLEAN DEFAULT FALSE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN is_qa_pool INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added column is_qa_pool to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add is_qa_pool column: {e}")
                    
                    if 'is_demo_user' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN is_demo_user BOOLEAN DEFAULT FALSE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN is_demo_user INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added column is_demo_user to {users_table}")
                        except Exception as e:
                            logger.warning(f"Could not add is_demo_user column: {e}")

                    # Обложка профиля на уровне User (ORM: User.cover_url). UserProfiles.cover_url — отдельное поле.
                    if 'cover_url' not in users_columns:
                        try:
                            if is_postgres:
                                db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN cover_url VARCHAR(500)'))
                            else:
                                db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN cover_url VARCHAR(500)'))
                            logger.info(f"Added column cover_url to {users_table}")
                            users_columns = users_columns | {'cover_url'}
                        except Exception as e:
                            logger.warning(f"Could not add cover_url column: {e}")
                            db.session.rollback()
                except Exception as e:
                    logger.warning(f"Error checking/updating Users table columns: {e}")

            qa_tasks_table = _resolve_table_name(table_names, 'qa_tasks')
            if qa_tasks_table:
                try:
                    qa_cols = {c['name'] for c in inspector.get_columns(qa_tasks_table)}
                    if 'task_type' not in qa_cols:
                        is_pg = _is_postgres(app)
                        if is_pg:
                            db.session.execute(text(f'ALTER TABLE "{qa_tasks_table}" ADD COLUMN task_type VARCHAR(30) DEFAULT \'task\' NOT NULL'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {qa_tasks_table} ADD COLUMN task_type VARCHAR(30) DEFAULT \'task\' NOT NULL'))
                        logger.info("Added task_type column to qa_tasks")
                except Exception as e:
                    logger.warning(f"Could not add task_type to qa_tasks: {e}")
                    db.session.rollback()

                try:
                    tasks_columns = {col['name'] for col in inspector.get_columns(qa_tasks_table)}
                    if 'screenshot_path' not in tasks_columns:
                        is_pg = _is_postgres(app)
                        if is_pg:
                            db.session.execute(text(f'ALTER TABLE "{qa_tasks_table}" ADD COLUMN screenshot_path VARCHAR(500)'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {qa_tasks_table} ADD COLUMN screenshot_path VARCHAR(500)'))
                        logger.info("Added screenshot_path column to qa_tasks")
                    if 'assignee_ids' not in tasks_columns:
                        is_pg = _is_postgres(app)
                        if is_pg:
                            db.session.execute(text(f'ALTER TABLE "{qa_tasks_table}" ADD COLUMN assignee_ids JSONB'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {qa_tasks_table} ADD COLUMN assignee_ids JSON'))
                        logger.info("Added assignee_ids column to qa_tasks")
                except Exception as e:
                    logger.warning(f"Could not add screenshot_path/assignee_ids to qa_tasks: {e}")
                    db.session.rollback()

            try:
                db.session.commit()
                logger.info("Database migrations committed successfully")
            except Exception as commit_error:
                db.session.rollback()
                logger.error(f"Error committing migrations: {commit_error}", exc_info=True)
            
            
            if users_table:
                users_columns = {col['name'] for col in inspector.get_columns(users_table)}
                if 'email' not in users_columns:
                    try:
                        db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN email VARCHAR(200)'))
                        logger.info("Added email column to Users table")
                    except Exception as e:
                        logger.warning(f"Could not add email to Users: {e}")
                        db.session.rollback()

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

                if 'numeric_id' not in users_columns:
                    try:
                        if _is_postgres(app):
                            db.session.execute(text(f'ALTER TABLE "{users_table}" ADD COLUMN numeric_id VARCHAR(10)'))
                        else:
                            db.session.execute(text(f'ALTER TABLE {users_table} ADD COLUMN numeric_id VARCHAR(10)'))
                        logger.info("Added numeric_id column to Users table")
                    except Exception as e:
                        logger.warning(f"Could not add numeric_id to Users: {e}")
                        db.session.rollback()
            
            user_roles_table = _resolve_table_name(table_names, 'UserRoles')
            if not user_roles_table:
                try:
                    db.create_all()
                    logger.info("Created UserRoles table")
                except Exception as e:
                    logger.warning(f"Could not create UserRoles table: {e}")
                table_names = [t for t in inspector.get_table_names()]
                user_roles_table = _resolve_table_name(table_names, 'UserRoles')
            if user_roles_table:
                try:
                    existing = db.session.query(UserRole).limit(1).first()
                    if not existing:
                        for u in User.query.all():
                            if u.role and not UserRole.query.filter_by(user_id=u.id).first():
                                db.session.add(UserRole(user_id=u.id, role=u.role))
                        logger.info("Backfilled UserRoles from User.role (will commit with RBAC)")
                except Exception as e:
                    logger.warning(f"Could not backfill UserRoles: {e}")
            
            profiles_table = _resolve_table_name(table_names, 'UserProfiles')
            if not profiles_table:
                try:
                    db.create_all()  # Создаст таблицу UserProfiles если её нет
                    logger.info("Created UserProfiles table")
                except Exception as e:
                    logger.warning(f"Could not create UserProfiles table: {e}")
            else:
                try:
                    cols = {c['name'] for c in inspector.get_columns(profiles_table)}
                    if 'cover_url' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN cover_url VARCHAR(500)'))
                            logger.info(f"Added cover_url to {profiles_table}")
                        except Exception as e:
                            logger.warning(f"Could not add cover_url to {profiles_table}: {e}")
                            db.session.rollback()
                    if 'telegram_chat_id' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN telegram_chat_id BIGINT'))
                            logger.info(f"Added telegram_chat_id to {profiles_table}")
                        except Exception as e:
                            logger.warning(f"Could not add telegram_chat_id to {profiles_table}: {e}")
                            db.session.rollback()
                    if 'telegram_link_code' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN telegram_link_code VARCHAR(32)'))
                            logger.info(f"Added telegram_link_code to {profiles_table}")
                        except Exception as e:
                            logger.warning(f"Could not add telegram_link_code to {profiles_table}: {e}")
                            db.session.rollback()
                    if 'telegram_link_code_expires' not in cols:
                        try:
                            col_type = 'TIMESTAMP' if _is_postgres(app) else 'DATETIME'
                            db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN telegram_link_code_expires {col_type}'))
                            logger.info(f"Added telegram_link_code_expires to {profiles_table}")
                        except Exception as e:
                            logger.warning(f"Could not add telegram_link_code_expires to {profiles_table}: {e}")
                            db.session.rollback()
                    if 'telegram_notifications_enabled' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN telegram_notifications_enabled BOOLEAN DEFAULT TRUE'))
                            logger.info(f"Added telegram_notifications_enabled to {profiles_table}")
                        except Exception as e:
                            logger.warning(f"Could not add telegram_notifications_enabled to {profiles_table}: {e}")
                            db.session.rollback()
                    
                    tg_notify_fields = [
                        'tg_notify_lesson_reminder',
                        'tg_notify_homework_checked',
                        'tg_notify_homework_returned',
                        'tg_notify_new_message',
                        'tg_notify_lesson_scheduled',
                        'tg_notify_low_lessons',
                        'tg_notify_news',
                        'tg_notify_referral_used',
                        'tg_notify_homework_submitted',
                        'tg_notify_system_errors'
                    ]
                    for field in tg_notify_fields:
                        if field not in cols:
                            try:
                                default_val = 'TRUE'
                                db.session.execute(text(f'ALTER TABLE "{profiles_table}" ADD COLUMN {field} BOOLEAN DEFAULT {default_val}'))
                                logger.info(f"Added {field} to {profiles_table}")
                            except Exception as e:
                                logger.warning(f"Could not add {field} to {profiles_table}: {e}")
                                db.session.rollback()
                    try:
                        db.session.execute(text(f'UPDATE "{profiles_table}" SET tg_notify_news = TRUE WHERE tg_notify_news IS NULL OR tg_notify_news = FALSE'))
                        logger.info("Updated tg_notify_news to TRUE for existing profiles")
                    except Exception as e:
                        logger.warning(f"Could not update tg_notify_news defaults: {e}")
                        db.session.rollback()
                except Exception:
                    pass
            
            bot_admins_table = _resolve_table_name(table_names, 'BotAdmins')
            if not bot_admins_table:
                try:
                    db.create_all()
                    logger.info("Created BotAdmins table")
                except Exception as e:
                    logger.warning(f"Could not create BotAdmins table: {e}")
            bot_error_reports_table = _resolve_table_name(table_names, 'BotErrorReports')
            if not bot_error_reports_table:
                try:
                    db.create_all()
                    logger.info("Created BotErrorReports table")
                except Exception as e:
                    logger.warning(f"Could not create BotErrorReports table: {e}")
            
            family_ties_table = _resolve_table_name(table_names, 'FamilyTies')
            if not family_ties_table:
                try:
                    db.create_all()  # Создаст таблицу FamilyTies если её нет
                    logger.info("Created FamilyTies table")
                except Exception as e:
                    logger.warning(f"Could not create FamilyTies table: {e}")
            
            enrollments_table = _resolve_table_name(table_names, 'Enrollments')
            if not enrollments_table:
                try:
                    db.create_all()  # Создаст таблицу Enrollments если её нет
                    logger.info("Created Enrollments table")
                except Exception as e:
                    logger.warning(f"Could not create Enrollments table: {e}")
            
            assignments_table = _resolve_table_name(table_names, 'Assignments')
            if not assignments_table:
                try:
                    db.create_all()  # Создаст все таблицы системы заданий если их нет
                    logger.info("Created Assignments system tables (Assignments, AssignmentTasks, Submissions, Answers)")
                except Exception as e:
                    logger.warning(f"Could not create Assignments system tables: {e}")

            rubric_templates_table = _resolve_table_name(table_names, 'RubricTemplates')
            if not rubric_templates_table:
                try:
                    db.create_all()
                    logger.info("Created RubricTemplates table")
                except Exception as e:
                    logger.warning(f"Could not create RubricTemplates table: {e}")

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
                    if 'max_attempts_default' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN max_attempts_default INTEGER'))
                            logger.info(f"Added max_attempts_default to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add max_attempts_default to {assignments_table}: {e}")
                            db.session.rollback()
                    if 'allow_separate_submission' not in cols:
                        try:
                            if _is_postgres(app):
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN allow_separate_submission BOOLEAN DEFAULT TRUE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN allow_separate_submission INTEGER DEFAULT 1 NOT NULL'))
                            logger.info(f"Added allow_separate_submission to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add allow_separate_submission to {assignments_table}: {e}")
                            db.session.rollback()
                    if 'time_limit_minutes' not in cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN time_limit_minutes INTEGER'))
                            logger.info(f"Added time_limit_minutes to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add time_limit_minutes to {assignments_table}: {e}")
                            db.session.rollback()
                    if 'time_limit_strict' not in cols:
                        try:
                            if _is_postgres(app):
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN time_limit_strict BOOLEAN DEFAULT FALSE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN time_limit_strict INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added time_limit_strict to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add time_limit_strict to {assignments_table}: {e}")
                            db.session.rollback()
                    if 'attempts_per_task' not in cols:
                        try:
                            if _is_postgres(app):
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN attempts_per_task BOOLEAN DEFAULT FALSE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE "{assignments_table}" ADD COLUMN attempts_per_task INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added attempts_per_task to {assignments_table}")
                        except Exception as e:
                            logger.warning(f"Could not add attempts_per_task to {assignments_table}: {e}")
                            db.session.rollback()
                assignment_tasks_table = _resolve_table_name(table_names, 'AssignmentTasks')
                if assignment_tasks_table:
                    at_cols = {c['name'] for c in inspector.get_columns(assignment_tasks_table)}
                    if 'max_attempts' not in at_cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{assignment_tasks_table}" ADD COLUMN max_attempts INTEGER'))
                            logger.info(f"Added max_attempts to {assignment_tasks_table}")
                        except Exception as e:
                            logger.warning(f"Could not add max_attempts to {assignment_tasks_table}: {e}")
                            db.session.rollback()
                    if 'answer_override' not in at_cols:
                        try:
                            db.session.execute(text(f'ALTER TABLE "{assignment_tasks_table}" ADD COLUMN answer_override TEXT'))
                            logger.info(f"Added answer_override to {assignment_tasks_table}")
                        except Exception as e:
                            logger.warning(f"Could not add answer_override to {assignment_tasks_table}: {e}")
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
                            try:
                                db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN rubric_scores TEXT'))
                                logger.info(f"Added rubric_scores (TEXT) to {submissions_table}")
                            except Exception as e2:
                                logger.warning(f"Could not add rubric_scores to {submissions_table}: {e} / {e2}")
                                db.session.rollback()
                    if 'is_overtime' not in cols:
                        try:
                            if _is_postgres(app):
                                db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN is_overtime BOOLEAN DEFAULT FALSE NOT NULL'))
                            else:
                                db.session.execute(text(f'ALTER TABLE "{submissions_table}" ADD COLUMN is_overtime INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added is_overtime to {submissions_table}")
                        except Exception as e:
                            logger.warning(f"Could not add is_overtime to {submissions_table}: {e}")
                            db.session.rollback()
                answers_table = _resolve_table_name(table_names, 'Answers')
                if answers_table:
                    try:
                        ans_cols = {c['name'] for c in inspector.get_columns(answers_table)}
                        if 'submitted_separately_at' not in ans_cols:
                            col_type = 'TIMESTAMP' if _is_postgres(app) else 'DATETIME'
                            db.session.execute(text(f'ALTER TABLE "{answers_table}" ADD COLUMN submitted_separately_at {col_type}'))
                            logger.info(f"Added submitted_separately_at to {answers_table}")
                        if 'attempts_used' not in ans_cols:
                            db.session.execute(text(f'ALTER TABLE "{answers_table}" ADD COLUMN attempts_used INTEGER DEFAULT 0 NOT NULL'))
                            logger.info(f"Added attempts_used to {answers_table}")
                        if 'student_code' not in ans_cols:
                            db.session.execute(text(f'ALTER TABLE "{answers_table}" ADD COLUMN student_code TEXT'))
                            logger.info(f"Added student_code to {answers_table}")
                        if 'student_code_saved_at' not in ans_cols:
                            col_type = 'TIMESTAMP' if _is_postgres(app) else 'DATETIME'
                            db.session.execute(text(f'ALTER TABLE "{answers_table}" ADD COLUMN student_code_saved_at {col_type}'))
                            logger.info(f"Added student_code_saved_at to {answers_table}")
                    except Exception as e:
                        logger.warning(f"Could not add Answer columns: {e}")
                        db.session.rollback()
            except Exception as e:
                logger.warning(f"Could not ensure rubric columns: {e}")
            
            comments_table = _resolve_table_name(table_names, 'SubmissionComments')
            if not comments_table:
                try:
                    db.create_all() # Создаст таблицу SubmissionComments если её нет
                    logger.info("Created SubmissionComments table")
                except Exception as e:
                    logger.warning(f"Could not create SubmissionComments table: {e}")

            subjects_table = _resolve_table_name(table_names, 'subjects')
            if not subjects_table:
                try:
                    Subject.__table__.create(db.engine)
                    logger.info("Created subjects table (analytics)")
                except Exception as e:
                    logger.warning(f"Could not create subjects table: {e}")
                    db.session.rollback()
            knowledge_nodes_table = _resolve_table_name(table_names, 'knowledge_nodes')
            if not knowledge_nodes_table:
                try:
                    KnowledgeNode.__table__.create(db.engine)
                    logger.info("Created knowledge_nodes table (analytics)")
                except Exception as e:
                    logger.warning(f"Could not create knowledge_nodes table: {e}")
                    db.session.rollback()
            user_mastery_table = _resolve_table_name(table_names, 'user_mastery')
            if not user_mastery_table:
                try:
                    UserMastery.__table__.create(db.engine)
                    logger.info("Created user_mastery table (analytics)")
                except Exception as e:
                    logger.warning(f"Could not create user_mastery table: {e}")
                    db.session.rollback()
            analytics_events_table = _resolve_table_name(table_names, 'analytics_events')
            if not analytics_events_table:
                try:
                    AnalyticsEvent.__table__.create(db.engine)
                    logger.info("Created analytics_events table (analytics)")
                except Exception as e:
                    logger.warning(f"Could not create analytics_events table: {e}")
                    db.session.rollback()

            tasks_table = _resolve_table_name(table_names, 'Tasks')
            if tasks_table:
                try:
                    inspector = inspect(db.engine)
                    table_names_after = inspector.get_table_names()
                    tasks_table_resolved = _resolve_table_name(table_names_after, 'Tasks')
                    if tasks_table_resolved:
                        cols = {c['name'] for c in inspector.get_columns(tasks_table_resolved)}
                        if 'knowledge_node_id' not in cols:
                            db.session.execute(text(f'ALTER TABLE "{tasks_table_resolved}" ADD COLUMN knowledge_node_id INTEGER'))
                            logger.info("Added knowledge_node_id to Tasks (analytics)")
                        # --- Фаза 0: difficulty_level & hints ---
                        if 'difficulty_level' not in cols:
                            db.session.execute(text(f'ALTER TABLE "{tasks_table_resolved}" ADD COLUMN difficulty_level INTEGER'))
                            logger.info("Added difficulty_level to Tasks")
                        if 'hints' not in cols:
                            col_type = 'JSONB' if is_postgres else 'JSON'
                            db.session.execute(text(f'ALTER TABLE "{tasks_table_resolved}" ADD COLUMN hints {col_type}'))
                            logger.info("Added hints (JSON) to Tasks")
                        if 'source_prototype' not in cols:
                            db.session.execute(text(f'ALTER TABLE "{tasks_table_resolved}" ADD COLUMN source_prototype VARCHAR(256)'))
                            logger.info("Added source_prototype to Tasks")
                        if 'task_group_id' not in cols:
                            db.session.execute(text(f'ALTER TABLE "{tasks_table_resolved}" ADD COLUMN task_group_id VARCHAR(64)'))
                            logger.info("Added task_group_id to Tasks (19-21 triplets)")
                        # Индекс для difficulty_level
                        try:
                            db.session.execute(text(f'CREATE INDEX IF NOT EXISTS ix_tasks_difficulty_level ON "{tasks_table_resolved}"(difficulty_level)'))
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"Could not add knowledge_node_id/difficulty/hints to Tasks: {e}")
                    db.session.rollback()

            # --- Фаза 0: новые поля в analytics_events ---
            analytics_events_table = _resolve_table_name(table_names_after if 'table_names_after' in dir() else table_names, 'analytics_events')
            if analytics_events_table:
                try:
                    ae_cols = {c['name'] for c in inspector.get_columns(analytics_events_table)}
                    if 'task_id' not in ae_cols:
                        db.session.execute(text(f'ALTER TABLE "{analytics_events_table}" ADD COLUMN task_id INTEGER'))
                        logger.info("Added task_id to analytics_events")
                    if 'time_spent_sec' not in ae_cols:
                        db.session.execute(text(f'ALTER TABLE "{analytics_events_table}" ADD COLUMN time_spent_sec INTEGER'))
                        logger.info("Added time_spent_sec to analytics_events")
                    if 'behavior_flags' not in ae_cols:
                        col_type = 'JSONB' if is_postgres else 'JSON'
                        db.session.execute(text(f'ALTER TABLE "{analytics_events_table}" ADD COLUMN behavior_flags {col_type}'))
                        logger.info("Added behavior_flags (JSON) to analytics_events")
                except Exception as e:
                    logger.warning(f"Could not add new columns to analytics_events: {e}")
                    db.session.rollback()

            # ===== Многокурсовая архитектура (ExamCourses, CourseTaskTemplates, etc.) =====
            _migrate_multi_course(app, inspector, table_names, is_postgres)

            try:
                db.session.commit()
                logger.info("RBAC and Assignments migrations committed successfully")
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Error committing RBAC/Assignments migrations: {e}")
            
            _fix_postgres_sequences(app, inspector)  # После миграций синхронизируем sequences (чинит 500 duplicate key на SERIAL)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при миграции схемы БД: {e}", exc_info=True)


def _migrate_multi_course(app, inspector, table_names, is_postgres):
    """Миграция для многокурсовой архитектуры: создание таблиц и seed данных."""
    from core.db_models import (
        Course as ExamCourse, CourseTaskTemplate, StudentCourseEnrollment,
        GradingScale, Student, Tasks, TheoryBlock, StudentTheoryAccess,
        StudentTaskStatistics, CallRequest, StudentTheoryState, TheoryFeedback,
    )
    try:
        for model in [ExamCourse, CourseTaskTemplate, StudentCourseEnrollment, GradingScale, CallRequest, StudentTheoryState, TheoryFeedback]:
            tname = model.__tablename__
            if tname.lower() not in [t.lower() for t in table_names]:
                try:
                    model.__table__.create(db.engine)
                    logger.info(f"{tname} table created")
                except Exception as e:
                    logger.warning(f"Could not create {tname}: {e}")
                    db.session.rollback()

        db.session.commit()

        # --- Новые колонки course_id / exam_course_id ---
        _add_col = _make_safe_add_column(inspector, is_postgres)
        _add_col('Tasks', 'course_id', 'INTEGER')
        _add_col('TheoryBlocks', 'course_id', 'INTEGER')
        _add_col('TheoryBlocks', 'pdf_path', 'VARCHAR(500)')
        _add_col('StudentTheoryAccess', 'course_id', 'INTEGER')
        _add_col('StudentTaskStatistics', 'course_id', 'INTEGER')
        _add_col('Assignments', 'exam_course_id', 'INTEGER')
        _add_col('Lessons', 'exam_course_id', 'INTEGER')
        db.session.commit()

        # --- Seed: ExamCourse «ЕГЭ Информатика» ---
        ege = ExamCourse.query.filter_by(slug='ege_informatics').first()
        if not ege:
            ege = ExamCourse(id=1, title='ЕГЭ Информатика', slug='ege_informatics', is_active=True)
            db.session.add(ege)
            db.session.flush()
            logger.info("Seeded ExamCourse: ЕГЭ Информатика (id=1)")

        # --- Seed: CourseTaskTemplate для ЕГЭ (1-27) ---
        existing_templates = CourseTaskTemplate.query.filter_by(course_id=ege.id).count()
        if existing_templates == 0:
            ege_scores = {
                1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1,
                11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1,
                19: 1, 20: 1, 21: 1, 22: 1, 23: 1,
                24: 1, 25: 2, 26: 2, 27: 2,
            }
            for tn in range(1, 28):
                tmpl = CourseTaskTemplate(
                    course_id=ege.id,
                    task_number=tn,
                    max_primary_score=ege_scores.get(tn, 1),
                    requires_manual_review=False,
                )
                db.session.add(tmpl)
            logger.info("Seeded 27 CourseTaskTemplates for ЕГЭ Информатика")

        # --- Seed: ExamCourse «ОГЭ Информатика» ---
        oge = ExamCourse.query.filter_by(slug='oge_informatics').first()
        if not oge:
            oge = ExamCourse(id=2, title='ОГЭ Информатика', slug='oge_informatics', is_active=True)
            db.session.add(oge)
            db.session.flush()
            logger.info("Seeded ExamCourse: ОГЭ Информатика (id=2)")

        existing_oge_templates = CourseTaskTemplate.query.filter_by(course_id=oge.id).count()
        if existing_oge_templates == 0:
            oge_scores = {
                1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1,
                11: 1, 12: 1, 13: 2, 14: 2, 15: 2,
            }
            for tn in range(1, 16):
                tmpl = CourseTaskTemplate(
                    course_id=oge.id,
                    task_number=tn,
                    max_primary_score=oge_scores.get(tn, 1),
                    requires_manual_review=(tn >= 13),
                )
                db.session.add(tmpl)
            logger.info("Seeded 15 CourseTaskTemplates for ОГЭ Информатика")

        # --- Seed: GradingScale для ОГЭ (оценка 2-5) ---
        existing_oge_scales = GradingScale.query.filter_by(course_id=oge.id).count()
        if existing_oge_scales == 0:
            oge_scale = [
                (0, 4, 2, 'Неудовлетворительно'),
                (5, 10, 3, 'Удовлетворительно'),
                (11, 15, 4, 'Хорошо'),
                (16, 19, 5, 'Отлично'),
            ]
            for min_p, max_p, grade, label in oge_scale:
                db.session.add(GradingScale(
                    course_id=oge.id, min_primary=min_p, max_primary=max_p,
                    final_grade=grade, label=label,
                ))
            logger.info("Seeded GradingScale for ОГЭ Информатика")

        # --- Backfill: присвоить course_id=1 всем Tasks без course_id ---
        try:
            updated = Tasks.query.filter(Tasks.course_id.is_(None)).update({Tasks.course_id: ege.id})
            if updated:
                logger.info(f"Backfilled course_id={ege.id} for {updated} Tasks")
        except Exception as e:
            logger.warning(f"Could not backfill Tasks.course_id: {e}")
            db.session.rollback()

        # --- Backfill: TheoryBlock ---
        try:
            updated = TheoryBlock.query.filter(TheoryBlock.course_id.is_(None)).update({TheoryBlock.course_id: ege.id})
            if updated:
                logger.info(f"Backfilled course_id={ege.id} for {updated} TheoryBlocks")
        except Exception as e:
            logger.warning(f"Could not backfill TheoryBlock.course_id: {e}")
            db.session.rollback()

        # --- Backfill: StudentTheoryAccess ---
        try:
            updated = StudentTheoryAccess.query.filter(StudentTheoryAccess.course_id.is_(None)).update({StudentTheoryAccess.course_id: ege.id})
            if updated:
                logger.info(f"Backfilled course_id={ege.id} for {updated} StudentTheoryAccess rows")
        except Exception as e:
            logger.warning(f"Could not backfill StudentTheoryAccess.course_id: {e}")
            db.session.rollback()

        # --- Backfill: StudentTaskStatistics ---
        try:
            updated = StudentTaskStatistics.query.filter(StudentTaskStatistics.course_id.is_(None)).update({StudentTaskStatistics.course_id: ege.id})
            if updated:
                logger.info(f"Backfilled course_id={ege.id} for {updated} StudentTaskStatistics rows")
        except Exception as e:
            logger.warning(f"Could not backfill StudentTaskStatistics.course_id: {e}")
            db.session.rollback()

        # --- Создание StudentCourseEnrollment для существующих учеников ---
        try:
            students = Student.query.filter(Student.is_active.is_(True)).all()
            created_count = 0
            for s in students:
                cat = (s.category or '').strip().upper()
                target_course_id = oge.id if cat == 'ОГЭ' else ege.id
                exists = StudentCourseEnrollment.query.filter_by(
                    student_id=s.student_id, course_id=target_course_id
                ).first()
                if not exists:
                    db.session.add(StudentCourseEnrollment(
                        student_id=s.student_id, course_id=target_course_id, is_active=True
                    ))
                    created_count += 1
            if created_count:
                logger.info(f"Created {created_count} StudentCourseEnrollments")
        except Exception as e:
            logger.warning(f"Could not create StudentCourseEnrollments: {e}")
            db.session.rollback()

        db.session.commit()
        logger.info("Multi-course migration completed successfully")

        # --- Seed: Subject + KnowledgeNode для ОГЭ ---
        try:
            from core.db_models import Subject, KnowledgeNode
            oge_subject = Subject.query.filter_by(slug='oge').first()
            if not oge_subject:
                oge_subject = Subject(slug='oge', name='Информатика (ОГЭ)')
                db.session.add(oge_subject)
                db.session.flush()
                logger.info("Created Subject: oge (Информатика ОГЭ)")

            existing_oge_nodes = KnowledgeNode.query.filter_by(subject_id=oge_subject.id).count()
            if existing_oge_nodes == 0:
                import json as _json
                _oge_data_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'analytics_oge_difficulty.json')
                if os.path.isfile(_oge_data_path):
                    with open(_oge_data_path, 'r', encoding='utf-8') as _f:
                        _oge_matrix = _json.load(_f)
                    _tn_to_node = {}
                    for _row in _oge_matrix:
                        _node = KnowledgeNode(
                            subject_id=oge_subject.id,
                            name=_row.get('topic', _row['node_code']),
                            code=_row['node_code'],
                            base_rating=int(_row.get('base_rating', 1000)),
                            exam_points=int(_row.get('exam_points', 1)),
                            complexity_tier=_row.get('complexity_tier'),
                        )
                        db.session.add(_node)
                        db.session.flush()
                        _tn_to_node[_row['task_number']] = _node.id
                    db.session.commit()
                    _oge_course = ExamCourse.query.filter_by(slug='oge_informatics').first()
                    if _oge_course:
                        _updated = 0
                        for _tn, _nid in _tn_to_node.items():
                            for _task in Tasks.query.filter_by(task_number=_tn, course_id=_oge_course.id).all():
                                _task.knowledge_node_id = _nid
                                _updated += 1
                        db.session.commit()
                        logger.info(f"Seeded {len(_tn_to_node)} KnowledgeNodes for ОГЭ, linked {_updated} tasks")
                else:
                    logger.warning(f"OGE analytics data not found at {_oge_data_path}")
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Could not seed OGE analytics: {e}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in multi-course migration: {e}", exc_info=True)


def _make_safe_add_column(inspector, is_postgres):
    """Фабрика: возвращает функцию для безопасного добавления колонки."""
    def _add_col(table_name, col_name, col_type):
        try:
            cols = {c['name'] for c in inspector.get_columns(table_name)}
        except Exception:
            try:
                cols = {c['name'] for c in inspector.get_columns(table_name.lower())}
            except Exception:
                return
        if col_name in cols:
            return
        try:
            q = table_name if not is_postgres else f'"{table_name}"'
            db.session.execute(text(f'ALTER TABLE {q} ADD COLUMN {col_name} {col_type}'))
            logger.info(f"Added column {col_name} to {table_name}")
        except Exception as e:
            logger.warning(f"Could not add {col_name} to {table_name}: {e}")
            db.session.rollback()
    return _add_col
