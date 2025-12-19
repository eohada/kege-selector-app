"""
Вспомогательные функции для работы с уроками
"""
import ast
import re
from decimal import Decimal, InvalidOperation
from flask import request, flash
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
    return sorted(assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else 999, ht.lesson_task_id))

def normalize_answer_value(value):
    """Нормализует значение ответа для сравнения"""
    if value is None:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    text_single_space = re.sub(r'\s+', ' ', text)
    if text_single_space.startswith('$') and text_single_space.endswith('$'):
        return text_single_space
    numeric_candidate = text_single_space.replace(',', '.')
    try:
        decimal_value = Decimal(numeric_candidate)
        normalized = format(decimal_value.normalize())
        return normalized
    except InvalidOperation:
        pass
    return text_single_space.lower()

def perform_auto_check(lesson, assignment_type):
    """Универсальная функция автопроверки для homework, classwork и exam"""
    tasks = get_sorted_assignments(lesson, assignment_type)
    
    if not tasks:
        type_name = {'homework': 'ДЗ', 'classwork': 'классной работы', 'exam': 'проверочной'}.get(assignment_type, 'заданий')
        error_msg = f'У этого урока нет заданий {type_name} для проверки.'
        # Для AJAX возвращаем ошибку в специальном формате
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'warning'}, None
        flash(error_msg, 'warning')
        return None, None
    
    answers_raw = request.form.get('auto_answers', '').strip()
    if not answers_raw:
        error_msg = 'Вставь массив ответов в формате [1, -1, "Москва"].'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'warning'}, None
        flash(error_msg, 'warning')
        return None, None
    
    try:
        parsed_answers = ast.literal_eval(answers_raw)
        if not isinstance(parsed_answers, (list, tuple)):
            raise ValueError
        answers_list = list(parsed_answers)
    except Exception:
        error_msg = 'Не удалось разобрать ответы. Используй формат [1, -1, "Москва"].'
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return {'error': error_msg, 'category': 'danger'}, None
        flash(error_msg, 'danger')
        return None, None
    
    total_tasks = len(tasks)
    correct_count = 0
    incorrect_count = 0
    
    # Для exam вес ×2
    weight = 2 if assignment_type == 'exam' else 1
    
    if len(answers_list) != total_tasks:
        warning_msg = f'Количество ответов ({len(answers_list)}) не совпадает с числом заданий ({total_tasks}). Отсутствующие ответы будут считаться неверными.'
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash(warning_msg, 'warning')
    
    def answer_at(index):
        if index < len(answers_list):
            return answers_list[index]
        return None
    
    for idx, task in enumerate(tasks):
        student_value = answer_at(idx)
        student_text = '' if student_value is None else str(student_value).strip()
        task.student_submission = student_text if student_text else None
        
        is_skip = student_text == '' or student_text == '-1' or student_text.lower() == 'null'
        # Используем student_answer, если он был введен вручную, иначе ответ из базы данных (task.answer)
        expected_text = (task.student_answer if task.student_answer else (task.task.answer if task.task and task.task.answer else '')) or ''
        
        if not expected_text:
            task.submission_correct = False
            incorrect_count += weight
            continue
        
        if is_skip:
            task.submission_correct = False
            incorrect_count += weight
            continue
        
        normalized_student = normalize_answer_value(student_text)
        normalized_expected = normalize_answer_value(expected_text)
        
        is_correct = normalized_student == normalized_expected and normalized_expected != ''
        task.submission_correct = is_correct
        
        if is_correct:
            correct_count += weight
        else:
            incorrect_count += weight
    
    # Для расчета процента учитываем вес
    total_weighted = correct_count + incorrect_count
    percent = round((correct_count / total_weighted) * 100, 2) if total_weighted > 0 else 0
    
    return correct_count, incorrect_count, percent, total_tasks

