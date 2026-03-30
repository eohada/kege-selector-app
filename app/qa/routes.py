import base64
import os
import time
import uuid
from datetime import timedelta
from flask import Blueprint, session, redirect, url_for, request, flash, jsonify, render_template, current_app
from flask_login import login_required, current_user, login_user
from app.models import db
from app.models import (
    User, Student, Enrollment, Submission, Assignment, AssignmentTask,
    Lesson, LessonTask, UserSubscription, UserNotification, UserRole,
    RolePermission, moscow_now,
)
from core.db_models import (
    QATask, QAComment, FamilyTie,
    InviteLink, SchoolGroup, GroupStudent, MaintenanceMode, Answer,
)
from app.auth.permissions import ALL_PERMISSIONS, PERMISSION_CATEGORIES
from app.utils.cross_env_login import build_cross_env_token
from werkzeug.security import generate_password_hash
from flask import jsonify, current_app, session
from datetime import datetime, timedelta
import random

qa_bp = Blueprint('qa', __name__, url_prefix='/qa')

QA_POOL_USERNAMES = [
    'qa_pool_student_1', 'qa_pool_student_2', 'qa_pool_student_3',
    'qa_pool_tutor_1', 'qa_pool_tutor_2', 'qa_pool_tutor_3',
    'qa_pool_parent_1', 'qa_pool_parent_2', 'qa_pool_parent_3',
    'qa_pool_admin_1',
]

def _get_roles() -> list[str]:
    try:
        roles = getattr(current_user, 'roles', lambda: [])() or []
        base = getattr(current_user, 'role', None)
        if base and base not in roles:
            roles.append(base)
        return [r for r in roles if r]
    except Exception:
        base = getattr(current_user, 'role', None)
        return [base] if base else []


def require_qa(*allowed_roles: str, allow_impersonation: bool = True) -> bool:
    if not getattr(current_user, 'is_authenticated', False):
        return False
    if allow_impersonation and 'impersonator_id' in session:
        return True
    roles = set(_get_roles())
    return any(r in roles for r in allowed_roles)


def is_qa_authorized():
    """Проверка прав: Chief Tester, Creator, Chief Admin или уже в режиме подмены."""
    return require_qa('chief_tester', 'creator', 'chief_admin', 'tester', 'admin')

# ==========================================
# 1. IMPERSONATION (Тумблер ролей)
# ==========================================


def _ensure_qa_pool():
    """Создаёт пул из 3 учеников, 3 преподавателей, 3 родителей, 1 админа (is_qa_pool=True)."""
    from werkzeug.security import generate_password_hash
    pwd = generate_password_hash('123456')
    created = []
    for username in QA_POOL_USERNAMES:
        u = User.query.filter_by(username=username).first()
        if u:
            if not getattr(u, 'is_qa_pool', False):
                u.is_qa_pool = True
                db.session.add(u)
            continue
        if 'student' in username:
            u = User(role='student', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(Student(user_id=u.id, platform_id=username, name=username.replace('_', ' ').title()))
            created.append(username)
        elif 'tutor' in username:
            u = User(role='tutor', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
        elif 'parent' in username:
            u = User(role='parent', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
        else:
            u = User(role='admin', username=username, email=f'{username}@qa.local', password_hash=pwd, is_qa_pool=True)
            db.session.add(u)
            created.append(username)
    db.session.commit()
    return created


def _pool_student_profiles():
    _ensure_qa_pool()
    student_users = User.query.filter(
        User.username.in_([u for u in QA_POOL_USERNAMES if 'student' in u])
    ).order_by(User.username.asc()).all()
    user_ids = [u.id for u in student_users]
    student_profiles = Student.query.filter(Student.user_id.in_(user_ids)).all() if user_ids else []
    by_user = {s.user_id: s for s in student_profiles}
    return [(u, by_user.get(u.id)) for u in student_users if by_user.get(u.id)]




# ==========================================
# 2. ФАБРИКА ДАННЫХ (Mock Data)
# ==========================================

@qa_bp.route('/factory/tutor-students', methods=['POST'])
@login_required
def factory_tutor_students():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403

    try:
        uid = str(uuid.uuid4())[:6]
        from werkzeug.security import generate_password_hash
        default_pwd = generate_password_hash('123456')
        
        tutor = User(role='tutor', username=f'mock_tutor_{uid}', email=f'mock_tutor_{uid}@test.com', password_hash=default_pwd)
        db.session.add(tutor)
        db.session.flush() # get ID
        
        student1 = User(role='student', username=f'mock_stud1_{uid}', email=f'mock_stud1_{uid}@test.com', password_hash=default_pwd)
        student2 = User(role='student', username=f'mock_stud2_{uid}', email=f'mock_stud2_{uid}@test.com', password_hash=default_pwd)
        db.session.add_all([student1, student2])
        db.session.flush() 
        
        db.session.add(Student(user_id=student1.id, platform_id=f'{uid}1', name=f'Student 1 {uid}'))
        db.session.add(Student(user_id=student2.id, platform_id=f'{uid}2', name=f'Student 2 {uid}'))
        
        db.session.add(Enrollment(student_id=student1.id, tutor_id=tutor.id, subject='Math (Test)'))
        db.session.add(Enrollment(student_id=student2.id, tutor_id=tutor.id, subject='Math (Test)'))
        
        db.session.commit()
        return jsonify({'status': 'success', 'tutor_id': tutor.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==========================================
# 3. МАНИПУЛЯТОРЫ СТАТУСАМИ (State Overrides)
# ==========================================

@qa_bp.route('/manipulate/pass_assignment', methods=['POST'])
@login_required
def pass_assignment():
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403

    try:
        from app.models import Submission, Student
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
             return jsonify({'status': 'error', 'message': 'Текущий пользователь не является учеником (нет профиля Student)'})

        # Находим последнюю активную работу
        submission = Submission.query.filter(
            Submission.student_id == student.student_id,
            Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED'])
        ).order_by(Submission.created_at.desc()).first()

        if submission:
            submission.status = 'GRADED'
            submission.percentage = 100
            submission.total_score = submission.max_score or 100
            submission.teacher_feedback = '[QA God Mode] Авто-сдача на 100%'
            db.session.commit()
            return jsonify({'status': 'success', 'message': f'Работа ID {submission.submission_id} успешно сдана на 100%!'})
        
        return jsonify({'status': 'error', 'message': 'Нет активных работ для сдачи'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@qa_bp.route('/manipulate/pay_course', methods=['POST'])
@login_required
def pay_course():
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        sub = UserSubscription.query.filter_by(user_id=current_user.id).first()
        if sub:
            sub.status = 'active'
            sub.ends_at = moscow_now().replace(year=moscow_now().year + 1) if moscow_now().year else None
            db.session.add(sub)
        else:
            db.session.add(UserSubscription(user_id=current_user.id, status='active'))
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Имитация оплаты: подписка активна.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/god_mode_30d', methods=['POST'])
@login_required
def god_mode_30d():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        now = moscow_now()
        sub = UserSubscription.query.filter_by(user_id=current_user.id).order_by(UserSubscription.ends_at.desc().nullslast()).first()
        if sub:
            sub.status = 'active'
            sub.ends_at = now + timedelta(days=30)
            db.session.add(sub)
        else:
            sub = UserSubscription(user_id=current_user.id, status='active', ends_at=now + timedelta(days=30))
            db.session.add(sub)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Выдан God Mode на 30 дней.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


def _get_current_student_submission():
    """Последняя активная работа ученика (Submission)."""
    student = Student.query.filter_by(user_id=current_user.id).first()
    if not student:
        return None, None
    sub = Submission.query.filter(
        Submission.student_id == student.student_id,
        Submission.status.in_(['ASSIGNED', 'IN_PROGRESS', 'RETURNED', 'SUBMITTED', 'LATE'])
    ).order_by(Submission.updated_at.desc()).first()
    return student, sub


@qa_bp.route('/manipulate/fail_assignment', methods=['POST'])
@login_required
def fail_assignment():
    """Провалить текущее ДЗ (0 баллов / RETURNED) — проверка кнопки «Пересдать» и блока разбора."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        student, sub = _get_current_student_submission()
        if not student or not sub:
            return jsonify({'status': 'error', 'message': 'Нет активной работы для провала'})
        sub.status = 'RETURNED'
        sub.percentage = 0
        sub.total_score = 0
        sub.max_score = sub.max_score or 100
        sub.teacher_feedback = '[QA] Провал: 0 баллов для проверки пересдачи.'
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Работа #{sub.submission_id} помечена как провал (0%). Должна появиться кнопка «Пересдать».'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/pass_assignment_half', methods=['POST'])
@login_required
def pass_assignment_half():
    """Выполнить ДЗ наполовину (50%)."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        student, sub = _get_current_student_submission()
        if not student or not sub:
            return jsonify({'status': 'error', 'message': 'Нет активной работы'})
        max_s = sub.max_score or 100
        sub.status = 'GRADED'
        sub.percentage = 50
        sub.total_score = max_s // 2
        sub.max_score = max_s
        sub.teacher_feedback = '[QA] 50% для теста.'
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Работа сдана на 50%.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/reset_lesson_progress', methods=['POST'])
@login_required
def reset_lesson_progress():
    """Сбросить прогресс текущего урока — урок снова «не пройден»."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        student = Student.query.filter_by(user_id=current_user.id).first()
        if not student:
            return jsonify({'status': 'error', 'message': 'Текущий пользователь не ученик'})
        lesson = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date.desc()).first()
        if not lesson:
            return jsonify({'status': 'error', 'message': 'Нет уроков у этого ученика'})
        lesson.status = 'planned'
        lesson.homework_status = 'not_assigned'
        lesson.homework_result_percent = None
        lesson.review_summaries = None
        for lt in (lesson.homework_tasks or []):
            lt.status = 'pending'
            lt.student_submission = None
            lt.submission_correct = None
            lt.teacher_comment = None
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Урок «{lesson.topic or lesson.lesson_id}» сброшен. Можно снова проходить.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/expire_subscription', methods=['POST'])
@login_required
def expire_subscription():
    """Имитировать истечение подписки — проверка пэйвола."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        for sub in UserSubscription.query.filter_by(user_id=current_user.id).all():
            sub.status = 'expired'
            sub.ends_at = moscow_now()
            db.session.add(sub)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Подписка истекла. Должен появиться пэйвол.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/mock_notifications', methods=['POST'])
@login_required
def mock_notifications():
    """Накидать 5 тестовых уведомлений — проверка колокольчика."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        import random
        titles = ['Новое задание', 'Урок завтра', 'Проверка работы', 'Напоминание', 'Обновление курса']
        for i in range(5):
            n = UserNotification(
                user_id=current_user.id,
                kind='generic',
                title=random.choice(titles),
                body='Тестовое уведомление для проверки верстки колокольчика.',
                is_read=False,
            )
            db.session.add(n)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Добавлено 5 тестовых уведомлений.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/bulk_approve', methods=['POST'])
@login_required
def bulk_approve():
    """Одобрить все висящие ДЗ (преподаватель) — очередь проверки с высшим баллом."""
    if not require_qa('tutor', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from app.auth.rbac_utils import get_user_scope
        scope = get_user_scope(current_user)
        q = Submission.query.join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        q = q.filter(Submission.status.in_(['SUBMITTED', 'LATE']))
        if not scope.get('can_see_all'):
            q = q.filter(Assignment.created_by_id == current_user.id)
        subs = q.all()
        for sub in subs:
            sub.status = 'GRADED'
            sub.percentage = 100
            sub.total_score = sub.max_score or 100
            sub.teacher_feedback = '[QA] Bulk Approve.'
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Одобрено работ: {len(subs)}.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/bulk_reject', methods=['POST'])
@login_required
def bulk_reject():
    """Отклонить все висящие ДЗ с шаблонным комментарием."""
    if not require_qa('tutor', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from app.auth.rbac_utils import get_user_scope
        scope = get_user_scope(current_user)
        q = Submission.query.join(Assignment, Assignment.assignment_id == Submission.assignment_id)
        q = q.filter(Submission.status.in_(['SUBMITTED', 'LATE']))
        if not scope.get('can_see_all'):
            q = q.filter(Assignment.created_by_id == current_user.id)
        subs = q.all()
        msg = request.form.get('comment') or request.get_json(silent=True) or {}
        comment = msg.get('comment', '[QA] Массовый возврат на доработку.') if isinstance(msg, dict) else str(msg)
        for sub in subs:
            sub.status = 'RETURNED'
            sub.teacher_feedback = comment
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Возвращено работ: {len(subs)}.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/inject_submission', methods=['POST'])
@login_required
def inject_submission():
    """Подкинуть себе новое ДЗ на проверку (как будто ученик только что сдал)."""
    if not require_qa('tutor', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        from app.auth.rbac_utils import get_user_scope
        scope = get_user_scope(current_user)
        assigs = Assignment.query.filter(Assignment.created_by_id == current_user.id).limit(20).all()
        if not assigs:
            return jsonify({'status': 'error', 'message': 'Нет ни одной вашей работы (Assignment). Создайте работу и назначьте ученику.'})
        pool_students = Student.query.join(User, User.id == Student.user_id).filter(
            User.username.in_([u for u in QA_POOL_USERNAMES if 'student' in u])
        ).all()
        if not pool_students:
            return jsonify({'status': 'error', 'message': 'Нет учеников пула. Зайдите в /qa/pool.'})
        import random
        a = random.choice(assigs)
        s = random.choice(pool_students)
        existing = Submission.query.filter_by(assignment_id=a.assignment_id, student_id=s.student_id).first()
        if existing and (existing.status or '').upper() in ('SUBMITTED', 'LATE'):
            return jsonify({'status': 'success', 'message': 'Уже есть сданная работа в очереди.'})
        if existing:
            existing.status = 'SUBMITTED'
            existing.submitted_at = moscow_now()
            db.session.add(existing)
        else:
            sub = Submission(assignment_id=a.assignment_id, student_id=s.student_id, status='SUBMITTED', submitted_at=moscow_now())
            db.session.add(sub)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Подкинуто новое ДЗ в очередь. Обновите страницу проверки.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/generate_debtor', methods=['POST'])
@login_required
def generate_debtor():
    """Создает ученика-должника: минимум 3 просроченных ДЗ."""
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})

        user, student = pool[0]
        now = moscow_now().replace(tzinfo=None)
        created = 0
        for i in range(3):
            lesson_dt = now - timedelta(days=7 + i)
            lesson = Lesson(
                student_id=student.student_id,
                lesson_date=lesson_dt,
                duration=60,
                lesson_type='regular',
                status='planned',
                topic=f'[QA PRESET] Долг #{i + 1}'
            )
            db.session.add(lesson)
            db.session.flush()

            assignment = Assignment(
                title=f'[QA PRESET] ДЗ просрочено #{i + 1}',
                description='Сгенерировано пресетом "Сгенерировать должника"',
                assignment_type='homework',
                deadline=lesson_dt - timedelta(days=1),
                hard_deadline=False,
                created_by_id=current_user.id,
                lesson_id=lesson.lesson_id,
                is_active=True,
            )
            db.session.add(assignment)
            db.session.flush()

            submission = Submission(
                assignment_id=assignment.assignment_id,
                student_id=student.student_id,
                status='LATE',
                assigned_at=lesson_dt - timedelta(days=2),
                started_at=lesson_dt - timedelta(days=1, hours=4),
                submitted_at=lesson_dt - timedelta(hours=1),
                is_late=True,
            )
            db.session.add(submission)
            created += 1

        db.session.commit()
        return jsonify(
            {
                'status': 'success',
                'message': f'Готово: создан должник {user.username} с {created} просроченными ДЗ.',
                'next': {
                    'label': 'Открыть профиль должника',
                    'url': url_for('students.student_profile', student_id=student.student_id),
                }
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/overwhelm_reviews', methods=['POST'])
@login_required
def overwhelm_reviews():
    """Заполняет очередь проверки 20 работами."""
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})

        now = moscow_now().replace(tzinfo=None)
        statuses = ['SUBMITTED', 'LATE', 'NEEDS_MANUAL_REVIEW']
        created = 0
        for i in range(20):
            user, student = pool[i % len(pool)]
            status = statuses[i % len(statuses)]
            deadline = now - timedelta(hours=(i % 6) + 1) if status in ('LATE', 'NEEDS_MANUAL_REVIEW') else now + timedelta(hours=12)
            assignment = Assignment(
                title=f'[QA PRESET] Очередь ревью #{i + 1}',
                description='Сгенерировано пресетом "Завалить проверками"',
                assignment_type='homework',
                deadline=deadline,
                hard_deadline=False,
                created_by_id=current_user.id,
                is_active=True,
            )
            db.session.add(assignment)
            db.session.flush()

            submission = Submission(
                assignment_id=assignment.assignment_id,
                student_id=student.student_id,
                status=status,
                assigned_at=now - timedelta(days=1),
                started_at=now - timedelta(hours=8),
                submitted_at=now - timedelta(minutes=(i + 1) * 3),
                is_late=(status == 'LATE'),
            )
            db.session.add(submission)
            created += 1

        db.session.commit()
        return jsonify(
            {
                'status': 'success',
                'message': f'Готово: в очередь добавлено {created} работ.',
                'next': {
                    'label': 'Открыть очередь проверки',
                    'url': url_for('lessons.review_queue'),
                }
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/break_schedule', methods=['POST'])
@login_required
def break_schedule():
    """Создает коллизию: два урока на одно время для одного преподавателя."""
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        _ensure_qa_pool()
        tutor_user = User.query.filter(
            User.username.in_([u for u in QA_POOL_USERNAMES if 'tutor' in u])
        ).order_by(User.username.asc()).first()
        pool = _pool_student_profiles()
        if not tutor_user or len(pool) < 2:
            return jsonify({'status': 'error', 'message': 'Недостаточно данных в пуле QA'})

        student_pairs = pool[:2]
        for su, _ in student_pairs:
            if not Enrollment.query.filter_by(student_id=su.id, tutor_id=tutor_user.id).first():
                db.session.add(Enrollment(student_id=su.id, tutor_id=tutor_user.id, subject='QA schedule collision'))

        dt = (moscow_now() + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0, tzinfo=None)
        created_ids = []
        for _, sp in student_pairs:
            lesson = Lesson(
                student_id=sp.student_id,
                lesson_date=dt,
                duration=60,
                lesson_type='regular',
                status='planned',
                topic='[QA PRESET] Коллизия слотов',
            )
            db.session.add(lesson)
            db.session.flush()
            created_ids.append(lesson.lesson_id)

        db.session.commit()
        return jsonify(
            {
                'status': 'success',
                'message': f'Создана коллизия слотов (уроки #{created_ids[0]} и #{created_ids[1]} на {dt:%d.%m %H:%M}).',
                'next': {
                    'label': 'Открыть расписание',
                    'url': url_for('schedule.schedule'),
                }
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/tabula_rasa', methods=['POST'])
@login_required
def tabula_rasa():
    """Пресет: с чистого листа — стереть прогресс/оплаты/уведомления у всех 10 профилей пула."""
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        pool_users = User.query.filter(User.username.in_(QA_POOL_USERNAMES)).all()
        user_ids = [u.id for u in pool_users]
        student_ids = [s.student_id for s in Student.query.filter(Student.user_id.in_(user_ids)).all()]
        assignment_ids = [r[0] for r in db.session.query(Submission.assignment_id).filter(Submission.student_id.in_(student_ids)).distinct().all()] if student_ids else []
        deleted_subs = Submission.query.filter(Submission.student_id.in_(student_ids)).delete(synchronize_session=False) if student_ids else 0
        if assignment_ids:
            AssignmentTask.query.filter(AssignmentTask.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
            Assignment.query.filter(Assignment.assignment_id.in_(assignment_ids)).delete(synchronize_session=False)
        Assignment.query.filter(Assignment.title.ilike('[QA PRESET]%')).delete(synchronize_session=False)
        UserSubscription.query.filter(UserSubscription.user_id.in_(user_ids)).delete(synchronize_session=False)
        UserNotification.query.filter(UserNotification.user_id.in_(user_ids)).delete(synchronize_session=False)
        if student_ids:
            Lesson.query.filter(Lesson.student_id.in_(student_ids)).delete(synchronize_session=False)
        Enrollment.query.filter(
            Enrollment.student_id.in_(user_ids) | Enrollment.tutor_id.in_(user_ids)
        ).delete(synchronize_session=False)
        FamilyTie.query.filter(
            FamilyTie.student_id.in_(user_ids) | FamilyTie.parent_id.in_(user_ids)
        ).delete(synchronize_session=False)
        db.session.commit()
        return jsonify(
            {
                'status': 'success',
                'message': f'Tabula Rasa: очищены подписки, уведомления, уроки и сдачи для {len(pool_users)} профилей пула.',
                'next': {
                    'label': 'Открыть пул профилей',
                    'url': url_for('qa.pool'),
                }
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 3.0 PRESETS CATALOG 1–7 (best-effort)
# ==========================================

def _preset_forbidden():
    return jsonify({'error': 'Forbidden', 'status': 'error', 'message': 'Forbidden'}), 403


def _next(label: str, url: str | None):
    if not url:
        return None
    return {'label': label, 'url': url}


def _hash_invite_token(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@qa_bp.route('/manipulate/perfectionist_student', methods=['POST'])
@login_required
def preset_perfectionist_student():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})
        user, student = pool[0]
        now = moscow_now().replace(tzinfo=None)
        created = 0
        for i in range(3):
            a = Assignment(
                title=f'[QA PRESET] Perfectionist #{i+1}',
                description='[QA PRESET] Perfectionist student',
                assignment_type='homework',
                deadline=now + timedelta(days=7 - i),
                hard_deadline=False,
                created_by_id=current_user.id,
                is_active=True,
            )
            db.session.add(a)
            db.session.flush()
            sub = Submission(
                assignment_id=a.assignment_id,
                student_id=student.student_id,
                status='GRADED',
                assigned_at=now - timedelta(days=2),
                started_at=now - timedelta(days=1),
                submitted_at=now - timedelta(hours=3),
                percentage=100,
                total_score=100,
                max_score=100,
                teacher_feedback='[QA PRESET] Отличная работа.',
            )
            db.session.add(sub)
            created += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: {user.username} получил {created} оцененных работ (100%).',
            'next': _next('Открыть профиль ученика', url_for('students.student_profile', student_id=student.student_id)),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/clean_slate_account', methods=['POST'])
@login_required
def preset_clean_slate_account():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        token = token[:32]
        link = InviteLink(
            token_hash=_hash_invite_token(token),
            email=f'qa_clean_slate_{uuid.uuid4().hex[:6]}@qa.local',
            role='student',
            note='[QA PRESET] clean_slate_account',
            created_by_user_id=current_user.id,
            created_at=moscow_now(),
            expires_at=(moscow_now() + timedelta(days=7)).replace(tzinfo=None),
        )
        db.session.add(link)
        db.session.commit()
        invite_url = url_for('onboarding.invite_accept', token=token, _external=True) if 'onboarding.invite_accept' in current_app.view_functions else url_for('main.index', _external=True)
        return jsonify({
            'status': 'success',
            'message': 'Готово: создан инвайт для онбординга (clean slate).',
            'next': _next('Открыть инвайт', invite_url),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/broken_work_10mb', methods=['POST'])
@login_required
def preset_broken_work_10mb():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})
        _, student = pool[0]
        sub = Submission.query.filter_by(student_id=student.student_id).order_by(Submission.created_at.desc()).first()
        if not sub:
            a = Assignment(
                title='[QA PRESET] Broken work seed',
                description='[QA PRESET] broken_work_10mb',
                assignment_type='homework',
                deadline=moscow_now().replace(tzinfo=None) + timedelta(days=3),
                hard_deadline=False,
                created_by_id=current_user.id,
                is_active=True,
            )
            db.session.add(a)
            db.session.flush()
            sub = Submission(assignment_id=a.assignment_id, student_id=student.student_id, status='SUBMITTED', submitted_at=moscow_now().replace(tzinfo=None))
            db.session.add(sub)
            db.session.flush()
        ans = Answer.query.filter_by(submission_id=sub.submission_id).order_by(Answer.id.desc()).first()
        if not ans:
            ans = Answer(submission_id=sub.submission_id)
            db.session.add(ans)
            db.session.flush()
        ans.value = ('X' * 10_000_000)
        db.session.add(ans)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Готово: записан payload ~10MB в Answer.value для стресс-теста UI.',
            'next': _next('Открыть работы/проверку', url_for('lessons.review_queue')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/deadline_timer_5min', methods=['POST'])
@login_required
def preset_deadline_timer_5min():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        now = moscow_now().replace(tzinfo=None)
        new_deadline = now + timedelta(minutes=5)
        q = Assignment.query.filter(Assignment.title.ilike('[QA PRESET]%')).filter(Assignment.is_active.is_(True))
        items = q.order_by(Assignment.assignment_id.desc()).limit(10).all()
        changed = 0
        for a in items:
            a.deadline = new_deadline
            db.session.add(a)
            changed += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: сдвинуто дедлайнов: {changed} (через 5 минут).',
            'next': _next('Открыть задания', url_for('main.dashboard')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/schedule_marathon_10x15', methods=['POST'])
@login_required
def preset_schedule_marathon_10x15():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        _ensure_qa_pool()
        tutor_user = User.query.filter(User.username.in_([u for u in QA_POOL_USERNAMES if 'tutor' in u])).order_by(User.username.asc()).first()
        pool = _pool_student_profiles()
        if not tutor_user or not pool:
            return jsonify({'status': 'error', 'message': 'Недостаточно данных в пуле QA'})
        user, student = pool[0]
        if not Enrollment.query.filter_by(student_id=user.id, tutor_id=tutor_user.id).first():
            db.session.add(Enrollment(student_id=user.id, tutor_id=tutor_user.id, subject='[QA PRESET] marathon'))
        start = (moscow_now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0, tzinfo=None)
        created = 0
        for i in range(10):
            lesson = Lesson(
                student_id=student.student_id,
                lesson_date=start + timedelta(minutes=15 * i),
                duration=15,
                lesson_type='regular',
                status='planned',
                topic=f'[QA PRESET] Marathon #{i+1}',
            )
            db.session.add(lesson)
            created += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: создано {created} уроков подряд (15 минут).',
            'next': _next('Открыть расписание', url_for('schedule.schedule')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/lesson_in_2030', methods=['POST'])
@login_required
def preset_lesson_in_2030():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})
        _, student = pool[0]
        dt = moscow_now().replace(tzinfo=None).replace(year=2030, month=1, day=10, hour=12, minute=0, second=0, microsecond=0)
        lesson = Lesson(student_id=student.student_id, lesson_date=dt, duration=60, lesson_type='regular', status='planned', topic='[QA PRESET] Lesson in 2030')
        db.session.add(lesson)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Готово: создан урок в 2030 году.',
            'next': _next('Открыть расписание', url_for('schedule.schedule')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/subscription_end_yesterday', methods=['POST'])
@login_required
def preset_subscription_end_yesterday():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        now = moscow_now().replace(tzinfo=None)
        sub = UserSubscription.query.filter_by(user_id=current_user.id).order_by(UserSubscription.ends_at.desc().nullslast()).first()
        if not sub:
            sub = UserSubscription(user_id=current_user.id, status='expired', ends_at=now - timedelta(days=1))
        sub.status = 'expired'
        sub.ends_at = now - timedelta(days=1)
        db.session.add(sub)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Готово: подписка закончилась вчера (paywall regression).',
            'next': _next('Открыть дашборд', url_for('main.dashboard')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/invite_generator_10', methods=['POST'])
@login_required
def preset_invite_generator_10():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        created = 0
        for _ in range(10):
            token = uuid.uuid4().hex + uuid.uuid4().hex
            token = token[:32]
            link = InviteLink(
                token_hash=_hash_invite_token(token),
                email=f'qa_invite_{uuid.uuid4().hex[:6]}@qa.local',
                role='student',
                note='[QA PRESET] invite_generator_10',
                created_by_user_id=current_user.id,
                created_at=moscow_now(),
                expires_at=(moscow_now() + timedelta(days=7)).replace(tzinfo=None),
            )
            db.session.add(link)
            created += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: создано инвайтов: {created}.',
            'next': _next('Открыть список инвайтов', url_for('onboarding.invites_list')) if 'onboarding.invites_list' in current_app.view_functions else _next('Открыть пул профилей', url_for('qa.pool')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/create_cluster_group', methods=['POST'])
@login_required
def preset_create_cluster_group():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        pool = _pool_student_profiles()
        if len(pool) < 1:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})
        g = SchoolGroup(title=f'[QA PRESET] Cluster group {uuid.uuid4().hex[:6]}', owner_user_id=current_user.id)
        db.session.add(g)
        db.session.flush()
        attached = 0
        for (u, s) in pool[:5]:
            db.session.add(GroupStudent(group_id=g.group_id, student_id=s.student_id, added_by_user_id=current_user.id))
            attached += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: создана группа и добавлено учеников: {attached}.',
            'next': _next('Открыть пул профилей', url_for('qa.pool')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/mass_homework_to_group', methods=['POST'])
@login_required
def preset_mass_homework_to_group():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        group = SchoolGroup.query.order_by(SchoolGroup.group_id.desc()).first()
        if not group:
            return jsonify({'status': 'error', 'message': 'Сначала создайте группу пресетом create_cluster_group'})
        student_ids = [gs.student_id for gs in GroupStudent.query.filter_by(group_id=group.group_id).all()]
        if not student_ids:
            return jsonify({'status': 'error', 'message': 'В группе нет учеников'})
        now = moscow_now().replace(tzinfo=None)
        a = Assignment(
            title=f'[QA PRESET] Group HW {group.title}',
            description='[QA PRESET] mass_homework_to_group',
            assignment_type='homework',
            deadline=now + timedelta(days=2),
            hard_deadline=False,
            created_by_id=current_user.id,
            is_active=True,
        )
        db.session.add(a)
        db.session.flush()
        created = 0
        for sid in student_ids:
            db.session.add(Submission(assignment_id=a.assignment_id, student_id=sid, status='ASSIGNED', assigned_at=now))
            created += 1
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: создано ДЗ и назначено ученикам группы: {created}.',
            'next': _next('Открыть очередь проверки', url_for('lessons.review_queue')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/stress_trainer_infinite_loop', methods=['POST'])
@login_required
def preset_stress_trainer_infinite_loop():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        pool = _pool_student_profiles()
        if not pool:
            return jsonify({'status': 'error', 'message': 'Пул учеников не инициализирован'})
        _, student = pool[0]
        sub = Submission.query.filter_by(student_id=student.student_id).order_by(Submission.created_at.desc()).first()
        if not sub:
            return jsonify({'status': 'error', 'message': 'Нет submission для ученика. Создайте работу/сдачу.'})
        ans = Answer.query.filter_by(submission_id=sub.submission_id).order_by(Answer.id.desc()).first()
        if not ans:
            ans = Answer(submission_id=sub.submission_id)
        ans.student_code = "while True:\n    print('test')\n"
        db.session.add(ans)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': 'Готово: записан stress-case код (while True) в Answer.student_code.',
            'next': _next('Открыть работы/проверку', url_for('lessons.review_queue')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/reset_streak', methods=['POST'])
@login_required
def preset_reset_streak():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        # Best-effort: fields may not exist in current schema
        changed = False
        for field in ('streak', 'streak_days', 'current_streak', 'daily_streak'):
            if hasattr(current_user, field):
                try:
                    setattr(current_user, field, 0)
                    changed = True
                except Exception:
                    pass
        if changed:
            db.session.add(current_user)
            db.session.commit()
            msg = 'Готово: стрик сброшен (best-effort).'
        else:
            msg = 'No-op: в модели пользователя нет полей streak. (best-effort)'
        return jsonify({'status': 'success', 'message': msg})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/system_cache_clear', methods=['POST'])
@login_required
def preset_system_cache_clear():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    # Best-effort: if there is no cache layer, do a no-op but keep it explicit
    return jsonify({'status': 'success', 'message': 'Cache clear: no-op (в проекте не настроен отдельный cache backend).'})


@qa_bp.route('/manipulate/maintenance_enable', methods=['POST'])
@login_required
def preset_maintenance_enable():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        row = MaintenanceMode.query.order_by(MaintenanceMode.id.desc()).first()
        if not row:
            row = MaintenanceMode(is_enabled=True)
        row.is_enabled = True
        db.session.add(row)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Maintenance mode включён.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/manipulate/nuke_test_data', methods=['POST'])
@login_required
def preset_nuke_test_data():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return _preset_forbidden()
    try:
        # Best-effort cleanup by marker prefix
        deleted_inv = InviteLink.query.filter(InviteLink.note.ilike('[QA PRESET]%')).delete(synchronize_session=False)
        deleted_groups = SchoolGroup.query.filter(SchoolGroup.title.ilike('[QA PRESET]%')).delete(synchronize_session=False)
        deleted_assign = Assignment.query.filter(Assignment.title.ilike('[QA PRESET]%')).delete(synchronize_session=False)
        deleted_lessons = Lesson.query.filter(Lesson.topic.ilike('[QA PRESET]%')).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f'Готово: удалено InviteLink={deleted_inv}, Groups={deleted_groups}, Assignments={deleted_assign}, Lessons={deleted_lessons} (best-effort).',
            'next': _next('Открыть пул профилей', url_for('qa.pool')),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
# 3.1 УПРАВЛЕНИЕ ТЕСТЕРАМИ (Chief Tester / Creator)
# ==========================================

@qa_bp.route('/testers')
@login_required
def testers():
    """Окно управления тестерами: список, создание, назначение прав."""
    if not current_user.is_chief_tester() and not current_user.is_creator():
        return "Access denied", 403
    testers_list = User.query.filter(User.role.in_(['tester', 'chief_tester'])).order_by(User.username).all()
    return_to = (request.args.get('return_to') or '').strip()
    return render_template('qa/testers.html', testers_list=testers_list,
                           all_permissions=ALL_PERMISSIONS, permission_categories=PERMISSION_CATEGORIES,
                           return_to=return_to)


@qa_bp.route('/testers/create', methods=['POST'])
@login_required
def testers_create():
    if not current_user.is_chief_tester() and not current_user.is_creator():
        return jsonify({'error': 'Forbidden'}), 403
    username = (request.form.get('username') or '').strip()
    password = (request.form.get('password') or '').strip()
    if not username or not password:
        flash('Укажите логин и пароль', 'error')
        return redirect(url_for('qa.testers'))
    user = User.query.filter_by(username=username).first()
    if user:
        user.password_hash = generate_password_hash(password)
        user.role = 'tester'
        UserRole.query.filter_by(user_id=user.id).delete()
        db.session.add(UserRole(user_id=user.id, role='tester'))
        user.is_active = True
        db.session.commit()
        flash(f'Тестировщик «{username}» обновлён.', 'success')
    else:
        user = User(username=username, password_hash=generate_password_hash(password), role='tester', is_active=True)
        db.session.add(user)
        db.session.flush()
        db.session.add(UserRole(user_id=user.id, role='tester'))
        db.session.commit()
        flash(f'Тестировщик «{username}» создан.', 'success')
    return redirect(url_for('qa.testers'))


@qa_bp.route('/testers/<int:user_id>/permissions', methods=['POST'])
@login_required
def testers_permissions(user_id):
    if not current_user.is_chief_tester() and not current_user.is_creator():
        return jsonify({'error': 'Forbidden'}), 403
    user = User.query.get_or_404(user_id)
    if user.role not in ('tester', 'chief_tester'):
        return jsonify({'error': 'Not a tester'}), 400
    data = request.get_json(silent=True) or {}
    perms = {}
    for key in ALL_PERMISSIONS:
        perms[key] = bool(data.get(key))
    user.custom_permissions = perms
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True})
    flash('Права обновлены', 'success')
    return redirect(url_for('qa.testers'))


# ==========================================
# 3.2 ПУЛ ПРОФИЛЕЙ И ПРИВЯЗКИ
# ==========================================

@qa_bp.route('/pool')
@login_required
def pool():
    """Страница управления тестовыми профилями: привязка учеников к преподавателям, родителей к ученикам."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    _ensure_qa_pool()
    pool_users = User.query.filter(User.username.in_(QA_POOL_USERNAMES)).order_by(User.username).all()
    students = [u for u in pool_users if u.role == 'student']
    tutors = [u for u in pool_users if u.role == 'tutor']
    parents = [u for u in pool_users if u.role == 'parent']
    admins = [u for u in pool_users if u.role == 'admin']
    enrollments = Enrollment.query.filter(
        Enrollment.student_id.in_([u.id for u in students]),
        Enrollment.tutor_id.in_([u.id for u in tutors])
    ).all()
    family_ties = FamilyTie.query.filter(
        FamilyTie.student_id.in_([u.id for u in students]),
        FamilyTie.parent_id.in_([u.id for u in parents])
    ).all()
    return render_template('qa/pool.html', students=students, tutors=tutors, parents=parents, admins=admins,
                           enrollments=enrollments, family_ties=family_ties)


@qa_bp.route('/pool/enrollment', methods=['POST'])
@login_required
def pool_enrollment_add():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    student_id = request.form.get('student_id', type=int)
    tutor_id = request.form.get('tutor_id', type=int)
    if not student_id or not tutor_id:
        flash('Выберите ученика и преподавателя', 'error')
        return redirect(url_for('qa.pool'))
    if Enrollment.query.filter_by(student_id=student_id, tutor_id=tutor_id).first():
        flash('Такая привязка уже есть', 'warning')
        return redirect(url_for('qa.pool'))
    db.session.add(Enrollment(student_id=student_id, tutor_id=tutor_id, subject='QA (тест)'))
    db.session.commit()
    flash('Ученик привязан к преподавателю', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/enrollment/<int:enrollment_id>/delete', methods=['POST'])
@login_required
def pool_enrollment_delete(enrollment_id):
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    e = Enrollment.query.get_or_404(enrollment_id)
    db.session.delete(e)
    db.session.commit()
    flash('Привязка ученик–препода удалена', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/family-tie', methods=['POST'])
@login_required
def pool_family_tie_add():
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    parent_id = request.form.get('parent_id', type=int)
    student_id = request.form.get('student_id', type=int)
    if not parent_id or not student_id:
        flash('Выберите родителя и ученика', 'error')
        return redirect(url_for('qa.pool'))
    if FamilyTie.query.filter_by(parent_id=parent_id, student_id=student_id).first():
        flash('Такая привязка уже есть', 'warning')
        return redirect(url_for('qa.pool'))
    db.session.add(FamilyTie(parent_id=parent_id, student_id=student_id, is_confirmed=True))
    db.session.commit()
    flash('Родитель привязан к ученику', 'success')
    return redirect(url_for('qa.pool'))


@qa_bp.route('/pool/family-tie/<int:tie_id>/delete', methods=['POST'])
@login_required
def pool_family_tie_delete(tie_id):
    if not require_qa('chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    t = FamilyTie.query.get_or_404(tie_id)
    db.session.delete(t)
    db.session.commit()
    flash('Привязка родитель–ученик удалена', 'success')
    return redirect(url_for('qa.pool'))


# ==========================================
# 4. КАНБАН (задачи Creator → Tester)
# ==========================================

@qa_bp.route('/board')
@login_required
def board():
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    tasks = QATask.query.filter(QATask.task_type == 'task').order_by(QATask.created_at.desc()).all()
    testers = User.query.filter(User.role.in_(['chief_tester', 'tester'])).all()
    can_edit_status = current_user.is_creator() or current_user.is_chief_tester() or current_user.is_tester()
    can_edit_assignee = current_user.is_creator() or current_user.is_chief_tester()
    assignee_ids = set()
    for t in tasks:
        if getattr(t, 'assignee_ids', None) and isinstance(t.assignee_ids, list):
            assignee_ids.update(x for x in t.assignee_ids if x)
        elif getattr(t, 'assignee_id', None):
            assignee_ids.add(t.assignee_id)
    assignee_map = {u.id: u for u in User.query.filter(User.id.in_(assignee_ids)).all()} if assignee_ids else {}
    return_to = (request.args.get('return_to') or '').strip()
    return render_template('qa/board.html', tasks=tasks, testers=testers, assignee_map=assignee_map,
                           can_edit_status=can_edit_status, can_edit_assignee=can_edit_assignee,
                           return_to=return_to)


@qa_bp.route('/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def task_set_status(task_id):
    """Смена статуса задачи на доске. Может Creator, Chief Tester или любой из исполнителей."""
    try:
        if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
            return jsonify({'error': 'Forbidden'}), 403
        task = QATask.query.get_or_404(task_id)
        if task.task_type != 'task':
            return jsonify({'error': 'Not a board task'}), 400
        assignee_ids = getattr(task, 'assignee_ids', None) or (([task.assignee_id] if task.assignee_id else []))
        can_edit = (
            current_user.is_creator() or current_user.is_chief_tester() or
            current_user.id == task.assignee_id or current_user.id in assignee_ids
        )
        if not can_edit:
            return jsonify({'error': 'Только создатель, главный тестер или исполнитель могут менять статус'}), 403
        if request.content_type and 'application/json' in (request.content_type or ''):
            data = request.get_json(silent=True) or {}
            status = (data.get('status') or '').strip()
        else:
            status = (request.form.get('status') or '').strip()
        if status not in ('todo', 'in_progress', 'review', 'done'):
            return jsonify({'error': 'Invalid status'}), 400
        task.status = status
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (request.content_type and 'application/json' in (request.content_type or '')):
            return jsonify({'success': True, 'status': status})
        flash('Статус обновлён', 'success')
        return redirect(url_for('qa.board'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(e)
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/tasks/<int:task_id>/assign', methods=['POST'])
@login_required
def task_assign(task_id):
    """Назначить исполнителя(ей). Creator или Chief Tester. assignee_ids — список id (главный тестер может добавить себя и тестеров)."""
    if not current_user.is_creator() and not current_user.is_chief_tester():
        return jsonify({'error': 'Forbidden'}), 403
    task = QATask.query.get_or_404(task_id)
    if task.task_type != 'task':
        return jsonify({'error': 'Not a board task'}), 400
    if request.content_type and 'application/json' in (request.content_type or ''):
        data = request.get_json(silent=True) or {}
        assignee_ids = data.get('assignee_ids')
        if assignee_ids is not None:
            task.assignee_ids = [int(x) for x in assignee_ids if x is not None and str(x).isdigit()]
            task.assignee_id = task.assignee_ids[0] if task.assignee_ids else None
        else:
            raw = data.get('assignee_id')
            try:
                aid = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                aid = None
            task.assignee_id = aid
            task.assignee_ids = [aid] if aid else []
    else:
        assignee_id = request.form.get('assignee_id', type=int)
        task.assignee_id = assignee_id if assignee_id else None
        task.assignee_ids = [assignee_id] if assignee_id else []
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (request.content_type and 'application/json' in (request.content_type or '')):
        return jsonify({'success': True})
    flash('Исполнитель назначен', 'success')
    return redirect(url_for('qa.board'))


# ==========================================
# 5. БАГ-РЕПОРТЫ (Tester → Creator, Creator управляет)
# ==========================================

@qa_bp.route('/bug-report', methods=['GET', 'POST'])
@login_required
def bug_report():
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    context_url = request.args.get('context_url') or request.form.get('context_url') or ''
    target_user_id = request.args.get('target_user_id') or request.form.get('target_user_id') or ''
    
    return_to = (request.args.get('return_to') or request.form.get('return_to') or '').strip()

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip() or 'Баг с страницы'
        description = (request.form.get('description') or '').strip()
        request_id = (request.form.get('request_id') or '').strip() or None
        severity = (request.form.get('severity') or '').strip().lower() or None
        environment = (request.form.get('environment') or '').strip() or None
        steps = (request.form.get('steps') or '').strip() or None
        expected = (request.form.get('expected') or '').strip() or None
        actual = (request.form.get('actual') or '').strip() or None
        logs_snapshot = (request.form.get('logs_snapshot') or '').strip()
        if any([severity, environment, steps, expected, actual]):
            parts = []
            if request_id:
                parts.append(f"RID: {request_id}")
            if severity:
                parts.append(f"Severity: {severity}")
            if environment:
                parts.append(f"Environment: {environment}")
            if steps:
                parts.append(f"\nSteps:\n{steps}")
            if expected:
                parts.append(f"\nExpected:\n{expected}")
            if actual:
                parts.append(f"\nActual:\n{actual}")
            if description:
                parts.append(f"\nNotes:\n{description}")
            description = "\n".join(parts).strip()
        if logs_snapshot:
            safe_snapshot = logs_snapshot[:12000]
            description = (description + '\n\n--- LOG SNAPSHOT ---\n' + safe_snapshot).strip()
        screenshot_data = request.form.get('screenshot') # Base64 string
        
        screenshot_path = None
        if screenshot_data and ',' in screenshot_data:
            try:
                header, encoded = screenshot_data.split(",", 1)
                data = base64.b64decode(encoded)
                ext = 'jpg' if 'image/jpeg' in (header or '') or 'image/jpg' in (header or '') else 'png'
                filename = f"bug_{int(time.time())}_{current_user.id}.{ext}"
                # Сохраняем в каталог static приложения (url будет /static/uploads/qa_screenshots/filename)
                upload_dir = os.path.join(current_app.static_folder, 'uploads', 'qa_screenshots')
                os.makedirs(upload_dir, exist_ok=True)
                filepath = os.path.join(upload_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(data)
                # В БД храним только путь для url_for('static', filename=...): uploads/qa_screenshots/filename
                screenshot_path = f"uploads/qa_screenshots/{filename}"
            except Exception as e:
                current_app.logger.warning("Screenshot save error: %s", e)

        if title:
            task = QATask(
                title=title,
                description=description or None,
                context_url=context_url or None,
                target_user_id=int(target_user_id) if target_user_id and str(target_user_id).isdigit() else None,
                reporter_id=current_user.id,
                status='new',
                priority=(severity if severity in ('low','medium','high','critical') else 'high'),
                task_type='bug_report',
                screenshot_path=screenshot_path
            )
            db.session.add(task)
            db.session.commit()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or getattr(request, 'want_json', False):
                 return jsonify({'success': True, 'redirect': url_for('qa.bug_reports')})
            
            flash('Баг-репорт создан. Создатель увидит его в разделе «Баг-репорты».', 'success')
            if return_to:
                return redirect(return_to)
            return redirect(url_for('qa.bug_reports'))
            
    return render_template('qa/bug_report.html', context_url=context_url, target_user_id=target_user_id, return_to=return_to)


@qa_bp.route('/bug-reports')
@login_required
def bug_reports():
    """Список баг-репортов. Creator может менять статус, Tester — только просмотр."""
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    reports = QATask.query.filter(QATask.task_type == 'bug_report').order_by(QATask.created_at.desc()).all()
    can_edit = current_user.is_creator()
    return_to = (request.args.get('return_to') or '').strip()
    return render_template('qa/bug_reports.html', reports=reports, can_edit=can_edit, return_to=return_to)


def _extract_rid(description: str | None) -> str | None:
    if not description:
        return None
    txt = description
    for key in ('RID:', 'RID=', 'rid:', 'rid='):
        if key in txt:
            tail = txt.split(key, 1)[1].strip()
            rid = (tail.split()[0] if tail else '').strip()
            if rid:
                return rid
    return None


def _parse_bug_description(description: str | None) -> dict:
    """
    Parse a stable template body into sections.
    Headers supported: Severity:, Environment:, Steps:, Expected:, Actual:, Notes:, --- LOG SNAPSHOT ---
    """
    desc = (description or '').strip()
    sections = {
        'rid': _extract_rid(desc),
        'severity': None,
        'environment': None,
        'steps': None,
        'expected': None,
        'actual': None,
        'notes': None,
        'logs': None,
        'raw': desc,
    }
    if not desc:
        return sections

    # Split logs snapshot first
    if '--- LOG SNAPSHOT ---' in desc:
        before, after = desc.split('--- LOG SNAPSHOT ---', 1)
        sections['logs'] = after.strip() or None
        body = before.strip()
    else:
        body = desc

    # Simple line-based fields
    lines = body.splitlines()
    i = 0
    def collect_block(start_idx: int) -> tuple[str, int]:
        buf = []
        j = start_idx
        while j < len(lines):
            line = lines[j]
            if line.strip() in ('Steps:', 'Expected:', 'Actual:', 'Notes:'):
                break
            if line.startswith('Severity:') or line.startswith('Environment:') or line.startswith('RID:') or line.startswith('RID='):
                # next scalar header
                break
            buf.append(line)
            j += 1
        return ("\n".join(buf).strip(), j)

    while i < len(lines):
        line = lines[i].strip()
        if line.lower().startswith('severity:'):
            sections['severity'] = line.split(':', 1)[1].strip() or None
            i += 1
            continue
        if line.lower().startswith('environment:'):
            sections['environment'] = line.split(':', 1)[1].strip() or None
            i += 1
            continue
        if line.startswith('Steps:'):
            block, i2 = collect_block(i + 1)
            sections['steps'] = block or None
            i = i2
            continue
        if line.startswith('Expected:'):
            block, i2 = collect_block(i + 1)
            sections['expected'] = block or None
            i = i2
            continue
        if line.startswith('Actual:'):
            block, i2 = collect_block(i + 1)
            sections['actual'] = block or None
            i = i2
            continue
        if line.startswith('Notes:'):
            block, i2 = collect_block(i + 1)
            sections['notes'] = block or None
            i = i2
            continue
        i += 1

    return sections


@qa_bp.route('/bug-reports/<int:task_id>')
@login_required
def bug_report_detail(task_id: int):
    if not require_qa('tester', 'chief_tester', 'creator', 'chief_admin', 'admin'):
        return "Access denied", 403
    r = QATask.query.get_or_404(task_id)
    if r.task_type != 'bug_report':
        return "Not a bug report", 404
    parsed = _parse_bug_description(getattr(r, 'description', None))
    return_to = (request.args.get('return_to') or '').strip()
    can_edit = current_user.is_creator()
    return render_template('qa/bug_report_detail.html', r=r, parsed=parsed, return_to=return_to, can_edit=can_edit)


@qa_bp.route('/bug-reports/<int:task_id>/status', methods=['POST'])
@login_required
def bug_report_set_status(task_id):
    """Смена статуса баг-репорта. Только Creator."""
    try:
        if not current_user.is_creator():
            return jsonify({'error': 'Forbidden'}), 403
        task = QATask.query.get_or_404(task_id)
        if task.task_type != 'bug_report':
            return jsonify({'error': 'Not a bug report'}), 400
        if request.content_type and 'application/json' in (request.content_type or ''):
            data = request.get_json(silent=True) or {}
            status = (data.get('status') or '').strip()
        else:
            status = (request.form.get('status') or '').strip()
        if status not in ('new', 'in_progress', 'review', 'done'):
            return jsonify({'error': 'Invalid status'}), 400
        task.status = status
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or (request.content_type and 'application/json' in (request.content_type or '')):
            return jsonify({'success': True, 'status': status})
        flash('Статус баг-репорта обновлён', 'success')
        return redirect(url_for('qa.bug_reports'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(e)
        return jsonify({'error': str(e)}), 500


@qa_bp.route('/tasks/new', methods=['GET', 'POST'])
@login_required
def task_new():
    """Создание задачи для тестера. Только Creator."""
    if not current_user.is_creator():
        return "Access denied: Only Creator can create tasks here.", 403
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        context_url = request.form.get('context_url')
        target_user_id = request.form.get('target_user_id')
        assignee_id = request.form.get('assignee_id', type=int)
        if title:
            task = QATask(
                title=title,
                description=description,
                context_url=context_url,
                target_user_id=int(target_user_id) if target_user_id and str(target_user_id).isdigit() else None,
                reporter_id=current_user.id,
                status='todo',
                task_type='task',
                assignee_id=assignee_id or None
            )
            db.session.add(task)
            db.session.commit()
            return redirect(url_for('qa.board'))
    testers = User.query.filter(User.role.in_(['chief_tester', 'tester'])).all()
    return render_template('qa/task_form.html', testers=testers)


# ==========================================
# Переход Прод ↔ Песочница с автовходом
# ==========================================

@qa_bp.route('/cross-env-redirect')
@login_required
def cross_env_redirect():
    """
    Редирект на другое окружение (прод/песочница) на /login с подписанным токеном
    для автоматического входа под текущим пользователем.
    """
    if not is_qa_authorized():
        flash('Доступ только для тестеров и администраторов.', 'warning')
        return redirect(url_for('main.dashboard'))
    target = request.args.get('target')
    secret = current_app.config.get('CROSS_ENV_LOGIN_SECRET')
    if target == 'sandbox':
        base_url = current_app.config.get('SANDBOX_URL')
    elif target == 'prod':
        base_url = current_app.config.get('PROD_URL')
    else:
        flash('Укажите target=sandbox или target=prod.', 'warning')
        return redirect(url_for('main.dashboard'))
    if not base_url:
        flash('URL другого окружения не настроен (SANDBOX_URL / PROD_URL).', 'warning')
        return redirect(url_for('main.dashboard'))
    if not secret:
        flash('Кросс-вход отключён: не задан CROSS_ENV_LOGIN_SECRET.', 'warning')
        return redirect(url_for('main.dashboard'))
    token = build_cross_env_token(current_user.id, current_user.username, secret)
    login_url = f"{base_url.rstrip('/')}/login?cross_env={token}"
    return redirect(login_url)

@qa_bp.route('/manipulate/<action>', methods=['POST'])
@login_required
def manipulate_preset(action):
    # Разрешаем только Главным Тестерам и Создателю
    if not (current_user.is_creator() or current_user.is_chief_tester()):
        return jsonify({"success": False, "message": "Нет прав на макросы"}), 403

    # Определяем, над кем проводим экзекуцию (Симулируемый юзер или текущий)
    target_user_id = session.get('impersonate_user_id') or current_user.id
    target_user = User.query.get(target_user_id)

    try:
        match action:
            case 'generate_debtor':
                # Создаем фейкового студента
                fake_username = f"qa_test_debtor_{random.randint(1000,9999)}"
                new_user = User(username=fake_username, email=f"{fake_username}@qa.local", role="student")
                new_user.set_password("testpassword123")
                db.session.add(new_user)
                db.session.commit()
                
                # Вешаем на него 3 просроченных ДЗ (эмуляция)
                for i in range(3):
                    hw = AssignmentTask(
                        user_id=new_user.id,
                        title=f"Просроченное ДЗ #{i+1}",
                        status="todo",
                        deadline=datetime.utcnow() - timedelta(days=random.randint(1, 5))
                    )
                    db.session.add(hw)
                db.session.commit()
                return jsonify({"success": True, "message": f"Должник {fake_username} сгенерирован!"})

            case 'overwhelm_reviews':
                # Заваливаем Создателя/Препода проверками
                for i in range(20):
                    sub = Submission(
                        task_id=1, # ID тестовой задачи
                        student_id=target_user_id,
                        status="AWAITING_REVIEW",
                        content="Тестовый ответ для завала ревью"
                    )
                    db.session.add(sub)
                db.session.commit()
                return jsonify({"success": True, "message": "Очередь проверок завалена (20 работ)."})

            case 'god_mode_30d':
                # Выдача админского тарифа симулируемому юзеру
                sub = UserSubscription.query.filter_by(user_id=target_user_id).first()
                if not sub:
                    sub = UserSubscription(user_id=target_user_id)
                    db.session.add(sub)
                sub.plan_id = "god_mode"
                sub.expires_at = datetime.utcnow() + timedelta(days=30)
                db.session.commit()
                return jsonify({"success": True, "message": f"Тариф God Mode выдан {target_user.username} на 30 дней."})

            case 'system_cache_clear':
                # Очистка кэша Flask (Best-Effort без Redis)
                current_app.cache.clear() # Если используешь flask-caching
                return jsonify({"success": True, "message": "Системный кэш Flask очищен."})

            case 'tabula_rasa':
                # Ядерная кнопка (Nuke) - удаляем только тестовые аккаунты
                test_users = User.query.filter(User.email.endswith('@qa.local')).all()
                count = len(test_users)
                for u in test_users:
                    db.session.delete(u)
                db.session.commit()
                return jsonify({"success": True, "message": f"База очищена. Удалено {count} тестовых фейков."})

            case _:
                return jsonify({"success": False, "message": "Пресет еще не реализован."}), 404

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ошибка пресета {action}: {e}")
        return jsonify({"success": False, "message": f"Ошибка: {str(e)}"}), 500


@qa_bp.route('/impersonate/<int:target_user_id>', methods=['POST'])
@login_required
def impersonate(target_user_id):
    if not (current_user.is_creator() or current_user.is_chief_tester() or getattr(current_user, 'role', '') in ['admin', 'chief_admin']):
        flash('У вас нет прав для этого действия', 'error')
        return redirect(request.referrer or url_for('main.index'))

    target_user = User.query.get_or_404(target_user_id)

    # Защита от "Матрицы" (симуляции внутри симуляции)
    if 'impersonator_id' not in session:
        session['impersonator_id'] = current_user.id

    login_user(target_user)
    flash(f'Вы вошли под аккаунтом: {target_user.username}', 'success')
    return redirect(request.referrer or url_for('main.index'))

@qa_bp.route('/revert_impersonation', methods=['POST'])
@login_required
def revert_impersonation():
    impersonator_id = session.pop('impersonator_id', None)
    if not impersonator_id:
        return redirect(url_for('main.index'))

    original_user = User.query.get(impersonator_id)
    if original_user:
        login_user(original_user)
        flash('Вы вернулись в свой QA-кабинет', 'success')
    
    return redirect(request.referrer or url_for('main.index'))