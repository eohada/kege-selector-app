"""
Роуты для управления напоминаниями
"""
from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from zoneinfo import ZoneInfo
import json

from app.reminders import reminders_bp
from app.models import db, Reminder, moscow_now, MOSCOW_TZ
from core.audit_logger import audit_logger

@reminders_bp.route('/reminders')
@login_required
def reminders_list():
    """Страница со списком напоминаний"""
    try:
        show_completed = request.args.get('show_completed', 'false').lower() == 'true'
        
        # Убеждаемся, что таблица существует
        try:
            query = Reminder.query.filter_by(user_id=current_user.id)
        except Exception as e:
            # Если таблицы нет, создаем её
            db.create_all()
            query = Reminder.query.filter_by(user_id=current_user.id)
        
        if not show_completed:
            query = query.filter_by(is_completed=False)
        
        # Сортируем: сначала с временем (по времени), потом без времени (по дате создания)
        try:
            from sqlalchemy import asc, desc
            reminders = query.order_by(
                case((Reminder.reminder_time.is_(None), 1), else_=0),
                asc(Reminder.reminder_time),
                desc(Reminder.created_at)
            ).all()
        except Exception as e:
            # Если сортировка не работает, используем простую
            import logging
            logging.warning(f"Reminders sorting error: {e}, using simple sort")
            reminders = query.order_by(Reminder.created_at.desc()).all()
        
        # Получаем текущее время для сравнения
        now = moscow_now()
        # Убираем timezone для сравнения в шаблоне
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        
        return render_template('reminders.html', 
                             reminders=reminders,
                             show_completed=show_completed,
                             now=now_naive)
    except Exception as e:
        import traceback
        error_msg = f"Ошибка в reminders_list: {str(e)}\n{traceback.format_exc()}"
        flash(f'Ошибка загрузки напоминаний: {str(e)}', 'error')
        # Возвращаем пустой список, чтобы страница хотя бы открылась
        return render_template('reminders.html', 
                             reminders=[],
                             show_completed=False,
                             now=moscow_now().replace(tzinfo=None) if moscow_now().tzinfo else moscow_now())

@reminders_bp.route('/reminders/create', methods=['POST'])
@login_required
def reminder_create():
    """Создание нового напоминания"""
    try:
        data = request.get_json() if request.is_json else {}
        
        if request.is_json:
            title = data.get('title', '').strip()
            message = data.get('message', '').strip()
            reminder_time_str = data.get('reminder_time', '').strip()
            timezone_offset = data.get('timezone_offset', None)  # Смещение в минутах от UTC
        else:
            title = request.form.get('title', '').strip()
            message = request.form.get('message', '').strip()
            reminder_time_str = request.form.get('reminder_time', '').strip()
            timezone_offset = request.form.get('timezone_offset', None)
        
        if not title:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Заголовок обязателен'}), 400
            flash('Заголовок обязателен', 'error')
            return redirect(url_for('reminders.reminders_list'))
        
        reminder_time = None
        if reminder_time_str:
            try:
                # datetime-local возвращает строку в формате YYYY-MM-DDTHH:MM
                # Это локальное время устройства пользователя
                reminder_time_naive = datetime.strptime(reminder_time_str, '%Y-%m-%dT%H:%M')
                
                # Если есть смещение часового пояса, используем его
                if timezone_offset is not None:
                    try:
                        offset_minutes = int(timezone_offset)
                        # Создаем timezone с учетом смещения
                        from datetime import timedelta
                        offset = timedelta(minutes=offset_minutes)
                        tz = ZoneInfo(f"Etc/GMT{-offset_minutes//60:+d}" if offset_minutes != 0 else "UTC")
                        reminder_time = reminder_time_naive.replace(tzinfo=tz)
                        # Конвертируем в московское время для хранения
                        reminder_time = reminder_time.astimezone(MOSCOW_TZ).replace(tzinfo=None)
                    except (ValueError, TypeError):
                        # Если не удалось обработать смещение, используем локальное время как московское
                        reminder_time = reminder_time_naive
                else:
                    # Если смещения нет, считаем что это московское время
                    reminder_time = reminder_time_naive
                    
            except ValueError as e:
                if request.is_json:
                    return jsonify({'success': False, 'error': f'Неверный формат времени: {str(e)}'}), 400
                flash(f'Неверный формат времени: {str(e)}', 'error')
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
        
        if request.is_json:
            return jsonify({
                'success': True,
                'reminder': {
                    'id': reminder.reminder_id,
                    'title': reminder.title,
                    'message': reminder.message,
                    'reminder_time': reminder.reminder_time.isoformat() if reminder.reminder_time else None,
                    'is_completed': reminder.is_completed,
                    'is_overdue': reminder.is_overdue()
                }
            })
        
        flash('Напоминание создано', 'success')
        return redirect(url_for('reminders.reminders_list'))
        
    except Exception as e:
        db.session.rollback()
        error_msg = f'Ошибка при создании напоминания: {str(e)}'
        if request.is_json:
            return jsonify({'success': False, 'error': error_msg}), 500
        flash(error_msg, 'error')
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
    
    if request.is_json:
        return jsonify({'success': True})
    
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
    
    data = request.get_json() if request.is_json else {}
    
    if request.is_json:
        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        reminder_time_str = data.get('reminder_time', '').strip()
        timezone_offset = data.get('timezone_offset', None)
    else:
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        reminder_time_str = request.form.get('reminder_time', '').strip()
        timezone_offset = request.form.get('timezone_offset', None)
    
    if not title:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Заголовок обязателен'}), 400
        flash('Заголовок обязателен', 'error')
        return redirect(url_for('reminders.reminders_list'))
    
    reminder_time = None
    if reminder_time_str:
        try:
            reminder_time_naive = datetime.strptime(reminder_time_str, '%Y-%m-%dT%H:%M')
            
            if timezone_offset is not None:
                try:
                    offset_minutes = int(timezone_offset)
                    from datetime import timedelta
                    tz = ZoneInfo(f"Etc/GMT{-offset_minutes//60:+d}" if offset_minutes != 0 else "UTC")
                    reminder_time = reminder_time_naive.replace(tzinfo=tz)
                    reminder_time = reminder_time.astimezone(MOSCOW_TZ).replace(tzinfo=None)
                except (ValueError, TypeError):
                    reminder_time = reminder_time_naive
            else:
                reminder_time = reminder_time_naive
                
        except ValueError as e:
            if request.is_json:
                return jsonify({'success': False, 'error': f'Неверный формат времени: {str(e)}'}), 400
            flash(f'Неверный формат времени: {str(e)}', 'error')
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
    
    if request.is_json:
        return jsonify({
            'success': True,
            'reminder': {
                'id': reminder.reminder_id,
                'title': reminder.title,
                'message': reminder.message,
                'reminder_time': reminder.reminder_time.isoformat() if reminder.reminder_time else None,
                'is_completed': reminder.is_completed,
                'is_overdue': reminder.is_overdue()
            }
        })
    
    flash('Напоминание обновлено', 'success')
    return redirect(url_for('reminders.reminders_list'))
