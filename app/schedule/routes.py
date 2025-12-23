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


def _parse_local_datetime(date_str: str, time_str: str, timezone: str):
    input_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
    lesson_datetime_str = f"{date_str} {time_str}"
    lesson_datetime_local = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
    lesson_datetime_local = lesson_datetime_local.replace(tzinfo=input_tz)
    base_lesson_datetime = lesson_datetime_local.astimezone(MOSCOW_TZ).replace(tzinfo=None)
    return base_lesson_datetime


def _student_has_overlap(student_id: int, start_dt: datetime, duration_min: int, exclude_lesson_id: int | None = None) -> bool:
    if not student_id or not start_dt or not duration_min:
        return False
    end_dt = start_dt + timedelta(minutes=duration_min)

    day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    q = Lesson.query.filter(
        Lesson.student_id == student_id,
        Lesson.lesson_date >= day_start,
        Lesson.lesson_date < day_end
    )
    if exclude_lesson_id:
        q = q.filter(Lesson.lesson_id != exclude_lesson_id)

    candidates = q.all()
    for l in candidates:
        l_start = l.lesson_date
        l_end = l.lesson_date + timedelta(minutes=int(l.duration or 60))
        if (l_start < end_dt) and (start_dt < l_end):
            return True

    return False

@schedule_bp.route('/schedule')
@login_required
def schedule():
    """Расписание уроков"""
    week_offset = request.args.get('week', 0, type=int)
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    timezone = request.args.get('timezone', 'moscow')
    student_filter = request.args.get('student_id', type=int)

    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ

    today = moscow_now().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]

    # Премиум UX: по умолчанию рабочий диапазон, но можно расширить через query
    slot_minutes = request.args.get('slot', 30, type=int)
    slot_minutes = slot_minutes if slot_minutes in (15, 30, 60) else 30
    # По умолчанию: полные сутки, как ты просил. Пользователь может сузить диапазон через query.
    day_start_hour = request.args.get('start', 0, type=int)
    day_end_hour = request.args.get('end', 23, type=int)
    if day_start_hour < 0:
        day_start_hour = 0
    if day_end_hour > 23:
        day_end_hour = 23
    if day_end_hour < day_start_hour:
        day_start_hour, day_end_hour = 7, 22
    total_minutes = (day_end_hour - day_start_hour + 1) * 60
    total_slots = int(total_minutes / slot_minutes)
    time_labels = [f"{hour:02d}:00" for hour in range(day_start_hour, day_end_hour + 1)]

    # Создаем datetime для фильтрации (lesson_date в БД хранится как naive в московском времени)
    # Используем date() для сравнения, чтобы избежать проблем с timezone
    week_start_datetime = datetime.combine(week_start, time.min)
    week_end_datetime = datetime.combine(week_end, time.max)
    
    # Добавляем небольшой запас для учета возможных проблем с часовыми поясами
    # Фильтруем уроки, которые попадают в диапазон недели
    query = Lesson.query.filter(
        Lesson.lesson_date >= week_start_datetime,
        Lesson.lesson_date < week_end_datetime + timedelta(days=1)
    )

    if status_filter:
        query = query.filter_by(status=status_filter)

    if category_filter:
        query = query.join(Student).filter(Student.category == category_filter)

    if student_filter:
        query = query.filter(Lesson.student_id == student_filter)

    lessons = query.options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date).all()

    real_events = []
    for lesson in lessons:
        lesson_date = lesson.lesson_date
        if lesson_date.tzinfo is None:
            lesson_date = lesson_date.replace(tzinfo=MOSCOW_TZ)

        lesson_date_display = lesson_date.astimezone(display_tz)
        lesson_date_local = lesson_date_display.date()
        day_index = (lesson_date_local - week_start).days
        
        # Отладочное логирование для проблемных случаев
        if day_index < 0 or day_index >= 7:
            logger.debug(f"Урок {lesson.lesson_id} вне недели: lesson_date={lesson.lesson_date}, "
                        f"lesson_date_local={lesson_date_local}, week_start={week_start}, day_index={day_index}")
            continue
        
        # Проверяем, что урок действительно попадает в нужный день недели
        if 0 <= day_index < 7:
            start_time = lesson_date_display.time()
            # Вычисляем время окончания, но сохраняем исходную длительность из БД
            end_datetime = lesson_date_display + timedelta(minutes=lesson.duration)
            end_time = end_datetime.time()
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
                'lesson_type': lesson.lesson_type,
                'duration_minutes': int(lesson.duration or 60)  # Сохраняем исходную длительность из БД
            })

    # Позиционирование отдаём фронтенду: сохраняем start_total/duration и колонку/ширину,
    # а top/height вычисляются из slot_minutes и pxPerSlot в JS.
    day_events = {i: [] for i in range(7)}
    day_start_minutes = day_start_hour * 60

    for event in real_events:
        # Используем исходную длительность из БД, а не пересчитываем из времени начала/окончания
        # Это важно, так как при переходе через полночь (например, 23:00 -> 00:00) пересчет даст неправильный результат
        duration_minutes = event.get('duration_minutes', 60)
        duration_minutes = max(duration_minutes, slot_minutes)
        event['start_total'] = event['start'].hour * 60 + event['start'].minute
        # Вычисляем end_total с учетом возможного перехода через полночь
        end_hour = event['end'].hour
        end_minute = event['end'].minute
        # Если end_time меньше start_time, значит урок перешел через полночь
        if end_hour * 60 + end_minute < event['start_total']:
            # Урок перешел через полночь, end_total = 24:00 (1440 минут)
            event['end_total'] = 1440
        else:
            event['end_total'] = end_hour * 60 + end_minute
        event['duration_minutes'] = duration_minutes
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
            # Ширина урока: минимум 8% для читаемости, но лучше использовать почти всю ширину колонки
            event['width_percent'] = max(column_width - 1.5, 8)

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
                'lesson_type': event.get('lesson_type'),
                'topic': event.get('topic'),
                'start_time': event['start_time'],
                'profile_url': event['profile_url'],
                'lesson_url': url_for('lessons.lesson_view', lesson_id=event['lesson_id']),
                'start_total': event['start_total'],
                'duration_minutes': event.get('duration_minutes') or 60,
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
        student_filter=student_filter,
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

        base_lesson_datetime = _parse_local_datetime(lesson_date_str, lesson_time_str, timezone)

        student = Student.query.get_or_404(student_id)

        if lesson_mode == 'recurring' and repeat_count and repeat_count > 1:
            lessons_to_create = repeat_count
        else:
            lessons_to_create = 1

        created_lessons = []
        for week_offset in range(lessons_to_create):
            lesson_datetime = base_lesson_datetime + timedelta(weeks=week_offset)
            
            if _student_has_overlap(student_id, lesson_datetime, duration):
                logger.warning(
                    f"Пересечение уроков: student_id={student_id}, "
                    f"start={lesson_datetime}, duration={duration}. Пропускаем."
                )
                continue
            
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
            display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
            created_payload = []
            for l in created_lessons:
                dt = l.lesson_date.replace(tzinfo=MOSCOW_TZ)
                dt_display = dt.astimezone(display_tz)
                created_payload.append({
                    'lesson_id': l.lesson_id,
                    'student': student.name,
                    'student_id': student.student_id,
                    'status': 'Запланирован',
                    'status_code': l.status,
                    'lesson_type': l.lesson_type,
                    'topic': l.topic,
                    'start_time': dt_display.strftime('%H:%M'),
                    'start_total': dt_display.hour * 60 + dt_display.minute,
                    'duration_minutes': int(l.duration or 60),
                    'profile_url': url_for('students.student_profile', student_id=student.student_id),
                    'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
                })
            return jsonify({
                'success': True,
                'message': success_message,
                'created_lessons': created_payload,
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


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/reschedule', methods=['POST'])
@login_required
def schedule_reschedule_lesson(lesson_id: int):
    """Перенос урока на другое время (AJAX)."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

    date_str = (data.get('lesson_date') or '').strip()
    time_str = (data.get('lesson_time') or '').strip()
    timezone = (data.get('timezone') or 'moscow').strip()

    if not date_str or not time_str:
        return jsonify({'success': False, 'error': 'lesson_date и lesson_time обязательны'}), 400

    try:
        new_dt = _parse_local_datetime(date_str, time_str, timezone)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Ошибка формата даты/времени: {e}'}), 400

    duration = int(lesson.duration or 60)
    if _student_has_overlap(lesson.student_id, new_dt, duration, exclude_lesson_id=lesson.lesson_id):
        return jsonify({'success': False, 'error': 'Есть пересечение по времени для этого ученика'}), 409

    try:
        old_dt = lesson.lesson_date
        lesson.lesson_date = new_dt
        db.session.commit()

        audit_logger.log(
            action='reschedule_lesson',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'old_lesson_date': str(old_dt),
                'new_lesson_date': str(new_dt),
            }
        )

        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='reschedule_lesson', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/set-status', methods=['POST'])
@login_required
def schedule_set_status(lesson_id: int):
    """Быстрое изменение статуса урока (AJAX)."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    status = (data.get('status') or '').strip()
    if status not in ('planned', 'in_progress', 'completed', 'cancelled'):
        return jsonify({'success': False, 'error': 'Некорректный status'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    try:
        old_status = lesson.status
        lesson.status = status
        db.session.commit()

        audit_logger.log(
            action='set_lesson_status',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'old_status': old_status,
                'new_status': status,
            }
        )
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='set_lesson_status', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/update', methods=['POST'])
@login_required
def schedule_update_lesson(lesson_id: int):
    """Инлайн-редактирование ключевых полей урока (AJAX)."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)

    duration = data.get('duration')
    lesson_type = data.get('lesson_type')
    topic = data.get('topic')

    # duration
    if duration is not None:
        try:
            duration = int(duration)
        except Exception:
            return jsonify({'success': False, 'error': 'duration должен быть числом'}), 400
        if duration < 30 or duration > 240 or (duration % 30) != 0:
            return jsonify({'success': False, 'error': 'duration: 30..240 с шагом 30'}), 400

    # lesson_type
    if lesson_type is not None:
        lesson_type = str(lesson_type).strip()
        if lesson_type not in ('regular', 'exam', 'introductory'):
            return jsonify({'success': False, 'error': 'Некорректный lesson_type'}), 400

    # topic
    if topic is not None:
        topic = str(topic).strip()
        if len(topic) > 300:
            return jsonify({'success': False, 'error': 'topic слишком длинная'}), 400

    # Пересечение по времени учитываем только если меняется duration
    if duration is not None:
        if _student_has_overlap(lesson.student_id, lesson.lesson_date, duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'success': False, 'error': 'Есть пересечение по времени для этого ученика'}), 409

    try:
        old = {
            'duration': lesson.duration,
            'lesson_type': lesson.lesson_type,
            'topic': lesson.topic,
        }

        if duration is not None:
            lesson.duration = duration
        if lesson_type is not None:
            lesson.lesson_type = lesson_type
        if topic is not None:
            lesson.topic = topic

        db.session.commit()

        audit_logger.log(
            action='update_lesson_inline',
            entity='Lesson',
            entity_id=lesson.lesson_id,
            status='success',
            metadata={
                'student_id': lesson.student_id,
                'student_name': lesson.student.name if lesson.student else None,
                'old': old,
                'new': {
                    'duration': lesson.duration,
                    'lesson_type': lesson.lesson_type,
                    'topic': lesson.topic,
                }
            }
        )

        return jsonify({
            'success': True,
            'lesson': {
                'lesson_id': lesson.lesson_id,
                'duration_minutes': int(lesson.duration or 60),
                'lesson_type': lesson.lesson_type,
                'topic': lesson.topic,
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='update_lesson_inline', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500
