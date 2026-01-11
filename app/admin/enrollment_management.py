"""
API endpoints для управления учебными контрактами (Enrollment)
Реализует функционал связи ученик-тьютор-предмет
"""
import logging
from flask import request, jsonify

from app.admin import admin_bp
from app.models import db, User, Enrollment, moscow_now
from app.auth.rbac_utils import require_admin
from core.audit_logger import audit_logger
from flask_login import current_user

logger = logging.getLogger(__name__)


@admin_bp.route('/api/enrollments', methods=['GET'])
@require_admin
def api_enrollments_list():
    """API: Список всех учебных контрактов (только для администратора)"""
    try:
        # Параметры фильтрации
        student_id = request.args.get('student_id', type=int)
        tutor_id = request.args.get('tutor_id', type=int)
        subject = request.args.get('subject')
        status = request.args.get('status')
        
        query = Enrollment.query
        
        if student_id:
            query = query.filter_by(student_id=student_id)
        if tutor_id:
            query = query.filter_by(tutor_id=tutor_id)
        if subject:
            query = query.filter_by(subject=subject)
        if status:
            query = query.filter_by(status=status)
        
        enrollments = query.order_by(Enrollment.created_at.desc()).all()
        
        enrollments_data = []
        for enrollment in enrollments:
            enrollment_data = {
                'enrollment_id': enrollment.enrollment_id,
                'student_id': enrollment.student_id,
                'student_username': enrollment.student.username if enrollment.student else None,
                'tutor_id': enrollment.tutor_id,
                'tutor_username': enrollment.tutor.username if enrollment.tutor else None,
                'subject': enrollment.subject,
                'status': enrollment.status,
                'is_active': enrollment.is_active,
                'settings': enrollment.settings,
                'created_at': enrollment.created_at.isoformat() if enrollment.created_at else None,
            }
            enrollments_data.append(enrollment_data)
        
        return jsonify({
            'success': True,
            'enrollments': enrollments_data,
            'total': len(enrollments_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Error in api_enrollments_list: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/enrollments', methods=['POST'])
@require_admin
def api_enrollments_create():
    """API: Создание учебного контракта (только для администратора)"""
    try:
        data = request.get_json()
        
        student_id = data.get('student_id')
        tutor_id = data.get('tutor_id')
        subject = data.get('subject', '').strip()
        status = data.get('status', 'active')
        settings = data.get('settings', {})
        
        if not student_id or not tutor_id:
            return jsonify({'success': False, 'error': 'student_id and tutor_id are required'}), 400
        
        if not subject:
            return jsonify({'success': False, 'error': 'subject is required'}), 400
        
        # Проверяем, что пользователи существуют и имеют правильные роли
        student = User.query.get(student_id)
        tutor = User.query.get(tutor_id)
        
        if not student:
            return jsonify({'success': False, 'error': 'Student not found'}), 404
        if not tutor:
            return jsonify({'success': False, 'error': 'Tutor not found'}), 404
        
        if not student.is_student():
            return jsonify({'success': False, 'error': 'User is not a student'}), 400
        if not tutor.is_tutor():
            return jsonify({'success': False, 'error': 'User is not a tutor'}), 400
        
        # Проверяем допустимые статусы
        valid_statuses = ['active', 'paused', 'archived']
        if status not in valid_statuses:
            return jsonify({'success': False, 'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
        
        # Проверяем, что контракт еще не существует (опционально - можно разрешить несколько контрактов по разным предметам)
        # Для простоты разрешаем несколько контрактов между одними и теми же student и tutor, но с разными предметами
        
        # Создаем контракт
        enrollment = Enrollment(
            student_id=student_id,
            tutor_id=tutor_id,
            subject=subject,
            status=status,
            is_active=(status == 'active'),
            settings=settings
        )
        db.session.add(enrollment)
        db.session.commit()
        
        # Логируем создание
        audit_logger.log(
            action='enrollment_created',
            entity='Enrollment',
            entity_id=enrollment.enrollment_id,
            status='success',
            metadata={
                'student_id': student_id,
                'tutor_id': tutor_id,
                'subject': subject,
                'created_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'enrollment_id': enrollment.enrollment_id,
            'message': 'Enrollment created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_enrollments_create: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/enrollments/<int:enrollment_id>', methods=['PUT'])
@require_admin
def api_enrollments_update(enrollment_id):
    """API: Обновление учебного контракта (только для администратора)"""
    try:
        enrollment = Enrollment.query.get_or_404(enrollment_id)
        data = request.get_json()
        
        if 'subject' in data:
            enrollment.subject = data['subject'].strip()
        
        if 'status' in data:
            status = data['status']
            valid_statuses = ['active', 'paused', 'archived']
            if status not in valid_statuses:
                return jsonify({'success': False, 'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400
            enrollment.status = status
            enrollment.is_active = (status == 'active')
        
        if 'settings' in data:
            enrollment.settings = data['settings']
        
        db.session.commit()
        
        # Логируем обновление
        audit_logger.log(
            action='enrollment_updated',
            entity='Enrollment',
            entity_id=enrollment_id,
            status='success',
            metadata={
                'updated_by': current_user.id,
                'changes': list(data.keys())
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Enrollment updated successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_enrollments_update: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/enrollments/<int:enrollment_id>', methods=['DELETE'])
@require_admin
def api_enrollments_delete(enrollment_id):
    """API: Удаление учебного контракта (только для администратора)"""
    try:
        enrollment = Enrollment.query.get_or_404(enrollment_id)
        
        student_id = enrollment.student_id
        tutor_id = enrollment.tutor_id
        
        db.session.delete(enrollment)
        db.session.commit()
        
        # Логируем удаление
        audit_logger.log(
            action='enrollment_deleted',
            entity='Enrollment',
            entity_id=enrollment_id,
            status='success',
            metadata={
                'student_id': student_id,
                'tutor_id': tutor_id,
                'deleted_by': current_user.id
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Enrollment deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in api_enrollments_delete: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
