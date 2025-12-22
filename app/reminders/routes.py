"""
Роуты для управления напоминаниями
"""
from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from zoneinfo import ZoneInfo

from app.reminders import reminders_bp
from app.models import db, Reminder, moscow_now, MOSCOW_TZ
from core.audit_logger import audit_logger

@reminders_bp.route('/reminders')
@login_required
def reminders_list():
    """Страница со списком напоминаний"""
    show_completed = request.args.get('show_completed', 'false').lower() == 'true'
    
    query = Reminder.query.filter_by(user_id=current_user.id)
    
    if not show_completed:
        query = query.filter_by(is_completed=False)
    
    query = query.order_by(Reminder.reminder_time.asc())
    
    reminders = query.all()
    
    now = moscow_now()
    
    return render_template('reminders.html', 
                         reminders=reminders,
                         show_completed=show_completed,
                         now=now)

@reminders_bp.route('/reminders/create', methods=['POST'])
@login_required
def reminder_create():
    """Создание нового напоминания"""
    try:
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        reminder_time_str = request.form.get('reminder_time', '').strip()
        
        if not title:
            flash('Заголовок обязателен', 'error')
            return redirect(url_for('reminders.reminders_list'))
        
        if not reminder_time_str:
            flash('Время напоминания обязательно', 'error')
            return redirect(url_for('reminders.reminders_list'))
        
        try:
            reminder_time = datetime.fromisoformat(reminder_time_str.replace('Z', '+00:00'))
            if reminder_time.tzinfo is None:
                reminder_time = reminder_time.replace(tzinfo=MOSCOW_TZ)
        except ValueError:
            flash('Неверный формат времени', 'error')
            return redirect(url_for('reminders.reminders_list'))
        
        reminder = Reminder(
            user_id=current_user.id,
            title=title,
            message=message if message else None,
            reminder_time=reminder_time
        )
        
        db.session.add(reminder)
        db.session.commit()
        
        audit_logger.log(
            action='create',
            entity='Reminder',
            entity_id=reminder.reminder_id,
            status='success'
        )
        
        flash('Напоминание создано', 'success')
        return redirect(url_for('reminders.reminders_list'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при создании напоминания: {str(e)}', 'error')
        return redirect(url_for('reminders.reminders_list'))

@reminders_bp.route('/reminders/<int:reminder_id>/toggle', methods=['POST'])
@login_required
def reminder_toggle(reminder_id):
    """Переключение статуса выполнения напоминания"""
    reminder = Reminder.query.filter_by(
        reminder_id=reminder_id,
        user_id=current_user.id
    ).first_or_404()
    
    reminder.is_completed = not reminder.is_completed
    db.session.commit()
    
    audit_logger.log(
        action='toggle',
        entity='Reminder',
        entity_id=reminder.reminder_id,
        status='success',
        meta_data={'is_completed': reminder.is_completed}
    )
    
    return jsonify({'success': True, 'is_completed': reminder.is_completed})

@reminders_bp.route('/reminders/<int:reminder_id>/delete', methods=['POST'])
@login_required
def reminder_delete(reminder_id):
    """Удаление напоминания"""
    reminder = Reminder.query.filter_by(
        reminder_id=reminder_id,
        user_id=current_user.id
    ).first_or_404()
    
    db.session.delete(reminder)
    db.session.commit()
    
    audit_logger.log(
        action='delete',
        entity='Reminder',
        entity_id=reminder_id,
        status='success'
    )
    
    flash('Напоминание удалено', 'success')
    return redirect(url_for('reminders.reminders_list'))

@reminders_bp.route('/reminders/<int:reminder_id>/update', methods=['POST'])
@login_required
def reminder_update(reminder_id):
    """Обновление напоминания"""
    reminder = Reminder.query.filter_by(
        reminder_id=reminder_id,
        user_id=current_user.id
    ).first_or_404()
    
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    reminder_time_str = request.form.get('reminder_time', '').strip()
    
    if not title:
        flash('Заголовок обязателен', 'error')
        return redirect(url_for('reminders.reminders_list'))
    
    if not reminder_time_str:
        flash('Время напоминания обязательно', 'error')
        return redirect(url_for('reminders.reminders_list'))
    
    try:
        reminder_time = datetime.fromisoformat(reminder_time_str.replace('Z', '+00:00'))
        if reminder_time.tzinfo is None:
            reminder_time = reminder_time.replace(tzinfo=MOSCOW_TZ)
    except ValueError:
        flash('Неверный формат времени', 'error')
        return redirect(url_for('reminders.reminders_list'))
    
    reminder.title = title
    reminder.message = message if message else None
    reminder.reminder_time = reminder_time
    db.session.commit()
    
    audit_logger.log(
        action='update',
        entity='Reminder',
        entity_id=reminder.reminder_id,
        status='success'
    )
    
    flash('Напоминание обновлено', 'success')
    return redirect(url_for('reminders.reminders_list'))

