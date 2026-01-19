"""
Внутренние API endpoints для удаленной админки
Доступны из production и sandbox окружений для управления через remote_admin
"""
import logging
import hmac
import os
from flask import request, jsonify
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.admin import admin_bp
import re

from app.models import User, AuditLog, MaintenanceMode, db, UserProfile, Tasks, TaskReview
from app.models import FamilyTie, Enrollment, Student, Lesson, RolePermission
from app.auth.permissions import ALL_PERMISSIONS, PERMISSION_CATEGORIES, DEFAULT_ROLE_PERMISSIONS
from core.audit_logger import audit_logger
from core.db_models import moscow_now

logger = logging.getLogger(__name__)


def _task_formator_normalize_answer(raw: str) -> str:
    if raw is None:
        return ''
    s = str(raw).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def _task_formator_quick_checks(task: Tasks):
    checks = []
    html = (task.content_html or '').strip()
    ans = _task_formator_normalize_answer(task.answer)

    if not html:
        checks.append({'level': 'fail', 'title': 'Пустое условие', 'details': 'content_html пустой. Вероятно, парсер не сохранил текст задания.'})
    else:
        text_len = len(re.sub(r'<[^>]+>', ' ', html))
        if text_len < 60:
            checks.append({'level': 'warn', 'title': 'Слишком короткое условие', 'details': f'Длина текста (без HTML) выглядит подозрительно маленькой: ~{text_len} символов.'})
        if 'undefined' in html.lower() or 'null' in html.lower():
            checks.append({'level': 'warn', 'title': 'Подозрительные токены в условии', 'details': 'В условии встречается "undefined"/"null". Часто это артефакт парсинга.'})

    if task.task_number in list(range(1, 24)):
        if not ans:
            checks.append({'level': 'fail', 'title': 'Нет ответа', 'details': 'Для заданий 1–23 ожидается короткий ответ. Сейчас поле answer пустое.'})
        else:
            if len(ans) > 60:
                checks.append({'level': 'warn', 'title': 'Слишком длинный ответ', 'details': f'Ответ слишком длинный для 1–23: {len(ans)} символов.'})
            if '<' in ans or '>' in ans:
                checks.append({'level': 'warn', 'title': 'Ответ похож на HTML/мусор', 'details': 'В ответе есть символы "<" или ">". Возможно, ответ спарсился неправильно.'})
            if '\n' in (task.answer or ''):
                checks.append({'level': 'warn', 'title': 'Многострочный ответ', 'details': 'Для 1–23 ответ обычно однострочный. Проверьте корректность.'})
            if not re.fullmatch(r"[0-9A-Za-zА-Яа-я\-\+\*/=(),.\s:;%№]+", ans):
                checks.append({'level': 'warn', 'title': 'Необычные символы в ответе', 'details': 'Ответ содержит необычные символы. Возможно, попали лишние куски.'})
    else:
        if not ans:
            checks.append({'level': 'ok', 'title': 'Ответ не задан (нормально для ручной проверки)', 'details': 'Для заданий 24–27 ответ может отсутствовать/быть неформальным.'})

    # source_url полезен, но в старых данных его может не быть — не шумим WARN,
    # если есть хотя бы site_task_id (можно верифицировать по нему).
    if not (task.source_url or '').strip():
        if (task.site_task_id or '').strip():
            checks.append({'level': 'ok', 'title': 'Нет source_url', 'details': 'URL источника не сохранён, но есть site_task_id — верификация возможна.'})
        else:
            checks.append({'level': 'warn', 'title': 'Нет source_url', 'details': 'У задания не сохранён URL источника и нет site_task_id — сложнее верифицировать.'})

    if not checks:
        checks.append({'level': 'ok', 'title': 'Базовые проверки пройдены', 'details': 'Явных проблем не найдено.'})

    return checks

# Импортируем csrf безопасным способом (после всех других импортов)
try:
    from app import csrf
except ImportError:
    # Если циклический импорт, используем current_app
    csrf = None


def _manage_student_tutor(student_user_id, tutor_id, replace=False):
    """Assign or update a tutor for a student via Enrollment"""
    if tutor_id is None:
        if replace:
            try:
                existing_active = Enrollment.query.filter_by(
                    student_id=student_user_id,
                    status='active',
                    subject='GENERAL'
                ).all()
                for enrollment in existing_active:
                    enrollment.status = 'archived'
            except Exception as e:
                logger.error(f"Error archiving enrollments for student {student_user_id}: {e}")
        return
        
    try:
        tutor_id_str = str(tutor_id).strip()
        tutor_id_int = int(tutor_id_str) if tutor_id_str else None
        
        if replace:
            existing_active = Enrollment.query.filter_by(
                student_id=student_user_id,
                status='active',
                subject='GENERAL'
            ).all()
            for enrollment in existing_active:
                if not tutor_id_int or enrollment.tutor_id != tutor_id_int:
                    enrollment.status = 'archived'
        
        if not tutor_id_int:
            return
        
        # Check if enrollment already exists
        existing = Enrollment.query.filter_by(
            student_id=student_user_id,
            tutor_id=tutor_id_int,
            subject='GENERAL'
        ).first()
        
        if existing:
            if existing.status != 'active':
                existing.status = 'active'
            return
        
        enrollment = Enrollment(
            student_id=student_user_id,
            tutor_id=tutor_id_int,
            subject='GENERAL', 
            status='active',
            created_at=moscow_now()
        )
        db.session.add(enrollment)
    except Exception as e:
        logger.error(f"Error assigning tutor {tutor_id} to student {student_user_id}: {e}")


def _manage_family_ties(target_user_id, target_role, related_ids, replace=False):
    """Manage FamilyTies for student (parents) or parent (children)"""
    if related_ids is None:
        return
        
    try:
        # related_ids can be a list of IDs
        if isinstance(related_ids, str):
            related_ids = [int(x.strip()) for x in related_ids.split(',') if x.strip()]
        
        new_ids = set(int(x) for x in related_ids if x)
        
        if target_role == 'student':
            # Add or remove parents
            current_ties = FamilyTie.query.filter_by(student_id=target_user_id).all()
            current_parent_ids = {t.parent_id for t in current_ties}
            
            if replace:
                for tie in current_ties:
                    if tie.parent_id not in new_ids:
                        db.session.delete(tie)
            
            for pid in new_ids:
                if pid not in current_parent_ids:
                    tie = FamilyTie(
                        parent_id=pid,
                        student_id=target_user_id,
                        access_level='full',
                        is_confirmed=True
                    )
                    db.session.add(tie)
                    
        elif target_role == 'parent':
            # Add or remove children
            current_ties = FamilyTie.query.filter_by(parent_id=target_user_id).all()
            current_child_ids = {t.student_id for t in current_ties}
            
            if replace:
                for tie in current_ties:
                    if tie.student_id not in new_ids:
                        db.session.delete(tie)
            
            for sid in new_ids:
                if sid not in current_child_ids:
                    tie = FamilyTie(
                        parent_id=target_user_id,
                        student_id=sid,
                        access_level='full',
                        is_confirmed=True
                    )
                    db.session.add(tie)
    except Exception as e:
        logger.error(f"Error managing family ties for {target_user_id}: {e}")


def _remote_admin_guard() -> bool:
    """Проверка токена для удаленной админки"""
    provided = request.headers.get('X-Admin-Token', '')
    
    if not provided:
        logger.warning(f"Remote admin API request without X-Admin-Token header: {request.path}")
        return False
    
    # Проверяем все возможные токены из переменных окружения
    # Production
    expected_prod = (os.environ.get('PRODUCTION_ADMIN_TOKEN') or '').strip()
    if expected_prod and hmac.compare_digest(provided, expected_prod):
        logger.debug(f"Remote admin request authenticated with PRODUCTION_ADMIN_TOKEN")
        return True
    
    # Sandbox
    expected_sandbox = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    if expected_sandbox and hmac.compare_digest(provided, expected_sandbox):
        logger.debug(f"Remote admin request authenticated with SANDBOX_ADMIN_TOKEN")
        return True
    
    # Admin
    expected_admin = (os.environ.get('ADMIN_ADMIN_TOKEN') or '').strip()
    if expected_admin and hmac.compare_digest(provided, expected_admin):
        logger.debug(f"Remote admin request authenticated with ADMIN_ADMIN_TOKEN")
        return True
    
    # Произвольные окружения (ENV_<NAME>_TOKEN)
    for key, value in os.environ.items():
        if key.startswith('ENV_') and key.endswith('_TOKEN'):
            token = value.strip()
            if token and hmac.compare_digest(provided, token):
                logger.debug(f"Remote admin request authenticated with {key}")
                return True
    
    logger.warning(f"Remote admin API request with invalid token: {request.path}, provided_token_preview: {provided[:10]}...")
    return False


@admin_bp.route('/internal/remote-admin/status', methods=['GET'])
@csrf.exempt
def remote_admin_status():
    """Статус окружения для удаленной админки"""
    logger.info(f"Remote admin status request received: path={request.path}, method={request.method}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    if not _remote_admin_guard():
        logger.warning(f"Remote admin status request rejected: no valid token")
        return jsonify({'error': 'unauthorized'}), 401
    
    logger.info(f"Remote admin status request authenticated successfully")
    
    try:
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        
        # Статистика по логам
        try:
            total_logs = AuditLog.query.count()
            today_logs = AuditLog.query.filter(
                func.date(AuditLog.timestamp) == func.current_date()
            ).count()
        except Exception:
            total_logs = 0
            today_logs = 0
        
        # Статус тех работ
        maintenance_status = MaintenanceMode.get_status()
        
        return jsonify({
            'status': 'ok',
            'stats': {
                'total_users': total_users,
                'active_users': active_users,
                'total_logs': total_logs,
                'today_logs': today_logs,
                'maintenance_enabled': maintenance_status.is_enabled
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/users', methods=['GET', 'POST'])
@csrf.exempt
def remote_admin_api_users():
    """API: Список пользователей или создание нового"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'POST':
            # Создание нового пользователя
            from werkzeug.security import generate_password_hash
            from core.db_models import moscow_now
            
            data = request.get_json() or {}
            logger.info(f"Creating user via remote admin API: {data}")
            username = data.get('username', '').strip()
            email = data.get('email', '').strip() or None
            password = data.get('password', '').strip()
            role = (data.get('role') or 'student').strip()  # comment
            is_active = data.get('is_active', True)  # comment
            platform_id = (data.get('platform_id') or '').strip() or None  # comment
            
            # Связи
            tutor_id = data.get('tutor_id')
            parent_ids = data.get('parent_ids', [])
            child_ids = data.get('child_ids', [])
            
            if not username:
                return jsonify({'error': 'username is required'}), 400
            
            if not password:
                return jsonify({'error': 'password is required'}), 400
            
            # Проверка уникальности
            if User.query.filter_by(username=username).first():
                return jsonify({'error': 'username already exists'}), 409
            
            if email and User.query.filter_by(email=email).first():
                return jsonify({'error': 'email already exists'}), 409
            
            # Если роль - студент, проверяем уникальность platform_id
            if role == 'student' and platform_id:
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id
                
                # Проверяем формат идентификатора
                if not is_valid_three_digit_id(platform_id):
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                # Проверяем уникальность
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
            
            # Создаем пользователя
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=is_active,
                created_at=moscow_now()
            )
            db.session.add(user)
            db.session.flush()
            
            # Создаем профиль
            profile = UserProfile(user_id=user.id)
            db.session.add(profile)
            
            # Если роль - студент, создаем запись Student
            if role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import assign_platform_id_if_needed
                
                # Проверяем, нет ли уже студента с таким email
                student_record = None
                if email:
                    student_record = Student.query.filter_by(email=email).first()
                
                if not student_record:
                    # Создаем новую запись Student
                    student_record = Student(
                        name=username,  # Используем username как имя по умолчанию
                        email=email,
                        platform_id=platform_id,
                        is_active=is_active
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    
                    # Автоматически присваиваем идентификатор, если не указан
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    # Обновляем существующую запись
                    student_record.name = username
                    student_record.email = email
                    student_record.is_active = is_active
                    if platform_id:
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        # Присваиваем идентификатор, если его нет
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                
                # Привязка тьютора
                if tutor_id:
                    _manage_student_tutor(user.id, tutor_id)
                
                # Привязка родителей
                if parent_ids:
                    _manage_family_ties(user.id, 'student', parent_ids)
            
            # Если роль - родитель, привязываем детей
            if role == 'parent' and child_ids:
                _manage_family_ties(user.id, 'parent', child_ids)
            
            db.session.commit()
            
            audit_logger.log(
                action='create_user',
                entity='User',
                entity_id=user.id,
                status='success',
                metadata={
                    'username': username,
                    'role': role,
                    'created_by_remote_admin': True
                }
            )
            
            return jsonify({
                'success': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active
                }
            }), 201
        
        else:
            # GET - список пользователей
            role_filter = request.args.get('role')
            is_active_filter = request.args.get('is_active')
            
            query = User.query
            
            if role_filter:
                query = query.filter(User.role == role_filter)
            if is_active_filter is not None:
                is_active = is_active_filter.lower() == 'true'
                query = query.filter(User.is_active == is_active)
            
            users = query.order_by(User.created_at.desc()).all()
            
            return jsonify({
                'success': True,
                'users': [{
                    'id': u.id,
                    'username': u.username,
                    'email': u.email,
                    'role': u.role,
                    'is_active': u.is_active,
                    'created_at': u.created_at.isoformat() if u.created_at else None,
                    'last_login': u.last_login.isoformat() if u.last_login else None
                } for u in users]
            })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_users: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/tasks/formator', methods=['GET'])
@csrf.exempt
def remote_admin_api_task_formator_list():
    """API: список заданий банка для формироватора (для remote-admin)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    q = (request.args.get('q') or '').strip()
    task_number = request.args.get('task_number', type=int)
    review_status = (request.args.get('review_status') or 'all').strip().lower()
    page = max(1, request.args.get('page', type=int) or 1)
    per_page = min(100, max(10, request.args.get('per_page', type=int) or 30))

    base = db.session.query(Tasks, TaskReview).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)

    if task_number:
        base = base.filter(Tasks.task_number == task_number)

    if q:
        like = f"%{q.lower()}%"
        base = base.filter(
            func.lower(Tasks.content_html).like(like) |
            func.lower(func.coalesce(Tasks.answer, '')).like(like) |
            func.lower(func.coalesce(Tasks.source_url, '')).like(like) |
            func.lower(func.coalesce(Tasks.site_task_id, '')).like(like)
        )

    if review_status != 'all':
        if review_status == 'new':
            base = base.filter((TaskReview.status.is_(None)) | (TaskReview.status == 'new'))
        else:
            base = base.filter(TaskReview.status == review_status)

    total = base.count()
    rows = base.order_by(Tasks.last_scraped.desc(), Tasks.task_id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # summary within current q/task_number (but ignoring review_status)
    summary_base = db.session.query(Tasks.task_id, TaskReview.status).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)
    if task_number:
        summary_base = summary_base.filter(Tasks.task_number == task_number)
    if q:
        like = f"%{q.lower()}%"
        summary_base = summary_base.filter(
            func.lower(Tasks.content_html).like(like) |
            func.lower(func.coalesce(Tasks.answer, '')).like(like) |
            func.lower(func.coalesce(Tasks.source_url, '')).like(like) |
            func.lower(func.coalesce(Tasks.site_task_id, '')).like(like)
        )
    summary_rows = summary_base.all()
    new_count = 0
    ok_count = 0
    needs_fix_count = 0
    skip_count = 0
    for _, st in summary_rows:
        stn = (st or 'new').lower()
        if stn == 'ok':
            ok_count += 1
        elif stn == 'needs_fix':
            needs_fix_count += 1
        elif stn == 'skip':
            skip_count += 1
        else:
            new_count += 1

    items = []
    for t, r in rows:
        st = (r.status if r else 'new') or 'new'
        items.append({
            'task_id': t.task_id,
            'task_number': t.task_number,
            'site_task_id': t.site_task_id,
            'source_url': t.source_url,
            'last_scraped': t.last_scraped.isoformat() if t.last_scraped else None,
            'review_status': st,
        })

    return jsonify({
        'success': True,
        'total': total,
        'page': page,
        'per_page': per_page,
        'summary': {
            'new': new_count,
            'ok': ok_count,
            'needs_fix': needs_fix_count,
            'skip': skip_count,
        },
        'items': items,
    })


@admin_bp.route('/internal/remote-admin/api/tasks/formator/<int:task_id>', methods=['GET'])
@csrf.exempt
def remote_admin_api_task_formator_task(task_id: int):
    """API: карточка задания + quick-checks + текущее ревью."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    task = Tasks.query.get_or_404(task_id)
    review = TaskReview.query.filter_by(task_id=task_id).first()
    checks = _task_formator_quick_checks(task)

    return jsonify({
        'success': True,
        'task': {
            'task_id': task.task_id,
            'task_number': task.task_number,
            'site_task_id': task.site_task_id,
            'source_url': task.source_url,
            'last_scraped': task.last_scraped.isoformat() if task.last_scraped else None,
            'content_html': task.content_html,
            'answer': task.answer or '',
        },
        'review': {
            'status': (review.status if review else 'new'),
            'notes': (review.notes if review else ''),
            'updated_at': (review.updated_at.isoformat() if review and review.updated_at else None),
        },
        'checks': checks,
    })


@admin_bp.route('/internal/remote-admin/api/tasks/formator/<int:task_id>/review', methods=['POST'])
@csrf.exempt
def remote_admin_api_task_formator_save(task_id: int):
    """API: сохранить ревью (status + notes)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    status = (payload.get('status') or 'new').strip().lower()
    notes = (payload.get('notes') or '').strip()
    if status not in ['new', 'ok', 'needs_fix', 'skip']:
        return jsonify({'success': False, 'error': 'Некорректный статус'}), 400

    task = Tasks.query.get_or_404(task_id)
    review = TaskReview.query.filter_by(task_id=task.task_id).first()
    if not review:
        review = TaskReview(task_id=task.task_id, status=status, notes=notes, reviewer_user_id=None)
        db.session.add(review)
    else:
        review.status = status
        review.notes = notes
        review.reviewer_user_id = None

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save TaskReview via remote-admin API: task_id={task_id}, err={e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Ошибка сохранения'}), 500

    return jsonify({
        'success': True,
        'status': review.status,
        'notes': review.notes or '',
        'updated_at': review.updated_at.isoformat() if review.updated_at else None,
    })


@admin_bp.route('/internal/remote-admin/api/users/<int:user_id>', methods=['GET', 'POST', 'DELETE'])
@csrf.exempt
def remote_admin_api_user(user_id):
    """API: Управление пользователем"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            # Получаем профиль
            profile = UserProfile.query.filter_by(user_id=user_id).first()
            
            # Получаем Student, если роль - студент
            student = None
            if user.role == 'student':
                from app.models import Student
                if user.email:
                    student = Student.query.filter_by(email=user.email).first()
                # Если не найден по email, ищем по связи через User.id (если есть такая связь)
                if not student:
                    # Пробуем найти по user_id, если есть поле user_id в Student
                    try:
                        student = Student.query.filter_by(user_id=user_id).first()
                    except:
                        pass
            
            user_data = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'profile': {
                    'first_name': profile.first_name if profile else None,
                    'last_name': profile.last_name if profile else None,
                    'phone': profile.phone if profile else None,
                } if profile else None
            }
            
            # Добавляем platform_id для студентов
            if student:
                user_data['student'] = {
                    'platform_id': student.platform_id,
                    'name': student.name
                }
            
            # Enrich with relationships
            if user.role == 'student':
                # Get tutor
                active_enrollment = Enrollment.query.filter_by(
                    student_id=user.id, 
                    status='active',
                    subject='GENERAL'
                ).first()
                if active_enrollment:
                    user_data['tutor_id'] = active_enrollment.tutor_id
                
                # Get parents
                ties = FamilyTie.query.filter_by(student_id=user.id).all()
                user_data['parent_ids'] = [t.parent_id for t in ties]
                
            elif user.role == 'parent':
                # Get children
                ties = FamilyTie.query.filter_by(parent_id=user.id).all()
                user_data['child_ids'] = [t.student_id for t in ties]
            
            return jsonify({
                'success': True,
                'user': user_data
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            if user.is_creator():
                return jsonify({'error': 'cannot modify creator'}), 403
            
            # Обновляем поля пользователя
            if 'username' in data:
                user.username = data['username']
            if 'email' in data:
                user.email = data['email'] or None
            if 'role' in data:
                user.role = data['role']
            if 'is_active' in data:
                user.is_active = bool(data['is_active'])
            
            # Обновляем пароль, если указан
            if 'password' in data and data['password']:
                from werkzeug.security import generate_password_hash
                user.password_hash = generate_password_hash(data['password'])
            
            # Если роль - студент, обновляем или создаем запись Student
            if user.role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id, assign_platform_id_if_needed
                
                platform_id = (data.get('platform_id') or '').strip() or None  # comment
                
                # Проверяем формат идентификатора, если указан
                if platform_id and not is_valid_three_digit_id(platform_id):
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                # Ищем существующую запись Student
                student_record = None
                if user.email:
                    student_record = Student.query.filter_by(email=user.email).first()
                
                # Если не найден по email, пробуем найти по user_id (если есть такая связь)
                if not student_record:
                    try:
                        student_record = Student.query.filter_by(user_id=user_id).first()
                    except:
                        pass
                
                if not student_record:
                    # Создаем новую запись Student
                    student_record = Student(
                        name=user.username,  # Используем username как имя по умолчанию
                        email=user.email,
                        platform_id=platform_id,
                        is_active=user.is_active
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    
                    # Автоматически присваиваем идентификатор, если не указан
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    # Обновляем существующую запись
                    student_record.name = user.username
                    student_record.email = user.email
                    student_record.is_active = user.is_active
                    
                    # Обновляем platform_id, если указан
                    if platform_id:
                        # Проверяем уникальность (кроме текущего студента)
                        existing = Student.query.filter(
                            Student.platform_id == platform_id,
                            Student.student_id != student_record.student_id
                        ).first()
                        if existing:
                            return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        # Присваиваем идентификатор, если его нет
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()

                # Привязка тьютора (обновление)
                if 'tutor_id' in data:
                    tutor_id = data['tutor_id']
                    _manage_student_tutor(user.id, tutor_id, replace=True)
                
                # Привязка родителей (обновление)
                if 'parent_ids' in data:
                    _manage_family_ties(user.id, 'student', data['parent_ids'], replace=True)
            
            # Если роль - родитель, обновляем детей
            if user.role == 'parent' and 'child_ids' in data:
                _manage_family_ties(user.id, 'parent', data['child_ids'], replace=True)
            
            db.session.commit()
            
            return jsonify({'success': True, 'user_id': user_id})
        
        elif request.method == 'DELETE':
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            if user.is_creator():
                return jsonify({'error': 'cannot delete creator'}), 403
            
            username = user.username
            
            # Удаляем логи
            try:
                deleted_logs = db.session.execute(
                    delete(AuditLog).where(AuditLog.user_id == user_id)
                ).rowcount
            except Exception as e:
                logger.warning(f"Error deleting user logs: {e}")
                db.session.rollback()
                deleted_logs = 0
            
            # Удаляем профиль
            try:
                profile = UserProfile.query.filter_by(user_id=user_id).first()
                if profile:
                    db.session.delete(profile)
            except Exception as e:
                logger.warning(f"Error deleting user profile: {e}")
            
            db.session.delete(user)
            db.session.commit()
            
            audit_logger.log(
                action='delete_user',
                entity='User',
                entity_id=user_id,
                status='success',
                metadata={
                    'username': username,
                    'deleted_logs': deleted_logs,
                    'deleted_by_remote_admin': True
                }
            )
            
            return jsonify({'success': True, 'deleted_logs': deleted_logs})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_user: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/stats', methods=['GET'])
@csrf.exempt
def remote_admin_api_stats():
    """API: Статистика окружения"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        stats = {
            'users': {
                'total': User.query.count(),
                'active': User.query.filter_by(is_active=True).count(),
                'by_role': {}
            },
            'students': {
                'total': Student.query.filter_by(is_active=True).count(),
                'archived': Student.query.filter_by(is_active=False).count()
            },
            'lessons': {
                'total': Lesson.query.count(),
                'completed': Lesson.query.filter_by(status='completed').count(),
                'planned': Lesson.query.filter_by(status='planned').count()
            }
        }
        
        # Статистика по ролям
        for role in ['admin', 'tutor', 'student', 'parent', 'tester', 'creator', 'chief_tester', 'designer']:
            stats['users']['by_role'][role] = User.query.filter_by(role=role).count()
        
        # Статистика по логам
        try:
            stats['audit_logs'] = {
                'total': AuditLog.query.count(),
                'today': AuditLog.query.filter(
                    func.date(AuditLog.timestamp) == func.current_date()
                ).count()
            }
        except Exception:
            stats['audit_logs'] = {'total': 0, 'today': 0}
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"Error in remote_admin_api_stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/audit-logs', methods=['GET'])
@csrf.exempt
def remote_admin_api_audit_logs():
    """API: Список логов действий"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        action_filter = request.args.get('action')
        user_id_filter = request.args.get('user_id')
        
        query = AuditLog.query
        
        if action_filter:
            query = query.filter(AuditLog.action == action_filter)
        if user_id_filter:
            query = query.filter(AuditLog.user_id == int(user_id_filter))
        
        logs = query.order_by(AuditLog.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'success': True,
            'logs': [{
                'id': log.id,
                'action': log.action,
                'entity': log.entity,
                'entity_id': log.entity_id,
                'user_id': log.user_id,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'status': log.status,
                'metadata': log.metadata
            } for log in logs.items],
            'pagination': {
                'page': logs.page,
                'per_page': logs.per_page,
                'total': logs.total,
                'pages': logs.pages
            }
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_audit_logs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/maintenance', methods=['GET', 'POST'])
@csrf.exempt
def remote_admin_api_maintenance():
    """API: Управление режимом обслуживания"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'GET':
            status = MaintenanceMode.get_status()
            return jsonify({
                'success': True,
                'status': {
                    'enabled': status.is_enabled,
                    'message': status.message,
                    'updated_at': status.updated_at.isoformat() if status.updated_at else None,
                    'updated_by': status.updated_by
                }
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            
            enabled = bool(data.get('enabled', False))
            message = data.get('message', '').strip()
            
            # Устанавливаем статус напрямую
            status = MaintenanceMode.get_status()
            status.is_enabled = enabled
            status.message = message
            status.updated_by = None  # System/Remote Admin
            db.session.commit()
            
            audit_logger.log(
                action='toggle_maintenance',
                entity='MaintenanceMode',
                entity_id=None,
                status='success',
                metadata={
                    'enabled': enabled,
                    'message': message,
                    'source': 'remote_admin'
                }
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        logger.error(f"Error in remote_admin_api_maintenance: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/testers', methods=['GET', 'POST'])
@csrf.exempt
def remote_admin_api_testers():
    """API: Управление тестерами (сущности Tester)"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    # Тестеры доступны только если модель существует (обычно Sandbox)
    try:
        from core.db_models import Tester
    except ImportError:
        return jsonify({'error': 'Tester model not found'}), 501
    
    try:
        if request.method == 'GET':
            testers = Tester.query.order_by(Tester.created_at.desc()).all()
            return jsonify({
                'success': True,
                'testers': [{
                    'id': t.id,
                    'name': t.name,
                    'is_active': t.is_active,
                    'created_at': t.created_at.isoformat() if t.created_at else None
                } for t in testers]
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            name = data.get('name', '').strip()
            is_active = bool(data.get('is_active', True))
            
            if not name:
                return jsonify({'error': 'name is required'}), 400
                
            tester = Tester(
                name=name,
                is_active=is_active,
                created_at=moscow_now()
            )
            db.session.add(tester)
            db.session.commit()
            
            audit_logger.log(
                action='create_tester',
                entity='Tester',
                entity_id=tester.id,
                status='success',
                metadata={'name': name, 'source': 'remote_admin'}
            )
            
            return jsonify({'success': True, 'tester_id': tester.id})
            
    except Exception as e:
        logger.error(f"Error in remote_admin_api_testers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/testers/<int:tester_id>', methods=['POST', 'DELETE'])
@csrf.exempt
def remote_admin_api_tester(tester_id):
    """API: Управление конкретным тестером"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
        
    try:
        from core.db_models import Tester
    except ImportError:
        return jsonify({'error': 'Tester model not found'}), 501
    
    try:
        tester = Tester.query.get(tester_id)
        if not tester:
            return jsonify({'error': 'tester not found'}), 404
            
        if request.method == 'POST':
            # Обновление (toggle active или edit)
            data = request.get_json() or {}
            
            if 'is_active' in data:
                tester.is_active = bool(data['is_active'])
            
            if 'name' in data:
                tester.name = data['name'].strip()
                
            db.session.commit()
            return jsonify({'success': True})
            
        elif request.method == 'DELETE':
            db.session.delete(tester)
            db.session.commit()
            
            audit_logger.log(
                action='delete_tester',
                entity='Tester',
                entity_id=tester_id,
                status='success',
                metadata={'source': 'remote_admin'}
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_tester: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/permissions', methods=['GET', 'POST'])
@csrf.exempt
def remote_admin_api_permissions():
    """API: Управление правами доступа"""
    logger.info(f"Remote admin permissions API request: method={request.method}, path={request.path}")
    
    if not _remote_admin_guard():
        logger.warning(f"Remote admin permissions API request rejected: no valid token")
        return jsonify({'error': 'unauthorized'}), 401
    
    logger.info(f"Remote admin permissions API request authenticated successfully")
    
    try:
        if request.method == 'GET':
            # Все возможные роли в системе
            ALL_ROLES = ['creator', 'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer']
            
            # Получаем все права из БД
            try:
                role_permissions = RolePermission.query.all()
                
                # Если в базе нет прав, инициализируем их из DEFAULT_ROLE_PERMISSIONS
                if len(role_permissions) == 0:
                    logger.info("No role permissions found in database. Initializing from DEFAULT_ROLE_PERMISSIONS...")
                    try:
                        count = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
                                # Проверяем, что право существует в ALL_PERMISSIONS
                                if perm_name not in ALL_PERMISSIONS:
                                    logger.warning(f"Permission '{perm_name}' not found in ALL_PERMISSIONS, skipping")
                                    continue
                                
                                rp = RolePermission(
                                    role=role, 
                                    permission_name=perm_name, 
                                    is_enabled=True
                                )
                                db.session.add(rp)
                                count += 1
                        
                        db.session.commit()
                        logger.info(f"Initialized {count} default permission records")
                        
                        # Перезагружаем права из БД
                        role_permissions = RolePermission.query.all()
                    except Exception as init_error:
                        db.session.rollback()
                        logger.error(f"Error initializing default permissions: {init_error}", exc_info=True)
                        # Продолжаем работу, даже если инициализация не удалась
                
                permissions_map = {}
                
                # Инициализируем все роли пустыми списками
                for role in ALL_ROLES:
                    permissions_map[role] = []
                
                # Заполняем правами из БД
                for rp in role_permissions:
                    if rp.role not in permissions_map:
                        permissions_map[rp.role] = []
                    # Используем только включенные права (is_enabled=True)
                    if rp.is_enabled:
                        permissions_map[rp.role].append(rp.permission_name)
                
                logger.debug(f"Found {len(role_permissions)} role permissions, {len(permissions_map)} roles")
                logger.debug(f"Roles in permissions_map: {list(permissions_map.keys())}")
                logger.debug(f"ALL_PERMISSIONS count: {len(ALL_PERMISSIONS) if ALL_PERMISSIONS else 0}")
                logger.debug(f"PERMISSION_CATEGORIES count: {len(PERMISSION_CATEGORIES) if PERMISSION_CATEGORIES else 0}")
            except Exception as db_error:
                logger.error(f"Database error in permissions GET: {db_error}", exc_info=True)
                raise
            
            # Проверяем, что ALL_PERMISSIONS и PERMISSION_CATEGORIES доступны
            try:
                all_perms = dict(ALL_PERMISSIONS) if ALL_PERMISSIONS else {}
                perm_cats = dict(PERMISSION_CATEGORIES) if PERMISSION_CATEGORIES else {}
            except Exception as e:
                logger.error(f"Error converting permissions to dict: {e}", exc_info=True)
                all_perms = {}
                perm_cats = {}
            
            return jsonify({
                'success': True,
                'roles_permissions': permissions_map,
                'all_permissions': all_perms,
                'permission_categories': perm_cats
            })
            
        elif request.method == 'POST':
            data = request.get_json() or {}
            role = data.get('role')
            permissions = data.get('permissions', []) # Список permissions для этой роли
            
            if not role:
                return jsonify({'error': 'role is required'}), 400
                
            # Удаляем старые права для роли
            db.session.execute(
                delete(RolePermission).where(RolePermission.role == role)
            )
            
            # Добавляем новые
            for perm in permissions:
                if perm in ALL_PERMISSIONS:
                    rp = RolePermission(role=role, permission_name=perm, is_enabled=True)
                    db.session.add(rp)
            
            db.session.commit()
            
            audit_logger.log(
                action='update_permissions',
                entity='RolePermission',
                entity_id=None,
                status='success',
                metadata={'role': role, 'count': len(permissions), 'source': 'remote_admin'}
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_permissions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
