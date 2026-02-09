"""
Внутренние API endpoints для удаленной админки
Доступны из production и sandbox окружений для управления через remote_admin
"""
import logging
import hmac
import os
from datetime import datetime
from flask import request, jsonify
from sqlalchemy import func, delete
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.admin import admin_bp
import re

from app.models import User, AuditLog, MaintenanceMode, db, UserProfile, Tasks, TaskReview
from app.models import FamilyTie, Enrollment, Student, Lesson, RolePermission, UserRole
from app.models import BotAdmin, BotErrorReport, UserNotification
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


def _task_formator_extract_source_url(content_html: str) -> str:
    """Пытаемся восстановить ссылку на источник из HTML условия (если поле source_url пустое)."""
    if not content_html:
        return ''

    html = str(content_html)

    m = re.search(r'href\s*=\s*["\'](https?://[^"\']+)["\']', html, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m2 = re.search(r'(https?://[^\s<>"\']+)', html, flags=re.IGNORECASE)
    if m2:
        return m2.group(1).strip().rstrip(').,;')

    return ''


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

    src_db = (task.source_url or '').strip()
    src_html = _task_formator_extract_source_url(task.content_html or '')
    if not src_db:
        if src_html:
            checks.append({'level': 'ok', 'title': 'Источник найден в условии', 'details': f'Поле source_url пустое, но в HTML найден URL: {src_html}'})
        elif (task.site_task_id or '').strip():
            checks.append({'level': 'warn', 'title': 'Нет source_url', 'details': 'Есть site_task_id, но source_url пустой — вероятно, потерялась ссылка при парсинге/импорте.'})
        else:
            checks.append({'level': 'ok', 'title': 'Нет источника (ручное задание?)', 'details': 'У задания нет source_url и site_task_id. Для ручных задач это нормально.'})

    if not checks:
        checks.append({'level': 'ok', 'title': 'Базовые проверки пройдены', 'details': 'Явных проблем не найдено.'})

    return checks

try:
    from app import csrf
except ImportError:
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
        if isinstance(related_ids, str):
            related_ids = [int(x.strip()) for x in related_ids.split(',') if x.strip()]
        
        new_ids = set(int(x) for x in related_ids if x)
        
        if target_role == 'student':
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
    """Проверка доступа: сессия создателя (вызовы из браузера с той же админки) или токен."""
    try:
        from flask_login import current_user
        if current_user.is_authenticated and getattr(current_user, 'is_creator', lambda: False)():
            return True
    except Exception:
        pass
    provided = request.headers.get('X-Admin-Token', '')
    if not provided:
        logger.warning(f"Remote admin API request without X-Admin-Token header: {request.path}")
        return False
    
    expected_prod = (os.environ.get('PRODUCTION_ADMIN_TOKEN') or '').strip()
    if expected_prod and hmac.compare_digest(provided, expected_prod):
        logger.debug(f"Remote admin request authenticated with PRODUCTION_ADMIN_TOKEN")
        return True
    
    expected_sandbox = (os.environ.get('SANDBOX_ADMIN_TOKEN') or '').strip()
    if expected_sandbox and hmac.compare_digest(provided, expected_sandbox):
        logger.debug(f"Remote admin request authenticated with SANDBOX_ADMIN_TOKEN")
        return True
    
    expected_admin = (os.environ.get('ADMIN_ADMIN_TOKEN') or '').strip()
    if expected_admin and hmac.compare_digest(provided, expected_admin):
        logger.debug(f"Remote admin request authenticated with ADMIN_ADMIN_TOKEN")
        return True
    
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
        
        try:
            total_logs = AuditLog.query.count()
            today_logs = AuditLog.query.filter(
                func.date(AuditLog.timestamp) == func.current_date()
            ).count()
        except Exception:
            total_logs = 0
            today_logs = 0
        
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


@admin_bp.route('/internal/remote-admin/api/username-available', methods=['GET'])
@csrf.exempt
def remote_admin_api_username_available():
    """API: Проверка доступности логина (для мгновенной проверки в удалённой админке)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    username = (request.args.get('username') or '').strip()
    if not username:
        return jsonify({'available': False, 'error': 'username is required'}), 400
    try:
        exclude_user_id = request.args.get('exclude_user_id', type=int)
        q = User.query.filter(func.lower(User.username) == username.lower())
        if exclude_user_id is not None:
            q = q.filter(User.id != exclude_user_id)
        existing = q.first()
        return jsonify({'available': existing is None, 'username': username})
    except Exception as e:
        logger.error(f"Error in username-available: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/platform-id-available', methods=['GET'])
@csrf.exempt
def remote_admin_api_platform_id_available():
    """API: Проверка доступности числового идентификатора ученика (#100–999) для удалённой админки."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    raw = (request.args.get('platform_id') or '').strip()
    if not raw:
        return jsonify({'available': False, 'error': 'platform_id is required'}), 400
    try:
        from app.utils.student_id_manager import is_valid_three_digit_id
        if not is_valid_three_digit_id(raw):
            return jsonify({'available': False, 'error': 'Идентификатор должен быть числом от 100 до 999', 'platform_id': raw})
        exclude_user_id = request.args.get('exclude_user_id', type=int)
        q = Student.query.filter(Student.platform_id == raw)
        if exclude_user_id is not None:
            q = q.filter(Student.user_id != exclude_user_id)
        existing = q.first()
        return jsonify({'available': existing is None, 'platform_id': raw})
    except Exception as e:
        logger.error(f"Error in platform-id-available: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/numeric-id-available', methods=['GET'])
@csrf.exempt
def remote_admin_api_numeric_id_available():
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    raw = (request.args.get('numeric_id') or '').strip()
    if not raw:
        return jsonify({'available': False, 'error': 'numeric_id is required'}), 400
    try:
        from app.utils.numeric_id_manager import is_valid_numeric_id_manual
        if not is_valid_numeric_id_manual(raw):
            return jsonify({'available': False, 'error': 'Укажите положительное число', 'numeric_id': raw})
        exclude_user_id = request.args.get('exclude_user_id', type=int)
        q = User.query.filter(User.numeric_id == raw)
        if exclude_user_id is not None:
            q = q.filter(User.id != exclude_user_id)
        existing = q.first()
        return jsonify({'available': existing is None, 'numeric_id': raw})
    except Exception as e:
        logger.error(f"Error in numeric-id-available: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/users', methods=['GET', 'POST'])
@csrf.exempt
def remote_admin_api_users():
    """API: Список пользователей или создание нового"""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        if request.method == 'POST':
            from werkzeug.security import generate_password_hash
            from core.db_models import moscow_now
            
            data = request.get_json() or {}
            logger.info(f"Creating user via remote admin API: {data}")
            username = data.get('username', '').strip()
            telegram_link = data.get('telegram_link', '').strip() or None
            password = data.get('password', '').strip()
            roles_raw = data.get('roles')
            if isinstance(roles_raw, list) and roles_raw:
                roles = [str(r).strip() for r in roles_raw if r]
            else:
                role_single = (data.get('role') or 'student').strip()
                roles = [role_single] if role_single else ['student']
            role = roles[0]
            is_active = data.get('is_active', True)
            platform_id = (data.get('platform_id') or '').strip() or None
            numeric_id = (data.get('numeric_id') or '').strip() or None
            
            tutor_id = data.get('tutor_id')
            parent_ids = data.get('parent_ids', [])
            child_ids = data.get('child_ids', [])
            
            if not username:
                return jsonify({'error': 'username is required'}), 400
            
            if not password:
                return jsonify({'error': 'password is required'}), 400
            
            if User.query.filter_by(username=username).first():
                return jsonify({'error': 'username already exists'}), 409
            
            if role == 'student' and platform_id:
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id
                
                if not is_valid_three_digit_id(platform_id):
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                existing_student = Student.query.filter_by(platform_id=platform_id).first()
                if existing_student:
                    return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
            
            if role != 'student' and 'student' not in roles:
                from app.utils.numeric_id_manager import is_valid_numeric_id_manual, assign_numeric_id_if_needed
                if numeric_id:
                    if not is_valid_numeric_id_manual(numeric_id):
                        return jsonify({'error': 'numeric_id должен быть положительным числом'}), 400
                    if User.query.filter_by(numeric_id=numeric_id).first():
                        return jsonify({'error': f'Идентификатор «{numeric_id}» уже занят'}), 409
            
            user = User(
                username=username,
                email=None,
                telegram_link=telegram_link,
                password_hash=generate_password_hash(password),
                role=role,
                is_active=is_active,
                created_at=moscow_now()
            )
            if role != 'student' and numeric_id:
                user.numeric_id = numeric_id
            db.session.add(user)
            db.session.flush()
            
            for r in roles:
                if r and not UserRole.query.filter_by(user_id=user.id, role=r).first():
                    db.session.add(UserRole(user_id=user.id, role=r))
            
            if role != 'student' and not user.numeric_id:
                from app.utils.numeric_id_manager import assign_numeric_id_if_needed
                assign_numeric_id_if_needed(user)
            
            profile = UserProfile(user_id=user.id)
            db.session.add(profile)
            
            if role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import assign_platform_id_if_needed
                student_record = Student.query.filter_by(user_id=user.id).first()
                if not student_record:
                    student_record = Student(
                        name=username,
                        email=None,
                        platform_id=platform_id,
                        is_active=is_active,
                        user_id=user.id
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    student_record.name = username
                    student_record.is_active = is_active
                    if platform_id:
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                if tutor_id:
                    _manage_student_tutor(user.id, tutor_id)
                
                if parent_ids:
                    _manage_family_ties(user.id, 'student', parent_ids)
            
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
                    'role': user.role,
                    'is_active': user.is_active
                }
            }), 201
        
        else:
            role_filter = request.args.get('role')
            is_active_filter = request.args.get('is_active')
            
            query = User.query
            
            if role_filter:
                ids_subq = db.session.query(User.id).join(UserRole, User.id == UserRole.user_id).filter(UserRole.role == role_filter).distinct()
                query = query.filter(User.id.in_(ids_subq))
            if is_active_filter is not None:
                is_active = is_active_filter.lower() == 'true'
                query = query.filter(User.is_active == is_active)
            
            users = query.order_by(User.created_at.desc()).all()
            
            return jsonify({
                'success': True,
                'users': [{
                    'id': u.id,
                    'username': u.username,
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


@admin_bp.route('/internal/remote-admin/api/users/graph', methods=['GET'])
@csrf.exempt
def remote_admin_api_users_graph():
    """
    API: Граф связей пользователей (для визуализации карточками/стрелками в remote-admin).

    Узлы: Users (по умолчанию tutor/student/parent)
    Рёбра:
    - Enrollment (tutor -> student) с subject/status
    - FamilyTie (parent -> student) с access_level/is_confirmed
    """
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        include_inactive = str(request.args.get('include_inactive', 'true')).lower() == 'true'
        all_enrollments = str(request.args.get('all_enrollments', 'false')).lower() == 'true'
        roles_raw = (request.args.get('roles') or '').strip()
        roles = [r.strip() for r in roles_raw.split(',') if r.strip()] if roles_raw else ['tutor', 'student', 'parent']
        roles = [r for r in roles if r in ('creator', 'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer')]
        if not roles:
            roles = ['tutor', 'student', 'parent']

        q = User.query.filter(User.role.in_(roles))
        if not include_inactive:
            q = q.filter(User.is_active == True)  # noqa: E712
        users = q.order_by(User.username.asc()).all()

        user_ids = [u.id for u in users]
        users_by_id = {u.id: u for u in users}

        profiles = UserProfile.query.filter(UserProfile.user_id.in_(user_ids)).all() if user_ids else []
        profiles_by_user_id = {p.user_id: p for p in profiles}

        nodes = []
        for u in users:
            p = profiles_by_user_id.get(u.id)
            display_name = (f"{(p.first_name or '').strip()} {(p.last_name or '').strip()}").strip() if p else ''
            nodes.append({
                'id': u.id,
                'username': u.username,
                'role': u.role,
                'is_active': bool(u.is_active),
                'display_name': display_name or None,
                'timezone': (p.timezone if p else None),
            })

        enrollment_edges = []
        enr_q = Enrollment.query
        try:
            enr_q = enr_q.filter(Enrollment.status != 'archived')
        except Exception:
            pass
        enrollments = enr_q.all()

        def _enr_rank(status: str) -> int:
            s = (status or '').strip().lower()
            if s == 'active':
                return 2
            if s == 'paused':
                return 1
            if s == 'archived':
                return 0
            return 1

        if all_enrollments:
            for e in enrollments:
                if e.tutor_id not in users_by_id or e.student_id not in users_by_id:
                    continue
                enrollment_edges.append({
                    'enrollment_id': e.enrollment_id,
                    'from_id': e.tutor_id,
                    'to_id': e.student_id,
                    'subject': e.subject,
                    'status': getattr(e, 'status', None) or 'active',
                })
        else:
            best_by_pair = {}
            for e in enrollments:
                if e.tutor_id not in users_by_id or e.student_id not in users_by_id:
                    continue
                key = (e.tutor_id, e.student_id)
                cur = best_by_pair.get(key)
                if not cur:
                    best_by_pair[key] = e
                    continue
                e_score = (_enr_rank(getattr(e, 'status', None)), getattr(e, 'updated_at', None) or getattr(e, 'created_at', None))
                c_score = (_enr_rank(getattr(cur, 'status', None)), getattr(cur, 'updated_at', None) or getattr(cur, 'created_at', None))
                if e_score > c_score:
                    best_by_pair[key] = e
            for e in best_by_pair.values():
                enrollment_edges.append({
                    'enrollment_id': e.enrollment_id,
                    'from_id': e.tutor_id,
                    'to_id': e.student_id,
                    'subject': e.subject,
                    'status': getattr(e, 'status', None) or 'active',
                })

        ties = FamilyTie.query.all()
        family_edges = []
        for t in ties:
            if t.parent_id not in users_by_id or t.student_id not in users_by_id:
                continue
            family_edges.append({
                'tie_id': t.tie_id,
                'from_id': t.parent_id,
                'to_id': t.student_id,
                'access_level': t.access_level,
                'is_confirmed': bool(t.is_confirmed),
            })

        return jsonify({
            'success': True,
            'nodes': nodes,
            'enrollments': enrollment_edges,
            'family_ties': family_edges,
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_users_graph: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/family-ties/<int:tie_id>', methods=['POST', 'DELETE'])
@csrf.exempt
def remote_admin_api_family_tie_manage(tie_id: int):
    """API: Обновление/удаление FamilyTie (для графа связей)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    tie = FamilyTie.query.get(tie_id)
    if not tie:
        return jsonify({'success': False, 'error': 'tie not found'}), 404

    try:
        if request.method == 'DELETE':
            db.session.delete(tie)
            db.session.commit()
            return jsonify({'success': True})

        data = request.get_json() or {}
        access_level = (data.get('access_level') or '').strip() or None
        is_confirmed = data.get('is_confirmed')

        if access_level is not None:
            allowed = {'full', 'financial_only', 'schedule_only'}
            if access_level not in allowed:
                return jsonify({'success': False, 'error': f'invalid access_level: {access_level}'}), 400
            tie.access_level = access_level

        if is_confirmed is not None:
            tie.is_confirmed = bool(is_confirmed)

        db.session.commit()
        return jsonify({
            'success': True,
            'tie': {
                'tie_id': tie.tie_id,
                'parent_id': tie.parent_id,
                'student_id': tie.student_id,
                'access_level': tie.access_level,
                'is_confirmed': bool(tie.is_confirmed),
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_family_tie_manage: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/enrollments/<int:enrollment_id>', methods=['POST', 'DELETE'])
@csrf.exempt
def remote_admin_api_enrollment_manage(enrollment_id: int):
    """API: Обновление/удаление Enrollment (для графа связей)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    enrollment = Enrollment.query.get(enrollment_id)
    if not enrollment:
        return jsonify({'success': False, 'error': 'enrollment not found'}), 404

    try:
        if request.method == 'DELETE':
            db.session.delete(enrollment)
            db.session.commit()
            return jsonify({'success': True})

        data = request.get_json() or {}
        status = (data.get('status') or '').strip() or None
        subject = (data.get('subject') or '').strip() or None

        if subject is not None:
            enrollment.subject = subject
        if status is not None:
            allowed = {'active', 'paused', 'archived'}
            if status not in allowed:
                return jsonify({'success': False, 'error': f'invalid status: {status}'}), 400
            enrollment.status = status
            try:
                enrollment.is_active = (status == 'active')
            except Exception:
                pass

        db.session.commit()
        return jsonify({
            'success': True,
            'enrollment': {
                'enrollment_id': enrollment.enrollment_id,
                'tutor_id': enrollment.tutor_id,
                'student_id': enrollment.student_id,
                'subject': enrollment.subject,
                'status': getattr(enrollment, 'status', None) or 'active',
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_enrollment_manage: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/family-ties', methods=['POST'])
@csrf.exempt
def remote_admin_api_family_tie_create():
    """API: Создание FamilyTie (для графа связей)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        parent_id = data.get('parent_id')
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                parent_id = None
        student_id = data.get('student_id')
        if student_id is not None:
            try:
                student_id = int(student_id)
            except (ValueError, TypeError):
                student_id = None
        access_level = (data.get('access_level') or 'full').strip()
        is_confirmed = data.get('is_confirmed', True)

        if not parent_id or not student_id:
            return jsonify({'success': False, 'error': 'parent_id and student_id are required'}), 400

        parent = User.query.get(parent_id)
        student = User.query.get(student_id)
        if not parent or not student:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if not parent.is_parent():
            return jsonify({'success': False, 'error': 'User is not a parent'}), 400
        if not student.is_student():
            return jsonify({'success': False, 'error': 'User is not a student'}), 400

        existing = FamilyTie.query.filter_by(parent_id=parent_id, student_id=student_id).first()
        if existing:
            return jsonify({'success': False, 'error': 'Family tie already exists'}), 409

        allowed = {'full', 'financial_only', 'schedule_only'}
        if access_level not in allowed:
            return jsonify({'success': False, 'error': f'invalid access_level: {access_level}'}), 400

        tie = FamilyTie(
            parent_id=parent_id,
            student_id=student_id,
            access_level=access_level,
            is_confirmed=bool(is_confirmed)
        )
        db.session.add(tie)
        db.session.commit()
        return jsonify({
            'success': True,
            'tie': {
                'tie_id': tie.tie_id,
                'parent_id': tie.parent_id,
                'student_id': tie.student_id,
                'access_level': tie.access_level,
                'is_confirmed': bool(tie.is_confirmed),
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_family_tie_create: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/enrollments', methods=['POST'])
@csrf.exempt
def remote_admin_api_enrollment_create():
    """API: Создание Enrollment (для графа связей)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        tutor_id = data.get('tutor_id')
        if tutor_id is not None:
            try:
                tutor_id = int(tutor_id)
            except (ValueError, TypeError):
                tutor_id = None
        student_id = data.get('student_id')
        if student_id is not None:
            try:
                student_id = int(student_id)
            except (ValueError, TypeError):
                student_id = None
        subject = (data.get('subject') or 'GENERAL').strip()
        status = (data.get('status') or 'active').strip()

        if not tutor_id or not student_id:
            return jsonify({'success': False, 'error': 'tutor_id and student_id are required'}), 400

        tutor = User.query.get(tutor_id)
        student = User.query.get(student_id)
        if not tutor or not student:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if not tutor.is_tutor():
            return jsonify({'success': False, 'error': 'User is not a tutor'}), 400
        if not student.is_student():
            return jsonify({'success': False, 'error': 'User is not a student'}), 400

        allowed = {'active', 'paused', 'archived'}
        if status not in allowed:
            return jsonify({'success': False, 'error': f'invalid status: {status}'}), 400

        enrollment = Enrollment(
            tutor_id=tutor_id,
            student_id=student_id,
            subject=subject,
            status=status
        )
        try:
            enrollment.is_active = (status == 'active')
        except Exception:
            pass
        db.session.add(enrollment)
        db.session.commit()
        return jsonify({
            'success': True,
            'enrollment': {
                'enrollment_id': enrollment.enrollment_id,
                'tutor_id': enrollment.tutor_id,
                'student_id': enrollment.student_id,
                'subject': enrollment.subject,
                'status': getattr(enrollment, 'status', None) or 'active',
            }
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_enrollment_create: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/tasks/formator', methods=['GET'])
@csrf.exempt
def remote_admin_api_task_formator_list():
    """API: список заданий банка для формироватора (для remote-admin)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    q = (request.args.get('q') or '').strip()
    task_number = request.args.get('task_number', type=int)
    review_status = (request.args.get('review_status') or 'all').strip().lower()
    only_parsed_raw = (request.args.get('only_parsed') or '1').strip().lower()
    only_parsed = only_parsed_raw in ('1', 'true', 'yes', 'on')
    page = max(1, request.args.get('page', type=int) or 1)
    per_page = min(100, max(10, request.args.get('per_page', type=int) or 30))

    base = db.session.query(Tasks, TaskReview).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)
    if only_parsed:
        base = base.filter(
            (func.coalesce(Tasks.site_task_id, '') != '') |
            (func.coalesce(Tasks.source_url, '') != '')
        )

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

    summary_base = db.session.query(Tasks.task_id, TaskReview.status).outerjoin(TaskReview, TaskReview.task_id == Tasks.task_id)
    if only_parsed:
        summary_base = summary_base.filter(
            (func.coalesce(Tasks.site_task_id, '') != '') |
            (func.coalesce(Tasks.source_url, '') != '')
        )
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
        derived = _task_formator_extract_source_url(t.content_html or '') if not (t.source_url or '').strip() else ''
        effective_source = (t.source_url or '').strip() or derived or None
        items.append({
            'task_id': t.task_id,
            'task_number': t.task_number,
            'site_task_id': t.site_task_id,
            'source_url': effective_source,
            'last_scraped': t.last_scraped.isoformat() if t.last_scraped else None,
            'review_status': st,
        })

    return jsonify({
        'success': True,
        'total': total,
        'page': page,
        'per_page': per_page,
        'only_parsed': only_parsed,
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
    derived = _task_formator_extract_source_url(task.content_html or '') if not (task.source_url or '').strip() else ''
    effective_source = (task.source_url or '').strip() or derived or None

    return jsonify({
        'success': True,
        'task': {
            'task_id': task.task_id,
            'task_number': task.task_number,
            'site_task_id': task.site_task_id,
            'source_url': effective_source,
            'source_url_kind': 'db' if (task.source_url or '').strip() else ('html' if derived else None),
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
            
            profile = UserProfile.query.filter_by(user_id=user_id).first()
            
            student = None
            if user.role == 'student':
                from app.models import Student
                student = Student.query.filter_by(user_id=user_id).first()
            
            user_data = {
                'id': user.id,
                'username': user.username,
                'telegram_link': user.telegram_link,
                'role': user.role,
                'roles': user.roles(),
                'numeric_id': user.numeric_id,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'profile': {
                    'first_name': profile.first_name if profile else None,
                    'last_name': profile.last_name if profile else None,
                    'phone': profile.phone if profile else None,
                } if profile else None
            }
            
            if student:
                user_data['student'] = {
                    'platform_id': student.platform_id,
                    'name': student.name
                }
            
            if user.role == 'student':
                active_enrollment = Enrollment.query.filter_by(
                    student_id=user.id, 
                    status='active',
                    subject='GENERAL'
                ).first()
                if active_enrollment:
                    user_data['tutor_id'] = active_enrollment.tutor_id
                
                ties = FamilyTie.query.filter_by(student_id=user.id).all()
                user_data['parent_ids'] = [t.parent_id for t in ties]
                
            elif user.role == 'parent':
                ties = FamilyTie.query.filter_by(parent_id=user.id).all()
                user_data['child_ids'] = [t.student_id for t in ties]
            
            return jsonify({
                'success': True,
                'user': user_data
            })
        
        elif request.method == 'POST':
            data = request.get_json() or {}
            logger.info("remote_admin_api_user POST user_id=%s data_keys=%s", user_id, list(data.keys()))
            user = User.query.get(user_id)
            if not user:
                logger.warning("remote_admin_api_user POST user_id=%s early return: user not found", user_id)
                return jsonify({'error': 'user not found'}), 404
            
            if 'username' in data:
                new_username = (data['username'] or '').strip()
                if not new_username:
                    logger.warning("remote_admin_api_user POST user_id=%s early return: username empty", user_id)
                    return jsonify({'error': 'username не может быть пустым'}), 400
                other = User.query.filter(func.lower(User.username) == new_username.lower()).filter(User.id != user_id).first()
                if other:
                    logger.warning("remote_admin_api_user POST user_id=%s early return: username taken by id=%s", user_id, other.id)
                    return jsonify({'error': f'Логин «{new_username}» уже занят'}), 409
                user.username = new_username
            if 'telegram_link' in data:
                user.telegram_link = data['telegram_link'] or None
            effective_roles = None
            if 'roles' in data:
                roles_list = data['roles'] if isinstance(data['roles'], list) else [data.get('role', user.role)]
                roles_list = [str(r).strip() for r in roles_list if r]
                if roles_list:
                    UserRole.query.filter_by(user_id=user_id).delete()
                    for r in roles_list:
                        db.session.add(UserRole(user_id=user_id, role=r))
                    user.role = roles_list[0]
                    effective_roles = roles_list
            elif 'role' in data:
                user.role = data['role']
                if not UserRole.query.filter_by(user_id=user_id).first():
                    db.session.add(UserRole(user_id=user_id, role=user.role))
            if 'is_active' in data:
                user.is_active = bool(data['is_active'])
            if effective_roles is None:
                effective_roles = user.roles() if hasattr(user, 'roles') and callable(getattr(user, 'roles')) else [user.role]
            if 'numeric_id' in data and 'student' not in effective_roles:
                from app.utils.numeric_id_manager import is_valid_numeric_id_manual, assign_numeric_id_if_needed
                raw = (data.get('numeric_id') or '').strip() or None
                if raw:
                    if not is_valid_numeric_id_manual(raw):
                        logger.warning("remote_admin_api_user POST user_id=%s early return: numeric_id invalid", user_id)
                        return jsonify({'error': 'numeric_id должен быть положительным числом'}), 400
                    other = User.query.filter(User.numeric_id == raw, User.id != user_id).first()
                    if other:
                        logger.warning("remote_admin_api_user POST user_id=%s early return: numeric_id taken by id=%s", user_id, other.id)
                        return jsonify({'error': f'Идентификатор «{raw}» уже занят'}), 409
                    user.numeric_id = raw
                else:
                    user.numeric_id = None
                    assign_numeric_id_if_needed(user)
            elif 'student' in effective_roles and not any(r != 'student' for r in effective_roles):
                user.numeric_id = None
            
            if 'password' in data and data['password']:
                from werkzeug.security import generate_password_hash
                user.password_hash = generate_password_hash(data['password'])
            
            if user.role == 'student':
                from app.models import Student
                from app.utils.student_id_manager import is_valid_three_digit_id, assign_platform_id_if_needed
                
                platform_id = (data.get('platform_id') or '').strip() or None  # comment
                
                if platform_id and not is_valid_three_digit_id(platform_id):
                    logger.warning("remote_admin_api_user POST user_id=%s early return: platform_id invalid", user_id)
                    return jsonify({'error': 'platform_id must be a three-digit number between 100 and 999'}), 400
                
                student_record = Student.query.filter_by(user_id=user_id).first()
                if not student_record:
                    student_record = Student(
                        name=user.username,
                        email=None,
                        platform_id=platform_id,
                        is_active=user.is_active,
                        user_id=user_id
                    )
                    db.session.add(student_record)
                    db.session.flush()
                    if not platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()
                else:
                    student_record.name = user.username
                    student_record.is_active = user.is_active
                    
                    if platform_id:
                        existing = Student.query.filter(
                            Student.platform_id == platform_id,
                            Student.student_id != student_record.student_id
                        ).first()
                        if existing:
                            logger.warning("remote_admin_api_user POST user_id=%s early return: platform_id exists", user_id)
                            return jsonify({'error': f'platform_id "{platform_id}" already exists'}), 409
                        student_record.platform_id = platform_id
                    elif not student_record.platform_id:
                        assign_platform_id_if_needed(student_record)
                        db.session.flush()

                if 'tutor_id' in data:
                    tutor_id = data['tutor_id']
                    _manage_student_tutor(user.id, tutor_id, replace=True)
                
                if 'parent_ids' in data:
                    _manage_family_ties(user.id, 'student', data['parent_ids'], replace=True)
            
            if user.role == 'parent' and 'child_ids' in data:
                _manage_family_ties(user.id, 'parent', data['child_ids'], replace=True)
            
            db.session.commit()
            logger.info("remote_admin_api_user POST user_id=%s committed successfully", user_id)
            return jsonify({'success': True, 'user_id': user_id})
        
        elif request.method == 'DELETE':
            user = User.query.get(user_id)
            if not user:
                return jsonify({'error': 'user not found'}), 404
            
            username = user.username
            user_role = user.role
            
            deleted_logs = 0
            try:
                deleted_logs = db.session.execute(
                    delete(AuditLog).where(AuditLog.user_id == user_id)
                ).rowcount
            except Exception as e:
                logger.warning(f"Error deleting user logs: {e}")
            
            try:
                if user_role == 'parent':
                    FamilyTie.query.filter_by(parent_id=user_id).delete()
                elif user_role == 'student':
                    FamilyTie.query.filter_by(student_id=user_id).delete()
            except Exception as e:
                logger.warning(f"Error deleting family ties: {e}")
            
            try:
                if user_role == 'student':
                    Enrollment.query.filter_by(student_id=user_id).delete()
                elif user_role == 'tutor':
                    Enrollment.query.filter_by(tutor_id=user_id).delete()
            except Exception as e:
                logger.warning(f"Error deleting enrollments: {e}")
            
            try:
                from app.models import UserSubscription
                UserSubscription.query.filter_by(user_id=user_id).delete()
            except Exception as e:
                logger.warning(f"Error deleting subscriptions: {e}")
            
            try:
                from app.models import UserNotification
                UserNotification.query.filter_by(user_id=user_id).delete()
            except Exception as e:
                logger.warning(f"Error deleting notifications: {e}")
            
            try:
                student_record = Student.query.filter_by(user_id=user_id).first()
                if student_record:
                    db.session.delete(student_record)
            except Exception as e:
                logger.warning(f"Error deleting student record: {e}")
            
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
        
        for role in ['admin', 'tutor', 'student', 'parent', 'tester', 'creator', 'chief_tester', 'designer']:
            stats['users']['by_role'][role] = User.query.filter_by(role=role).count()
        
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
        if per_page < 1:
            per_page = 50
        if per_page > 200:
            per_page = 200

        action_filter = (request.args.get('action') or '').strip() or None
        entity_filter = (request.args.get('entity') or '').strip() or None
        status_filter = (request.args.get('status') or '').strip() or None
        user_id_filter = request.args.get('user_id')
        date_from_raw = (request.args.get('date_from') or '').strip()
        date_to_raw = (request.args.get('date_to') or '').strip()

        def _parse_dt(s: str) -> datetime | None:
            if not s:
                return None
            try:
                dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                return dt.replace(tzinfo=None)
            except Exception:
                return None

        date_from = _parse_dt(date_from_raw)
        date_to = _parse_dt(date_to_raw)
        
        query = AuditLog.query
        
        if action_filter:
            query = query.filter(AuditLog.action == action_filter)
        if entity_filter:
            query = query.filter(AuditLog.entity == entity_filter)
        if status_filter:
            query = query.filter(AuditLog.status == status_filter)
        if user_id_filter:
            query = query.filter(AuditLog.user_id == int(user_id_filter))
        if date_from:
            query = query.filter(AuditLog.timestamp >= date_from)
        if date_to:
            query = query.filter(AuditLog.timestamp <= date_to)
        
        logs = query.order_by(AuditLog.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        try:
            available_actions = [
                r[0] for r in AuditLog.query.with_entities(AuditLog.action).distinct().order_by(AuditLog.action.asc()).limit(500).all()
                if r and r[0]
            ]
        except Exception:
            available_actions = []
        try:
            available_entities = [
                r[0] for r in AuditLog.query.with_entities(AuditLog.entity).distinct().order_by(AuditLog.entity.asc()).limit(500).all()
                if r and r[0]
            ]
        except Exception:
            available_entities = []
        try:
            available_statuses = [
                r[0] for r in AuditLog.query.with_entities(AuditLog.status).distinct().order_by(AuditLog.status.asc()).limit(50).all()
                if r and r[0]
            ]
        except Exception:
            available_statuses = ['success', 'error', 'warning', 'info']
        
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
            'filters': {
                'action': action_filter or '',
                'entity': entity_filter or '',
                'status': status_filter or '',
                'user_id': int(user_id_filter) if user_id_filter else None,
                'date_from': date_from_raw,
                'date_to': date_to_raw,
                'per_page': per_page,
            },
            'meta': {
                'actions': available_actions,
                'entities': available_entities,
                'statuses': available_statuses,
            },
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
            ALL_ROLES = ['creator', 'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer']
            
            try:
                role_permissions = RolePermission.query.all()
                
                if len(role_permissions) == 0:
                    logger.info("No role permissions found in database. Initializing from DEFAULT_ROLE_PERMISSIONS...")
                    try:
                        count = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
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
                        
                        role_permissions = RolePermission.query.all()
                    except Exception as init_error:
                        db.session.rollback()
                        logger.error(f"Error initializing default permissions: {init_error}", exc_info=True)
                else:
                    try:
                        added = 0
                        for role, perms in DEFAULT_ROLE_PERMISSIONS.items():
                            for perm_name in perms:
                                if perm_name not in ALL_PERMISSIONS:
                                    continue
                                exists = RolePermission.query.filter_by(role=role, permission_name=perm_name).first()
                                if not exists:
                                    db.session.add(RolePermission(role=role, permission_name=perm_name, is_enabled=True))
                                    added += 1
                        if added:
                            db.session.commit()
                            logger.info(f"Backfilled {added} missing RolePermission records (defaults) for remote admin")
                            role_permissions = RolePermission.query.all()
                    except Exception as backfill_err:
                        db.session.rollback()
                        logger.warning(f"Could not backfill missing RolePermissions for remote admin: {backfill_err}")
                
                permissions_map = {}
                
                for role in ALL_ROLES:
                    permissions_map[role] = []
                
                for rp in role_permissions:
                    if rp.role not in permissions_map:
                        permissions_map[rp.role] = []
                    if rp.is_enabled:
                        permissions_map[rp.role].append(rp.permission_name)
                
                logger.debug(f"Found {len(role_permissions)} role permissions, {len(permissions_map)} roles")
                logger.debug(f"Roles in permissions_map: {list(permissions_map.keys())}")
                logger.debug(f"ALL_PERMISSIONS count: {len(ALL_PERMISSIONS) if ALL_PERMISSIONS else 0}")
                logger.debug(f"PERMISSION_CATEGORIES count: {len(PERMISSION_CATEGORIES) if PERMISSION_CATEGORIES else 0}")
            except Exception as db_error:
                logger.error(f"Database error in permissions GET: {db_error}", exc_info=True)
                raise
            
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
                
            enabled = set(p for p in (permissions or []) if p in ALL_PERMISSIONS)

            db.session.execute(delete(RolePermission).where(RolePermission.role == role))

            for perm_key in ALL_PERMISSIONS.keys():
                db.session.add(RolePermission(role=role, permission_name=perm_key, is_enabled=(perm_key in enabled)))
            
            db.session.commit()
            
            audit_logger.log(
                action='update_permissions',
                entity='RolePermission',
                entity_id=None,
                status='success',
                metadata={'role': role, 'enabled_count': len(enabled), 'source': 'remote_admin'}
            )
            
            return jsonify({'success': True})
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_permissions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot', methods=['GET'])
@csrf.exempt
def remote_admin_api_bot_panel():
    """API: Данные для админки Telegram-бота."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    status_filter = (request.args.get('status') or '').strip().lower()
    if status_filter not in {'new', 'in_progress', 'answered', 'closed'}:
        status_filter = ''

    try:
        bot_admins = BotAdmin.query.join(User, BotAdmin.user_id == User.id).order_by(User.username.asc()).all()
        reports_query = BotErrorReport.query.order_by(BotErrorReport.created_at.desc(), BotErrorReport.report_id.desc())
        if status_filter:
            reports_query = reports_query.filter_by(status=status_filter)
        reports = reports_query.limit(200).all()

        admins_payload = [{
            'admin_id': a.admin_id,
            'user_id': a.user_id,
            'username': a.user.username if a.user else '',
            'role': a.user.role if a.user else '',
            'is_active': bool(a.is_active),
        } for a in bot_admins]

        reports_payload = [{
            'report_id': r.report_id,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else '',
            'message': r.message,
            'status': r.status,
            'admin_reply': r.admin_reply,
        } for r in reports]

        return jsonify({
            'success': True,
            'bot_admins': admins_payload,
            'reports': reports_payload,
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_bot_panel: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/admins/add', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_admin_add():
    """API: Добавить администратора бота."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        identifier = (data.get('identifier') or '').strip()
        if not identifier:
            return jsonify({'error': 'identifier is required'}), 400

        user = None
        normalized = identifier.lstrip('@').strip()

        if identifier.isdigit():
            user = User.query.get(int(identifier))
            if not user:
                chat_id = int(identifier)
                user = (
                    User.query
                    .join(UserProfile, UserProfile.user_id == User.id)
                    .filter(UserProfile.telegram_chat_id == chat_id)
                    .first()
                )

        if not user and normalized:
            lowered = normalized.lower()
            user = (
                User.query
                .outerjoin(UserProfile, UserProfile.user_id == User.id)
                .filter(
                    (func.lower(User.username) == lowered) |
                    (func.lower(User.telegram_link) == lowered) |
                    (User.telegram_link.ilike(f"%{normalized}%")) |
                    (func.lower(UserProfile.telegram_id) == lowered) |
                    (func.lower(UserProfile.telegram_id) == f"@{lowered}") |
                    (UserProfile.telegram_id.ilike(f"%{normalized}%"))
                )
                .first()
            )

        if not user and normalized:
            tg_variants = {
                normalized,
                f"@{normalized}",
                f"https://t.me/{normalized}",
                f"http://t.me/{normalized}",
                f"t.me/{normalized}",
            }
            user = User.query.filter(
                User.telegram_link.in_(tg_variants)
            ).first()

        if not user:
            return jsonify({'error': 'Пользователь не найден в выбранном окружении'}), 404

        admin = BotAdmin.query.filter_by(user_id=user.id).first()
        if admin:
            admin.is_active = True
        else:
            admin = BotAdmin(user_id=user.id, created_by_user_id=None, is_active=True)
            db.session.add(admin)

        db.session.commit()
        return jsonify({'success': True, 'message': f'Админ бота добавлен: {user.username}'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_admin_add: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/admins/<int:admin_id>/toggle', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_admin_toggle(admin_id: int):
    """API: Переключить статус администратора бота."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        admin = BotAdmin.query.get_or_404(admin_id)
        admin.is_active = not admin.is_active
        db.session.commit()
        return jsonify({'success': True, 'message': 'Статус администратора обновлен.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_admin_toggle: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/admins/<int:admin_id>', methods=['DELETE'])
@csrf.exempt
def remote_admin_api_bot_admin_delete(admin_id: int):
    """API: Удалить администратора бота."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        admin = BotAdmin.query.get_or_404(admin_id)
        db.session.delete(admin)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Администратор удален.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_admin_delete: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/broadcast', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_broadcast():
    """API: Создать рассылку новостей платформы."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        body = (data.get('body') or '').strip()
        link_url = (data.get('link_url') or '').strip() or None

        if not title or not body:
            return jsonify({'error': 'title and body are required'}), 400

        users = (
            db.session.query(User.id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .filter(UserProfile.telegram_chat_id.isnot(None))
            .filter((UserProfile.telegram_notifications_enabled.is_(True)) | (UserProfile.telegram_notifications_enabled.is_(None)))
            .filter(UserProfile.tg_notify_news.is_(True))
            .all()
        )
        count = 0
        for (user_id,) in users:
            db.session.add(UserNotification(
                user_id=user_id,
                kind='platform_news',
                title=title,
                body=body,
                link_url=link_url,
            ))
            count += 1
        db.session.commit()

        audit_logger.log(
            action='bot_broadcast',
            entity='UserNotification',
            entity_id=None,
            status='success',
            metadata={'count': count, 'title': title, 'source': 'remote_admin'}
        )

        return jsonify({'success': True, 'message': f'Рассылка создана: {count} получателей.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_broadcast: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/errors/<int:report_id>/reply', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_error_reply(report_id: int):
    """API: Ответить на сообщение об ошибке."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        reply = (data.get('reply') or '').strip()
        if not reply:
            return jsonify({'error': 'reply is required'}), 400

        report = BotErrorReport.query.get_or_404(report_id)
        report.admin_reply = reply
        report.admin_user_id = None
        report.status = 'answered'
        report.replied_at = moscow_now()
        report.reply_sent_at = None

        db.session.commit()
        return jsonify({'success': True, 'message': 'Ответ сохранен и будет отправлен пользователю.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_error_reply: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/errors/<int:report_id>/status', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_error_status(report_id: int):
    """API: Изменить статус сообщения об ошибке."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        status = (data.get('status') or '').strip().lower()
        if status not in {'new', 'in_progress', 'answered', 'closed'}:
            return jsonify({'error': 'invalid status'}), 400

        report = BotErrorReport.query.get_or_404(report_id)
        report.status = status
        db.session.commit()
        return jsonify({'success': True, 'message': 'Статус обновлен.'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_error_status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/bot/unlink', methods=['POST'])
@csrf.exempt
def remote_admin_api_bot_unlink():
    """API: Отвязать Telegram от профиля."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401

    try:
        data = request.get_json() or {}
        identifier = (data.get('identifier') or '').strip()
        if not identifier:
            return jsonify({'error': 'identifier is required'}), 400

        normalized = identifier.lstrip('@').strip()
        profile = None
        user = None

        if identifier.isdigit():
            chat_id = int(identifier)
            profile = UserProfile.query.filter(UserProfile.telegram_chat_id == chat_id).first()
            if profile:
                user = User.query.get(profile.user_id)

        if not profile and normalized:
            lowered = normalized.lower()
            profile = UserProfile.query.filter(
                (func.lower(UserProfile.telegram_id) == lowered) |
                (func.lower(UserProfile.telegram_id) == f"@{lowered}") |
                (UserProfile.telegram_id.ilike(f"%{normalized}%"))
            ).first()
            if profile:
                user = User.query.get(profile.user_id)

        if not profile and normalized:
            lowered = normalized.lower()
            user = (
                User.query
                .outerjoin(UserProfile, UserProfile.user_id == User.id)
                .filter(
                    (func.lower(User.username) == lowered) |
                    (func.lower(User.telegram_link) == lowered) |
                    (User.telegram_link.ilike(f"%{normalized}%")) |
                    (func.lower(UserProfile.telegram_id) == lowered) |
                    (func.lower(UserProfile.telegram_id) == f"@{lowered}") |
                    (UserProfile.telegram_id.ilike(f"%{normalized}%"))
                )
                .first()
            )
            if user:
                profile = UserProfile.query.filter_by(user_id=user.id).first()

        if not profile:
            return jsonify({'error': 'Профиль не найден в выбранном окружении'}), 404

        if not profile.telegram_chat_id and not profile.telegram_id:
            return jsonify({'error': 'Telegram не привязан к этому профилю'}), 409

        profile.telegram_chat_id = None
        profile.telegram_id = None
        profile.telegram_link_code = None
        profile.telegram_link_code_expires = None
        db.session.commit()

        username = user.username if user else None
        return jsonify({
            'success': True,
            'message': f'Telegram отвязан{f": {username}" if username else ""}.'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_bot_unlink: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/tariffs', methods=['GET'])
@csrf.exempt
def remote_admin_api_tariffs():
    """API: Список тарифных планов."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        from app.models import TariffPlan
        
        tariffs = TariffPlan.query.filter_by(is_active=True).order_by(TariffPlan.title).all()
        
        return jsonify({
            'success': True,
            'tariffs': [{
                'plan_id': t.plan_id,
                'title': t.title,
                'description': t.description,
                'lessons_count': t.lessons_count,
                'period_days': t.period_days,
            } for t in tariffs]
        })
    except Exception as e:
        logger.error(f"Error in remote_admin_api_tariffs: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/internal/remote-admin/api/create-pack', methods=['POST'])
@csrf.exempt
def remote_admin_api_create_pack():
    """API: Быстрое создание пака (ученик + родитель + тариф)."""
    if not _remote_admin_guard():
        return jsonify({'error': 'unauthorized'}), 401
    
    try:
        from werkzeug.security import generate_password_hash
        from core.db_models import moscow_now
        from app.models import Student, UserSubscription, TariffPlan, FamilyTie, Enrollment
        from app.utils.student_id_manager import assign_platform_id_if_needed
        import secrets
        
        data = request.get_json() or {}
        logger.info(f"Creating pack via remote admin API: {data}")
        
        student_name = (data.get('student_name') or '').strip()
        student_telegram = (data.get('student_telegram') or '').strip()
        student_phone = (data.get('student_phone') or '').strip()
        student_password = (data.get('student_password') or '').strip() or secrets.token_urlsafe(8)
        school_class = data.get('school_class')
        target_score = data.get('target_score')
        category = (data.get('category') or '').strip()
        tutor_id = data.get('tutor_id')
        
        if not student_name:
            return jsonify({'error': 'Имя ученика обязательно'}), 400
        
        student_username = _generate_username(student_name, 'student')
        
        create_parent = data.get('create_parent', False)
        parent_name = (data.get('parent_name') or '').strip()
        parent_telegram = (data.get('parent_telegram') or '').strip()
        parent_phone = (data.get('parent_phone') or '').strip()
        parent_password = (data.get('parent_password') or '').strip() or secrets.token_urlsafe(8)
        
        if create_parent and not parent_name:
            parent_name = f"Родитель {student_name}"
        
        parent_username = _generate_username(parent_name, 'parent') if create_parent else None
        
        assign_tariff = data.get('assign_tariff', False)
        tariff_id = data.get('tariff_id')
        lessons_count = data.get('lessons_count')
        
        student_user = User(
            username=student_username,
            email=None,
            password_hash=generate_password_hash(student_password),
            role='student',
            is_active=True,
            telegram_link=student_telegram or None,
            created_at=moscow_now()
        )
        db.session.add(student_user)
        db.session.flush()
        
        student_profile = UserProfile(
            user_id=student_user.id,
            first_name=student_name.split()[0] if student_name else None,
            last_name=' '.join(student_name.split()[1:]) if len(student_name.split()) > 1 else None,
            phone=student_phone or None,
        )
        db.session.add(student_profile)
        
        student_record = Student(
            user_id=student_user.id,  # Прямая связь с User
            name=student_name,
            telegram=student_telegram or None,
            school_class=int(school_class) if school_class else None,
            target_score=int(target_score) if target_score else None,
            category=category or None,
            is_active=True
        )
        db.session.add(student_record)
        db.session.flush()
        
        assign_platform_id_if_needed(student_record)
        db.session.flush()
        
        if tutor_id:
            enrollment = Enrollment(
                student_id=student_user.id,
                tutor_id=int(tutor_id),
                subject=category or 'INFORMATICS',
                status='active'
            )
            db.session.add(enrollment)
        
        result = {
            'success': True,
            'student': {
                'id': student_user.id,
                'username': student_username,
                'password': student_password,
                'platform_id': student_record.platform_id,
            }
        }
        
        if create_parent and parent_name:
            parent_user = User(
                username=parent_username,
                email=None,
                password_hash=generate_password_hash(parent_password),
                role='parent',
                is_active=True,
                telegram_link=parent_telegram or None,
                created_at=moscow_now()
            )
            db.session.add(parent_user)
            db.session.flush()
            
            parent_profile = UserProfile(
                user_id=parent_user.id,
                first_name=parent_name.split()[0] if parent_name else None,
                last_name=' '.join(parent_name.split()[1:]) if len(parent_name.split()) > 1 else None,
                phone=parent_phone or None,
            )
            db.session.add(parent_profile)
            
            family_tie = FamilyTie(
                parent_id=parent_user.id,
                student_id=student_user.id,
                access_level='full',
                is_confirmed=True
            )
            db.session.add(family_tie)
            
            result['parent'] = {
                'id': parent_user.id,
                'username': parent_username,
                'password': parent_password,
            }
        
        if assign_tariff and (tariff_id or lessons_count):
            plan = None
            if tariff_id:
                plan = TariffPlan.query.get(int(tariff_id))
            
            final_lessons = None
            if lessons_count:
                final_lessons = int(lessons_count)
            elif plan and plan.lessons_count:
                final_lessons = plan.lessons_count
            
            subscription = UserSubscription(
                user_id=student_user.id,
                plan_id=plan.plan_id if plan else None,
                status='active',
                started_at=moscow_now(),
                lessons_remaining=final_lessons,
            )
            db.session.add(subscription)
            
            result['subscription'] = {
                'plan_title': plan.title if plan else None,
                'lessons_remaining': final_lessons,
            }
        
        db.session.commit()
        
        audit_logger.log(
            action='create_pack',
            entity='User',
            entity_id=student_user.id,
            status='success',
            metadata={
                'student_username': student_username,
                'parent_created': create_parent,
                'tariff_assigned': assign_tariff,
            }
        )
        
        return jsonify(result), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in remote_admin_api_create_pack: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def _generate_username(name: str, role: str) -> str:
    """Генерация уникального username из имени."""
    import re
    import secrets
    
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    
    name_lower = name.lower().strip()
    result = ''
    for char in name_lower:
        if char in translit_map:
            result += translit_map[char]
        elif char.isalnum():
            result += char
        elif char == ' ':
            result += '_'
    
    result = re.sub(r'_+', '_', result).strip('_')
    
    if not result:
        result = role
    
    base_username = result[:20]
    suffix = secrets.token_hex(2)
    username = f"{base_username}_{suffix}"
    
    while User.query.filter_by(username=username).first():
        suffix = secrets.token_hex(2)
        username = f"{base_username}_{suffix}"
    
    return username
