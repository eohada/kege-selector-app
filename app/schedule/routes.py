"""
Маршруты расписания
"""
import logging
from datetime import datetime, timedelta, time, date, timezone as dt_timezone
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from app.schedule import schedule_bp
from app.models import Lesson, Student, User, RecurringLessonSlot, db, moscow_now, MOSCOW_TZ, TOMSK_TZ
from app.auth.rbac_utils import get_user_scope, has_permission
from app.notifications.service import notify_student_and_parents
from core.audit_logger import audit_logger
import secrets

logger = logging.getLogger(__name__)

RU_MONTHS_GEN = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
]
RU_MONTHS_NOM = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
]


def _add_months(src: date, months: int) -> date:
    month_idx = src.month - 1 + months
    year = src.year + month_idx // 12
    month = month_idx % 12 + 1
    return date(year, month, 1)

def _resolve_accessible_student_ids_for_current_user() -> list[int] | None:
    """
    Lessons.student_id хранит Student.student_id.
    get_user_scope() возвращает список User.id учеников.
    Маппим User.id -> Student.student_id по user_id и fallback student_id==user.id.
    """
    if not current_user.is_authenticated:
        return []
    if current_user.is_creator() or current_user.is_admin() or current_user.is_chief_tester():
        return None

    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return None

    user_ids = scope.get('student_ids') or []
    if current_user.is_student() and current_user.id not in user_ids:
        user_ids = [current_user.id]

    if not user_ids:
        return []

    student_ids: list[int] = []
    try:
        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in by_user_id if s])
        usernames = list(dict.fromkeys([(u.username or '').strip() for u in User.query.filter(User.id.in_(user_ids)).all() if (u.username or '').strip()]))
        if usernames:
            by_platform = Student.query.filter(Student.platform_id.in_(usernames)).all()
            student_ids.extend([s.student_id for s in by_platform if s])
        if user_ids:
            by_legacy = Student.query.filter(Student.student_id.in_(user_ids)).all()
            student_ids.extend([s.student_id for s in by_legacy if s])
    except Exception as e:
        logger.warning(f"Schedule: failed map scope user_ids->student_ids: {e}")

    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _resolve_accessible_student_ids_for_user(user: User) -> list[int] | None:
    """То же, что scope для current_user, но для token-based export."""
    if not user:
        return []
    if user.is_creator() or user.is_admin() or user.is_chief_tester():
        return None

    scope = get_user_scope(user)
    if scope.get('can_see_all'):
        return None

    user_ids = scope.get('student_ids') or []
    if user.is_student() and user.id not in user_ids:
        user_ids = [user.id]
    if not user_ids:
        return []

    student_ids: list[int] = []
    try:
        by_user_id = Student.query.filter(Student.user_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in by_user_id if s])
    except Exception:
        pass
    try:
        students_by_id = Student.query.filter(Student.student_id.in_(user_ids)).all()
        student_ids.extend([s.student_id for s in students_by_id if s])
    except Exception:
        pass

    seen = set()
    out: list[int] = []
    for sid in student_ids:
        if sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _can_manage_schedule() -> bool:
    if not current_user.is_authenticated:
        return False
    if current_user.is_creator() or current_user.is_admin():
        return True
    if current_user.is_student() or current_user.is_parent():
        return False
    if getattr(current_user, 'is_tutor', None) and current_user.is_tutor():
        return True
    return bool(
        has_permission(current_user, 'tools.schedule')
        or has_permission(current_user, 'lesson.create')
        or has_permission(current_user, 'lesson.edit')
    )


def _require_lesson_in_scope(lesson: Lesson) -> bool:
    """Проверка, что урок в области видимости пользователя."""
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is None:
        return True
    return bool(allowed and lesson.student_id in allowed)

def _parse_date(value: str | None):
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return None

def _dt_to_ics_utc(dt_naive_msk: datetime) -> str:
    """Lessons.lesson_date хранится naive как MSK. Конвертим в UTC для .ics."""
    try:
        from zoneinfo import ZoneInfo
        if getattr(dt_naive_msk, 'tzinfo', None) is None:
            dt = dt_naive_msk.replace(tzinfo=MOSCOW_TZ).astimezone(ZoneInfo("UTC"))
        else:
            dt = dt_naive_msk.astimezone(ZoneInfo("UTC"))
    except Exception:
        if getattr(dt_naive_msk, 'tzinfo', None) is None:
            dt = dt_naive_msk.replace(tzinfo=MOSCOW_TZ)
        else:
            dt = dt_naive_msk
    return dt.strftime('%Y%m%dT%H%M%SZ')


def _dt_to_ics_local(dt_naive_msk: datetime, tz) -> str:
    """
    Возвращаем datetime в локальной таймзоне (без 'Z'), чтобы импорт в Google Calendar
    совпадал с отображением в UI (wall time).
    """
    try:
        if getattr(dt_naive_msk, 'tzinfo', None) is None:
            aware = dt_naive_msk.replace(tzinfo=MOSCOW_TZ)
        else:
            aware = dt_naive_msk
        local = aware.astimezone(tz)
    except Exception:
        local = dt_naive_msk
    return local.strftime('%Y%m%dT%H%M%S')


def _parse_local_datetime(date_str: str, time_str: str, timezone: str):
    input_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
    lesson_datetime_str = f"{date_str} {time_str}"
    lesson_datetime_local = datetime.strptime(lesson_datetime_str, '%Y-%m-%d %H:%M')
    lesson_datetime_local = lesson_datetime_local.replace(tzinfo=input_tz)
    lesson_datetime_msk = lesson_datetime_local.astimezone(MOSCOW_TZ)
    return lesson_datetime_msk.replace(tzinfo=None)


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


def _tutor_has_overlap(tutor_user_id: int, start_dt: datetime, duration_min: int, exclude_lesson_id: int | None = None) -> bool:
    """
    Проверка пересечения по преподавателю (чтобы не поставить 2 урока одновременно).
    Работает по области видимости тьютора (через Enrollment→scope→student_ids→Student.student_id).
    """
    if not tutor_user_id or not start_dt or not duration_min:
        return False
    end_dt = start_dt + timedelta(minutes=duration_min)

    day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    allowed_student_ids = _resolve_accessible_student_ids_for_current_user()
    if allowed_student_ids is None:
        return False
    if not allowed_student_ids:
        return False

    q = Lesson.query.filter(
        Lesson.student_id.in_(allowed_student_ids),
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
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        if not (current_user.is_student() or current_user.is_parent() or current_user.is_tutor() or current_user.is_admin() or current_user.is_creator()):
            flash('У вас недостаточно прав для просмотра расписания.', 'danger')
            return redirect(url_for('main.dashboard'))

    week_offset = request.args.get('week', 0, type=int)
    view_mode = (request.args.get('view') or 'week').strip().lower()
    if view_mode not in ('week', 'agenda', 'day', 'month'):
        view_mode = 'week'
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category', '')
    timezone = request.args.get('timezone', 'moscow')
    student_filter = request.args.get('student_id', type=int)

    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ

    today = moscow_now().date()
    month_weeks = []
    month_start = None
    month_end = None
    day_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    if view_mode in ('week', 'agenda'):
        week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        week_days = [week_start + timedelta(days=i) for i in range(7)]
        week_end = week_days[-1]
        period_start = week_start
        period_end = week_end
        week_label = f"{week_days[0].strftime('%d.%m.%Y')} — {week_days[-1].strftime('%d.%m.%Y')}"
    elif view_mode == 'day':
        day_date = today + timedelta(days=week_offset)
        week_start = day_date
        week_days = [day_date]
        week_end = day_date
        period_start = day_date
        period_end = day_date
        week_label = f"{day_date.day:02d} {RU_MONTHS_GEN[day_date.month - 1]} {day_date.year}"
    else:
        month_start = _add_months(today.replace(day=1), week_offset)
        month_end = _add_months(month_start, 1) - timedelta(days=1)
        week_start = month_start
        week_end = month_end
        week_days = []
        period_start = month_start
        period_end = month_end
        week_label = f"{RU_MONTHS_NOM[month_start.month - 1]} {month_start.year}"

    slot_minutes = request.args.get('slot', 30, type=int)
    slot_minutes = slot_minutes if slot_minutes in (15, 30, 60) else 30
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

    week_start_datetime = datetime.combine(period_start, time.min)
    week_end_datetime = datetime.combine(period_end, time.max)
    
    query = Lesson.query.filter(
        Lesson.lesson_date >= week_start_datetime,
        Lesson.lesson_date < week_end_datetime + timedelta(days=1)
    )

    allowed_student_ids = _resolve_accessible_student_ids_for_current_user()
    if allowed_student_ids is not None:
        if not allowed_student_ids:
            query = query.filter(False)
        else:
            query = query.filter(Lesson.student_id.in_(allowed_student_ids))

    if status_filter:
        query = query.filter_by(status=status_filter)

    if category_filter:
        query = query.join(Student).filter(Student.category == category_filter)

    if student_filter:
        if allowed_student_ids is not None and student_filter not in allowed_student_ids:
            flash('Доступ запрещен.', 'danger')
            return redirect(url_for('schedule.schedule', week=week_offset, timezone=timezone))
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
        
        if day_index < 0 or day_index >= 7:
            logger.debug(f"Урок {lesson.lesson_id} вне недели: lesson_date={lesson.lesson_date}, "
                        f"lesson_date_local={lesson_date_local}, week_start={week_start}, day_index={day_index}")
            continue
        
        if 0 <= day_index < 7:
            start_time = lesson_date_display.time()
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

    day_columns_count = len(week_days) if view_mode in ('week', 'day') else 0
    day_events = {i: [] for i in range(day_columns_count)}
    day_start_minutes = day_start_hour * 60

    for event in real_events:
        duration_minutes = event.get('duration_minutes', 60)
        duration_minutes = max(duration_minutes, slot_minutes)
        event['start_total'] = event['start'].hour * 60 + event['start'].minute
        end_hour = event['end'].hour
        end_minute = event['end'].minute
        if end_hour * 60 + end_minute < event['start_total']:
            event['end_total'] = 1440
        else:
            event['end_total'] = end_hour * 60 + end_minute
        event['duration_minutes'] = duration_minutes
        if day_columns_count and event['day_index'] in day_events:
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
            event['width_percent'] = max(column_width - 1.5, 8)

    day_events_json = {i: [] for i in range(day_columns_count)}
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
            json_event['is_conflict'] = bool((event.get('columns_total') or 1) > 1)
            day_events_json[day_index].append(json_event)

    month_lessons_map = {}
    if view_mode == 'month' and month_start and month_end:
        for l in lessons:
            if not l.student:
                continue
            dt = l.lesson_date.replace(tzinfo=MOSCOW_TZ).astimezone(display_tz)
            day_key = dt.date().isoformat()
            month_lessons_map.setdefault(day_key, []).append({
                'time': dt.strftime('%H:%M'),
                'student_name': l.student.name,
                'status': l.status,
                'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
            })

        grid_start = month_start - timedelta(days=month_start.weekday())
        grid_end = month_end + timedelta(days=(6 - month_end.weekday()))
        cursor = grid_start
        while cursor <= grid_end:
            week_cells = []
            for _ in range(7):
                iso = cursor.isoformat()
                items = month_lessons_map.get(iso, [])
                week_cells.append({
                    'date': cursor,
                    'iso': iso,
                    'in_month': cursor.month == month_start.month,
                    'is_today': cursor == today,
                    'day_name': day_names[cursor.weekday()],
                    'events': items[:3],
                    'events_count': len(items),
                })
                cursor += timedelta(days=1)
            month_weeks.append(week_cells)

    students_q = Student.query.filter_by(is_active=True)
    if allowed_student_ids is not None:
        if not allowed_student_ids:
            students_q = students_q.filter(False)
        else:
            students_q = students_q.filter(Student.student_id.in_(allowed_student_ids))
    students = students_q.order_by(Student.name).all()
    statuses = ['planned', 'in_progress', 'completed', 'cancelled']
    categories = ['ЕГЭ', 'ОГЭ', 'ЛЕВЕЛАП', 'ПРОГРАММИРОВАНИЕ']

    agenda = []
    try:
        for l in lessons:
            if not l.student:
                continue
            dt = l.lesson_date.replace(tzinfo=MOSCOW_TZ)
            dt_display = dt.astimezone(display_tz)
            agenda.append({
                'lesson_id': l.lesson_id,
                'date': dt_display.strftime('%Y-%m-%d'),
                'time': dt_display.strftime('%H:%M'),
                'date_human': dt_display.strftime('%d.%m.%Y'),
                'student_name': l.student.name,
                'student_id': l.student.student_id,
                'status': l.status,
                'topic': l.topic,
                'duration': int(l.duration or 60),
                'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
                'profile_url': url_for('students.student_profile', student_id=l.student.student_id),
            })
    except Exception:
        agenda = []

    agenda_week_sidebar = agenda
    try:
        if view_mode == 'week' and (not status_filter) and (current_user.is_student() or current_user.is_tutor()):
            agenda_week_sidebar = [a for a in (agenda or []) if (a.get('status') or '').lower() != 'planned']
    except Exception:
        agenda_week_sidebar = agenda

    today_display_date = moscow_now().astimezone(display_tz).date()

    return render_template(
        'schedule.html',
        week_days=week_days,
        week_label=week_label,
        time_labels=time_labels,
        day_events=day_events_json,
        slot_minutes=slot_minutes,
        total_slots=total_slots,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
        week_offset=week_offset,
        status_filter=status_filter,
        category_filter=category_filter,
        timezone=timezone,
        student_filter=student_filter,
        students=students,
        statuses=statuses,
        categories=categories,
        can_manage_schedule=_can_manage_schedule(),
        is_student_view=current_user.is_student(),
        is_parent_view=current_user.is_parent(),
        agenda=agenda,
        agenda_week_sidebar=agenda_week_sidebar,
        view_mode=view_mode,
        today_display_date=today_display_date,
        day_names=day_names,
        day_columns_count=day_columns_count,
        month_weeks=month_weeks,
    )

@schedule_bp.route('/schedule/create-lesson', methods=['POST'])
@login_required
def schedule_create_lesson():
    """Создание урока из расписания"""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        flash('У вас недостаточно прав для создания уроков.', 'danger')
        return redirect(url_for('schedule.schedule'))
        
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
        allowed_student_ids = _resolve_accessible_student_ids_for_current_user()
        if allowed_student_ids is not None and student.student_id not in allowed_student_ids:
            error_message = 'Доступ запрещен'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                return jsonify({'success': False, 'error': error_message}), 403
            flash(error_message, 'danger')
            return redirect(url_for('schedule.schedule'))

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

            if current_user.is_tutor() and _tutor_has_overlap(current_user.id, lesson_datetime, duration):
                logger.warning(
                    f"Пересечение уроков у преподавателя: tutor_id={current_user.id}, "
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

        try:
            for created_lesson in created_lessons:
                if created_lesson.status == 'planned':
                    date_str = created_lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if created_lesson.lesson_date else ''
                    notify_student_and_parents(
                        student,
                        kind='lesson_scheduled',
                        title='Новый урок запланирован',
                        body=(created_lesson.topic or '').strip() or None,
                        link_url=url_for('lessons.lesson_view', lesson_id=created_lesson.lesson_id),
                        meta={'lesson_id': created_lesson.lesson_id, 'date': date_str, 'topic': created_lesson.topic or ''},
                    )
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Could not commit lesson_scheduled notifications (schedule_create_lesson): {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson_scheduled (schedule_create_lesson): {e}")
        
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
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

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
    if current_user.is_tutor() and _tutor_has_overlap(current_user.id, new_dt, duration, exclude_lesson_id=lesson.lesson_id):
        return jsonify({'success': False, 'error': 'У вас уже есть урок в это время'}), 409

    try:
        old_dt = lesson.lesson_date
        lesson.lesson_date = new_dt
        db.session.commit()

        try:
            if lesson.status == 'planned' and lesson.student:
                date_str = lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else ''
                notify_student_and_parents(
                    lesson.student,
                    kind='lesson_scheduled',
                    title='Урок перенесён',
                    body=(lesson.topic or '').strip() or None,
                    link_url=url_for('lessons.lesson_view', lesson_id=lesson.lesson_id),
                    meta={'lesson_id': lesson.lesson_id, 'date': date_str, 'topic': lesson.topic or '', 'rescheduled': True},
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson reschedule notification: {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson reschedule: {e}")

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
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    status = (data.get('status') or '').strip()
    if status not in ('planned', 'in_progress', 'completed', 'cancelled'):
        return jsonify({'success': False, 'error': 'Некорректный status'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    try:
        old_status = lesson.status
        lesson.status = status
        db.session.commit()

        try:
            if status == 'planned' and old_status != 'planned' and lesson.student:
                date_str = lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else ''
                notify_student_and_parents(
                    lesson.student,
                    kind='lesson_scheduled',
                    title='Новый урок запланирован',
                    body=(lesson.topic or '').strip() or None,
                    link_url=url_for('lessons.lesson_view', lesson_id=lesson.lesson_id),
                    meta={'lesson_id': lesson.lesson_id, 'date': date_str, 'topic': lesson.topic or ''},
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson_scheduled notification (set_status): {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson status planned: {e}")

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
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.edit') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'Некорректный формат запроса'}), 400

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    duration = data.get('duration')
    lesson_type = data.get('lesson_type')
    topic = data.get('topic')
    lesson_date = data.get('lesson_date')
    lesson_time = data.get('lesson_time')
    timezone = (data.get('timezone') or 'moscow').strip()

    new_lesson_date = None
    if lesson_date is not None and lesson_time is not None:
        date_str = str(lesson_date).strip()
        time_str = str(lesson_time).strip()
        if date_str and time_str:
            try:
                new_lesson_date = _parse_local_datetime(date_str, time_str, timezone)
            except Exception as e:
                return jsonify({'success': False, 'error': f'Ошибка формата даты/времени: {e}'}), 400

    if duration is not None:
        try:
            duration = int(duration)
        except Exception:
            return jsonify({'success': False, 'error': 'duration должен быть числом'}), 400
        if duration < 30 or duration > 240 or (duration % 30) != 0:
            return jsonify({'success': False, 'error': 'duration: 30..240 с шагом 30'}), 400

    if lesson_type is not None:
        lesson_type = str(lesson_type).strip()
        if lesson_type not in ('regular', 'exam', 'introductory'):
            return jsonify({'success': False, 'error': 'Некорректный lesson_type'}), 400

    if topic is not None:
        topic = str(topic).strip()
        if len(topic) > 300:
            return jsonify({'success': False, 'error': 'topic слишком длинная'}), 400

    check_date = new_lesson_date if new_lesson_date is not None else lesson.lesson_date
    check_duration = duration if duration is not None else (lesson.duration or 60)
    
    if new_lesson_date is not None or duration is not None:
        if _student_has_overlap(lesson.student_id, check_date, check_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'success': False, 'error': 'Есть пересечение по времени для этого ученика'}), 409
        if current_user.is_tutor() and _tutor_has_overlap(current_user.id, check_date, check_duration, exclude_lesson_id=lesson.lesson_id):
            return jsonify({'success': False, 'error': 'У вас уже есть урок в это время'}), 409

    try:
        old = {
            'duration': lesson.duration,
            'lesson_type': lesson.lesson_type,
            'topic': lesson.topic,
            'lesson_date': str(lesson.lesson_date) if lesson.lesson_date else None,
        }

        if new_lesson_date is not None:
            lesson.lesson_date = new_lesson_date
        if duration is not None:
            lesson.duration = duration
        if lesson_type is not None:
            lesson.lesson_type = lesson_type
        if topic is not None:
            lesson.topic = topic

        db.session.commit()

        try:
            if new_lesson_date is not None and lesson.status == 'planned' and lesson.student:
                date_str = lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else ''
                notify_student_and_parents(
                    lesson.student,
                    kind='lesson_scheduled',
                    title='Урок перенесён',
                    body=(lesson.topic or '').strip() or None,
                    link_url=url_for('lessons.lesson_view', lesson_id=lesson.lesson_id),
                    meta={'lesson_id': lesson.lesson_id, 'date': date_str, 'topic': lesson.topic or '', 'rescheduled': True},
                )
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    logger.warning(f"Could not commit lesson update reschedule notification: {e}")
        except Exception as e:
            logger.warning(f"Failed to notify about lesson update reschedule: {e}")

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

        response_data = {
            'lesson_id': lesson.lesson_id,
            'duration_minutes': int(lesson.duration or 60),
            'lesson_type': lesson.lesson_type,
            'topic': lesson.topic,
        }
        
        if new_lesson_date is not None:
            response_data['lesson_date'] = str(lesson.lesson_date)
        
        return jsonify({
            'success': True,
            'lesson': response_data
        }), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='update_lesson_inline', entity='Lesson', error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/api/events')
@login_required
def schedule_api_events():
    """
    JSON события для синхронизации внутри интерфейса.
    Права/видимость строго как у расписания.
    """
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    start_date = _parse_date(request.args.get('start'))
    end_date = _parse_date(request.args.get('end'))
    timezone = (request.args.get('timezone') or 'moscow').strip()
    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ

    if not start_date or not end_date:
        return jsonify({'success': False, 'error': 'start/end обязательны (YYYY-MM-DD)'}), 400

    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)

    q = Lesson.query.filter(Lesson.lesson_date >= start_dt, Lesson.lesson_date <= end_dt).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(Lesson.student_id.in_(allowed))

    lessons = q.all()
    out = []
    for l in lessons:
        if not l.student:
            continue
        dt = l.lesson_date.replace(tzinfo=MOSCOW_TZ)
        dt_display = dt.astimezone(display_tz)
        out.append({
            'lesson_id': l.lesson_id,
            'student_id': l.student.student_id,
            'student': l.student.name,
            'status_code': l.status,
            'lesson_type': l.lesson_type,
            'topic': l.topic,
            'duration_minutes': int(l.duration or 60),
            'date': dt_display.strftime('%Y-%m-%d'),
            'start_time': dt_display.strftime('%H:%M'),
            'start_total': dt_display.hour * 60 + dt_display.minute,
            'profile_url': url_for('students.student_profile', student_id=l.student.student_id),
            'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
        })
    return jsonify({'success': True, 'events': out})


@schedule_bp.route('/schedule/api/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
def schedule_delete_lesson(lesson_id: int):
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    try:
        meta = {
            'student_id': lesson.student_id,
            'student_name': lesson.student.name if lesson.student else None,
            'lesson_date': str(lesson.lesson_date),
            'duration': int(lesson.duration or 60),
            'lesson_type': lesson.lesson_type,
            'status': lesson.status,
        }
        db.session.delete(lesson)
        db.session.commit()
        try:
            audit_logger.log(action='delete_lesson_from_schedule', entity='Lesson', entity_id=lesson_id, status='success', metadata=meta)
        except Exception:
            pass
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        audit_logger.log_error(action='delete_lesson_from_schedule', entity='Lesson', entity_id=lesson_id, error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/export.ics')
@login_required
def schedule_export_ics():
    """Экспорт видимого расписания в iCalendar (.ics) для синхронизации."""
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        flash('У вас недостаточно прав для экспорта расписания.', 'danger')
        return redirect(url_for('schedule.schedule'))

    tz_param = (request.args.get('timezone') or '').strip().lower()
    if tz_param not in ('moscow', 'tomsk'):
        tz_param = 'moscow'
    export_tz = TOMSK_TZ if tz_param == 'tomsk' else MOSCOW_TZ
    export_tzid = 'Asia/Tomsk' if tz_param == 'tomsk' else 'Europe/Moscow'

    today = moscow_now().date()
    start_dt = datetime.combine(today - timedelta(days=14), time.min)
    end_dt = datetime.combine(today + timedelta(days=60), time.max)

    q = Lesson.query.filter(Lesson.lesson_date >= start_dt, Lesson.lesson_date <= end_dt).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(Lesson.student_id.in_(allowed))

    lessons = q.all()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BlackNeon//Schedule//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{export_tzid}",
    ]
    for l in lessons:
        if not l.student:
            continue
        dt_start_local = _dt_to_ics_local(l.lesson_date, export_tz)
        dt_end_local = _dt_to_ics_local(l.lesson_date + timedelta(minutes=int(l.duration or 60)), export_tz)
        summary = f"Урок: {l.student.name}"
        if l.topic:
            summary = f"{summary} · {l.topic}"
        uid = f"lesson-{l.lesson_id}@black-neon"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dt_to_ics_utc(moscow_now().replace(tzinfo=None))}",
            f"DTSTART;TZID={export_tzid}:{dt_start_local}",
            f"DTEND;TZID={export_tzid}:{dt_end_local}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    ics = "\r\n".join(lines) + "\r\n"

    from flask import Response
    return Response(
        ics,
        mimetype="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=\"schedule.ics\""},
    )


@schedule_bp.route('/schedule/ics/<string:token>')
def schedule_export_ics_by_token(token: str):
    """Приватный экспорт .ics по токену (для внешней синхронизации без логина)."""
    token = (token or '').strip()
    if not token or len(token) < 16:
        from flask import abort
        abort(404)

    user = User.query.filter_by(schedule_ics_token=token).first()
    if not user or not user.is_active:
        from flask import abort
        abort(404)

    tz_param = (request.args.get('timezone') or '').strip().lower()
    if tz_param not in ('moscow', 'tomsk'):
        tz_param = 'moscow'
    export_tz = TOMSK_TZ if tz_param == 'tomsk' else MOSCOW_TZ
    export_tzid = 'Asia/Tomsk' if tz_param == 'tomsk' else 'Europe/Moscow'

    today = moscow_now().date()
    start_dt = datetime.combine(today - timedelta(days=14), time.min)
    end_dt = datetime.combine(today + timedelta(days=60), time.max)

    q = Lesson.query.filter(Lesson.lesson_date >= start_dt, Lesson.lesson_date <= end_dt).options(db.joinedload(Lesson.student)).order_by(Lesson.lesson_date.asc())
    allowed = _resolve_accessible_student_ids_for_user(user)
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(Lesson.student_id.in_(allowed))

    lessons = q.all()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BlackNeon//Schedule//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{export_tzid}",
    ]
    for l in lessons:
        if not l.student:
            continue
        dt_start_local = _dt_to_ics_local(l.lesson_date, export_tz)
        dt_end_local = _dt_to_ics_local(l.lesson_date + timedelta(minutes=int(l.duration or 60)), export_tz)
        summary = f"Урок: {l.student.name}"
        if l.topic:
            summary = f"{summary} · {l.topic}"
        uid = f"lesson-{l.lesson_id}@black-neon"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_dt_to_ics_utc(moscow_now().replace(tzinfo=None))}",
            f"DTSTART;TZID={export_tzid}:{dt_start_local}",
            f"DTEND;TZID={export_tzid}:{dt_end_local}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    ics = "\r\n".join(lines) + "\r\n"

    from flask import Response
    return Response(ics, mimetype="text/calendar; charset=utf-8")


@schedule_bp.route('/schedule/ics-token/regenerate', methods=['POST'])
@login_required
def schedule_regenerate_ics_token():
    """Ротация приватного токена календаря."""
    if not has_permission(current_user, 'schedule.view') and not has_permission(current_user, 'tools.schedule'):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    try:
        for _ in range(5):
            token = secrets.token_urlsafe(24)
            exists = User.query.filter(User.schedule_ics_token == token).first()
            if not exists:
                current_user.schedule_ics_token = token
                db.session.commit()
                return jsonify({'success': True, 'token': token}), 200
        return jsonify({'success': False, 'error': 'Не удалось сгенерировать токен'}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@schedule_bp.route('/schedule/templates/api/list')
@login_required
def schedule_templates_list():
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    allowed = _resolve_accessible_student_ids_for_current_user()
    q = RecurringLessonSlot.query.filter(RecurringLessonSlot.is_active.is_(True)).options(db.joinedload(RecurringLessonSlot.student))
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(RecurringLessonSlot.student_id.in_(allowed))
    if not (current_user.is_admin() or current_user.is_creator()):
        q = q.filter((RecurringLessonSlot.owner_user_id == current_user.id) | (RecurringLessonSlot.owner_user_id.is_(None)))

    items = q.order_by(RecurringLessonSlot.student_id.asc(), RecurringLessonSlot.weekday.asc(), RecurringLessonSlot.time_hhmm.asc()).limit(500).all()
    out = []
    for t in items:
        out.append({
            'slot_id': t.slot_id,
            'student_id': t.student_id,
            'student_name': t.student.name if t.student else f"Student #{t.student_id}",
            'weekday': int(t.weekday),
            'time_hhmm': t.time_hhmm,
            'duration': int(t.duration or 60),
            'lesson_type': t.lesson_type,
            'timezone': t.timezone,
        })
    return jsonify({'success': True, 'templates': out})


@schedule_bp.route('/schedule/templates/api/create', methods=['POST'])
@login_required
def schedule_templates_create():
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
    except Exception:
        return jsonify({'success': False, 'error': 'student_id обязателен'}), 400

    try:
        weekday = int(data.get('weekday'))
    except Exception:
        return jsonify({'success': False, 'error': 'weekday обязателен'}), 400
    if weekday < 0 or weekday > 6:
        return jsonify({'success': False, 'error': 'weekday 0..6'}), 400

    time_hhmm = (data.get('time_hhmm') or '').strip()
    if not time_hhmm or len(time_hhmm) != 5 or time_hhmm[2] != ':':
        return jsonify({'success': False, 'error': 'time_hhmm формат HH:MM'}), 400

    duration = data.get('duration', 60)
    try:
        duration = int(duration)
    except Exception:
        return jsonify({'success': False, 'error': 'duration должен быть числом'}), 400
    if duration < 30 or duration > 240 or (duration % 30) != 0:
        return jsonify({'success': False, 'error': 'duration: 30..240 с шагом 30'}), 400

    lesson_type = (data.get('lesson_type') or 'regular').strip()
    if lesson_type not in ('regular', 'exam', 'introductory'):
        lesson_type = 'regular'

    timezone = (data.get('timezone') or 'moscow').strip().lower()
    if timezone not in ('moscow', 'tomsk'):
        timezone = 'moscow'

    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None and student_id not in allowed:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    exists = RecurringLessonSlot.query.filter_by(student_id=student_id, weekday=weekday, time_hhmm=time_hhmm, is_active=True).first()
    if exists:
        return jsonify({'success': True, 'slot_id': exists.slot_id}), 200

    tpl = RecurringLessonSlot(
        owner_user_id=current_user.id,
        student_id=student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        lesson_type=lesson_type,
        timezone=timezone,
        is_active=True,
    )
    db.session.add(tpl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'slot_id': tpl.slot_id}), 201


@schedule_bp.route('/schedule/templates/api/delete/<int:slot_id>', methods=['POST'])
@login_required
def schedule_templates_delete(slot_id: int):
    if not _can_manage_schedule():
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    tpl = RecurringLessonSlot.query.get_or_404(slot_id)
    allowed = _resolve_accessible_student_ids_for_current_user()
    if allowed is not None and tpl.student_id not in allowed:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    if not (current_user.is_admin() or current_user.is_creator()) and tpl.owner_user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403
    tpl.is_active = False
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True}), 200


@schedule_bp.route('/schedule/templates/api/from-lesson/<int:lesson_id>', methods=['POST'])
@login_required
def schedule_templates_create_from_lesson(lesson_id: int):
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    timezone = (data.get('timezone') or 'moscow').strip().lower()
    if timezone not in ('moscow', 'tomsk'):
        timezone = 'moscow'

    lesson = Lesson.query.options(db.joinedload(Lesson.student)).get_or_404(lesson_id)
    if not _require_lesson_in_scope(lesson):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    dt = lesson.lesson_date.replace(tzinfo=MOSCOW_TZ)
    display_tz = TOMSK_TZ if timezone == 'tomsk' else MOSCOW_TZ
    dt_local = dt.astimezone(display_tz)

    weekday = int(dt_local.weekday())
    time_hhmm = dt_local.strftime('%H:%M')
    duration = int(lesson.duration or 60)
    lesson_type = lesson.lesson_type or 'regular'
    if lesson_type not in ('regular', 'exam', 'introductory'):
        lesson_type = 'regular'

    exists = RecurringLessonSlot.query.filter_by(student_id=lesson.student_id, weekday=weekday, time_hhmm=time_hhmm, is_active=True).first()
    if exists:
        return jsonify({'success': True, 'slot_id': exists.slot_id}), 200

    tpl = RecurringLessonSlot(
        owner_user_id=current_user.id,
        student_id=lesson.student_id,
        weekday=weekday,
        time_hhmm=time_hhmm,
        duration=duration,
        lesson_type=lesson_type,
        timezone=timezone,
        is_active=True,
    )
    db.session.add(tpl)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'slot_id': tpl.slot_id}), 201


@schedule_bp.route('/schedule/templates/api/apply-week', methods=['POST'])
@login_required
def schedule_templates_apply_week():
    """Сгенерировать уроки на текущую неделю по шаблонам."""
    if not _can_manage_schedule() or (not has_permission(current_user, 'lesson.create') and not current_user.is_tutor()):
        return jsonify({'success': False, 'error': 'Доступ запрещен'}), 403

    data = request.get_json(silent=True) or {}
    try:
        week_offset = int(data.get('week_offset', 0))
    except Exception:
        week_offset = 0

    today = moscow_now().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)

    allowed = _resolve_accessible_student_ids_for_current_user()
    q = RecurringLessonSlot.query.filter(RecurringLessonSlot.is_active.is_(True))
    if allowed is not None:
        if not allowed:
            q = q.filter(False)
        else:
            q = q.filter(RecurringLessonSlot.student_id.in_(allowed))
    if not (current_user.is_admin() or current_user.is_creator()):
        q = q.filter(RecurringLessonSlot.owner_user_id == current_user.id)
    templates = q.all()

    created_payload = []
    created_pairs = []
    for t in templates:
        day = week_start + timedelta(days=int(t.weekday))
        dt = _parse_local_datetime(day.strftime('%Y-%m-%d'), t.time_hhmm, t.timezone)

        exists = Lesson.query.filter(
            Lesson.student_id == t.student_id,
            Lesson.lesson_date >= (dt - timedelta(minutes=1)),
            Lesson.lesson_date <= (dt + timedelta(minutes=1)),
        ).first()
        if exists:
            continue

        if _student_has_overlap(t.student_id, dt, int(t.duration or 60)):
            continue
        if current_user.is_tutor() and _tutor_has_overlap(current_user.id, dt, int(t.duration or 60)):
            continue

        l = Lesson(
            student_id=t.student_id,
            lesson_date=dt,
            duration=int(t.duration or 60),
            lesson_type=t.lesson_type,
            status='planned'
        )
        db.session.add(l)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            continue

        display_tz = TOMSK_TZ if (data.get('timezone') or 'moscow') == 'tomsk' else MOSCOW_TZ
        dt_display = l.lesson_date.replace(tzinfo=MOSCOW_TZ).astimezone(display_tz)
        st = Student.query.get(t.student_id)
        if not st:
            continue
        created_pairs.append((l, st))
        created_payload.append({
            'lesson_id': l.lesson_id,
            'student': st.name,
            'student_id': st.student_id,
            'status': 'Запланирован',
            'status_code': l.status,
            'lesson_type': l.lesson_type,
            'topic': l.topic,
            'start_time': dt_display.strftime('%H:%M'),
            'start_total': dt_display.hour * 60 + dt_display.minute,
            'duration_minutes': int(l.duration or 60),
            'profile_url': url_for('students.student_profile', student_id=st.student_id),
            'lesson_url': url_for('lessons.lesson_view', lesson_id=l.lesson_id),
            'is_conflict': False,
        })

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

    try:
        for lesson, st in created_pairs:
            if lesson.status == 'planned':
                date_str = lesson.lesson_date.strftime('%d.%m.%Y %H:%M') if lesson.lesson_date else ''
                notify_student_and_parents(
                    st,
                    kind='lesson_scheduled',
                    title='Новый урок запланирован',
                    body=(lesson.topic or '').strip() or None,
                    link_url=url_for('lessons.lesson_view', lesson_id=lesson.lesson_id),
                    meta={'lesson_id': lesson.lesson_id, 'date': date_str, 'topic': lesson.topic or ''},
                )
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Could not commit lesson_scheduled notifications (recurring slots): {e}")
    except Exception as e:
        logger.warning(f"Failed to notify about lesson_scheduled (recurring slots): {e}")

    return jsonify({'success': True, 'created_lessons': created_payload}), 200
