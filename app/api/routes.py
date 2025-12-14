"""
API маршруты
"""
import logging
from flask import request, jsonify, url_for
from flask_login import login_required
from sqlalchemy import or_

from app.api import api_bp
from app.models import Student, Lesson, Tasks, db
from app.students.forms import normalize_school_class
from core.audit_logger import audit_logger
from datetime import datetime

logger = logging.getLogger(__name__)

@api_bp.route('/api/audit-log', methods=['POST'])
def api_audit_log():
    """API для логирования действий"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        audit_logger.log(
            action=data.get('action', 'unknown'),
            entity=data.get('entity'),
            entity_id=data.get('entity_id'),
            status=data.get('status', 'success'),
            metadata=data.get('metadata', {}),
            duration_ms=data.get('duration_ms')
        )

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f'Error processing audit log: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/api/student/create', methods=['POST'])
@login_required
def api_student_create():
    """API для создания студента"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        school_class_value = normalize_school_class(data.get('school_class'))
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None
        
        student = Student(
            name=data.get('name'),
            platform_id=platform_id,
            target_score=int(data.get('target_score')) if data.get('target_score') else None,
            deadline=data.get('deadline'),
            diagnostic_level=data.get('diagnostic_level'),
            preferences=data.get('preferences'),
            strengths=data.get('strengths'),
            weaknesses=data.get('weaknesses'),
            overall_rating=data.get('overall_rating'),
            description=data.get('description'),
            notes=data.get('notes'),
            category=data.get('category') if data.get('category') else None,
            school_class=school_class_value,
            goal_text=goal_text_value,
            programming_language=programming_language_value
        )
        db.session.add(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student.name} успешно добавлен!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category,
                'school_class': student.school_class,
                'goal_text': student.goal_text,
                'programming_language': student.programming_language
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании студента: {str(e)}'}), 500

@api_bp.route('/api/student/<int:student_id>/update', methods=['POST', 'PUT'])
@login_required
def api_student_update(student_id):
    """API для обновления студента"""
    try:
        student = Student.query.get_or_404(student_id)
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Имя ученика обязательно'}), 400

        platform_id = data.get('platform_id', '').strip() if data.get('platform_id') else None
        if platform_id:
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student and existing_student.student_id != student_id:
                return jsonify({'success': False, 'error': f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})'}), 400

        school_class_value = normalize_school_class(data.get('school_class'))
        goal_text_value = data.get('goal_text').strip() if data.get('goal_text') else None
        programming_language_value = data.get('programming_language').strip() if data.get('programming_language') else None
        
        student.name = data.get('name')
        student.platform_id = platform_id
        student.target_score = int(data.get('target_score')) if data.get('target_score') else None
        student.deadline = data.get('deadline')
        student.diagnostic_level = data.get('diagnostic_level')
        student.preferences = data.get('preferences')
        student.strengths = data.get('strengths')
        student.weaknesses = data.get('weaknesses')
        student.overall_rating = data.get('overall_rating')
        student.description = data.get('description')
        student.notes = data.get('notes')
        student.category = data.get('category') if data.get('category') else None
        student.school_class = school_class_value
        student.goal_text = goal_text_value
        student.programming_language = programming_language_value

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Данные ученика {student.name} обновлены!',
            'student': {
                'id': student.student_id,
                'name': student.name,
                'platform_id': student.platform_id,
                'category': student.category,
                'school_class': student.school_class,
                'goal_text': student.goal_text,
                'programming_language': student.programming_language
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при обновлении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при обновлении студента: {str(e)}'}), 500

@api_bp.route('/api/student/<int:student_id>/delete', methods=['POST', 'DELETE'])
@login_required
def api_student_delete(student_id):
    """API для удаления студента"""
    try:
        student = Student.query.get_or_404(student_id)
        student_name = student.name
        db.session.delete(student)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Ученик {student_name} удален'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при удалении студента через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при удалении студента: {str(e)}'}), 500

@api_bp.route('/api/global-search', methods=['GET'])
@login_required
def api_global_search():
    """Глобальный поиск по всем сущностям: ученики, уроки, задания"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({
            'success': False,
            'error': 'Минимум 2 символа для поиска'
        }), 400
    
    results = {
        'students': [],
        'lessons': [],
        'tasks': []
    }
    
    try:
        # Поиск по ученикам
        search_pattern = f'%{query}%'
        students = Student.query.filter(
            or_(
                Student.name.ilike(search_pattern),
                Student.platform_id.ilike(search_pattern),
                Student.category.ilike(search_pattern)
            )
        ).limit(10).all()
        
        for student in students:
            results['students'].append({
                'id': student.student_id,
                'name': student.name,
                'category': student.category,
                'platform_id': student.platform_id,
                'is_active': student.is_active,
                'url': url_for('students.student_profile', student_id=student.student_id)
            })
        
        # Поиск по урокам
        try:
            lesson_id = int(query)
            lessons = Lesson.query.filter(Lesson.lesson_id == lesson_id).limit(5).all()
        except ValueError:
            lessons = Lesson.query.filter(
                or_(
                    Lesson.topic.ilike(search_pattern),
                    Lesson.notes.ilike(search_pattern),
                    Lesson.homework.ilike(search_pattern)
                )
            ).limit(5).all()
        
        for lesson in lessons:
            results['lessons'].append({
                'id': lesson.lesson_id,
                'student_name': lesson.student.name if lesson.student else 'Неизвестно',
                'student_id': lesson.student_id,
                'topic': lesson.topic,
                'date': lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else None,
                'status': lesson.status,
                'url': url_for('lessons.lesson_edit', lesson_id=lesson.lesson_id)
            })
        
        # Поиск по заданиям
        try:
            task_id = int(query)
            tasks = Tasks.query.filter(
                or_(
                    Tasks.task_id == task_id,
                    Tasks.site_task_id == task_id
                )
            ).limit(5).all()
        except ValueError:
            tasks = Tasks.query.filter(
                Tasks.content_html.ilike(search_pattern)
            ).limit(5).all()
        
        for task in tasks:
            results['tasks'].append({
                'id': task.task_id,
                'site_task_id': task.site_task_id,
                'task_number': task.task_number,
                'content_preview': task.content_html[:200] + '...' if task.content_html and len(task.content_html) > 200 else (task.content_html or ''),
                'url': url_for('kege_generator.generate_results', task_id=task.task_id)
            })
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results['students']) + len(results['lessons']) + len(results['tasks'])
        })
    
    except Exception as e:
        logger.error(f"Ошибка при глобальном поиске: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route('/api/lesson/create', methods=['POST'])
@login_required
def api_lesson_create():
    """API для создания урока"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()

        if not data.get('student_id'):
            return jsonify({'success': False, 'error': 'ID студента обязателен'}), 400
        if not data.get('lesson_date'):
            return jsonify({'success': False, 'error': 'Дата урока обязательна'}), 400

        try:
            if isinstance(data.get('lesson_date'), str):
                lesson_date = datetime.fromisoformat(data['lesson_date'].replace('Z', '+00:00'))
            else:
                lesson_date = data.get('lesson_date')
        except Exception as e:
            return jsonify({'success': False, 'error': f'Неверный формат даты: {str(e)}'}), 400

        from app.lessons.forms import ensure_introductory_without_homework
        from app.models import MOSCOW_TZ
        
        lesson_type = data.get('lesson_type', 'regular')
        homework_status_value = data.get('homework_status', 'not_assigned')
        homework_value = data.get('homework')
        if lesson_type == 'introductory':
            homework_value = ''
            homework_status_value = 'not_assigned'

        lesson = Lesson(
            student_id=int(data.get('student_id')),
            lesson_type=lesson_type,
            lesson_date=lesson_date,
            duration=int(data.get('duration', 60)),
            status=data.get('status', 'planned'),
            topic=data.get('topic'),
            notes=data.get('notes'),
            homework=homework_value,
            homework_status=homework_status_value
        )
        db.session.add(lesson)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Урок успешно создан!',
            'lesson': {
                'id': lesson.lesson_id,
                'student_id': lesson.student_id,
                'lesson_date': lesson.lesson_date.isoformat() if lesson.lesson_date else None,
                'duration': lesson.duration,
                'status': lesson.status
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f'Ошибка при создании урока через API: {e}')
        return jsonify({'success': False, 'error': f'Ошибка при создании урока: {str(e)}'}), 500

@api_bp.route('/api/templates', methods=['GET'])
@login_required
def api_templates():
    """API для получения списка шаблонов"""
    try:
        from app.models import TaskTemplate
        
        # Получаем параметры фильтрации
        template_type = request.args.get('type', '')
        category = request.args.get('category', '')
        
        # Строим запрос
        query = TaskTemplate.query.filter_by(is_active=True)
        
        if template_type:
            query = query.filter_by(template_type=template_type)
        
        if category:
            query = query.filter_by(category=category)
        
        templates = query.options(
            db.joinedload(TaskTemplate.template_tasks)
        ).order_by(TaskTemplate.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'templates': [{
                'id': t.template_id,
                'name': t.name,
                'description': t.description,
                'type': t.template_type,
                'category': t.category,
                'task_count': len(t.template_tasks) if t.template_tasks else 0
            } for t in templates]
        })
    except Exception as e:
        logger.error(f'Ошибка при получении шаблонов через API: {e}', exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
