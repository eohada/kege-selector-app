"""
API endpoints для управления пользователями (Admin only)
Реализует CRUD операции для пользователей с поддержкой новых ролей
"""
import logging
from flask import request, jsonify
from werkzeug.security import generate_password_hash

from app.admin import admin_bp
from app.models import db, User, UserProfile, FamilyTie, Enrollment, moscow_now, UserRole
from app.auth.rbac_utils import require_admin
from core.audit_logger import audit_logger
from flask_login import current_user
from app.telegram.role_management import actor_can_assign_role, notify_role_changed, set_single_role

logger = logging.getLogger(__name__)


@admin_bp.route('/api/users', methods=['GET'])
@require_admin
def api_users_list():
    """API: Список всех пользователей (только для администратора)"""
    try:
        role_filter = request.args.get('role')  # Фильтр по роли
        is_active_filter = request.args.get('is_active')  # Фильтр по активности
        
        query = User.query
        
        if role_filter:
            ids_subq = db.session.query(User.id).join(UserRole, User.id == UserRole.user_id).filter(UserRole.role == role_filter).distinct()
            query = query.filter(User.id.in_(ids_subq))
        if is_active_filter is not None:
            is_active = is_active_filter.lower() == 'true'
            query = query.filter(User.is_active == is_active)
        
        users = query.order_by(User.created_at.desc()).all()
        
        users_data = []
        for user in users:
            user_data = {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_display': user.get_role_display(),
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None,
            }
            
            if user.profile:
                user_data['profile'] = {
                    'first_name': user.profile.first_name,
                    'last_name': user.profile.last_name,
                    'phone': user.profile.phone,
                    'telegram_id': user.profile.telegram_id,
                    'timezone': user.profile.timezone,
                }
            
            users_data.append(user_data)
        
        return jsonify({
            'success': True,
            'users': users_data,
            'total': len(users_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Error in api_users_list: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users', methods=['POST'])
@require_admin
def api_users_create():
    """API: Создание нового пользователя (только для администратора)"""
    try:
        data = request.get_json()
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'student').strip()
        
        if not username:
            return jsonify({'success': False, 'error': 'Username is required'}), 400
        
        if not password:
            return jsonify({'success': False, 'error': 'Password is required'}), 400
        
        valid_roles = ['creator', 'chief_admin', 'admin', 'tutor', 'student', 'parent', 'tester', 'chief_tester', 'designer', 'content_maker']
        if role not in valid_roles:
            return jsonify({'success': False, 'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400

        if current_user.role == 'chief_admin' and role in ('creator', 'chief_admin'):
            return jsonify({'success': False, 'error': 'Старший администратор не может создавать создателей или других старших администраторов.'}), 403
        if current_user.role == 'admin' and role in ('creator', 'chief_admin', 'admin'):
            return jsonify({'success': False, 'error': 'Обычный администратор не может создавать или назначать администраторов.'}), 403
        
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'error': 'Username already exists'}), 409
        
        user = User(
            username=username,
            email=None,
            password_hash=generate_password_hash(password),
            role=role,
            is_active=data.get('is_active', True)
        )
        db.session.add(user)
        db.session.flush()  # Получаем ID пользователя
        db.session.add(UserRole(user_id=user.id, role=role))
        
        profile_data = data.get('profile', {})
        if profile_data:
            profile = UserProfile(
                user_id=user.id,
                first_name=profile_data.get('first_name'),
                last_name=profile_data.get('last_name'),
                middle_name=profile_data.get('middle_name'),
                phone=profile_data.get('phone'),
                telegram_id=profile_data.get('telegram_id'),
                timezone=profile_data.get('timezone', 'Europe/Moscow'),
                avatar_url=profile_data.get('avatar_url')
            )
            db.session.add(profile)
        
        db.session.commit()
        
        audit_logger.log(
            action='user_created',
            entity='User',
            entity_id=user.id,
            status='success',
            metadata={
                'username': username,
                'role': role,
                'created_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'message': 'User created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_users_create: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users/<int:user_id>', methods=['GET'])
@require_admin
def api_users_get(user_id):
    """API: Получение информации о пользователе (только для администратора)"""
    try:
        user = User.query.get_or_404(user_id)
        
        user_data = {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'role_display': user.get_role_display(),
            'is_active': user.is_active,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'last_login': user.last_login.isoformat() if user.last_login else None,
        }
        
        if user.profile:
            user_data['profile'] = {
                'first_name': user.profile.first_name,
                'last_name': user.profile.last_name,
                'middle_name': user.profile.middle_name,
                'phone': user.profile.phone,
                'telegram_id': user.profile.telegram_id,
                'timezone': user.profile.timezone,
                'avatar_url': user.profile.avatar_url,
            }
        
        if user.is_student():
            family_ties = FamilyTie.query.filter_by(student_id=user.id).all()
            user_data['parents'] = [
                {
                    'parent_id': ft.parent_id,
                    'parent_username': ft.parent.username if ft.parent else None,
                    'access_level': ft.access_level,
                    'is_confirmed': ft.is_confirmed
                }
                for ft in family_ties
            ]
            
            enrollments = Enrollment.query.filter_by(student_id=user.id, status='active').all()
            user_data['enrollments'] = [
                {
                    'enrollment_id': e.enrollment_id,
                    'tutor_id': e.tutor_id,
                    'tutor_username': e.tutor.username if e.tutor else None,
                    'subject': e.subject,
                    'status': e.status
                }
                for e in enrollments
            ]
        
        if user.is_parent():
            family_ties = FamilyTie.query.filter_by(parent_id=user.id).all()
            user_data['children'] = [
                {
                    'student_id': ft.student_id,
                    'student_username': ft.student.username if ft.student else None,
                    'access_level': ft.access_level,
                    'is_confirmed': ft.is_confirmed
                }
                for ft in family_ties
            ]
        
        if user.is_tutor():
            enrollments = Enrollment.query.filter_by(tutor_id=user.id, status='active').all()
            user_data['students'] = [
                {
                    'enrollment_id': e.enrollment_id,
                    'student_id': e.student_id,
                    'student_username': e.student.username if e.student else None,
                    'subject': e.subject
                }
                for e in enrollments
            ]
        
        return jsonify({
            'success': True,
            'user': user_data
        }), 200
        
    except Exception as e:
        logger.error(f"Error in api_users_get: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@require_admin
def api_users_update(user_id):
    """API: Обновление пользователя (только для администратора)"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        if 'username' in data:
            new_username = data['username'].strip()
            if new_username != user.username:
                if User.query.filter_by(username=new_username).first():
                    return jsonify({'success': False, 'error': 'Username already exists'}), 409
                user.username = new_username
        
        if 'role' in data:
            role = data['role'].strip()
            valid_roles = ['creator', 'chief_admin', 'admin', 'tutor', 'student', 'parent']
            if role not in valid_roles:
                return jsonify({'success': False, 'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400
            if role != user.role:
                ok, reason = actor_can_assign_role(current_user, user, role)
                if not ok:
                    return jsonify({'success': False, 'error': reason}), 403
                old_role = set_single_role(user, role)
            else:
                old_role = user.role
        
        if 'is_active' in data:
            user.is_active = bool(data['is_active'])
        
        if 'profile' in data:
            profile_data = data['profile']
            if not user.profile:
                profile = UserProfile(user_id=user.id)
                db.session.add(profile)
                db.session.flush()
                user.profile = profile
            
            if 'first_name' in profile_data:
                user.profile.first_name = profile_data['first_name']
            if 'last_name' in profile_data:
                user.profile.last_name = profile_data['last_name']
            if 'middle_name' in profile_data:
                user.profile.middle_name = profile_data['middle_name']
            if 'phone' in profile_data:
                user.profile.phone = profile_data['phone']
            if 'telegram_id' in profile_data:
                user.profile.telegram_id = profile_data['telegram_id']
            if 'timezone' in profile_data:
                user.profile.timezone = profile_data['timezone']
            if 'avatar_url' in profile_data:
                user.profile.avatar_url = profile_data['avatar_url']
        
        db.session.commit()
        if 'role' in data and data['role'].strip() != old_role:
            notify_role_changed(user, old_role, data['role'].strip(), actor=current_user)
        
        audit_logger.log(
            action='user_updated',
            entity='User',
            entity_id=user.id,
            status='success',
            metadata={
                'updated_by': current_user.id,
                'changes': list(data.keys())
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'User updated successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_users_update: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users/<int:user_id>/reset-password', methods=['POST'])
@require_admin
def api_users_reset_password(user_id):
    """API: Сброс пароля пользователя (только для администратора)"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        new_password = data.get('password', '')
        if not new_password:
            return jsonify({'success': False, 'error': 'Password is required'}), 400
        
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        audit_logger.log(
            action='password_reset',
            entity='User',
            entity_id=user.id,
            status='success',
            metadata={
                'reset_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Password reset successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_users_reset_password: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/users/<int:user_id>/activate', methods=['POST'])
@require_admin
def api_users_activate(user_id):
    """API: Активация/деактивация пользователя (только для администратора)"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()
        
        is_active = data.get('is_active', True)
        user.is_active = bool(is_active)
        db.session.commit()
        
        action = 'activated' if is_active else 'deactivated'
        
        audit_logger.log(
            action=f'user_{action}',
            entity='User',
            entity_id=user.id,
            status='success',
            metadata={
                'action_by': current_user.id,
                'is_active': is_active
            }
        )
        
        return jsonify({
            'success': True,
            'message': f'User {action} successfully',
            'is_active': user.is_active
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_users_activate: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
