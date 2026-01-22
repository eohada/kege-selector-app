"""
Роуты для управления напоминаниями
"""
from flask import render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import inspect, text
from sqlalchemy import case
import json
import logging

from app.reminders import reminders_bp
from app.models import db, Reminder, moscow_now, MOSCOW_TZ
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

@reminders_bp.route('/reminders')
@login_required
def reminders_list():
    """Страница со списком напоминаний"""
    try:
        show_completed = request.args.get('show_completed', 'false').lower() == 'true'
        
        # Убеждаемся, что таблица существует и миграции применены
        try:
            query = Reminder.query.filter_by(user_id=current_user.id)
        except Exception as e:
            # Если таблицы нет, создаем её
            db.create_all()
            query = Reminder.query.filter_by(user_id=current_user.id)
        
        # Принудительно проверяем и применяем миграцию для reminder_time
        try:
            inspector = inspect(db.engine)
            table_names = inspector.get_table_names()
            reminders_table = 'Reminders' if 'Reminders' in table_names else ('reminders' if 'reminders' in table_names else None)
            
            if reminders_table:
                db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if 'postgresql' in db_url or 'postgres' in db_url:
                    # Проверяем через information_schema
                    result = db.session.execute(text("""
                        SELECT is_nullable 
                        FROM information_schema.columns 
                        WHERE table_name = :table_name AND column_name = 'reminder_time'
                    """), {'table_name': reminders_table})
                    row = result.fetchone()
                    if row and row[0] == 'NO':
                        # Колонка NOT NULL, делаем её nullable
                        db.session.execute(text(f'ALTER TABLE "{reminders_table}" ALTER COLUMN reminder_time DROP NOT NULL'))
                        db.session.commit()
                        logger.info(f"Made reminder_time nullable in {reminders_table}")
        except Exception as e:
            # Игнорируем ошибки миграции, чтобы не блокировать работу
            logger.warning(f"Could not check/update reminder_time nullable: {e}")
            db.session.rollback()
        
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
        
        # Подготавливаем данные для отображения времени в локальном часовом поясе
        reminders_data = []
        for reminder in reminders:
            reminder_dict = {
                'reminder': reminder,
                'time_iso': None
            }
            if reminder.reminder_time:
                # Создаем ISO строку с московским timezone для правильной конвертации на клиенте
                reminder_time_moscow = reminder.reminder_time.replace(tzinfo=MOSCOW_TZ) if not reminder.reminder_time.tzinfo else reminder.reminder_time
                reminder_dict['time_iso'] = reminder_time_moscow.isoformat()
            reminders_data.append(reminder_dict)
        
        return render_template('reminders.html', 
                             reminders_data=reminders_data,
                             show_completed=show_completed,
                             now=now_naive)
    except Exception as e:
        import traceback
        error_msg = f"Ошибка в reminders_list: {str(e)}\n{traceback.format_exc()}"
        flash(f'Ошибка загрузки напоминаний: {str(e)}', 'error')
        # Возвращаем пустой список, чтобы страница хотя бы открылась
        now_naive = moscow_now().replace(tzinfo=None) if moscow_now().tzinfo else moscow_now()
        return render_template('reminders.html', 
                             reminders_data=[],
                             show_completed=False,
                             now=now_naive)

@reminders_bp.route('/reminders/create', methods=['GET'])
@login_required
def reminder_create_page():
    """
    UX-алиас: прямой заход на /reminders/create должен открывать страницу,
    а не отдавать 405 (создание выполняется POST-ом из модалки).
    """
    return redirect(url_for('reminders.reminders_list', create='1'))

@reminders_bp.route('/reminders/create', methods=['POST'])
@login_required
def reminder_create():
    """Создание нового напоминания"""
    # Принудительно проверяем и применяем миграцию для reminder_time перед созданием
    try:
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        reminders_table = 'Reminders' if 'Reminders' in table_names else ('reminders' if 'reminders' in table_names else None)
        
        if reminders_table:
            db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
            if 'postgresql' in db_url or 'postgres' in db_url:
                result = db.session.execute(text("""
                    SELECT is_nullable 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name AND column_name = 'reminder_time'
                """), {'table_name': reminders_table})
                row = result.fetchone()
                if row and row[0] == 'NO':
                    db.session.execute(text(f'ALTER TABLE "{reminders_table}" ALTER COLUMN reminder_time DROP NOT NULL'))
                    db.session.commit()
                    logger.info(f"Made reminder_time nullable in {reminders_table} before create")
    except Exception as e:
        logger.warning(f"Could not check/update reminder_time nullable before create: {e}")
        db.session.rollback()
    
    try:
        data = request.get_json() if request.is_json else {}
        
        if request.is_json:
            title = (data.get('title') or '').strip()
            message = (data.get('message') or '').strip()
            reminder_time_str = (data.get('reminder_time') or '').strip()
            timezone_offset = data.get('timezone_offset', None)  # Смещение в минутах от UTC
        else:
            title = (request.form.get('title') or '').strip()
            message = (request.form.get('message') or '').strip()
            reminder_time_str = (request.form.get('reminder_time') or '').strip()
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
    try:
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
            metadata={'is_completed': reminder.is_completed}
        )
        
        # Если это AJAX запрос, возвращаем JSON
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'is_completed': reminder.is_completed})
        
        # Иначе редиректим обратно
        flash('Статус напоминания обновлен', 'success')
        return redirect(url_for('reminders.reminders_list'))
    except Exception as e:
        db.session.rollback()
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash(f'Ошибка при обновлении статуса: {str(e)}', 'error')
        return redirect(url_for('reminders.reminders_list'))

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
        title = (data.get('title') or '').strip()
        message = (data.get('message') or '').strip()
        reminder_time_str = (data.get('reminder_time') or '').strip()
        timezone_offset = data.get('timezone_offset', None)
    else:
        title = (request.form.get('title') or '').strip()
        message = (request.form.get('message') or '').strip()
        reminder_time_str = (request.form.get('reminder_time') or '').strip()
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
                    if offset_minutes == 0:
                        tz = ZoneInfo("UTC")
                    else:
                        tz_name = f"Etc/GMT{-offset_minutes//60:+d}"
                        tz = ZoneInfo(tz_name)
                    reminder_time = reminder_time_naive.replace(tzinfo=tz)
                    reminder_time_moscow = reminder_time.astimezone(MOSCOW_TZ)
                    reminder_time = reminder_time_moscow.replace(tzinfo=None)
                except (ValueError, TypeError) as e:
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
