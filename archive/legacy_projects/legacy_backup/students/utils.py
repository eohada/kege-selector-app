"""
Вспомогательные функции для работы со студентами
"""
from app.models import Lesson, LessonTask

def get_sorted_assignments(lesson, assignment_type):
    """Получает отсортированные задания по типу"""
    if assignment_type == 'homework':
        assignments = lesson.homework_assignments
    elif assignment_type == 'classwork':
        assignments = lesson.classwork_assignments
    elif assignment_type == 'exam':
        assignments = lesson.exam_assignments
    else:
        assignments = lesson.homework_assignments
    return sorted(assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))

