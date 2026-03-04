"""
Вспомогательные функции для работы с CourseTaskTemplate.
Используются вместо захардкоженных range(1, 28) и range(1, 24).
"""
from app.models import Course, CourseTaskTemplate


def _get_default_course_id():
    """Возвращает ID первого активного курса или None."""
    course = Course.query.filter_by(is_active=True).order_by(Course.id).first()
    return course.id if course else None


def get_task_numbers(course_id=None):
    """
    Возвращает список номеров заданий для курса.
    course_id: опционально; если не указан — берётся первый активный Course.
    Fallback: range(1, 28) при отсутствии CourseTaskTemplate.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        return list(range(1, 28))
    templates = CourseTaskTemplate.query.filter_by(course_id=cid).order_by(
        CourseTaskTemplate.task_number
    ).all()
    if not templates:
        return list(range(1, 28))
    return [t.task_number for t in templates]


def get_short_answer_task_numbers(course_id=None):
    """
    Возвращает номера заданий с коротким ответом (1–23).
    Задания 24–27 требуют ручной проверки (requires_manual_review=True).
    course_id: опционально; если не указан — берётся первый активный Course.
    Fallback: range(1, 24) при отсутствии CourseTaskTemplate.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        return list(range(1, 24))
    templates = CourseTaskTemplate.query.filter_by(course_id=cid).order_by(
        CourseTaskTemplate.task_number
    ).all()
    if not templates:
        return list(range(1, 24))
    return [t.task_number for t in templates if not t.requires_manual_review]


def get_max_score_for_task(course_id, task_number):
    """
    Возвращает max_primary_score для задания по CourseTaskTemplate.
    course_id: ID курса (если None — берётся первый активный).
    task_number: номер задания.
    Fallback: 2 если task_number >= 19, иначе 1.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        return 2 if task_number >= 19 else 1
    tpl = CourseTaskTemplate.query.filter_by(
        course_id=cid, task_number=task_number
    ).first()
    if tpl:
        return tpl.max_primary_score or 1
    return 2 if task_number >= 19 else 1
