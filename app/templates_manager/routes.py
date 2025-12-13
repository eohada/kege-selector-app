"""
Маршруты управления шаблонами
"""
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.templates_manager import templates_bp
from app.models import TaskTemplate, TemplateTask, Lesson, LessonTask, UsageHistory, db, moscow_now
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

@templates_bp.route('/templates')
@login_required
def templates_list():
    """Список всех шаблонов с фильтрацией по типу"""
    template_type = request.args.get('type', '')
    category = request.args.get('category', '')
    
    query = TaskTemplate.query.filter_by(is_active=True)
    
    if template_type:
        query = query.filter_by(template_type=template_type)
    if category:
        query = query.filter_by(category=category)
    
    templates = query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).order_by(TaskTemplate.created_at.desc()).all()
    
    templates_by_type = {
        'homework': [],
        'classwork': [],
        'exam': [],
        'lesson': []
    }
    
    for template in templates:
        templates_by_type[template.template_type].append(template)
    
    return render_template('templates_list.html',
                         templates=templates,
                         templates_by_type=templates_by_type,
                         current_type=template_type,
                         current_category=category)

@templates_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
def template_new():
    """Создание нового шаблона"""
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            name = data.get('name', '').strip()
            if not name:
                return jsonify({'success': False, 'error': 'Название шаблона обязательно'}), 400
            
            template = TaskTemplate(
                name=name,
                description=data.get('description', '').strip() or None,
                template_type=data.get('template_type', 'homework'),
                category=data.get('category') or None,
                created_by=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(template)
            db.session.flush()
            
            task_ids = data.get('task_ids', [])
            for order, task_id in enumerate(task_ids):
                template_task = TemplateTask(
                    template_id=template.template_id,
                    task_id=task_id,
                    order=order
                )
                db.session.add(template_task)
            
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                raise
            
            audit_logger.log(
                action='create_template',
                entity='TaskTemplate',
                entity_id=template.template_id,
                status='success',
                metadata={
                    'name': name,
                    'template_type': template.template_type,
                    'task_count': len(task_ids)
                }
            )
            
            if request.is_json:
                return jsonify({'success': True, 'template_id': template.template_id})
            flash('Шаблон успешно создан', 'success')
            return redirect(url_for('templates_manager.templates_list'))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при создании шаблона: {e}", exc_info=True)
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f'Ошибка при создании шаблона: {e}', 'error')
            return redirect(url_for('templates_manager.templates_list'))
    
    return render_template('template_form.html', template=None, is_new=True)

@templates_bp.route('/templates/<int:template_id>')
@login_required
def template_view(template_id):
    """Просмотр шаблона"""
    template = TaskTemplate.query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).get_or_404(template_id)
    
    template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
    
    return render_template('template_view.html',
                         template=template,
                         template_tasks=template_tasks)

@templates_bp.route('/templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
def template_edit(template_id):
    """Редактирование шаблона"""
    template = TaskTemplate.query.options(
        db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
    ).get_or_404(template_id)
    
    if request.method == 'POST':
        try:
            data = request.get_json() if request.is_json else request.form.to_dict()
            
            template.name = data.get('name', template.name).strip()
            template.description = data.get('description', '').strip() or None
            template.template_type = data.get('template_type', template.template_type)
            template.category = data.get('category') or None
            template.updated_at = moscow_now()
            
            task_ids = data.get('task_ids', [])
            
            TemplateTask.query.filter_by(template_id=template_id).delete()
            
            for order, task_id in enumerate(task_ids):
                template_task = TemplateTask(
                    template_id=template_id,
                    task_id=task_id,
                    order=order
                )
                db.session.add(template_task)
            
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                raise
            
            audit_logger.log(
                action='edit_template',
                entity='TaskTemplate',
                entity_id=template_id,
                status='success',
                metadata={'name': template.name}
            )
            
            if request.is_json:
                return jsonify({'success': True})
            flash('Шаблон успешно обновлен', 'success')
            return redirect(url_for('templates_manager.template_view', template_id=template_id))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка при редактировании шаблона: {e}", exc_info=True)
            if request.is_json:
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f'Ошибка при редактировании шаблона: {e}', 'error')
            return redirect(url_for('templates_manager.template_edit', template_id=template_id))
    
    template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
    return render_template('template_form.html',
                         template=template,
                         template_tasks=template_tasks,
                         is_new=False)

@templates_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
def template_delete(template_id):
    """Удаление шаблона (мягкое удаление - is_active=False)"""
    template = TaskTemplate.query.get_or_404(template_id)
    
    template.is_active = False
    template.updated_at = moscow_now()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise
    
    audit_logger.log(
        action='delete_template',
        entity='TaskTemplate',
        entity_id=template_id,
        status='success',
        metadata={'name': template.name}
    )
    
    flash('Шаблон удален', 'success')
    return redirect(url_for('templates_manager.templates_list'))

@templates_bp.route('/templates/<int:template_id>/apply', methods=['POST'])
@login_required
def template_apply(template_id):
    """Применение шаблона к уроку"""
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        lesson_id = data.get('lesson_id')
        
        if not lesson_id:
            return jsonify({'success': False, 'error': 'ID урока обязателен'}), 400
        
        lesson = Lesson.query.get_or_404(lesson_id)
        template = TaskTemplate.query.options(
            db.joinedload(TaskTemplate.template_tasks).joinedload(TemplateTask.task)
        ).get_or_404(template_id)
        
        template_tasks = sorted(template.template_tasks, key=lambda tt: tt.order)
        assignment_type = template.template_type
        
        applied_count = 0
        skipped_count = 0
        
        for template_task in template_tasks:
            existing = LessonTask.query.filter_by(
                lesson_id=lesson_id,
                task_id=template_task.task_id
            ).first()
            
            if not existing:
                lesson_task = LessonTask(
                    lesson_id=lesson_id,
                    task_id=template_task.task_id,
                    assignment_type=assignment_type
                )
                db.session.add(lesson_task)
                applied_count += 1
                
                usage = UsageHistory(
                    task_fk=template_task.task_id,
                    session_tag=f"student_{lesson.student_id}"
                )
                db.session.add(usage)
            else:
                skipped_count += 1
        
        if assignment_type == 'homework':
            if lesson.lesson_type != 'introductory':
                lesson.homework_status = 'assigned_not_done'
            else:
                lesson.homework_status = 'not_assigned'
        
        try:
            db.session.commit()
        except Exception as commit_error:
            db.session.rollback()
            raise
        
        audit_logger.log(
            action='apply_template',
            entity='TaskTemplate',
            entity_id=template_id,
            status='success',
            metadata={
                'lesson_id': lesson_id,
                'applied_count': applied_count,
                'skipped_count': skipped_count,
                'assignment_type': assignment_type
            }
        )
        
        message = f'Шаблон применен: добавлено {applied_count} заданий'
        if skipped_count > 0:
            message += f', пропущено {skipped_count} (уже были в уроке)'
        
        if request.is_json:
            return jsonify({'success': True, 'message': message})
        flash(message, 'success')
        return redirect(url_for('lessons.lesson_edit', lesson_id=lesson_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Ошибка при применении шаблона: {e}", exc_info=True)
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Ошибка при применении шаблона: {e}', 'error')
        return redirect(url_for('templates_manager.templates_list'))
