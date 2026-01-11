"""
API endpoints для управления семейными связями (Parent-Student)
Реализует функционал привязки родителей к ученикам
"""
import logging
from flask import request, jsonify

from app.admin import admin_bp
from app.models import db, User, FamilyTie, moscow_now
from app.auth.rbac_utils import require_admin
from core.audit_logger import audit_logger
from flask_login import current_user

logger = logging.getLogger(__name__)


@admin_bp.route('/api/family-ties', methods=['GET'])
@require_admin
def api_family_ties_list():
    """API: Список всех семейных связей (только для администратора)"""
    try:
        # Параметры фильтрации
        parent_id = request.args.get('parent_id', type=int)
        student_id = request.args.get('student_id', type=int)
        is_confirmed = request.args.get('is_confirmed')
        
        query = FamilyTie.query
        
        if parent_id:
            query = query.filter_by(parent_id=parent_id)
        if student_id:
            query = query.filter_by(student_id=student_id)
        if is_confirmed is not None:
            is_confirmed_bool = is_confirmed.lower() == 'true'
            query = query.filter_by(is_confirmed=is_confirmed_bool)
        
        ties = query.order_by(FamilyTie.created_at.desc()).all()
        
        ties_data = []
        for tie in ties:
            tie_data = {
                'tie_id': tie.tie_id,
                'parent_id': tie.parent_id,
                'parent_username': tie.parent.username if tie.parent else None,
                'student_id': tie.student_id,
                'student_username': tie.student.username if tie.student else None,
                'access_level': tie.access_level,
                'is_confirmed': tie.is_confirmed,
                'created_at': tie.created_at.isoformat() if tie.created_at else None,
            }
            ties_data.append(tie_data)
        
        return jsonify({
            'success': True,
            'family_ties': ties_data,
            'total': len(ties_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Error in api_family_ties_list: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/family-ties', methods=['POST'])
@require_admin
def api_family_ties_create():
    """API: Создание связи родитель-ученик (только для администратора)"""
    try:
        data = request.get_json()
        
        parent_id = data.get('parent_id')
        student_id = data.get('student_id')
        access_level = data.get('access_level', 'full')
        is_confirmed = data.get('is_confirmed', False)
        
        if not parent_id or not student_id:
            return jsonify({'success': False, 'error': 'parent_id and student_id are required'}), 400
        
        # Проверяем, что пользователи существуют и имеют правильные роли
        parent = User.query.get(parent_id)
        student = User.query.get(student_id)
        
        if not parent:
            return jsonify({'success': False, 'error': 'Parent not found'}), 404
        if not student:
            return jsonify({'success': False, 'error': 'Student not found'}), 404
        
        if not parent.is_parent():
            return jsonify({'success': False, 'error': 'User is not a parent'}), 400
        if not student.is_student():
            return jsonify({'success': False, 'error': 'User is not a student'}), 400
        
        # Проверяем, что связь еще не существует
        existing = FamilyTie.query.filter_by(
            parent_id=parent_id,
            student_id=student_id
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Family tie already exists'}), 409
        
        # Проверяем уровень доступа
        valid_access_levels = ['full', 'financial_only', 'schedule_only']
        if access_level not in valid_access_levels:
            return jsonify({'success': False, 'error': f'Invalid access_level. Must be one of: {", ".join(valid_access_levels)}'}), 400
        
        # Создаем связь
        family_tie = FamilyTie(
            parent_id=parent_id,
            student_id=student_id,
            access_level=access_level,
            is_confirmed=is_confirmed
        )
        db.session.add(family_tie)
        db.session.commit()
        
        # Логируем создание
        audit_logger.log(
            action='family_tie_created',
            entity='FamilyTie',
            entity_id=family_tie.tie_id,
            status='success',
            metadata={
                'parent_id': parent_id,
                'student_id': student_id,
                'access_level': access_level,
                'created_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'tie_id': family_tie.tie_id,
            'message': 'Family tie created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_family_ties_create: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/family-ties/<int:tie_id>', methods=['PUT'])
@require_admin
def api_family_ties_update(tie_id):
    """API: Обновление семейной связи (только для администратора)"""
    try:
        tie = FamilyTie.query.get_or_404(tie_id)
        data = request.get_json()
        
        if 'access_level' in data:
            access_level = data['access_level']
            valid_access_levels = ['full', 'financial_only', 'schedule_only']
            if access_level not in valid_access_levels:
                return jsonify({'success': False, 'error': f'Invalid access_level. Must be one of: {", ".join(valid_access_levels)}'}), 400
            tie.access_level = access_level
        
        if 'is_confirmed' in data:
            tie.is_confirmed = bool(data['is_confirmed'])
        
        db.session.commit()
        
        # Логируем обновление
        audit_logger.log(
            action='family_tie_updated',
            entity='FamilyTie',
            entity_id=tie_id,
            status='success',
            metadata={
                'updated_by': current_user.id,
                'changes': list(data.keys())
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Family tie updated successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_family_ties_update: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/family-ties/<int:tie_id>', methods=['DELETE'])
@require_admin
def api_family_ties_delete(tie_id):
    """API: Удаление семейной связи (только для администратора)"""
    try:
        tie = FamilyTie.query.get_or_404(tie_id)
        
        parent_id = tie.parent_id
        student_id = tie.student_id
        
        db.session.delete(tie)
        db.session.commit()
        
        # Логируем удаление
        audit_logger.log(
            action='family_tie_deleted',
            entity='FamilyTie',
            entity_id=tie_id,
            status='success',
            metadata={
                'parent_id': parent_id,
                'student_id': student_id,
                'deleted_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Family tie deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_family_ties_delete: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/family-ties/<int:tie_id>/confirm', methods=['POST'])
@require_admin
def api_family_ties_confirm(tie_id):
    """API: Подтверждение семейной связи (только для администратора)"""
    try:
        tie = FamilyTie.query.get_or_404(tie_id)
        tie.is_confirmed = True
        db.session.commit()
        
        # Логируем подтверждение
        audit_logger.log(
            action='family_tie_confirmed',
            entity='FamilyTie',
            entity_id=tie_id,
            status='success',
            metadata={
                'confirmed_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Family tie confirmed successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_family_ties_confirm: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
