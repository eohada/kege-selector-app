"""
BooStudy — Сервис ежедневных серий активности (Стрики / Streaks).

Отвечает за:
- Инкремент стрика при ежедневных образовательных действиях (ДЗ, уроки, теория, задачи)
- Сброс стрика при пропуске дней
- Механику заморозки стрика (Streak Freeze), спасающую серию при пропуске
- Корректное склонение числительных ("1 день", "2 дня", "5 дней", "21 день")
- Отображение актуального статуса серии (активен сегодня, под угрозой, заморожен, сгорел)
"""
from datetime import timedelta, date, datetime
import logging
from app.models import db, Student, moscow_now

logger = logging.getLogger(__name__)


def pluralize_days(n) -> str:
    """
    Склонение фразы 'N дней' в зависимости от числа n.
    Примеры:
      1 день, 2 дня, 5 дней, 11 дней, 21 день, 22 дня.
    """
    n = abs(int(n or 0))
    if n % 100 in (11, 12, 13, 14):
        return f"{n} дней"
    if n % 10 == 1:
        return f"{n} день"
    if n % 10 in (2, 3, 4):
        return f"{n} дня"
    return f"{n} дней"


def pluralize_days_word(n) -> str:
    """Возвращает только слово ('день', 'дня', 'дней') без цифры."""
    return pluralize_days(n).split()[-1]


def _normalize_date(d) -> date | None:
    """Приводит дату любого формата (date, datetime, str) к datetime.date."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d.strip()[:10]).date()
        except Exception:
            return None
    return None


def get_effective_streak(student, *, today_date: date | None = None) -> int:
    """
    Возвращает фактический активный стрик ученика на текущий момент.
    Если ученик не занимался 2+ дня и стрик не заморожен, возвращает 0.
    """
    if not student:
        return 0
    today = today_date or moscow_now().date()
    last_date = _normalize_date(student.last_activity_date)
    raw_streak = int(student.streak_days or 0)
    
    if raw_streak <= 0:
        return 0

    if not last_date:
        # Для обратной совместимости с legacy-профилями или новыми записями
        return raw_streak

    # Занимался сегодня или вчера — серия жива
    if last_date >= today - timedelta(days=1):
        return raw_streak

    # Пропустил дни, но серия защищена заморозкой
    if getattr(student, 'streak_frozen', False):
        return raw_streak

    # Пропустил дни без заморозки — серия сгорела
    return 0


def get_student_streak_info(student, *, today_date: date | None = None) -> dict:
    """
    Полная информация о состоянии серии ученика для UI.
    """
    empty = {
        'streak_days': 0,
        'raw_streak_days': 0,
        'is_active_today': False,
        'needs_activity_today': False,
        'is_frozen': False,
        'is_broken': False,
        'days_label': '0 дней',
        'days_word': 'дней',
    }
    if not student:
        return empty

    today = today_date or moscow_now().date()
    last_date = _normalize_date(student.last_activity_date)
    raw_streak = int(student.streak_days or 0)
    is_frozen = bool(getattr(student, 'streak_frozen', False))

    if raw_streak <= 0:
        return {**empty, 'is_frozen': is_frozen}

    if not last_date:
        return {
            'streak_days': raw_streak,
            'raw_streak_days': raw_streak,
            'is_active_today': False,
            'needs_activity_today': True,
            'is_frozen': is_frozen,
            'is_broken': False,
            'days_label': pluralize_days(raw_streak),
            'days_word': pluralize_days_word(raw_streak),
        }

    if last_date == today:
        return {
            'streak_days': raw_streak,
            'raw_streak_days': raw_streak,
            'is_active_today': True,
            'needs_activity_today': False,
            'is_frozen': is_frozen,
            'is_broken': False,
            'days_label': pluralize_days(raw_streak),
            'days_word': pluralize_days_word(raw_streak),
        }
    elif last_date == today - timedelta(days=1):
        return {
            'streak_days': raw_streak,
            'raw_streak_days': raw_streak,
            'is_active_today': False,
            'needs_activity_today': True,
            'is_frozen': is_frozen,
            'is_broken': False,
            'days_label': pluralize_days(raw_streak),
            'days_word': pluralize_days_word(raw_streak),
        }
    else:
        # Пропущен 1 или более дней
        if is_frozen:
            return {
                'streak_days': raw_streak,
                'raw_streak_days': raw_streak,
                'is_active_today': False,
                'needs_activity_today': False,
                'is_frozen': True,
                'is_broken': False,
                'days_label': pluralize_days(raw_streak),
                'days_word': pluralize_days_word(raw_streak),
            }
        else:
            return {
                'streak_days': 0,
                'raw_streak_days': raw_streak,
                'is_active_today': False,
                'needs_activity_today': False,
                'is_frozen': False,
                'is_broken': True,
                'days_label': '0 дней',
                'days_word': 'дней',
            }


def update_student_streak(student, *, today_date: date | None = None, commit=True) -> bool:
    """
    Обновляет стрик ежедневной активности ученика при совершении полезного действия.

    Логика:
    1. Если сегодня уже была активность: стрик не меняется.
    2. Если активность была вчера: стрик инкрементируется (+1). Заморозка (если была) сохраняется.
    3. Если был пропуск (2+ дней назад):
       - Если стрик заморожен: заморозка спасает серию!
         Заморозка расходуется (streak_frozen = False), серия продолжается (+1).
       - Если стрик не заморожен: серия сбрасывается в 1 день.
    4. Если первая активность (last_activity_date is None): стрик = 1.
    
    Возвращает True, если стрик увеличился, иначе False.
    """
    if not student:
        return False

    try:
        today = today_date or moscow_now().date()
        last_date = _normalize_date(student.last_activity_date)
        is_frozen = bool(getattr(student, 'streak_frozen', False))
        incremented = False

        if last_date is None:
            # Первая активность в истории ученика
            student.streak_days = 1
            student.last_activity_date = today
            incremented = True
        elif last_date == today:
            # Уже занимался сегодня — стрик зафиксирован
            pass
        elif last_date == today - timedelta(days=1):
            # Активность вчера — непрерывная серия продолжается
            student.streak_days = max(0, int(student.streak_days or 0)) + 1
            student.last_activity_date = today
            incremented = True
        else:
            # Пропуск дней
            if is_frozen:
                # Заморозка спасает стрик! Расходуем заморозку и продолжаем серию
                student.streak_frozen = False
                student.streak_days = max(0, int(student.streak_days or 0)) + 1
                student.last_activity_date = today
                incremented = True
                logger.info("Streak freeze saved student %s streak! Current: %s days", student.student_id, student.streak_days)
            else:
                # Сброс в 1 день
                student.streak_days = 1
                student.last_activity_date = today
                incremented = True

        if commit:
            db.session.commit()
        return incremented
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error updating student daily streak: %s", e, exc_info=True)
        return False


def freeze_student_streak(student, *, commit=True) -> bool:
    """Активирует заморозку стрика для ученика."""
    if not student:
        return False
    try:
        student.streak_frozen = True
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error freezing student streak: %s", e, exc_info=True)
        return False


def unfreeze_student_streak(student, *, commit=True) -> bool:
    """Снимает заморозку стрика у ученика."""
    if not student:
        return False
    try:
        student.streak_frozen = False
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error unfreezing student streak: %s", e, exc_info=True)
        return False


def set_student_streak(student, days: int, *, frozen: bool | None = None, commit=True) -> bool:
    """Устанавливает конкретное число дней стрика (для админа/создателя)."""
    if not student:
        return False
    try:
        today = moscow_now().date()
        student.streak_days = max(0, int(days or 0))
        student.last_activity_date = today if student.streak_days > 0 else None
        if frozen is not None:
            student.streak_frozen = bool(frozen)
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error setting student streak: %s", e, exc_info=True)
        return False


def update_student_streak_by_user_id(user_id):
    """Ищет Student по user_id и обновляет стрик."""
    if not user_id:
        return False
    student = Student.query.filter_by(user_id=user_id).first()
    if student:
        return update_student_streak(student)
    return False


# ---------------------------------------------------------------------------
# НЕДЕЛЬНЫЙ РИТМ (Weekly Streak)
# ---------------------------------------------------------------------------

def pluralize_weeks(n) -> str:
    """
    Склонение фразы 'N недель' в зависимости от числа n.
    Примеры:
      1 неделя, 2 недели, 4 недели, 5 недель, 11 недель, 21 неделя, 22 недели.
    """
    n = abs(int(n or 0))
    if n % 100 in (11, 12, 13, 14):
        return f"{n} недель"
    if n % 10 == 1:
        return f"{n} неделя"
    if n % 10 in (2, 3, 4):
        return f"{n} недели"
    return f"{n} недель"


def pluralize_weeks_word(n) -> str:
    """Возвращает только слово ('неделя', 'недели', 'недель') без цифры."""
    return pluralize_weeks(n).split()[-1]


def get_iso_week_key(d: date) -> str:
    """Возвращает ключ ISO-недели, например '2026-W15'."""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def get_week_date_range(d: date) -> tuple[date, date]:
    """Возвращает даты понедельника и воскресенья недели даты d."""
    start = d - timedelta(days=d.weekday())
    end = start + timedelta(days=6)
    return start, end


def evaluate_student_week_status(student, *, week_date: date | None = None) -> dict:
    """
    Оценивает успешность учебной недели для ученика:
    1. Все прошедшие уроки недели (кроме cancelled) должны быть завершены (status == 'completed').
    2. Нет просроченных незавершенных уроков.
    3. Присутствует образовательная активность за неделю (урок, сдача ДЗ, активность).
    """
    if not student:
        return {
            'is_successful': False,
            'is_on_track': False,
            'status_text': 'Нет профиля',
            'lessons_total': 0,
            'lessons_completed': 0,
            'lessons_missed': 0,
            'submissions_count': 0,
        }

    target_date = week_date or moscow_now().date()
    start_date, end_date = get_week_date_range(target_date)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    if week_date:
        now_dt = datetime.combine(week_date, datetime.min.time())
    else:
        now_dt = moscow_now()

    try:
        from core.db_models import Lesson, Submission

        # Уроки недели
        lessons = Lesson.query.filter(
            Lesson.student_id == student.student_id,
            Lesson.lesson_date >= start_dt,
            Lesson.lesson_date <= end_dt
        ).all()

        lessons_active = [l for l in lessons if (getattr(l, 'status', '') or '').lower() != 'cancelled']
        lessons_completed = [l for l in lessons_active if (getattr(l, 'status', '') or '').lower() == 'completed']
        
        # Пропущенные уроки: дата урока уже наступила, но статус не completed
        lessons_missed = []
        for l in lessons_active:
            st = (getattr(l, 'status', '') or '').lower()
            ldate = getattr(l, 'lesson_date', None)
            if st != 'completed':
                if ldate and (hasattr(ldate, 'date') and ldate.date() < target_date or ldate < now_dt):
                    lessons_missed.append(l)

        # Домашние задания: проверяем работы, дедлайн которых приходился на эту неделю
        from core.db_models import Assignment
        submissions = Submission.query.join(Assignment, Submission.assignment_id == Assignment.assignment_id).filter(
            Submission.student_id == student.student_id
        ).all()

        assignments_due_in_week = []
        assignments_overdue = []
        submissions_week = []

        for sub in submissions:
            asgn = sub.assignment
            if not asgn:
                continue
            dline = getattr(asgn, 'deadline', None)
            if dline:
                dline_naive = dline.replace(tzinfo=None) if hasattr(dline, 'tzinfo') and dline.tzinfo else dline
                # ДЗ оценивается на той неделе, где находится его дедлайн!
                if start_dt <= dline_naive <= end_dt:
                    assignments_due_in_week.append(sub)
                    st = (getattr(sub, 'status', '') or '').upper()
                    if st in ('ASSIGNED', 'IN_PROGRESS', 'DRAFT') and dline_naive < now_dt:
                        assignments_overdue.append(sub)

            sub_at = getattr(sub, 'submitted_at', None)
            if sub_at:
                sub_at_naive = sub_at.replace(tzinfo=None) if hasattr(sub_at, 'tzinfo') and sub_at.tzinfo else sub_at
                if start_dt <= sub_at_naive <= end_dt:
                    submissions_week.append(sub)

        # Активность: посещен хотя бы 1 урок, сдано ДЗ, или была активность в эту неделю
        last_date = _normalize_date(student.last_activity_date)
        activity_in_week = bool(last_date and start_date <= last_date <= end_date)
        has_activity = len(lessons_completed) > 0 or len(submissions_week) > 0 or activity_in_week

        is_on_track = len(lessons_missed) == 0 and len(assignments_overdue) == 0
        is_successful = is_on_track and has_activity

        status_text = "В графике"
        if len(lessons_missed) > 0:
            status_text = "Пропущен урок"
        elif len(assignments_overdue) > 0:
            status_text = "Просрочено ДЗ"
        elif is_successful:
            status_text = "План недели выполнен"
        elif not has_activity:
            status_text = "Ожидает активности"

        return {
            'start_date': start_date,
            'end_date': end_date,
            'week_key': get_iso_week_key(start_date),
            'lessons_total': len(lessons_active),
            'lessons_completed': len(lessons_completed),
            'lessons_missed': len(lessons_missed),
            'assignments_due': len(assignments_due_in_week),
            'assignments_overdue': len(assignments_overdue),
            'submissions_count': len(submissions_week),
            'has_activity': has_activity,
            'is_on_track': is_on_track,
            'is_successful': is_successful,
            'status_text': status_text
        }
    except Exception as e:
        logger.error("Error evaluating student week status: %s", e, exc_info=True)
        return {
            'start_date': start_date,
            'end_date': end_date,
            'week_key': get_iso_week_key(start_date),
            'lessons_total': 0,
            'lessons_completed': 0,
            'lessons_missed': 0,
            'submissions_count': 0,
            'has_activity': False,
            'is_on_track': False,
            'is_successful': False,
            'status_text': 'Ошибка расчёта'
        }


def update_student_weekly_streak(student, *, current_date: date | None = None, commit=True) -> dict:
    """
    Проверяет и обновляет недельный стрик (учебный ритм) ученика.
    Оценивает завершившуюся неделю и начисляет прогресс.
    """
    if not student:
        return {'updated': False, 'streak_weeks': 0}

    today = current_date or moscow_now().date()
    prev_week_date = today - timedelta(days=7)
    prev_week_key = get_iso_week_key(prev_week_date)

    updated = False
    old_weeks = int(student.streak_weeks or 0)
    old_frozen = bool(getattr(student, 'streak_weeks_frozen', False))

    try:
        # Если прошлая неделя ещё не была зафиксирована в last_completed_week
        if student.last_completed_week != prev_week_key:
            prev_status = evaluate_student_week_status(student, week_date=prev_week_date)
            
            if prev_status.get('is_successful'):
                # Прошлая неделя выполнена успешно!
                prev_prev_week_key = get_iso_week_key(prev_week_date - timedelta(days=7))
                
                if student.last_completed_week == prev_prev_week_key or not student.last_completed_week:
                    # Непрерывная недельная серия
                    student.streak_weeks = max(0, old_weeks) + 1
                else:
                    # Был пропуск одной или нескольких недель
                    if old_frozen:
                        # Заморозка спасает недельный ритм!
                        student.streak_weeks_frozen = False
                        student.streak_weeks = max(0, old_weeks) + 1
                        logger.info("Weekly streak freeze saved student %s streak! Now %s weeks", student.student_id, student.streak_weeks)
                    else:
                        # Сброс в 1 неделю
                        student.streak_weeks = 1
                
                student.last_completed_week = prev_week_key
                updated = True

                from app.utils.achievement_service import check_and_grant_dynamic_achievements
                check_and_grant_dynamic_achievements(student, commit=False)

        if updated and commit:
            db.session.commit()

        return {
            'updated': updated,
            'streak_weeks': int(student.streak_weeks or 0),
            'last_completed_week': student.last_completed_week,
            'is_frozen': bool(getattr(student, 'streak_weeks_frozen', False))
        }
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error updating student weekly streak: %s", e, exc_info=True)
        return {'updated': False, 'streak_weeks': old_weeks}


def get_student_weekly_streak_info(student, *, current_date: date | None = None) -> dict:
    """
    Возвращает полную сводку по недельному ритму ученика для UI дашборда и профиля.
    """
    empty = {
        'streak_weeks': 0,
        'weeks_label': '0 недель',
        'weeks_word': 'недель',
        'is_frozen': False,
        'is_on_track': False,
        'current_week': {},
        'status_text': 'Нет данных'
    }
    if not student:
        return empty

    today = current_date or moscow_now().date()
    raw_weeks = int(student.streak_weeks or 0)
    is_frozen = bool(getattr(student, 'streak_weeks_frozen', False))

    curr_eval = evaluate_student_week_status(student, week_date=today)

    return {
        'streak_weeks': raw_weeks,
        'weeks_label': pluralize_weeks(raw_weeks),
        'weeks_word': pluralize_weeks_word(raw_weeks),
        'is_frozen': is_frozen,
        'is_on_track': curr_eval.get('is_on_track', False),
        'current_week': curr_eval,
        'status_text': curr_eval.get('status_text', 'В графике')
    }


def freeze_student_weekly_streak(student, *, commit=True) -> bool:
    """Активирует заморозку недельного ритма."""
    if not student:
        return False
    try:
        student.streak_weeks_frozen = True
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error freezing weekly streak: %s", e, exc_info=True)
        return False


def unfreeze_student_weekly_streak(student, *, commit=True) -> bool:
    """Снимает заморозку недельного ритма."""
    if not student:
        return False
    try:
        student.streak_weeks_frozen = False
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error unfreezing weekly streak: %s", e, exc_info=True)
        return False


def set_student_weekly_streak(student, weeks: int, *, frozen: bool | None = None, commit=True) -> bool:
    """Устанавливает конкретное число недель в серии (для админа/создателя)."""
    if not student:
        return False
    try:
        student.streak_weeks = max(0, int(weeks or 0))
        if frozen is not None:
            student.streak_weeks_frozen = bool(frozen)
        if commit:
            db.session.commit()
        return True
    except Exception as e:
        if commit:
            db.session.rollback()
        logger.error("Error setting weekly streak: %s", e, exc_info=True)
        return False
