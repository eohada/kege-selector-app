"""
Маршруты расписания
"""
import logging
from datetime import datetime, timedelta, time
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required

from app.schedule import schedule_bp
from app.models import Lesson, Student, db, moscow_now, MOSCOW_TZ, TOMSK_TZ
from core.audit_logger import audit_logger

logger = logging.getLogger(__name__)

@schedule_bp.route('/schedule')
@login_required
def schedule():
    """Расписание уроков"""
    week_offset = request.args.get('week', 0, type=int)
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    timezone = request.args.get('timezone', 'moscow')

    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ

    today = moscow_now().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]

    slot_minutes = 60
    day_start_hour = 0
    day_end_hour = 23
    total_slots = int((24 * 60) / slot_minutes)
    time_labels = [f"{hour:02d}:00" for hour in range(day_start_hour, day_end_hour + 1)]

    week_start_datetime = datetime.combine(week_start, time.min).replace(tzinfo=MOSCOW_TZ)
    week_end_datetime = datetime.combine(week_end, time.max).replace(tzinfo=MOSCOW_TZ)

    query = Lesson.query.filter(Lesson.lesson_date >= week_start_datetime, Lesson.lesson_date <= week_end_datetime)

    if status_filter:
        query = query.filter_by(status=status_filter)

    if category_filter:
        query = query.join(Student).filter(Student.category == category_filter)

    lessons = query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date).all()

    real_events = []
    for lesson in lessons:
        lesson_date = lesson.lesson_date
        if lesson_date.tzinfo is None:
            lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)

        lesson_date_display = lesson_date.astimezone(display_tz)
        lesson_date_local = lesson_date_display.date()
        day_index = (lesson_date_local - week_start).days
        if 0 <= day_index < 7:
            start_time = lesson_date_display.time()
            end_time = (lesson_date_display + timedelta(minutes=lesson.duration)).time()
            status_text = {'planned': 'Запланирован', 'in_progress': 'Идет сейчас', 'completed': 'Проведен', 'cancelled': 'Отменен'}.get(lesson.status, lesson.status)
            if not lesson.student:
                continue  # Пропускаем уроки без студента
            profile_url = url_for('students.student_profile', student_id=lesson.student.student_id)
            real_events.append({
                'lesson_id': lesson.lesson_id,
                'student': lesson.student.name,
                'student_id': lesson.student.student_id,
                'subject': 'Информатика',
                'grade': f"{lesson.student.school_class} класс" if lesson.student.school_class else (lesson.student.category or 'Не указано'),
                'status': status_text,
                'status_code': lesson.status,
                'day_index': day_index,
                'start': start_time,
                'end': end_time,
                'start_time': start_time.strftime('%H:%M'),
                'profile_url': profile_url,
                'topic': lesson.topic,
                'lesson_type': lesson.lesson_type
            })

    slot_height_px = 32
    visual_slot_height_px = slot_height_px * 2
    day_events = {i: [] for i in range(7)}
    day_start_minutes = day_start_hour * 60

    for event in real_events:
        start_minutes = (event['start'].hour * 60 + event['start'].minute) - day_start_minutes
        start_minutes = max(start_minutes, 0)
        duration_minutes = ((event['end'].hour * 60 + event['end'].minute) - (event['start'].hour * 60 + event['start'].minute))
        duration_minutes = max(duration_minutes, slot_minutes)
        offset_slots = start_minutes / slot_minutes
        duration_slots = duration_minutes / slot_minutes
        event['offset_slots'] = offset_slots
        event['duration_slots'] = duration_slots
        event['start_total'] = event['start'].hour * 60 + event['start'].minute
        event['end_total'] = event['end'].hour * 60 + event['end'].minute
        event['top_px'] = offset_slots * visual_slot_height_px
        event['height_px'] = max(duration_slots * visual_slot_height_px - 4, visual_slot_height_px * 0.75)
        day_events[event['day_index']].append(event)

    for day_index, events in day_events.items():
        events.sort(key=lambda e: (e['start_total'], e['end_total']))
        active = []
        max_columns = 1
        for event in events:
            current_start = event['start_total']
            active = [a for a in active if a['end_total'] > current_start]
            used_columns = {a['column_index'] for a in active}
            column_index = 0
            while column_index in used_columns:
                column_index += 1
            event['column_index'] = column_index
            active.append(event)
            max_columns = max(max_columns, len(active))
        for event in events:
            event['columns_total'] = max_columns
            column_width = 100 / max_columns
            event['left_percent'] = column_width * event['column_index']
            event['width_percent'] = max(column_width - 1.5, 5)

    day_events_json = {i: [] for i in range(7)}
    for day_index, events in day_events.items():
        for event in events:
            json_event = {
                'lesson_id': event['lesson_id'],
                'student': event['student'],
                'student_id': event['student_id'],
                'subject': event['subject'],
                'grade': event['grade'],
                'status': event['status'],
                'status_code': event['status_code'],
                'start_time': event['start_time'],
                'profile_url': event['profile_url'],
                'top_px': event['top_px'],
                'height_px': event['height_px'],
                'left_percent': event['left_percent'],
                'width_percent': event['width_percent']
            }
            day_events_json[day_index].append(json_event)

    week_label = f"{week_days[0].strftime('%d.%m.%Y')} — {week_days[-1].strftime('%d.%m.%Y')}"

    students = Student.query.filter_by(is_active=True).order_by(Student.name).all()
    statuses = ['planned', 'in_progress', 'completed', 'cancelled']
    categories = ['ЕГЭ', 'ОГЭ', 'ЛЕВЕЛАП', 'ПРОГРАММИРОВАНИЕ']

    return render_template(
        'schedule.html',
        week_days=week_days,
        week_label=week_label,
        time_labels=time_labels,
        day_events=day_events_json,
        slot_minutes=slot_minutes,
        total_slots=total_slots,
        start_hour=day_start_hour,
        end_hour=day_end_hour,
        week_offset=week_offset,
        status_filter=status_filter,
        category_filter=category_filter,
        timezone=timezone,
        students=students,
        statuses=statuses,
        categories=categories
    )

@schedule_bp.route('/schedule/create-lesson', methods=['POST'])
@login_required
def schedule_create_lesson():
    """Создание урока из расписания"""
    try:
        student_id = request.form.get('student_id', type=int)
        lesson_date_str = request.form.get('lesson_date')
        lesson_time_str = request.form.get('lesson_time')
        duration = request.form.get('duration', 60, type=int)
        lesson_type = request.form.get('lesson_type', 'regular')
        timezone = request.form.get('timezone', 'moscow')
        lesson_mode = request.form.get('lesson_mode', 'single')
        repeat_count = request.form.get('repeat_count', type=int)

        if not student_id or not lesson_date_str or not lesson_time_str:
            error_message = 'Заполните все обязательные поля'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({
                    'success': False,
                    'error': error_message
                }), 400
            flash(error_message, 'error')
            return redirect(url_for('schedule.schedule'))

        input_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
        lesson_datetime_str = f"{lesson_date_str} {lesson_time_str}"
        lesson_datetime_local = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
        # Создаем timezone-aware datetime
        lesson_datetime_local = lesson_datetime_local.replace(tzinfo=input_tz)
        # Конвертируем в московское время для хранения в БД
        base_lesson_datetime = lesson_datetime_local.astimezone(MOSCOW_TZ)
        # Убираем timezone перед сохранением в БД (SQLAlchemy сохранит как naive)
        base_lesson_datetime = base_lesson_datetime.replace(tzinfo=None)

        student = Student.query.get_or_404(student_id)

        if lesson_mode == 'recurring' and repeat_count and repeat_count > 1:
            lessons_to_create = repeat_count
        else:
            lessons_to_create = 1

        created_lessons = []
        for week_offset in range(lessons_to_create):
            lesson_datetime = base_lesson_datetime + timedelta(weeks=week_offset)
            new_lesson = Lesson(
                student_id=student_id,
                lesson_date=lesson_datetime,
                duration=duration,
                lesson_type=lesson_type,
                status='planned'
            )
            db.session.add(new_lesson)
            created_lessons.append(new_lesson)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise
        
        for created_lesson in created_lessons:
            audit_logger.log(
                action='create_lesson_from_schedule',
                entity='Lesson',
                entity_id=created_lesson.lesson_id,
                status='success',
                metadata={
                    'student_id': student_id,
                    'student_name': student.name,
                    'lesson_mode': lesson_mode,
                    'repeat_count': lessons_to_create,
                    'lesson_date': str(created_lesson.lesson_date),
                    'duration': duration,
                    'lesson_type': lesson_type
                }
            )

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if lessons_to_create > 1:
            success_message = f'Создано {lessons_to_create} уроков с {student.name} (на {lessons_to_create} недель)'
            logger.info(f'Created {lessons_to_create} lessons for student {student_id} starting from {base_lesson_datetime}')
        else:
            success_message = f'Урок с {student.name} успешно создан'
            logger.info(f'Created lesson {created_lessons[0].lesson_id} for student {student_id} at {base_lesson_datetime}')

        if is_ajax:
            return jsonify({
                'success': True,
                'message': success_message
            }), 200

        flash(success_message, 'success')
    except Exception as e:
        db.session.rollback()
        error_details = str(e)
        logger.error(f'Error creating lesson: {error_details}', exc_info=True)

        if 'time' in error_details.lower() or 'date' in error_details.lower() or 'strptime' in error_details.lower():
            error_message = f'Ошибка в формате даты или времени: {error_details}'
        elif 'not found' in error_details.lower() or '404' in error_details.lower():
            error_message = 'Ученик не найден'
        else:
            error_message = f'Ошибка при создании урока: {error_details}'

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if is_ajax:
            return jsonify({
                'success': False,
                'error': error_message
            }), 500

        flash(error_message, 'error')

    week_offset = request.form.get('week_offset', 0, type=int)
    status_filter = request.form.get('status_filter', '')
    category_filter = request.form.get('category_filter', '')
    timezone = request.form.get('timezone', 'moscow')

    params = {'week': week_offset, 'timezone': timezone}
    if status_filter:
        params['status'] = status_filter
    if category_filter:
        params['category'] = category_filter

    return redirect(url_for('schedule.schedule', **params))
