"""
Маршруты для управления студентами
"""
import json
import logging  # Логирование для отладки и прод-логов
import os
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app  # current_app нужен для определения типа БД (Postgres)
from flask_login import login_required
from sqlalchemy import text, or_, func  # text нужен для выполнения SQL setval(pg_get_serial_sequence(...)) при сбитых sequences
from sqlalchemy.exc import OperationalError, ProgrammingError
from datetime import datetime
import csv
import io
from flask import Response

from flask_wtf.csrf import validate_csrf, CSRFError

from app.students import students_bp
from app.students.forms import StudentForm, normalize_school_class
from app.students.utils import get_sorted_assignments
from app.students.stats_service import StatsService
from app.lessons.forms import LessonForm, ensure_introductory_without_homework
from app.notifications.service import notify_student_and_parents
from app.telegram.user_notify import notify_user_by_id
from app.utils.datetime_utc import effective_timezone_name
from app.utils.relationship_scope import (
    can_user_access_student,
    get_family_tie_between,
    get_family_ties_for_student,
    remove_family_ties_for_parent,
    remove_family_ties_for_student,
)
from app.utils.lesson_time import parse_local_lesson_datetime, lesson_storage_to_local
from app.models import (
    Student,
    StudentTaskStatistics,
    StudentLearningPlanItem,
    GradebookEntry,
    Topic,
    Lesson,
    LessonTask,
    LearningTrajectory,
    TrajectoryModule,
    db,
    moscow_now,
    MOSCOW_TZ,
    TOMSK_TZ,
    Submission,
    Assignment,
    StudentCourseEnrollment,
    CallRequest,
)
from app.models import User, UserProfile, TelegramStartLead, FamilyTie, Enrollment
from app.utils.student_id_manager import assign_platform_id_if_needed
from core.audit_logger import audit_logger
from flask_login import current_user
from app.utils.db_migrations import ensure_schema_columns
from app.auth.rbac_utils import get_user_scope, has_permission
from app.utils.subscription_access import get_effective_access_for_user

logger = logging.getLogger(__name__)


def _absolute_app_url(path: str) -> str:
    base = (os.environ.get('APP_URL') or '').rstrip('/')
    if base:
        return f'{base}{path}'
    return path


def _normalize_tg_username(value: str | None) -> str:
    value = (value or '').strip()
    if value.startswith('https://t.me/'):
        value = value.rsplit('/', 1)[-1]
    return value.strip().lstrip('@').lower()


def _telegram_display(profile: UserProfile | None) -> str:
    if not profile:
        return ''
    if profile.telegram_id:
        return str(profile.telegram_id)
    if profile.telegram_chat_id:
        return f'chat_id {profile.telegram_chat_id}'
    return ''

def _get_student_user_for_scope(student: Student) -> User | None:
    """Сопоставляет Student с User по user_id или legacy student_id."""
    if not student:
        return None
    if getattr(student, 'user_id', None):
        u = User.query.get(student.user_id)
        if u:
            return u
    try:
        u = User.query.get(student.student_id)
        if u and u.role == 'student':
            return u
    except Exception:
        pass
    return None


def _can_access_student(student: Student) -> bool:
    """
    Унифицированная проверка доступа к ученику:
    - admin/creator: всё
    - student: только себя (user_id или legacy student_id==User.id)
    - tutor/parent: через data scope (Enrollment/FamilyTie)
    """
    if not current_user.is_authenticated:
        return False

    if current_user.is_creator() or current_user.is_admin():
        return True

    if current_user.is_student():
        if getattr(student, 'user_id', None) == current_user.id:
            return True
        if student.student_id == current_user.id:
            return True
        return False

    st_user = _get_student_user_for_scope(student)
    if can_user_access_student(current_user, student_user_id=getattr(st_user, 'id', None), student_platform_id=student.student_id):
        return True
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    return student.student_id in (scope.get('student_ids') or [])


def _guard_student_access(student_id: int) -> Student:
    student = Student.query.get_or_404(student_id)
    if not _can_access_student(student):
        from flask import abort
        abort(403)
    return student


def _parse_datetime_local(value: str | None):
    """Парсим значение из input[type=datetime-local]. Храним как naive (обычно MSK)."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _delete_student_related_rows(student_id: int, linked_user_id: int | None = None) -> None:
    """Удаляет зависимые записи, которые не везде имеют DB-level cascade."""
    from app import models as m

    lesson_ids = [
        row[0]
        for row in db.session.query(Lesson.lesson_id)
        .filter(Lesson.student_id == student_id)
        .all()
    ]
    lesson_task_ids = []
    if lesson_ids:
        lesson_task_ids = [
            row[0]
            for row in db.session.query(LessonTask.lesson_task_id)
            .filter(LessonTask.lesson_id.in_(lesson_ids))
            .all()
        ]
        if lesson_task_ids:
            m.LessonTaskTeacherComment.query.filter(
                m.LessonTaskTeacherComment.lesson_task_id.in_(lesson_task_ids)
            ).delete(synchronize_session=False)
            m.LessonTaskAttempt.query.filter(
                m.LessonTaskAttempt.lesson_task_id.in_(lesson_task_ids)
            ).delete(synchronize_session=False)
        m.LessonMaterialLink.query.filter(
            m.LessonMaterialLink.lesson_id.in_(lesson_ids)
        ).delete(synchronize_session=False)
        m.LessonMessage.query.filter(
            m.LessonMessage.lesson_id.in_(lesson_ids)
        ).delete(synchronize_session=False)
        m.LessonWhiteboard.query.filter(
            m.LessonWhiteboard.lesson_id.in_(lesson_ids)
        ).delete(synchronize_session=False)
        m.PendingAssignmentNotification.query.filter(
            m.PendingAssignmentNotification.lesson_id.in_(lesson_ids)
        ).delete(synchronize_session=False)
        LessonTask.query.filter(LessonTask.lesson_id.in_(lesson_ids)).delete(synchronize_session=False)

    submission_ids = [
        row[0]
        for row in db.session.query(Submission.submission_id)
        .filter(Submission.student_id == student_id)
        .all()
    ]
    if submission_ids:
        from core.db_models import SubmissionTelegramDeadlineSent

        m.Answer.query.filter(m.Answer.submission_id.in_(submission_ids)).delete(synchronize_session=False)
        m.SubmissionAttempt.query.filter(
            m.SubmissionAttempt.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)
        m.SubmissionComment.query.filter(
            m.SubmissionComment.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)
        m.SubmissionCommentThreadRead.query.filter(
            m.SubmissionCommentThreadRead.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)
        SubmissionTelegramDeadlineSent.query.filter(
            SubmissionTelegramDeadlineSent.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    course_ids = [
        row[0]
        for row in db.session.query(LearningTrajectory.course_id)
        .filter(LearningTrajectory.student_id == student_id)
        .all()
    ]
    if course_ids:
        m.TrajectoryModule.query.filter(
            m.TrajectoryModule.course_id.in_(course_ids)
        ).delete(synchronize_session=False)

    for model in (
        m.GroupStudent,
        m.StudentDiagnosticCheckpoint,
        m.StudentTaskSeen,
        m.PendingAssignmentNotification,
        m.RecurringLessonSlot,
        m.CallRequest,
        m.InviteLink,
        m.TrainerSession,
        m.TrainerLlmLog,
        m.StudentTheoryAccess,
        m.StudentTheoryState,
        m.TheoryFeedback,
        m.TheoryFeedbackHistory,
        StudentTaskStatistics,
        GradebookEntry,
        StudentLearningPlanItem,
        StudentCourseEnrollment,
        LearningTrajectory,
        Submission,
        Lesson,
        Enrollment,
    ):
        model.query.filter_by(student_id=student_id).delete(synchronize_session=False)

    if linked_user_id:
        remove_family_ties_for_student(linked_user_id)
        m.Enrollment.query.filter_by(student_id=linked_user_id).delete(synchronize_session=False)
        m.StudentWorkspaceFile.query.filter_by(user_id=linked_user_id).delete(synchronize_session=False)
        m.TaskCanvasDrawing.query.filter_by(user_id=linked_user_id).delete(synchronize_session=False)


def _delete_user_related_rows(user_id: int) -> None:
    """Удаляет/отвязывает зависимости User перед физическим удалением демо-аккаунта."""
    from app import models as m
    from core.db_models import (
        AnalyticsEvent,
        AuditLog,
        BotAdmin,
        BotErrorReport,
        MiroUserToken,
        PlatformBugReport,
        QAComment,
        QATask,
        ReferralCode,
        ReferralUsage,
        RematchQueue,
        Reminder,
        SubmissionTelegramDeadlineSent,
        TelegramStartLead,
        UserConsent,
        UserMastery,
        UserNotification,
        UserRole,
        UserSubscription,
        UserTaskMMR,
    )

    remove_family_ties_for_parent(user_id)
    remove_family_ties_for_student(user_id)
    m.Enrollment.query.filter(
        or_(m.Enrollment.student_id == user_id, m.Enrollment.tutor_id == user_id)
    ).delete(synchronize_session=False)

    qa_task_ids = [
        row[0]
        for row in db.session.query(QATask.id)
        .filter(QATask.reporter_id == user_id)
        .all()
    ]
    if qa_task_ids:
        QAComment.query.filter(QAComment.task_id.in_(qa_task_ids)).delete(synchronize_session=False)
        QATask.query.filter(QATask.id.in_(qa_task_ids)).delete(synchronize_session=False)
    QAComment.query.filter_by(author_id=user_id).delete(synchronize_session=False)
    QATask.query.filter_by(assignee_id=user_id).update(
        {'assignee_id': None},
        synchronize_session=False,
    )

    assignment_ids = [
        row[0]
        for row in db.session.query(m.Assignment.assignment_id)
        .filter(m.Assignment.created_by_id == user_id)
        .all()
    ]
    if assignment_ids:
        submission_ids = [
            row[0]
            for row in db.session.query(m.Submission.submission_id)
            .filter(m.Submission.assignment_id.in_(assignment_ids))
            .all()
        ]
        if submission_ids:
            m.Answer.query.filter(m.Answer.submission_id.in_(submission_ids)).delete(synchronize_session=False)
            m.SubmissionAttempt.query.filter(
                m.SubmissionAttempt.submission_id.in_(submission_ids)
            ).delete(synchronize_session=False)
            m.SubmissionComment.query.filter(
                m.SubmissionComment.submission_id.in_(submission_ids)
            ).delete(synchronize_session=False)
            m.SubmissionCommentThreadRead.query.filter(
                m.SubmissionCommentThreadRead.submission_id.in_(submission_ids)
            ).delete(synchronize_session=False)
            m.GradebookEntry.query.filter(
                m.GradebookEntry.submission_id.in_(submission_ids)
            ).delete(synchronize_session=False)
            SubmissionTelegramDeadlineSent.query.filter(
                SubmissionTelegramDeadlineSent.submission_id.in_(submission_ids)
            ).delete(synchronize_session=False)
        m.AssignmentTask.query.filter(
            m.AssignmentTask.assignment_id.in_(assignment_ids)
        ).delete(synchronize_session=False)
        m.Submission.query.filter(
            m.Submission.assignment_id.in_(assignment_ids)
        ).delete(synchronize_session=False)
        m.Assignment.query.filter(
            m.Assignment.assignment_id.in_(assignment_ids)
        ).delete(synchronize_session=False)

    for model in (
        UserRole,
        UserNotification,
        m.UserProfile,
        MiroUserToken,
        ReferralUsage,
        Reminder,
        BotAdmin,
        UserSubscription,
        m.TrainerSession,
        m.TrainerLlmLog,
        UserMastery,
        AnalyticsEvent,
        UserTaskMMR,
        RematchQueue,
        m.StudentWorkspaceFile,
        m.TaskCanvasDrawing,
        PlatformBugReport,
        UserConsent,
    ):
        model.query.filter_by(user_id=user_id).delete(synchronize_session=False)

    m.CallRequest.query.filter_by(created_by_user_id=user_id).delete(synchronize_session=False)

    ReferralCode.query.filter_by(creator_id=user_id).delete(synchronize_session=False)
    m.LessonMessage.query.filter_by(author_user_id=user_id).delete(synchronize_session=False)
    m.LessonTaskTeacherComment.query.filter_by(author_user_id=user_id).delete(synchronize_session=False)
    m.SubmissionComment.query.filter_by(author_id=user_id).delete(synchronize_session=False)

    m.StudentDiagnosticCheckpoint.query.filter_by(created_by_user_id=user_id).update(
        {'created_by_user_id': None},
        synchronize_session=False,
    )
    m.GroupStudent.query.filter_by(added_by_user_id=user_id).update(
        {'added_by_user_id': None},
        synchronize_session=False,
    )
    m.LearningTrajectory.query.filter_by(created_by_user_id=user_id).update(
        {'created_by_user_id': None},
        synchronize_session=False,
    )
    m.MaterialAsset.query.filter_by(owner_user_id=user_id).update(
        {'owner_user_id': None},
        synchronize_session=False,
    )
    m.LessonMaterialLink.query.filter_by(created_by_user_id=user_id).update(
        {'created_by_user_id': None},
        synchronize_session=False,
    )
    m.LessonRoomTemplate.query.filter_by(created_by_user_id=user_id).update(
        {'created_by_user_id': None},
        synchronize_session=False,
    )
    m.RecurringLessonSlot.query.filter_by(owner_user_id=user_id).update(
        {'owner_user_id': None},
        synchronize_session=False,
    )
    m.RubricTemplate.query.filter_by(owner_user_id=user_id).update(
        {'owner_user_id': None},
        synchronize_session=False,
    )
    m.GradebookEntry.query.filter_by(created_by_user_id=user_id).update(
        {'created_by_user_id': None},
        synchronize_session=False,
    )
    m.TheoryFeedback.query.filter_by(user_id=user_id).update(
        {'user_id': None},
        synchronize_session=False,
    )
    m.TheoryFeedbackHistory.query.filter_by(user_id=user_id).update(
        {'user_id': None},
        synchronize_session=False,
    )
    m.TheoryBlock.query.filter_by(author_id=user_id).update(
        {'author_id': None},
        synchronize_session=False,
    )
    m.TheoryGroup.query.filter_by(created_by=user_id).update(
        {'created_by': None},
        synchronize_session=False,
    )
    TelegramStartLead.query.filter_by(assigned_user_id=user_id).update(
        {'assigned_user_id': None},
        synchronize_session=False,
    )
    BotErrorReport.query.filter_by(user_id=user_id).update(
        {'user_id': None},
        synchronize_session=False,
    )
    BotErrorReport.query.filter_by(admin_user_id=user_id).update(
        {'admin_user_id': None},
        synchronize_session=False,
    )
    AuditLog.query.filter_by(user_id=user_id).update(
        {'user_id': None},
        synchronize_session=False,
    )

@students_bp.route('/students')
@login_required
def students_list():
    """V2 Route for student list rendering sandbox/students.html layout."""
    return redirect(url_for('main.dashboard', **request.args))


@students_bp.route('/student/<int:student_id>/telegram/link-request', methods=['POST'])
@login_required
def student_telegram_link_request(student_id: int):
    """Админ запрашивает у ученика подтверждение ручной привязки Telegram."""
    if not (current_user.is_admin() or current_user.is_creator()):
        from flask import abort
        abort(403)

    student = Student.query.get_or_404(student_id)
    student_user = _get_student_user_for_scope(student)
    if not student_user:
        flash('У ученика нет связанного аккаунта платформы.', 'error')
        return redirect(url_for('students.student_profile', student_id=student_id))

    tg_username = _normalize_tg_username(request.form.get('telegram_username'))
    if not tg_username:
        flash('Укажи Telegram-тег ученика, например @username.', 'error')
        return redirect(url_for('students.student_profile', student_id=student_id))

    lead = TelegramStartLead.query.filter(func.lower(TelegramStartLead.telegram_username) == tg_username).first()
    target_chat_id = getattr(lead, 'telegram_chat_id', None)
    if not target_chat_id:
        existing_profile = UserProfile.query.filter(
            func.lower(UserProfile.telegram_id).in_((tg_username, f'@{tg_username}'))
        ).filter(UserProfile.telegram_chat_id.isnot(None)).first()
        if existing_profile:
            existing_user = getattr(existing_profile, 'user', None)
            if existing_user and getattr(existing_user, 'is_active', True):
                target_chat_id = getattr(existing_profile, 'telegram_chat_id', None)
            else:
                existing_profile.telegram_chat_id = None
                existing_profile.telegram_id = None
                existing_profile.telegram_link_code = None
                existing_profile.telegram_link_code_expires = None
                existing_profile.telegram_link_token = None
                existing_profile.telegram_link_token_expires = None
                db.session.commit()
                existing_profile = None
        target_chat_id = getattr(existing_profile, 'telegram_chat_id', None)

    if not target_chat_id:
        flash('Не могу написать этому Telegram: ученик должен сначала открыть бота BooStudy и нажать /start.', 'error')
        return redirect(url_for('students.student_profile', student_id=student_id))

    admin_profile = UserProfile.query.filter_by(user_id=current_user.id).first()
    admin_chat_id = getattr(admin_profile, 'telegram_chat_id', None)
    if not admin_chat_id:
        flash('Сначала привяжи Telegram к своему аккаунту, чтобы получить обратную связь о подтверждении.', 'error')
        return redirect(url_for('students.student_profile', student_id=student_id))

    student_profile = UserProfile.query.filter_by(user_id=student_user.id).first()
    if not student_profile:
        student_profile = UserProfile(user_id=student_user.id)
        db.session.add(student_profile)
        db.session.flush()

    student_profile.telegram_id = f'@{tg_username}'
    student.telegram = f'@{tg_username}'
    student.telegram_username = tg_username
    db.session.commit()

    from app.telegram.notifications import send_telegram_message

    admin_name = getattr(current_user, 'username', None) or 'администратор'
    msg = (
        '🔗 <b>Запрос на привязку Telegram к BooStudy</b>\n\n'
        f'Аккаунт на платформе: <b>{student.name}</b>\n'
        f'Запросил: <b>{admin_name}</b>\n\n'
        'Если это твой аккаунт BooStudy, подтверди связь кнопкой ниже.'
    )
    markup = {'inline_keyboard': [[{
        'text': '✅ Подтвердить привязку',
        'callback_data': f'admin_link_confirm:{student_profile.profile_id}:{current_user.id}',
    }]]}
    result = send_telegram_message(int(target_chat_id), msg, reply_markup=markup)
    if result and result.get('ok'):
        flash(f'Запрос на привязку отправлен @{tg_username}.', 'success')
    else:
        flash('Не удалось отправить запрос в Telegram. Проверь тег и что ученик писал боту.', 'error')
    return redirect(url_for('students.student_profile', student_id=student_id))


@students_bp.route('/student/<int:student_id>/telegram/unlink', methods=['POST'])
@login_required
def student_telegram_unlink(student_id: int):
    """Админская отвязка Telegram без подтверждения ученика."""
    if not (current_user.is_admin() or current_user.is_creator()):
        from flask import abort
        abort(403)

    student = Student.query.get_or_404(student_id)
    student_user = _get_student_user_for_scope(student)
    if not student_user:
        flash('У ученика нет связанного аккаунта платформы.', 'error')
        return redirect(url_for('students.student_profile', student_id=student_id))

    profile = UserProfile.query.filter_by(user_id=student_user.id).first()
    if not profile or (not profile.telegram_chat_id and not profile.telegram_id):
        flash('Telegram у ученика уже не привязан.', 'info')
        return redirect(url_for('students.student_profile', student_id=student_id))

    profile.telegram_chat_id = None
    profile.telegram_id = None
    profile.telegram_link_code = None
    profile.telegram_link_code_expires = None
    profile.telegram_link_token = None
    profile.telegram_link_token_expires = None
    student.telegram = None
    student.telegram_username = None
    db.session.commit()
    flash('Telegram отвязан от аккаунта ученика.', 'success')
    return redirect(url_for('students.student_profile', student_id=student_id))

@students_bp.route('/student/new', methods=['GET', 'POST'])
@login_required
def student_new():
    """Создание нового студента"""
    if not (current_user.is_admin() or current_user.is_creator()):
        from flask import abort
        abort(403)

    form = StudentForm()

    if form.validate_on_submit():
        try:
            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return redirect(url_for('students.student_new'))

            school_class_value = normalize_school_class(form.school_class.data)
            goal_text_value = form.goal_text.data.strip() if (form.goal_text.data and form.goal_text.data.strip()) else None
            programming_language_value = form.programming_language.data.strip() if (form.programming_language.data and form.programming_language.data.strip()) else None
            
            student = Student(
                name=form.name.data,
                platform_id=platform_id,
                target_score=form.target_score.data,
                deadline=form.deadline.data,
                diagnostic_level=form.diagnostic_level.data,
                preferences=form.preferences.data,
                strengths=form.strengths.data,
                weaknesses=form.weaknesses.data,
                overall_rating=form.overall_rating.data,
                description=form.description.data,
                notes=form.notes.data,
                category=form.category.data if form.category.data else None,
                school_class=school_class_value,
                goal_text=goal_text_value,
                programming_language=programming_language_value
            )
            
            if not platform_id:
                assign_platform_id_if_needed(student)
            
            db.session.add(student)
            db.session.commit()
            
            try:
                audit_logger.log(
                    action='create_student',
                    status='success',
                    metadata={
                        'name': student.name,
                        'platform_id': student.platform_id,
                        'category': student.category,
                        'school_class': student.school_class,
                        'goal_text': student.goal_text,
                        'programming_language': student.programming_language
                    }
                )
            except Exception as log_err:
                logger.warning(f"Ошибка при логировании создания ученика: {log_err}")
            
            flash(f'Ученик {student.name} успешно добавлен!', 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при добавлении ученика: {e}', exc_info=True)
            
            try:
                audit_logger.log_error(
                    action='create_student',
                    entity='Student',
                    error=str(e),
                    metadata={'form_data': {k: str(v) for k, v in form.data.items() if k != 'csrf_token'}}
                )
            except Exception as log_error:
                logger.error(f'Ошибка при логировании: {log_error}')
            
            flash(f'Ошибка при добавлении ученика: {str(e)}', 'error')
            return redirect(url_for('students.student_new'))

    if request.method == 'POST' and not form.validate_on_submit():
        logger.warning(f'Ошибки валидации формы при создании ученика: {form.errors}')

    return render_template('student_form.html', form=form, title='Добавить ученика', is_new=True)

import hashlib
import secrets
from datetime import timedelta
from core.db_models import InviteLink, TeacherStudent, moscow_now

def ensure_invitelinks_schema():
    """Фоновая проверка и добавление полей teacher_id, student_id, revoked_at в InviteLinks при необходимости."""
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        inv_table = 'InviteLinks' if 'InviteLinks' in table_names else ('invitelinks' if 'invitelinks' in table_names else None)
        if inv_table:
            cols = {c['name'] for c in inspector.get_columns(inv_table)}
            if 'teacher_id' not in cols:
                db.session.execute(text(f'ALTER TABLE "{inv_table}" ADD COLUMN teacher_id INTEGER'))
                db.session.commit()
            if 'student_id' not in cols:
                db.session.execute(text(f'ALTER TABLE "{inv_table}" ADD COLUMN student_id INTEGER'))
                db.session.commit()
            if 'revoked_at' not in cols:
                col_type = 'TIMESTAMP' if db.engine.name == 'postgresql' else 'DATETIME'
                db.session.execute(text(f'ALTER TABLE "{inv_table}" ADD COLUMN revoked_at {col_type}'))
                db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

@students_bp.route('/api/teacher/invites/student', methods=['POST'])
@students_bp.route('/api/teacher/invites/generate', methods=['POST'])
@students_bp.route('/api/teacher/generate_invite', methods=['POST'])
@login_required
def generate_student_invite_api():
    """Генерация безопасной токен-ссылки приглашения для нового ученика"""
    if not (current_user.is_tutor() or current_user.is_admin()):
        return jsonify({'status': 'error', 'message': 'Доступ запрещён'}), 403

    ensure_invitelinks_schema()

    try:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        expires_at = moscow_now() + timedelta(days=7)

        invite = InviteLink(
            token_hash=token_hash,
            email='',
            role='student',
            teacher_id=current_user.id,
            created_by_user_id=current_user.id,
            expires_at=expires_at
        )
        db.session.add(invite)
        db.session.commit()

        host = request.host_url.rstrip('/')
        invite_url = f"{host}/register/student/{raw_token}"

        return jsonify({
            'status': 'success',
            'success': True,
            'token': raw_token,
            'invite_code': raw_token,
            'invite_url': invite_url,
            'expires_at': expires_at.strftime('%d.%m.%Y %H:%M'),
            'message': 'Ссылка-приглашение для ученика успешно создана'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating student invite: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@students_bp.route('/api/teacher/invites/parent', methods=['POST'])
@login_required
def generate_parent_invite_api():
    """Генерация безопасной токен-ссылки приглашения для родителя конкретного ученика"""
    if not (current_user.is_tutor() or current_user.is_admin()):
        return jsonify({'status': 'error', 'message': 'Доступ запрещён'}), 403

    data = request.get_json(silent=True) or request.form or {}
    student_param = data.get('student_id')
    if not student_param:
        return jsonify({'status': 'error', 'message': 'Укажите ID ученика'}), 400

    student = Student.query.get(student_param)
    if not student:
        student = Student.query.filter_by(user_id=student_param).first()
    if not student:
        return jsonify({'status': 'error', 'message': 'Ученик не найден'}), 404

    from app.utils.relationship_scope import can_user_access_student
    if not can_user_access_student(current_user, student_user_id=student.user_id, student_platform_id=student.student_id):
        return jsonify({'status': 'error', 'message': 'У вас нет доступа к этому ученику'}), 403

    ensure_invitelinks_schema()

    try:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        expires_at = moscow_now() + timedelta(days=7)

        invite = InviteLink(
            token_hash=token_hash,
            email='',
            role='parent',
            student_id=student.student_id,
            teacher_id=current_user.id,
            created_by_user_id=current_user.id,
            expires_at=expires_at
        )
        db.session.add(invite)
        db.session.commit()

        host = request.host_url.rstrip('/')
        invite_url = f"{host}/register/parent/{raw_token}"

        return jsonify({
            'status': 'success',
            'success': True,
            'token': raw_token,
            'invite_url': invite_url,
            'student_name': student.name,
            'expires_at': expires_at.strftime('%d.%m.%Y %H:%M'),
            'message': f'Ссылка-приглашение для родителя ученика {student.name} создана'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating parent invite: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@students_bp.route('/api/teacher/invites/revoke', methods=['POST'])
@login_required
def revoke_invite_api():
    """Отзыв токена приглашения"""
    data = request.get_json(silent=True) or request.form or {}
    invite_id = data.get('invite_id')
    token = data.get('token')

    invite = None
    if invite_id:
        invite = InviteLink.query.get(invite_id)
    elif token:
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        invite = InviteLink.query.filter_by(token_hash=token_hash).first()

    if not invite:
        return jsonify({'status': 'error', 'message': 'Приглашение не найдено'}), 404

    if invite.created_by_user_id != current_user.id and not current_user.is_admin():
        return jsonify({'status': 'error', 'message': 'Отказать в доступе'}), 403

    invite.revoke()
    db.session.commit()
    return jsonify({'status': 'success', 'success': True, 'message': 'Приглашение успешно отозвано'}), 200


@students_bp.route('/api/teacher/invites/list', methods=['GET'])
@login_required
def list_invites_api():
    """Список приглашений, созданных преподавателем"""
    if not (current_user.is_tutor() or current_user.is_admin()):
        return jsonify({'status': 'error', 'message': 'Доступ запрещён'}), 403

    invites = InviteLink.query.filter_by(created_by_user_id=current_user.id).order_by(InviteLink.created_at.desc()).limit(100).all()
    result = []
    for inv in invites:
        st_name = inv.student.name if inv.student else None
        result.append({
            'invite_id': inv.invite_id,
            'role': inv.role,
            'student_name': st_name,
            'is_valid': inv.is_valid,
            'used_at': inv.used_at.isoformat() if inv.used_at else None,
            'revoked_at': inv.revoked_at.isoformat() if inv.revoked_at else None,
            'expires_at': inv.expires_at.isoformat() if inv.expires_at else None,
            'created_at': inv.created_at.isoformat() if inv.created_at else None,
        })

    return jsonify({'status': 'success', 'invites': result}), 200


@students_bp.route('/student/<int:student_id>')
@students_bp.route('/students/<int:student_id>')
@students_bp.route('/teacher/students/<int:student_id>')
@login_required
def student_profile(student_id):
    """Профиль студента (V2 Sandbox Universal Profile)"""
    student = Student.query.get(student_id)
    if not student:
        student = Student.query.filter_by(user_id=student_id).first()
    
    if student and student.user_id:
        return redirect(url_for('main.universal_profile_view', user_id=student.user_id))
    
    if student:
        return redirect(url_for('students.teacher_student_dashboard', student_id=student.student_id))
        
    return redirect(url_for('main.universal_profile_view', user_id=student_id))


@students_bp.route('/student/<int:student_id>/dashboard')
@students_bp.route('/students/<int:student_id>/dashboard')
@login_required
def teacher_student_dashboard(student_id: int):
    """Дашборд ученика со стороны преподавателя/создателя."""
    student = _guard_student_access(student_id)
    student_user = _get_student_user_for_scope(student)
    
    now = moscow_now()
    active_lesson = Lesson.query.filter_by(student_id=student.student_id, status='in_progress').order_by(Lesson.lesson_date.desc()).first()
    upcoming_lesson = (
        Lesson.query
        .filter(Lesson.student_id == student.student_id, Lesson.status == 'planned', Lesson.lesson_date >= now)
        .order_by(Lesson.lesson_date.asc())
        .first()
    )

    recent_lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).limit(10).all()
    recent_submissions = Submission.query.filter_by(student_id=student.student_id).order_by(Submission.submitted_at.desc()).limit(10).all()

    family_ties = FamilyTie.query.filter_by(student_id=student_user.id).all() if student_user else []
    parents_count = len(family_ties)

    tutor_user = User.query.get(student.tutor_id) if getattr(student, 'tutor_id', None) else None
    student_profile_obj = UserProfile.query.filter_by(user_id=student_user.id).first() if student_user else None

    return render_template(
        'sandbox/teacher_dashboard.html',
        student=student,
        user=student_user,
        student_profile=student_profile_obj,
        active_lesson=active_lesson,
        upcoming_lesson=upcoming_lesson,
        recent_lessons=recent_lessons,
        recent_submissions=recent_submissions,
        parents_count=parents_count,
        tutor_user=tutor_user,
        active_page='student_dashboard'
    )


@students_bp.route('/student/<int:student_id>/balance', methods=['POST'])
@login_required
def student_update_balance(student_id: int):
    """Обновление баланса оплаченных уроков ученика из дашборда преподавателя."""
    if not (current_user.is_admin() or current_user.is_creator() or current_user.is_tutor() or current_user.role in ('teacher', 'tutor')):
        from flask import abort
        abort(403)

    student = _guard_student_access(student_id)
    try:
        new_balance = int(request.form.get('lessons_balance', 0))
        old_balance = student.lessons_balance or 0
        student.lessons_balance = new_balance
        db.session.commit()

        # Отправляем уведомление ученику при смене баланса
        if student.user_id:
            from app.telegram.notifications import notify_lesson_balance_changed
            notify_lesson_balance_changed(
                student_user_id=student.user_id,
                before=old_balance,
                after=new_balance,
                reason='Обновление преподавателем',
                source='manual'
            )
        flash(f'Баланс уроков ученика {student.name} успешно обновлен до {new_balance}!', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating student balance: {e}", exc_info=True)
        flash(f'Ошибка при обновлении баланса: {e}', 'error')

    return redirect(url_for('students.teacher_student_dashboard', student_id=student_id))


@students_bp.route('/student/<int:student_id>/chat')
@login_required
def student_chat(student_id: int):
    """Студенческий чат. Используем диалог LessonMessages по ближайшему/последнему уроку."""
    student = _guard_student_access(student_id)

    now = moscow_now()
    in_progress = None
    upcoming = None
    latest = None
    try:
        in_progress = Lesson.query.filter_by(student_id=student.student_id, status='in_progress').order_by(Lesson.lesson_date.desc()).first()
    except Exception:
        in_progress = None
    try:
        upcoming = (
            Lesson.query
            .filter(Lesson.student_id == student.student_id, Lesson.status == 'planned', Lesson.lesson_date >= now)
            .order_by(Lesson.lesson_date.asc())
            .first()
        )
    except Exception:
        upcoming = None
    try:
        latest = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).first()
    except Exception:
        latest = None

    lesson = in_progress or upcoming or latest
    if not lesson:
        flash('Пока нет уроков, к которым можно привязать чат.', 'info')
        return redirect(url_for('students.student_profile', student_id=student.student_id))

    student_user_obj = User.query.get(student.user_id) if getattr(student, 'user_id', None) else None
    student_profile_obj = UserProfile.query.filter_by(user_id=student_user_obj.id).first() if student_user_obj else None
    return render_template('student_chat.html', student=student, student_user=student_user_obj, lesson=lesson, active_page='student_profile')


@students_bp.route('/student/<int:student_id>/call-request', methods=['GET', 'POST'])
@login_required
def student_call_request(student_id: int):
    """Заявка ученика на созвон/консультацию."""
    student = _guard_student_access(student_id)

    if request.method == 'POST':
        try:
            validate_csrf(request.form.get('csrf_token') or request.headers.get('X-CSRFToken'))
        except CSRFError:
            flash('Ошибка безопасности. Обновите страницу и попробуйте снова.', 'error')
            return redirect(url_for('students.student_call_request', student_id=student.student_id))

        preferred_at = _parse_datetime_local(request.form.get('preferred_at'))
        message = (request.form.get('message') or '').strip()
        if len(message) > 4000:
            message = message[:4000]

        try:
            req_row = CallRequest(
                student_id=student.student_id,
                created_by_user_id=current_user.id,
                preferred_at=preferred_at,
                message=message or None,
                status='new',
            )
            db.session.add(req_row)
            db.session.commit()
            flash('Заявка отправлена. Наставник увидит её и предложит время.', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error("CallRequest create failed: %s", e, exc_info=True)
            flash('Не удалось отправить заявку. Попробуйте позже.', 'error')

        return redirect(url_for('students.student_call_request', student_id=student.student_id))

    recent = []
    try:
        recent = (
            CallRequest.query
            .filter_by(student_id=student.student_id)
            .order_by(CallRequest.created_at.desc(), CallRequest.id.desc())
            .limit(10)
            .all()
        )
    except Exception:
        recent = []

    student_user_obj = User.query.get(student.user_id) if getattr(student, 'user_id', None) else None
    return render_template('student_call_request.html', student=student, student_user=student_user_obj, recent_requests=recent, active_page='student_profile')


@students_bp.route('/student/<int:student_id>/info')
@login_required
def student_info(student_id: int):
    """Профиль ученика (карточка): данные, контакты, подписка, родители. Без уроков и ленты."""
    student = Student.query.options(db.joinedload(Student.user)).get_or_404(student_id)
    if not _can_access_student(student):
        from flask import abort
        abort(403)
    if current_user.is_student():
        me_student = Student.query.filter_by(user_id=current_user.id).first()
        if not me_student:
            cand = Student.query.get(current_user.id)
            if cand and getattr(cand, 'user_id', None) is None:
                me_student = cand
        if me_student and me_student.student_id != student_id:
            return redirect(url_for('students.student_info', student_id=me_student.student_id))
    student_user_obj = User.query.get(student.user_id) if getattr(student, 'user_id', None) else None
    student_profile_obj = UserProfile.query.filter_by(user_id=student_user_obj.id).first() if student_user_obj else None
    student_subscription = None
    try:
        if student_user_obj:
            student_subscription = get_effective_access_for_user(student_user_obj.id)
    except Exception:
        student_subscription = None
    parents_info = []
    try:
        can_see_parents = (
            getattr(current_user, 'is_tutor', None) and current_user.is_tutor()
        ) or (
            getattr(current_user, 'is_admin', None) and current_user.is_admin()
        ) or (
            getattr(current_user, 'is_creator', None) and current_user.is_creator()
        )
        if can_see_parents and student_user_obj:
            family_ties = get_family_ties_for_student(student_user_obj.id, include_pending=False)
            for tie in family_ties:
                try:
                    parent_user = User.query.get(tie.parent_id)
                    if parent_user:
                        parent_profile = UserProfile.query.filter_by(user_id=parent_user.id).first()
                        if parent_profile:
                            name = f"{parent_profile.first_name or ''} {parent_profile.last_name or ''}".strip()
                            if not name:
                                name = parent_user.username
                            parents_info.append({
                                'name': name,
                                'phone': parent_profile.phone,
                                'telegram_id': parent_profile.telegram_id,
                            })
                except Exception:
                    continue
    except Exception:
        pass
    tutors_list = []
    if student_user_obj:
        try:
            enrollments = Enrollment.query.filter_by(student_id=student_user_obj.id).options(
                db.joinedload(Enrollment.tutor)
            ).all()
            tutors_list = [e.tutor for e in enrollments if getattr(e, 'tutor', None)]
        except Exception:
            pass
    return render_template(
        'student_info.html',
        student=student,
        student_user=student_user_obj,
        student_profile=student_profile_obj,
        student_subscription=student_subscription,
        tutors_list=tutors_list,
        parents_info=parents_info,
    )


@students_bp.route('/student/<int:student_id>/plan')
@login_required
def student_learning_plan(student_id: int):
    """Учебный план/траектория ученика (просмотр для ученика/родителя, редактирование для преподавателя)."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'plan.view'):
        from flask import abort
        abort(403)

    is_teacher_actor = (not current_user.is_student()) and (not current_user.is_parent())
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    can_edit = is_teacher_actor and (has_permission(current_user, 'plan.edit') or is_tutor_actor)

    items = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).order_by(
        StudentLearningPlanItem.priority.desc(),
        StudentLearningPlanItem.due_date.asc(),
        StudentLearningPlanItem.item_id.desc(),
    ).all()

    topics = []
    modules = []
    if can_edit:
        topics = Topic.query.order_by(Topic.name.asc()).all()
        modules = (
            TrajectoryModule.query.join(LearningTrajectory, TrajectoryModule.course_id == LearningTrajectory.course_id)
            .filter(LearningTrajectory.student_id == student.student_id)
            .order_by(TrajectoryModule.order_index.asc(), TrajectoryModule.module_id.asc())
            .all()
        )

    status_counts = {'planned': 0, 'in_progress': 0, 'done': 0, 'failed': 0}
    for it in items:
        key = (it.status or 'planned').strip().lower()
        if key not in status_counts:
            key = 'planned'
        status_counts[key] += 1

    return render_template(
        'student_learning_plan.html',
        student=student,
        items=items,
        topics=topics,
        modules=modules,
        can_edit=can_edit,
        status_counts=status_counts,
    )


@students_bp.route('/student/<int:student_id>/plan/items/create', methods=['POST'])
@login_required
def student_learning_plan_item_create(student_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название пункта траектории обязательно.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    status = (request.form.get('status') or 'planned').strip().lower()
    if status not in {'planned', 'in_progress', 'done', 'failed'}:
        status = 'planned'

    due_date = _parse_datetime_local(request.form.get('due_date'))
    priority = request.form.get('priority', type=int) or 0
    notes = (request.form.get('notes') or '').strip() or None
    topic_id = request.form.get('topic_id', type=int)
    course_module_id = request.form.get('course_module_id', type=int)

    parent_id = request.form.get('parent_id', type=int)
    item = StudentLearningPlanItem(
        student_id=student.student_id,
        title=title,
        status=status,
        due_date=due_date,
        priority=priority,
        notes=notes,
        topic_id=topic_id or None,
        course_module_id=course_module_id or None,
        created_by_user_id=current_user.id,
        parent_id=parent_id or None,
    )
    db.session.add(item)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_create', entity='StudentLearningPlanItem', error=str(e))
        flash('Не удалось добавить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_create',
            entity='StudentLearningPlanItem',
            entity_id=item.item_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'title': item.title,
                'status': item.status,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'priority': item.priority,
            },
        )
    except Exception:
        pass
    flash('Пункт траектории добавлен.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/update', methods=['POST'])
@login_required
def student_learning_plan_item_update(student_id: int, item_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название пункта траектории обязательно.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    status = (request.form.get('status') or 'planned').strip().lower()
    if status not in {'planned', 'in_progress', 'done', 'failed'}:
        status = 'planned'

    item.title = title
    item.status = status
    item.due_date = _parse_datetime_local(request.form.get('due_date'))
    item.priority = request.form.get('priority', type=int) or 0
    item.notes = (request.form.get('notes') or '').strip() or None
    item.topic_id = request.form.get('topic_id', type=int) or None
    item.course_module_id = request.form.get('course_module_id', type=int) or None
    item.parent_id = request.form.get('parent_id', type=int) or None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_update', entity='StudentLearningPlanItem', entity_id=item.item_id, error=str(e))
        flash('Не удалось обновить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_update',
            entity='StudentLearningPlanItem',
            entity_id=item.item_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'title': item.title,
                'status': item.status,
                'due_date': item.due_date.isoformat() if item.due_date else None,
                'priority': item.priority,
            },
        )
    except Exception:
        pass
    flash('Пункт траектории обновлён.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/delete', methods=['POST'])
@login_required
def student_learning_plan_item_delete(student_id: int, item_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()
    meta = {'student_id': student.student_id, 'title': item.title, 'status': item.status}
    db.session.delete(item)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='plan_item_delete', entity='StudentLearningPlanItem', entity_id=item_id, error=str(e))
        flash('Не удалось удалить пункт траектории.', 'danger')
        return redirect(url_for('students.student_learning_plan', student_id=student.student_id))

    try:
        audit_logger.log(
            action='plan_item_delete',
            entity='StudentLearningPlanItem',
            entity_id=item_id,
            status='success',
            metadata=meta,
        )
    except Exception:
        pass
    flash('Пункт траектории удалён.', 'success')
    return redirect(url_for('students.student_learning_plan', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/coords', methods=['POST'])
@login_required
def student_learning_plan_item_coords(student_id: int, item_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)
        
    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()
    data = request.get_json() or {}
    item.x = data.get('x')
    item.y = data.get('y')
    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@students_bp.route('/student/<int:student_id>/plan/items/<int:item_id>/parent', methods=['POST'])
@login_required
def student_learning_plan_item_parent(student_id: int, item_id: int):
    """AJAX endpoint: save parent_id for map edge connections."""
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'plan.edit') or is_tutor_actor)):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    item = StudentLearningPlanItem.query.filter_by(item_id=item_id, student_id=student.student_id).first_or_404()
    data = request.get_json() or {}
    raw_parent = data.get('parent_id')
    if raw_parent is None or raw_parent == '' or raw_parent == 0:
        item.parent_id = None
    else:
        try:
            pid = int(raw_parent)
            # Validate parent belongs to same student
            parent_item = StudentLearningPlanItem.query.filter_by(item_id=pid, student_id=student.student_id).first()
            item.parent_id = parent_item.item_id if parent_item else None
        except (ValueError, TypeError):
            item.parent_id = None
    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@students_bp.route('/student/<int:student_id>/gradebook')
@login_required
def student_gradebook(student_id: int):
    """Единый журнал оценок: ученик/родитель смотрят, преподаватель редактирует."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    is_teacher_actor = (not current_user.is_student()) and (not current_user.is_parent())
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    can_edit = is_teacher_actor and (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)

    entries = (
        GradebookEntry.query
        .outerjoin(Submission, GradebookEntry.submission_id == Submission.submission_id)
        .outerjoin(Assignment, Submission.assignment_id == Assignment.assignment_id)
        .filter(
            GradebookEntry.student_id == student.student_id,
            db.or_(
                GradebookEntry.submission_id.is_(None),  # ручные записи
                Assignment.is_active == True,  # noqa: E712  скрываем архивные
            )
        )
        .order_by(GradebookEntry.created_at.desc(), GradebookEntry.entry_id.desc())
        .all()
    )

    lessons = []
    submissions = []
    if can_edit:
        lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).all()
        submissions = (
            Submission.query
            .join(Assignment, Submission.assignment_id == Assignment.assignment_id)
            .filter(
                Submission.student_id == student.student_id,
                Assignment.is_active == True,  # noqa: E712  не показываем архивные
            )
            .options(db.contains_eager(Submission.assignment))
            .order_by(Submission.assigned_at.desc())
            .all()
        )

    return render_template(
        'student_gradebook.html',
        student=student,
        entries=entries,
        can_edit=can_edit,
        lessons=lessons,
        submissions=submissions,
    )


@students_bp.route('/student/<int:student_id>/gradebook/create', methods=['POST'])
@login_required
def student_gradebook_create(student_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    kind = (request.form.get('kind') or 'manual').strip().lower()
    if kind not in {'manual', 'lesson', 'assignment'}:
        kind = 'manual'

    title = (request.form.get('title') or '').strip()
    category = (request.form.get('category') or '').strip().lower() or None
    comment = (request.form.get('comment') or '').strip() or None
    score = request.form.get('score', type=int)
    max_score = request.form.get('max_score', type=int)
    grade_text = (request.form.get('grade_text') or '').strip() or None
    weight = request.form.get('weight', type=int) or 1

    lesson_id = request.form.get('lesson_id', type=int) if kind == 'lesson' else None
    submission_id = request.form.get('submission_id', type=int) if kind == 'assignment' else None

    if not title:
        if kind == 'lesson' and lesson_id:
            l = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
            title = (l.topic or 'Урок') if l else 'Урок'
        elif kind == 'assignment' and submission_id:
            s = Submission.query.filter_by(submission_id=submission_id, student_id=student.student_id).first()
            title = (s.assignment.title if (s and s.assignment) else 'Работа') if s else 'Работа'

    if not title:
        flash('Название записи обязательно.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    entry = GradebookEntry(
        student_id=student.student_id,
        kind=kind,
        category=category,
        title=title,
        comment=comment,
        score=score,
        max_score=max_score,
        grade_text=grade_text,
        weight=weight,
        lesson_id=lesson_id,
        submission_id=submission_id,
        created_by_user_id=current_user.id,
    )
    db.session.add(entry)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_create', entity='GradebookEntry', error=str(e))
        flash('Не удалось добавить запись в журнал.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    if student.user_id:
        try:
            from app.telegram.notifications import notify_new_gradebook_entry
            parts = []
            if entry.score is not None:
                parts.append(f'Баллы: {entry.score}' + (f' / {entry.max_score}' if entry.max_score else ''))
            if entry.grade_text:
                parts.append(str(entry.grade_text))
            score_line = ' · '.join(parts) if parts else ''
            notify_new_gradebook_entry(
                student_user_id=int(student.user_id),
                student_id=int(student.student_id),
                entry_title=entry.title or 'Запись',
                score_text=score_line,
            )
        except Exception:
            logger.warning('notify_new_gradebook_entry after gradebook_create failed', exc_info=True)

    try:
        audit_logger.log(
            action='gradebook_create',
            entity='GradebookEntry',
            entity_id=entry.entry_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'kind': entry.kind,
                'category': entry.category,
                'title': entry.title,
                'score': entry.score,
                'max_score': entry.max_score,
                'grade_text': entry.grade_text,
                'weight': entry.weight,
                'lesson_id': entry.lesson_id,
                'submission_id': entry.submission_id,
            },
        )
    except Exception:
        pass
    flash('Запись добавлена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook/<int:entry_id>/update', methods=['POST'])
@login_required
def student_gradebook_update(student_id: int, entry_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    entry = GradebookEntry.query.filter_by(entry_id=entry_id, student_id=student.student_id).first_or_404()

    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Название записи обязательно.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    entry.title = title
    entry.category = (request.form.get('category') or '').strip().lower() or None
    entry.comment = (request.form.get('comment') or '').strip() or None
    entry.score = request.form.get('score', type=int)
    entry.max_score = request.form.get('max_score', type=int)
    entry.grade_text = (request.form.get('grade_text') or '').strip() or None
    entry.weight = request.form.get('weight', type=int) or 1

    if (entry.kind or '').lower() == 'lesson':
        lesson_id = request.form.get('lesson_id', type=int)
        if lesson_id:
            l = Lesson.query.filter_by(lesson_id=lesson_id, student_id=student.student_id).first()
            entry.lesson_id = l.lesson_id if l else None
        else:
            entry.lesson_id = None
    if (entry.kind or '').lower() == 'assignment':
        submission_id = request.form.get('submission_id', type=int)
        if submission_id:
            s = Submission.query.filter_by(submission_id=submission_id, student_id=student.student_id).first()
            entry.submission_id = s.submission_id if s else None
        else:
            entry.submission_id = None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_update', entity='GradebookEntry', entity_id=entry.entry_id, error=str(e))
        flash('Не удалось обновить запись в журнале.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    try:
        audit_logger.log(
            action='gradebook_update',
            entity='GradebookEntry',
            entity_id=entry.entry_id,
            status='success',
            metadata={
                'student_id': student.student_id,
                'kind': entry.kind,
                'category': entry.category,
                'title': entry.title,
                'score': entry.score,
                'max_score': entry.max_score,
                'grade_text': entry.grade_text,
                'weight': entry.weight,
                'lesson_id': entry.lesson_id,
                'submission_id': entry.submission_id,
            },
        )
    except Exception:
        pass
    flash('Запись обновлена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook/<int:entry_id>/delete', methods=['POST'])
@login_required
def student_gradebook_delete(student_id: int, entry_id: int):
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'gradebook.edit') or is_tutor_actor)):
        from flask import abort
        abort(403)

    entry = GradebookEntry.query.filter_by(entry_id=entry_id, student_id=student.student_id).first_or_404()
    meta = {
        'student_id': student.student_id,
        'kind': entry.kind,
        'category': entry.category,
        'title': entry.title,
        'score': entry.score,
        'max_score': entry.max_score,
        'grade_text': entry.grade_text,
        'weight': entry.weight,
        'lesson_id': entry.lesson_id,
        'submission_id': entry.submission_id,
    }
    db.session.delete(entry)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='gradebook_delete', entity='GradebookEntry', entity_id=entry_id, error=str(e))
        flash('Не удалось удалить запись из журнала.', 'danger')
        return redirect(url_for('students.student_gradebook', student_id=student.student_id))

    try:
        audit_logger.log(
            action='gradebook_delete',
            entity='GradebookEntry',
            entity_id=entry_id,
            status='success',
            metadata=meta,
        )
    except Exception:
        pass
    flash('Запись удалена.', 'success')
    return redirect(url_for('students.student_gradebook', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/gradebook.csv')
@login_required
def student_gradebook_export_csv(student_id: int):
    """Экспорт журнала ученика в CSV."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    entries = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
        GradebookEntry.created_at.asc(),
        GradebookEntry.entry_id.asc(),
    ).all()

    try:
        audit_logger.log(
            action='export_gradebook_csv',
            entity='Student',
            entity_id=student.student_id,
            status='success',
            metadata={'entries_count': len(entries)},
        )
    except Exception:
        pass

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['created_at', 'kind', 'category', 'title', 'score', 'max_score', 'grade_text', 'weight', 'comment'])
    for e in entries:
        w.writerow([
            e.created_at.isoformat() if e.created_at else '',
            e.kind or '',
            e.category or '',
            e.title or '',
            '' if e.score is None else e.score,
            '' if e.max_score is None else e.max_score,
            e.grade_text or '',
            e.weight if e.weight is not None else '',
            (e.comment or '').replace('\r', '').replace('\n', ' ').strip(),
        ])

    csv_bytes = buf.getvalue().encode('utf-8-sig')
    filename = f'gradebook-student-{student.student_id}.csv'
    return Response(
        csv_bytes,
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@students_bp.route('/student/<int:student_id>/gradebook.pdf')
@login_required
def student_gradebook_export_pdf(student_id: int):
    """Экспорт журнала ученика в PDF (через Playwright)."""
    student = _guard_student_access(student_id)
    if not has_permission(current_user, 'gradebook.view'):
        from flask import abort
        abort(403)

    entries = GradebookEntry.query.filter_by(student_id=student.student_id).order_by(
        GradebookEntry.created_at.asc(),
        GradebookEntry.entry_id.asc(),
    ).all()

    html = render_template('student_gradebook_print.html', student=student, entries=entries)
    filename = f'gradebook-student-{student.student_id}.pdf'

    try:
        from app.utils.pdf_export import html_to_pdf_bytes
        pdf_bytes = html_to_pdf_bytes(html)
    except Exception as e:
        logger.warning(f"PDF export not available, fallback to HTML: {e}")
        return Response(
            html,
            mimetype='text/html; charset=utf-8',
            headers={'Content-Disposition': f'inline; filename="{filename}.html"'}
        )

    try:
        audit_logger.log(
            action='export_gradebook_pdf',
            entity='Student',
            entity_id=student.student_id,
            status='success',
            metadata={'entries_count': len(entries)},
        )
    except Exception:
        pass

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@students_bp.route('/student/<int:student_id>/diagnostics')
@login_required
def student_diagnostics(student_id: int):
    """Диагностика ученика: слабые темы + сохранённые контрольные точки."""
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if not ((has_permission(current_user, 'plan.view') and has_permission(current_user, 'diagnostics.view')) or is_tutor_actor):
        from flask import abort
        abort(403)

    from app.students.stats_service import StatsService
    from app.models import StudentDiagnosticCheckpoint

    diag_course_id = request.args.get('course_id', type=int)
    if not diag_course_id:
        enrollment = StudentCourseEnrollment.query.filter_by(student_id=student.student_id, is_active=True).first()
        if enrollment:
            diag_course_id = enrollment.course_id

    stats = None
    metrics = {}
    problem_topics = []
    problem_tasks = []
    coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}
    try:
        stats = StatsService(student.student_id, course_id=diag_course_id)
        metrics = stats.get_summary_metrics()
        problem_topics = stats.get_problem_topics(threshold=60)
        try:
            problem_tasks = stats.get_problem_task_numbers(threshold=60, min_attempts=3, course_id=diag_course_id)
        except Exception:
            problem_tasks = []

        try:
            total = 0
            with_topics = 0
            uniq_topics = set()
            for _is_correct, _ratio, _weight, topics in stats._iter_scored_items():
                total += 1
                if topics:
                    with_topics += 1
                    for t in topics:
                        try:
                            name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
                        except Exception:
                            name = None
                        if name:
                            uniq_topics.add(str(name))
            coverage = {'scored_items': int(total), 'scored_with_topics': int(with_topics), 'unique_topics': int(len(uniq_topics))}
        except Exception:
            coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}
    except Exception as e:
        logger.warning(f"Failed to compute diagnostics for student {student.student_id}: {e}")
        metrics = {}
        problem_topics = []
        problem_tasks = []
        coverage = {'scored_items': 0, 'scored_with_topics': 0, 'unique_topics': 0}

    checkpoints = []
    try:
        checkpoints = StudentDiagnosticCheckpoint.query.filter_by(student_id=student.student_id).order_by(
            StudentDiagnosticCheckpoint.created_at.desc(),
            StudentDiagnosticCheckpoint.checkpoint_id.desc(),
        ).limit(50).all()
    except Exception:
        checkpoints = []

    can_save = (not current_user.is_student()) and (not current_user.is_parent()) and (has_permission(current_user, 'diagnostics.checkpoints') or is_tutor_actor)

    recommendations = []
    try:
        for t in problem_topics[:3]:
            recommendations.append({
                'topic': getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None),
                'plan': '2 урока по теме + 10 задач (с разбором ошибок)',
            })
    except Exception:
        recommendations = []

    return render_template(
        'student_diagnostics.html',
        student=student,
        metrics=metrics,
        problem_topics=problem_topics,
        problem_tasks=problem_tasks,
        coverage=coverage,
        recommendations=recommendations,
        checkpoints=checkpoints,
        can_save=can_save,
    )


@students_bp.route('/student/<int:student_id>/diagnostics/checkpoints/create', methods=['POST'])
@login_required
def student_diagnostics_checkpoint_create(student_id: int):
    """Сохранить контрольную точку диагностики (учитель/админ)."""
    student = _guard_student_access(student_id)
    is_tutor_actor = bool(getattr(current_user, 'is_tutor', None) and current_user.is_tutor())
    if current_user.is_student() or current_user.is_parent() or (not (has_permission(current_user, 'diagnostics.checkpoints') or is_tutor_actor)):
        from flask import abort
        abort(403)

    from app.students.stats_service import StatsService
    from app.models import StudentDiagnosticCheckpoint

    kind = (request.form.get('kind') or 'checkpoint').strip().lower()
    if kind not in {'baseline', 'checkpoint'}:
        kind = 'checkpoint'
    note = (request.form.get('note') or '').strip() or None

    metrics = None
    problem_topics = None
    recommendations = None
    try:
        stats = StatsService(student.student_id)
        metrics = stats.get_summary_metrics()
        problem_topics = stats.get_problem_topics(threshold=60)[:10]
        recs = []
        for t in problem_topics[:3]:
            name = getattr(t, 'name', None) or (t.get('name') if isinstance(t, dict) else None)
            if name:
                recs.append({'topic': name, 'plan': '2 урока по теме + 10 задач (с разбором ошибок)'})
        recommendations = recs
    except Exception as e:
        logger.warning(f"Failed to compute diagnostics snapshot for student {student.student_id}: {e}")

    cp = StudentDiagnosticCheckpoint(
        student_id=student.student_id,
        created_by_user_id=current_user.id,
        kind=kind,
        note=note,
        metrics=metrics,
        problem_topics=problem_topics,
        recommendations=recommendations,
    )
    db.session.add(cp)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='diagnostics_checkpoint_create', entity='StudentDiagnosticCheckpoint', error=str(e))
        flash('Не удалось сохранить контрольную точку.', 'danger')
        return redirect(url_for('students.student_diagnostics', student_id=student.student_id))

    try:
        audit_logger.log(action='diagnostics_checkpoint_create', entity='StudentDiagnosticCheckpoint', entity_id=cp.checkpoint_id, status='success', metadata={'student_id': student.student_id, 'kind': kind})
    except Exception:
        pass

    flash('Контрольная точка сохранена.', 'success')
    return redirect(url_for('students.student_diagnostics', student_id=student.student_id))


@students_bp.route('/student/<int:student_id>/statistics')
@login_required
def student_statistics(student_id):
    """Редирект на единую страницу статистики"""
    return redirect(url_for('students.student_analytics', student_id=student_id))
    
    lessons = Lesson.query.filter_by(student_id=student_id).options(
        db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
    ).all()
    
    task_stats = {}
    
    for lesson in lessons:
        for assignment_type in ['homework', 'classwork', 'exam']:
            assignments = get_sorted_assignments(lesson, assignment_type)
            weight = 2 if assignment_type == 'exam' else 1
            
            for lt in assignments:
                if not lt.task or not lt.task.task_number:
                    continue
                
                task_num = lt.task.task_number
                
                if task_num not in task_stats:
                    task_stats[task_num] = {
                        'auto_correct': 0, 
                        'auto_total': 0,
                        'manual_correct': 0, 
                        'manual_incorrect': 0,
                        'correct': 0,
                        'total': 0
                    }
                
                if lt.submission_correct is not None:
                    task_stats[task_num]['auto_total'] += weight
                    if lt.submission_correct:
                        task_stats[task_num]['auto_correct'] += weight
    
    manual_stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
    manual_stats_dict = {stat.task_number: stat for stat in manual_stats}
    
    logger.info(f"Автоматическая статистика для ученика {student_id}: {[(k, v['auto_correct'], v['auto_total']) for k, v in task_stats.items()]}")
    logger.info(f"Ручные изменения для ученика {student_id}: {[(s.task_number, s.manual_correct, s.manual_incorrect) for s in manual_stats]}")
    
    for task_num in list(task_stats.keys()):
        if task_num in manual_stats_dict:
            manual_stat = manual_stats_dict[task_num]
            task_stats[task_num]['manual_correct'] = manual_stat.manual_correct
            task_stats[task_num]['manual_incorrect'] = manual_stat.manual_incorrect
        
        task_stats[task_num]['correct'] = task_stats[task_num]['auto_correct'] + task_stats[task_num]['manual_correct']
        task_stats[task_num]['total'] = task_stats[task_num]['auto_total'] + task_stats[task_num]['manual_correct'] + task_stats[task_num]['manual_incorrect']
    
    for task_num, manual_stat in manual_stats_dict.items():
        if task_num not in task_stats:
            task_stats[task_num] = {
                'auto_correct': 0,
                'auto_total': 0,
                'correct': manual_stat.manual_correct,
                'total': manual_stat.manual_correct + manual_stat.manual_incorrect,
                'manual_correct': manual_stat.manual_correct,
                'manual_incorrect': manual_stat.manual_incorrect
            }
    
    logger.info(f"Итоговая статистика для ученика {student_id}: {[(k, v['correct'], v['total']) for k, v in task_stats.items()]}")
    
    chart_data = []
    for task_num in sorted(task_stats.keys()):
        stats = task_stats[task_num]
        if stats['total'] > 0:
            percent = round((stats['correct'] / stats['total']) * 100, 1)
            if percent < 40:
                color = '#ef4444'  # красный
            elif percent < 80:
                color = '#eab308'  # желтый
            else:
                color = '#22c55e'  # зеленый
            
            chart_data.append({
                'task_number': task_num,
                'percent': percent,
                'correct': stats['correct'],
                'total': stats['total'],
                'color': color,
                'manual_correct': stats.get('manual_correct', 0),
                'manual_incorrect': stats.get('manual_incorrect', 0)
            })
    
    return render_template('student_statistics.html', 
                         student=student, 
                         chart_data=chart_data)

@students_bp.route('/student/<int:student_id>/statistics/update', methods=['POST'])
@login_required
def update_statistics(student_id):
    """API endpoint для обновления ручной статистики с поддержкой разных режимов редактирования"""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    try:
        logger.info(f"Получен запрос на обновление статистики для ученика {student_id}")
        
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        
        logger.info(f"Данные запроса: {data}")
        
        if not data or 'task_number' not in data:
            logger.warning("Не указан номер задания в запросе")
            return jsonify({'success': False, 'error': 'Не указан номер задания'}), 400
        
        task_number = int(data['task_number'])
        edit_mode = data.get('mode', 'add').lower()
        stat_course_id = data.get('course_id', type=int) if hasattr(data, 'get') else None
        try:
            stat_course_id = int(data.get('course_id')) if data.get('course_id') else None
        except (TypeError, ValueError):
            stat_course_id = None
        
        if edit_mode not in ['add', 'set', 'subtract']:
            return jsonify({'success': False, 'error': 'Некорректный режим редактирования. Используйте: add, set или subtract'}), 400
        
        manual_correct_value = int(data.get('manual_correct', 0))
        manual_incorrect_value = int(data.get('manual_incorrect', 0))
        
        if edit_mode in ['add', 'subtract']:
            if manual_correct_value < 0 or manual_incorrect_value < 0:
                return jsonify({'success': False, 'error': 'Значения должны быть неотрицательными'}), 400
        
        stat_filter = {'student_id': student_id, 'task_number': task_number}
        if stat_course_id:
            stat_filter['course_id'] = stat_course_id
        stat = StudentTaskStatistics.query.filter_by(**stat_filter).first()
        
        old_correct = stat.manual_correct if stat else 0
        old_incorrect = stat.manual_incorrect if stat else 0
        
        if stat:
            if edit_mode == 'add':
                stat.manual_correct += manual_correct_value
                stat.manual_incorrect += manual_incorrect_value
            elif edit_mode == 'set':
                stat.manual_correct = manual_correct_value
                stat.manual_incorrect = manual_incorrect_value
            elif edit_mode == 'subtract':
                stat.manual_correct = max(0, stat.manual_correct - manual_correct_value)
                stat.manual_incorrect = max(0, stat.manual_incorrect - manual_incorrect_value)
            
            stat.updated_at = moscow_now()
            logger.info(f"Обновлена запись (режим {edit_mode}): task_number={task_number}, было: correct={old_correct}, incorrect={old_incorrect}, стало: correct={stat.manual_correct}, incorrect={stat.manual_incorrect}")
        else:
            if edit_mode == 'set':
                stat = StudentTaskStatistics(
                    student_id=student_id,
                    task_number=task_number,
                    course_id=stat_course_id,
                    manual_correct=manual_correct_value,
                    manual_incorrect=manual_incorrect_value
                )
            else:  # add или subtract
                stat = StudentTaskStatistics(
                    student_id=student_id,
                    task_number=task_number,
                    course_id=stat_course_id,
                    manual_correct=max(0, manual_correct_value if edit_mode == 'add' else -manual_correct_value),
                    manual_incorrect=max(0, manual_incorrect_value if edit_mode == 'add' else -manual_incorrect_value)
                )
            db.session.add(stat)
            logger.info(f"Создана новая запись (режим {edit_mode}): task_number={task_number}, correct={stat.manual_correct}, incorrect={stat.manual_incorrect}")
        
        db.session.commit()
        
        db.session.refresh(stat)
        
        logger.info(f"Статистика успешно обновлена: student_id={student_id}, task_number={task_number}, режим={edit_mode}")
        
        try:
            audit_logger.log(
                action='update_statistics',
                entity='StudentTaskStatistics',
                entity_id=stat.stat_id,
                status='success',
                metadata={
                    'student_id': student_id,
                    'student_name': student.name,
                    'task_number': task_number,
                    'edit_mode': edit_mode,
                    'manual_correct_old': old_correct,
                    'manual_incorrect_old': old_incorrect,
                    'manual_correct_new': stat.manual_correct,
                    'manual_incorrect_new': stat.manual_incorrect
                }
            )
        except Exception as log_err:
            logger.warning(f"Ошибка при логировании: {log_err}")
        
        response_data = {
            'success': True,
            'message': 'Статистика обновлена',
            'stat_id': stat.stat_id,
            'manual_correct': stat.manual_correct,
            'manual_incorrect': stat.manual_incorrect
        }
        
        logger.info(f"Отправка ответа: {response_data}")
        return jsonify(response_data), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Некорректные данные: {str(e)}'}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении статистики: {e}', exc_info=True)
        audit_logger.log_error(
            action='update_statistics',
            entity='StudentTaskStatistics',
            error=str(e)
        )
        return jsonify({'success': False, 'error': str(e)}), 500

@students_bp.route('/student/<int:student_id>/statistics/reset', methods=['POST'])
@login_required
def reset_statistics(student_id):
    """API endpoint для сброса ручных изменений статистики"""
    if current_user.is_student() or current_user.is_parent():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json()
        
        task_number = data.get('task_number')
        
        if task_number:
            stat = StudentTaskStatistics.query.filter_by(
                student_id=student_id,
                task_number=task_number
            ).first()
            
            if stat:
                db.session.delete(stat)
                db.session.commit()
                logger.info(f"Сброшена статистика для задания {task_number} ученика {student_id}")
                return jsonify({'success': True, 'message': 'Статистика сброшена'}), 200
            else:
                return jsonify({'success': False, 'error': 'Запись не найдена'}), 404
        else:
            stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
            count = len(stats)
            for stat in stats:
                db.session.delete(stat)
            db.session.commit()
            logger.info(f"Сброшена вся статистика для ученика {student_id} ({count} записей)")
            return jsonify({'success': True, 'message': f'Сброшено {count} записей статистики'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при сбросе статистики: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@students_bp.route('/student/<int:student_id>/analytics')
@login_required
def student_analytics(student_id):
    """Единая страница статистики и аналитики ученика с табами"""
    from app.auth.rbac_utils import get_user_scope
    
    try:
        student = Student.query.get_or_404(student_id)
    except Exception as e:
        logger.error(f"Error loading student {student_id}: {e}", exc_info=True)
        flash('Ошибка при загрузке данных ученика', 'danger')
        return redirect(url_for('main.dashboard'))

    if getattr(current_user, 'is_demo_user', False):
        from datetime import datetime, timedelta
        _now = datetime.utcnow()
        demo_trend_dates = []
        demo_trend_scores = []
        for w in range(12, 0, -1):
            d = _now - timedelta(days=w * 7)
            demo_trend_dates.append(d.strftime('%d.%m'))
            demo_trend_scores.append(round(55 + (12 - w) * 2 + (w % 3), 1))
        demo_chart_data = []
        for i in range(1, 28):
            pct = 70 + (i % 5) - 2
            pct = max(40, min(98, pct))
            color = '#ef4444' if pct < 40 else '#eab308' if pct < 80 else '#22c55e'
            demo_chart_data.append({
                'task_number': i, 'percent': round(pct, 1), 'correct': int(round(pct)), 'total': 100,
                'color': color, 'auto_correct': 0, 'auto_total': 0, 'manual_correct': 0, 'manual_incorrect': 0
            })
        charts_context = {
            'trend_dates': json.dumps(demo_trend_dates, ensure_ascii=False),
            'trend_scores': json.dumps(demo_trend_scores),
            'skill_labels': '[]',
            'skill_values': '[]',
            'attendance_labels': '[]', 'attendance_values': '[]',
            'heatmap_dates': '[]', 'heatmap_values': '[]', 'heatmap_statuses': '[]'
        }
        metrics_demo = {'current_gpa': 72, 'delta': 5, 'completed_lessons': 12, 'total_lessons': 20}
        gpa_demo = {'homework': 75, 'exam': 68}
        try:
            return render_template(
                'student_stats_unified.html',
                student=student,
                charts=charts_context,
                metrics=metrics_demo,
                gpa_by_type=gpa_demo,
                problem_topics=[],
                chart_data=demo_chart_data,
                punctuality={},
                lessons_late_count=0,
                can_edit=False,
                active_lesson=None,
                active_student=None,
                hide_skills_radar=True
            )
        except Exception as e:
            logger.error(f"Error rendering analytics for demo user {student_id}: {e}", exc_info=True)
            flash('Ошибка при отображении статистики', 'danger')
            return redirect(url_for('students.student_profile', student_id=student_id))

    try:
        scope = get_user_scope(current_user)
        if not scope['can_see_all']:
            student_user_id = getattr(student, 'user_id', None)
            if student_user_id is not None:
                if student_user_id not in scope['student_ids']:
                    flash('У вас нет доступа к статистике этого ученика.', 'danger')
                    return redirect(url_for('main.dashboard'))
            elif not scope['student_ids']:
                flash('У вас нет доступа к статистике этого ученика.', 'danger')
                return redirect(url_for('main.dashboard'))
    except Exception as e:
        logger.error(f"Error checking access for student {student_id}: {e}", exc_info=True)
        flash('Ошибка при проверке доступа', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        stats = StatsService(student_id)
        
        try:
            gpa_data = stats.get_gpa_trend(period_days=90)
        except Exception as e:
            logger.error(f"Error getting GPA trend: {e}", exc_info=True)
            gpa_data = {'dates': [], 'scores': []}
        
        try:
            skill_data = stats.get_skills_map()
        except Exception as e:
            logger.error(f"Error getting skills map: {e}", exc_info=True)
            skill_data = {'labels': [], 'values': []}
        
        try:
            metrics = stats.get_summary_metrics()
        except Exception as e:
            logger.error(f"Error getting summary metrics: {e}", exc_info=True)
            metrics = {}
        
        try:
            problem_topics = stats.get_problem_topics(threshold=60)
        except Exception as e:
            logger.error(f"Error getting problem topics: {e}", exc_info=True)
            problem_topics = []
        
        try:
            gpa_by_type = stats.get_gpa_by_type()
        except Exception as e:
            logger.error(f"Error getting GPA by type: {e}", exc_info=True)
            gpa_by_type = {}
        
        try:
            attendance_data = stats.get_attendance_pie()
        except Exception as e:
            logger.error(f"Error getting attendance pie: {e}", exc_info=True)
            attendance_data = {'labels': [], 'values': []}
        
        try:
            attendance_heatmap = stats.get_attendance_heatmap(weeks=52)
        except Exception as e:
            logger.error(f"Error getting attendance heatmap: {e}", exc_info=True)
            attendance_heatmap = {'dates': [], 'values': [], 'statuses': []}
        
        try:
            punctuality = stats.get_submission_punctuality()
        except Exception as e:
            logger.error(f"Error getting punctuality: {e}", exc_info=True)
            punctuality = {}
        try:
            lessons_late_count = stats.get_lessons_late_count()
        except Exception as e:
            logger.error(f"Error getting lessons late count: {e}", exc_info=True)
            lessons_late_count = 0
    except Exception as e:
        logger.error(f"Error initializing StatsService: {e}", exc_info=True)
        gpa_data = {'dates': [], 'scores': []}
        skill_data = {'labels': [], 'values': []}
        metrics = {}
        problem_topics = []
        gpa_by_type = {}
        attendance_data = {'labels': [], 'values': []}
        attendance_heatmap = {'dates': [], 'values': [], 'statuses': []}
        punctuality = {}
        lessons_late_count = 0
    
    try:
        lessons = Lesson.query.filter_by(student_id=student_id).options(
            db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
        ).all()
    except Exception as e:
        logger.error(f"Error loading lessons for student {student_id}: {e}", exc_info=True)
        lessons = []
    
    task_stats = {}
    try:
        for lesson in lessons:
            for assignment_type in ['homework', 'classwork', 'exam']:
                try:
                    assignments = get_sorted_assignments(lesson, assignment_type)
                except Exception as e:
                    logger.error(f"Error getting sorted assignments for lesson {lesson.lesson_id}, type {assignment_type}: {e}", exc_info=True)
                    continue
                weight = 2 if assignment_type == 'exam' else 1
                
                for lt in assignments:
                    if not lt.task or not lt.task.task_number:
                        continue
                    
                    task_num = lt.task.task_number
                    
                    if task_num not in task_stats:
                        task_stats[task_num] = {
                            'auto_correct': 0, 
                            'auto_total': 0,
                            'manual_correct': 0, 
                            'manual_incorrect': 0,
                            'correct': 0,
                            'total': 0
                        }
                    
                    if lt.submission_correct is not None:
                        task_stats[task_num]['auto_total'] += weight
                        if lt.submission_correct:
                            task_stats[task_num]['auto_correct'] += weight
    except Exception as e:
        logger.error(f"Error processing lessons for student {student_id}: {e}", exc_info=True)
    
    try:
        manual_stats = StudentTaskStatistics.query.filter_by(student_id=student_id).all()
        for ms in manual_stats:
            if ms.task_number in task_stats:
                task_stats[ms.task_number]['manual_correct'] = ms.manual_correct or 0
                task_stats[ms.task_number]['manual_incorrect'] = ms.manual_incorrect or 0
                task_stats[ms.task_number]['correct'] = task_stats[ms.task_number]['auto_correct'] + ms.manual_correct - (ms.manual_incorrect or 0)
                task_stats[ms.task_number]['total'] = task_stats[ms.task_number]['auto_total'] + ms.manual_correct + (ms.manual_incorrect or 0)
            else:
                task_stats[ms.task_number] = {
                    'auto_correct': 0,
                    'auto_total': 0,
                    'manual_correct': ms.manual_correct or 0,
                    'manual_incorrect': ms.manual_incorrect or 0,
                    'correct': ms.manual_correct - (ms.manual_incorrect or 0),
                    'total': (ms.manual_correct or 0) + (ms.manual_incorrect or 0)
                }
    except Exception as e:
        logger.error(f"Error loading manual stats for student {student_id}: {e}", exc_info=True)
    
    chart_data = []
    try:
        for task_num in sorted(task_stats.keys()):
            stats_data = task_stats[task_num]
            if stats_data['auto_total'] > 0 or stats_data.get('manual_correct', 0) > 0 or stats_data.get('manual_incorrect', 0) > 0:
                total = stats_data['auto_total'] + stats_data.get('manual_correct', 0) + stats_data.get('manual_incorrect', 0)
                correct = stats_data['auto_correct'] + stats_data.get('manual_correct', 0) - stats_data.get('manual_incorrect', 0)
                
                if total > 0:
                    percent = round((correct / total) * 100, 1)
                    if percent < 0:
                        percent = 0
                else:
                    percent = 0
                
                if percent < 40:
                    color = '#ef4444'
                elif percent < 80:
                    color = '#eab308'
                else:
                    color = '#22c55e'
                
                chart_data.append({
                    'task_number': task_num,
                    'percent': percent,
                    'correct': correct,
                    'total': total,
                    'color': color,
                    'auto_correct': stats_data.get('auto_correct', 0),
                    'auto_total': stats_data.get('auto_total', 0),
                    'manual_correct': stats_data.get('manual_correct', 0),
                    'manual_incorrect': stats_data.get('manual_incorrect', 0)
                })
    except Exception as e:
        logger.error(f"Error building chart_data for student {student_id}: {e}", exc_info=True)
        chart_data = []
    
    charts_context = {
        'trend_dates': json.dumps(gpa_data['dates'], ensure_ascii=False),
        'trend_scores': json.dumps(gpa_data['scores']),
        'skill_labels': json.dumps(skill_data['labels'], ensure_ascii=False),
        'skill_values': json.dumps(skill_data['values']),
        'attendance_labels': json.dumps(attendance_data['labels'], ensure_ascii=False),
        'attendance_values': json.dumps(attendance_data['values']),
        'heatmap_dates': json.dumps(attendance_heatmap['dates'], ensure_ascii=False),
        'heatmap_values': json.dumps(attendance_heatmap['values']),
        'heatmap_statuses': json.dumps(attendance_heatmap['statuses'], ensure_ascii=False)
    }
    
    try:
        can_edit = not (current_user.is_student() or current_user.is_parent())
    except Exception as e:
        logger.error(f"Error checking can_edit for student {student_id}: {e}", exc_info=True)
        can_edit = False
    
    try:
        return render_template('student_stats_unified.html',
                             student=student,
                             charts=charts_context,
                             metrics=metrics,
                             gpa_by_type=gpa_by_type,
                             problem_topics=problem_topics,
                             chart_data=chart_data,
                             punctuality=punctuality,
                             lessons_late_count=lessons_late_count,
                             can_edit=can_edit)
    except Exception as e:
        logger.error(f"Error rendering template for student {student_id}: {e}", exc_info=True)
        flash('Ошибка при отображении статистики', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

@students_bp.route('/student/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
def student_edit(student_id):
    """Редактирование студента"""
    student = Student.query.get_or_404(student_id)
    form = StudentForm(obj=student)
    form._student_id = student_id
    if request.method == 'GET':
        form.school_class.data = student.school_class if student.school_class else 0

    if form.validate_on_submit():
        try:
            platform_id = form.platform_id.data.strip() if form.platform_id.data else None
            if platform_id:
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student and existing_student.student_id != student_id:
                    flash(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})', 'error')
                    return render_template('student_form.html', form=form, title='Редактировать ученика',
                                         is_new=False, student=student)

            student.name = form.name.data
            student.platform_id = platform_id
            student.target_score = form.target_score.data
            student.deadline = form.deadline.data
            student.diagnostic_level = form.diagnostic_level.data
            student.preferences = form.preferences.data
            student.strengths = form.strengths.data
            student.weaknesses = form.weaknesses.data
            student.overall_rating = form.overall_rating.data
            student.description = form.description.data
            student.notes = form.notes.data
            student.category = form.category.data if form.category.data else None
            student.school_class = normalize_school_class(form.school_class.data)
            student.goal_text = form.goal_text.data.strip() if form.goal_text.data else None
            student.programming_language = form.programming_language.data.strip() if form.programming_language.data else None
            db.session.commit()
            
            audit_logger.log(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                status='success',
                metadata={
                    'name': student.name,
                    'platform_id': student.platform_id,
                    'category': student.category,
                    'school_class': student.school_class,
                    'goal_text': student.goal_text,
                    'programming_language': student.programming_language
                }
            )
            
            flash(f'Данные ученика {student.name} обновлены!', 'success')
            return redirect(url_for('students.student_profile', student_id=student.student_id))
        except Exception as e:
            db.session.rollback()
            logger.error(f'Ошибка при обновлении ученика {student_id}: {e}')
            
            audit_logger.log_error(
                action='update_student',
                entity='Student',
                entity_id=student_id,
                error=str(e)
            )
            
            flash(f'Ошибка при обновлении данных: {str(e)}', 'error')

    return render_template('student_form.html', form=form, title='Редактировать ученика',
                         is_new=False, student=student)

@students_bp.route('/student/<int:student_id>/delete', methods=['POST'])
@login_required
def student_delete(student_id):
    """Удаление студента (только creator/admin)"""
    if not (current_user.is_creator() or current_user.is_admin()):
        flash('У вас недостаточно прав для удаления учеников.', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        student = Student.query.get_or_404(student_id)
        name = student.name
        platform_id = student.platform_id
        category = student.category
        linked_user = student.user if student.user_id else None
        is_demo = linked_user and getattr(linked_user, 'is_demo_user', False)

        _delete_student_related_rows(student_id, linked_user.id if linked_user else None)

        db.session.delete(student)

        if is_demo and linked_user:
            _delete_user_related_rows(linked_user.id)
            db.session.delete(linked_user)

        db.session.commit()

        audit_logger.log(
            action='delete_student',
            entity='Student',
            entity_id=student_id,
            status='success',
            metadata={
                'name': name,
                'platform_id': platform_id,
                'category': category,
                'demo_user_deleted': is_demo,
            }
        )

        flash(f'Ученик {name} удалён из системы.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении ученика {student_id}: {e}', exc_info=True)

        try:
            audit_logger.log_error(
                action='delete_student',
                entity='Student',
                entity_id=student_id,
                error=str(e)
            )
        except Exception as log_error:
            logger.warning(f'Ошибка при логировании удаления ученика {student_id}: {log_error}')

        flash(f'Ошибка при удалении ученика: {str(e)}', 'error')
    next_url = (request.form.get('next') or request.args.get('next') or '').strip()
    if next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)

    return redirect(url_for('main.dashboard'))

@students_bp.route('/student/<int:student_id>/archive', methods=['POST'])
@login_required
def student_archive(student_id):
    """Архивирование/восстановление студента (только creator/admin)"""
    if not (current_user.is_creator() or current_user.is_admin()):
        flash('У вас недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    student = Student.query.get_or_404(student_id)
    student.is_active = not student.is_active
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise

    if student.is_active:
        flash(f'Ученик {student.name} восстановлен из архива.', 'success')
    else:
        flash(f'Ученик {student.name} перемещён в архив.', 'success')

    return redirect(url_for('main.dashboard'))


@students_bp.route('/students/delete-all-demo', methods=['POST'])
@login_required
def delete_all_demo():
    """Массовое удаление всех демо-учеников и связанных демо-пользователей"""
    if not (current_user.is_creator() or current_user.is_admin()):
        flash('У вас недостаточно прав.', 'danger')
        return redirect(url_for('main.dashboard'))

    try:
        demo_users = User.query.filter_by(is_demo_user=True).all()
        demo_user_ids = [u.id for u in demo_users]

        if not demo_user_ids:
            flash('Демо-учеников не найдено.', 'info')
            return redirect(url_for('main.dashboard'))

        demo_students = Student.query.filter(Student.user_id.in_(demo_user_ids)).all()
        demo_student_ids = [s.student_id for s in demo_students]
        deleted_count = len(demo_students)

        for sid in demo_student_ids:
            student = next((s for s in demo_students if s.student_id == sid), None)
            _delete_student_related_rows(sid, student.user_id if student else None)

        for uid in demo_user_ids:
            _delete_user_related_rows(uid)

        if demo_student_ids:
            Student.query.filter(Student.student_id.in_(demo_student_ids)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(demo_user_ids)).delete(synchronize_session=False)

        db.session.commit()

        audit_logger.log(
            action='delete_all_demo_students',
            entity='Student',
            entity_id=0,
            status='success',
            metadata={'deleted_count': deleted_count, 'demo_user_ids': demo_user_ids}
        )

        flash(f'Удалено демо-учеников: {deleted_count}.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при массовом удалении демо-учеников: {e}')
        flash(f'Ошибка при удалении: {str(e)}', 'error')

    return redirect(url_for('main.dashboard'))


@students_bp.route('/student/<int:student_id>/lesson/new', methods=['GET', 'POST'])
@login_required
def lesson_new(student_id):
    """Создание нового урока для студента"""
    if current_user.is_student() or current_user.is_parent():
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    if not has_permission(current_user, 'lesson.create'):
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    student = _guard_student_access(student_id)
    form = LessonForm()
    course_module_id = request.args.get('course_module_id', type=int)
    return_to = (request.args.get('return_to') or '').strip().lower()

    from app.models import Course
    courses = Course.query.filter_by(is_active=True).order_by(Course.id).all()
    form.exam_course_id.choices = [(0, '— Не выбрано —')] + [(c.id, c.title) for c in courses]
    enrollment = StudentCourseEnrollment.query.filter_by(student_id=student.student_id, is_active=True).first()
    if enrollment and not form.is_submitted():
        form.exam_course_id.data = enrollment.course_id

    if not form.is_submitted():
        creator_tz_name = effective_timezone_name(current_user)
        user_tz = 'tomsk' if 'tomsk' in creator_tz_name.lower() or 'asia/tomsk' in creator_tz_name.lower() else 'moscow'
        form.timezone.data = user_tz

        from datetime import datetime
        if user_tz == 'tomsk':
            form.lesson_date.data = datetime.now(TOMSK_TZ).replace(tzinfo=None)
        else:
            form.lesson_date.data = datetime.now(MOSCOW_TZ).replace(tzinfo=None)

    if course_module_id:
        try:
            from app.models import TrajectoryModule, LearningTrajectory
            module = TrajectoryModule.query.filter_by(module_id=course_module_id).first()
            if not module:
                flash('Модуль курса не найден. Урок будет создан без привязки к модулю.', 'warning')
                course_module_id = None
            else:
                course = LearningTrajectory.query.filter_by(course_id=module.course_id).first()
                if not course or course.student_id != student.student_id:
                    flash('Модуль курса не относится к этому ученику. Урок будет создан без привязки к модулю.', 'warning')
                    course_module_id = None
        except Exception:
            course_module_id = None

    if form.validate_on_submit():
        ensure_introductory_without_homework(form)
        
        lesson_date_local = form.lesson_date.data
        timezone = form.timezone.data

        if lesson_date_local.tzinfo is not None:
            lesson_date_local = lesson_date_local.replace(tzinfo=None)

        lesson_date_utc = parse_local_lesson_datetime(
            lesson_date_local.strftime('%Y-%m-%d'),
            lesson_date_local.strftime('%H:%M'),
            timezone,
        )
        
        selected_exam_course_id = form.exam_course_id.data if form.exam_course_id.data else None
        if selected_exam_course_id == 0:
            selected_exam_course_id = None

        lesson = Lesson(
            student_id=student_id,
            course_module_id=course_module_id,
            exam_course_id=selected_exam_course_id,
            lesson_type=form.lesson_type.data,
            lesson_date=lesson_date_utc,
            duration=form.duration.data,
            status=form.status.data,
            topic=form.topic.data,
            notes=form.notes.data,
            homework=form.homework.data,
            homework_status=form.homework_status.data
        )
        db.session.add(lesson)
        try:  # Пытаемся сохранить урок обычным способом
            db.session.commit()  # Коммитим вставку урока
        except Exception as e:  # Если упали (часто из‑за сбитого sequence lesson_id)
            db.session.rollback()  # Откатываем транзакцию перед повтором
            msg = str(e)  # Превращаем ошибку в строку для распознавания
            is_unique = ('psycopg2.errors.UniqueViolation' in msg) or ('duplicate key value violates unique constraint' in msg)  # Признак UniqueViolation на Postgres
            is_lesson_pk = ('Lessons_pkey' in msg) or ('lesson_id' in msg)  # Признак, что упали именно на PK уроков
            db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')  # Берём строку подключения
            is_pg = ('postgresql' in db_url) or ('postgres' in db_url)  # Определяем, что это PostgreSQL
            if is_pg and is_unique and is_lesson_pk:  # Если это именно сбитый sequence у Lessons
                try:  # Пытаемся починить sequence и повторить commit один раз
                    db.session.execute(text('SELECT setval(pg_get_serial_sequence(\'"Lessons"\', \'lesson_id\'), COALESCE((SELECT MAX("lesson_id") FROM "Lessons"), 0), true)'))  # Выравниваем sequence по MAX(lesson_id)
                    db.session.commit()  # Коммитим фиксацию sequence
                    db.session.add(lesson)  # Повторно добавляем объект урока в сессию
                    db.session.commit()  # Повторяем вставку урока
                except Exception as e2:  # Если не удалось починить/повторить
                    db.session.rollback()  # Откатываем
                    raise  # Пробрасываем реальную ошибку дальше
            else:  # Если это не sequence‑проблема — не маскируем её
                raise  # Пробрасываем реальную ошибку дальше

        try:
            if lesson.status == 'planned':
                if student.user_id:
                    recipient_tz = 'Europe/Moscow'
                    try:
                        if getattr(student, 'user', None):
                            recipient_tz = effective_timezone_name(student.user)
                    except Exception:
                        recipient_tz = 'Europe/Moscow'
                    date_dt = lesson_storage_to_local(lesson.lesson_date, recipient_tz)
                    date_str = date_dt.strftime('%d.%m.%Y %H:%M') if date_dt else (lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else '')
                    notify_user_by_id(
                        int(student.user_id),
                        f'📅 <b>Новый урок запланирован</b>\n\n{date_str}\n{(lesson.topic or "").strip() or "Без темы"}',
                        kind='lesson_scheduled',
                        reply_markup={'inline_keyboard': [[{'text': 'Открыть урок', 'url': _absolute_app_url(url_for('lessons.lesson_view', lesson_id=lesson.lesson_id))}]]},
                    )
                if current_user.is_authenticated:
                    creator_tz = effective_timezone_name(current_user)
                    creator_dt = lesson_storage_to_local(lesson.lesson_date, creator_tz)
                    creator_date_str = creator_dt.strftime('%d.%m.%Y %H:%M') if creator_dt else (lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else '')
                    if current_user.id != (student.user_id or current_user.id):
                        notify_user_by_id(
                            int(current_user.id),
                            f'📅 <b>Новый урок запланирован</b>\n\n{creator_date_str}\n{(lesson.topic or "").strip() or "Без темы"}',
                            kind='lesson_scheduled',
                            reply_markup={'inline_keyboard': [[{'text': 'Открыть урок', 'url': _absolute_app_url(url_for('lessons.lesson_view', lesson_id=lesson.lesson_id))}]]},
                        )
        except Exception as e:
            logger.warning(f"Failed to notify about lesson_scheduled: {e}")
        
        audit_logger.log(
            action='create_lesson',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': student_id,
                'student_name': student.name,
                'lesson_type': lesson.lesson_type,
                'lesson_date': str(lesson.lesson_date),
                'status': lesson.status
            }
        )
        
        flash(f'Урок добавлен для ученика {student.name}!', 'success')
        next_action = request.form.get('next', '').strip()  # Куда перейти сразу после создания (ДЗ/КР/Проверочная)
        if next_action == 'homework':  # Домашнее задание — через раздел «Задания»
            return redirect(url_for('assignments.assignment_create', source='lesson', lesson_id=lesson.lesson_id, assignment_type='homework'))
        if next_action == 'classwork':  # Классная работа — в комнате урока
            return redirect(url_for('lessons.lesson_classwork_view', lesson_id=lesson.lesson_id, open_create=1))
        if next_action == 'exam':  # Проверочная — через раздел «Задания»
            return redirect(url_for('assignments.assignment_create', source='lesson', lesson_id=lesson.lesson_id, assignment_type='exam'))
        if return_to == 'course' and course_module_id:
            try:
                from app.models import TrajectoryModule
                module = TrajectoryModule.query.filter_by(module_id=course_module_id).first()
                if module:
                    return redirect(url_for('courses.course_view', course_id=module.course_id, _anchor=f'module-{course_module_id}'))
            except Exception:
                pass
        return redirect(url_for('students.student_profile', student_id=student_id))  # Дефолт: возвращаемся в профиль

    return render_template('lesson_form.html', form=form, student=student, title='Добавить урок', is_new=True)

@students_bp.route('/student/<int:student_id>/lesson/<int:lesson_id>/test-reminder', methods=['POST'])
@login_required
def lesson_test_reminder(student_id, lesson_id):
    """Manual diagnostic send for the 30-minute Telegram lesson reminder."""
    student = _guard_student_access(student_id)
    if current_user.is_student() or current_user.is_parent():
        flash('У вас недостаточно прав для тестовой отправки.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))
    if not (has_permission(current_user, 'lesson.create') or has_permission(current_user, 'lesson.edit') or current_user.is_creator() or current_user.is_admin()):
        flash('У вас недостаточно прав для тестовой отправки.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.student_id != student.student_id:
        flash('Урок не относится к этому ученику.', 'danger')
        return redirect(url_for('students.student_profile', student_id=student_id))

    try:
        from app.tasks.telegram_lesson_reminders import send_lesson_30min_reminder

        ok = send_lesson_30min_reminder(lesson, force=True)
        if ok:
            flash('Тестовое Telegram-напоминание отправлено.', 'success')
        else:
            flash('Не удалось отправить тестовое напоминание. Проверь привязку Telegram и включённые уведомления у ученика.', 'warning')
    except Exception as e:
        logger.warning('lesson_test_reminder failed lesson_id=%s: %s', lesson_id, e, exc_info=True)
        flash(f'Ошибка тестового напоминания: {e}', 'danger')

    return redirect(url_for('students.student_profile', student_id=student_id))

@students_bp.route('/student/<int:student_id>/lesson-mode')
@login_required
def lesson_mode(student_id):
    """Режим урока для студента"""
    student = Student.query.options(db.joinedload(Student.user)).get_or_404(student_id)
    now = moscow_now()
    
    all_lessons = Lesson.query.filter_by(student_id=student_id).order_by(Lesson.lesson_date.desc()).all()
    lessons = all_lessons
    
    current_lesson = next((l for l in all_lessons if l.status == 'in_progress'), None)
    planned_lessons = [l for l in all_lessons if l.status == 'planned' and l.lesson_date and l.lesson_date >= now]
    upcoming_lesson = sorted(planned_lessons, key=lambda x: x.lesson_date)[0] if planned_lessons else None

    return render_template('lesson_mode.html',
                         student=student,
                         lessons=lessons,
                         current_lesson=current_lesson,
                         upcoming_lesson=upcoming_lesson)

@students_bp.route('/student/<int:student_id>/start-lesson', methods=['POST'])
@login_required
def student_start_lesson(student_id):
    """Начало урока для студента"""
    student = Student.query.get_or_404(student_id)
    now = moscow_now()

    active_lesson = Lesson.query.filter_by(student_id=student_id, status='in_progress').first()
    if active_lesson:
        flash('Урок уже идет!', 'info')
        return redirect(url_for('students.student_profile', student_id=student_id))

    upcoming_lesson = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.status == 'planned',
        Lesson.lesson_date >= now
    ).order_by(Lesson.lesson_date).limit(1).first()

    if upcoming_lesson:
        upcoming_lesson.status = 'in_progress'
        lid = upcoming_lesson.lesson_id
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        try:
            from app.telegram.notifications import notify_lesson_started_for_lesson
            notify_lesson_started_for_lesson(int(lid))
        except Exception:
            logger.warning('notify_lesson_started_for_lesson after student_start_lesson failed', exc_info=True)
        flash(f'Урок начат!', 'success')
    else:
        new_lesson = Lesson(
            student_id=student_id,
            lesson_type='regular',
            lesson_date=moscow_now(),
            duration=60,
            status='in_progress',
            topic='Занятие'
        )
        db.session.add(new_lesson)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        try:
            from app.telegram.notifications import notify_lesson_started_for_lesson
            notify_lesson_started_for_lesson(int(new_lesson.lesson_id))
        except Exception:
            logger.warning('notify_lesson_started_for_lesson after student_start_lesson (new) failed', exc_info=True)
        flash(f'Новый урок создан и начат!', 'success')

    return redirect(url_for('students.student_profile', student_id=student_id))
