"""
Вспомогательные функции для работы с CourseTaskTemplate.

Все функции возвращают данные из CourseTaskTemplate.
Если шаблоны не найдены — возвращается пустой список (нет hardcoded fallback).
"""
import logging
from app.models import Course, CourseTaskTemplate

log = logging.getLogger(__name__)


def _get_default_course_id():
    """Возвращает ID первого активного курса или None."""
    course = Course.query.filter_by(is_active=True).order_by(Course.id).first()
    return course.id if course else None


def get_task_numbers(course_id=None):
    """
    Возвращает список номеров заданий для курса.
    course_id: опционально; если не указан — берётся первый активный Course.
    Возвращает пустой список, если курс или шаблоны не найдены.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        log.warning('get_task_numbers: no active course found')
        return []
    templates = CourseTaskTemplate.query.filter_by(course_id=cid).order_by(
        CourseTaskTemplate.task_number
    ).all()
    if not templates:
        log.warning('get_task_numbers: no CourseTaskTemplate for course_id=%s', cid)
        return []
    return [t.task_number for t in templates]


def get_short_answer_task_numbers(course_id=None):
    """
    Возвращает номера заданий с коротким ответом (requires_manual_review=False).
    course_id: опционально; если не указан — берётся первый активный Course.
    Возвращает пустой список, если курс или шаблоны не найдены.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        log.warning('get_short_answer_task_numbers: no active course found')
        return []
    templates = CourseTaskTemplate.query.filter_by(course_id=cid).order_by(
        CourseTaskTemplate.task_number
    ).all()
    if not templates:
        log.warning('get_short_answer_task_numbers: no CourseTaskTemplate for course_id=%s', cid)
        return []
    return [t.task_number for t in templates if not t.requires_manual_review]


def get_max_score_for_task(course_id, task_number):
    """
    Возвращает max_primary_score для задания по CourseTaskTemplate.
    course_id: ID курса (если None — берётся первый активный).
    task_number: номер задания.
    Возвращает 1, если шаблон не найден.
    """
    cid = course_id or _get_default_course_id()
    if not cid:
        log.warning('get_max_score_for_task: no active course found, returning 1')
        return 1
    tpl = CourseTaskTemplate.query.filter_by(
        course_id=cid, task_number=task_number
    ).first()
    if tpl:
        return tpl.max_primary_score or 1
    log.warning('get_max_score_for_task: no template for course_id=%s task=%s, returning 1', cid, task_number)
    return 1
