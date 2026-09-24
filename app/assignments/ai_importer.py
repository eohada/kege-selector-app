import json
import logging
import re
import uuid
from typing import Any, Optional

import markdown
from app import db
from core.db_models import Course, Tasks, TaskReview, TaskSolution
from app.utils.jinja_filters import prepare_task_content_html, normalize_task_plain_text_to_html
from flask import current_app
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _fix_tasks_pk_sequence():
    """Выравнивание sequence Tasks.task_id в PostgreSQL после ручных вставок."""
    try:
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
        is_pg = ('postgresql' in db_url) or ('postgres' in db_url)
        if is_pg:
            db.session.execute(text(
                'SELECT setval(pg_get_serial_sequence(\'"Tasks"\', \'task_id\'), '
                'COALESCE((SELECT MAX("task_id") FROM "Tasks"), 0), true)'
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()


def _extract_task_number(raw_task: dict[str, Any], default_num: int) -> int:
    """Извлечь или определить номер задания (из task_number, id или порядкового индекса)."""
    if raw_task.get('task_number'):
        try:
            return max(1, int(raw_task['task_number']))
        except (ValueError, TypeError):
            pass

    task_id_str = str(raw_task.get('id') or '')
    if task_id_str:
        digits = re.findall(r'\d+', task_id_str)
        if digits:
            try:
                return max(1, int(digits[-1]))
            except (ValueError, TypeError):
                pass

    return default_num


def _build_task_content_html(title: str, prompt: str) -> str:
    """Собрать Markdown и скомпилировать в чистый валидный HTML."""
    prompt_clean = (prompt or '').strip()
    title_clean = (title or '').strip()

    if title_clean and not prompt_clean.lower().startswith(title_clean.lower()):
        md_text = f"### {title_clean}\n\n{prompt_clean}"
    else:
        md_text = prompt_clean

    if not md_text:
        return '<div class="task-text"></div>'

    try:
        html = markdown.markdown(md_text, extensions=['fenced_code', 'tables'])
        return html
    except Exception:
        return normalize_task_plain_text_to_html(md_text)


def parse_and_convert_ai_homework(
    raw_input: Any,
    user_id: int,
    course_id: Optional[int] = None,
    task_payload_serializer: Optional[Any] = None
) -> dict[str, Any]:
    """
    Преобразует JSON домашней работы / набора заданий от ИИ-агента в каноничные сущности платформы Tasks.
    Поддерживает:
      - Полный объект ДЗ ({ title, subtitle, instructions, tasks: [...] })
      - Список заданий ([ { type, prompt, ... }, ... ])
      - Одиночное задание ({ type, prompt, ... })
    """
    if isinstance(raw_input, str):
        raw_text = raw_input.strip()
        if not raw_text:
            raise ValueError('Передан пустой текст JSON')
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'Некорректный синтаксис JSON: {exc}')
    elif isinstance(raw_input, (dict, list)):
        data = raw_input
    else:
        raise ValueError('Ожидается JSON строка, объект или массив')

    # 1. Извлечение метаданных работы
    assignment_meta: dict[str, Any] = {
        'title': '',
        'time_limit': None,
        'description': '',
        'subtitle': '',
        'instructions': '',
        'skills_checked': [],
        'teacher_note': '',
    }
    raw_tasks_list: list[dict[str, Any]] = []

    if isinstance(data, dict):
        if 'tasks' in data and isinstance(data['tasks'], list):
            raw_tasks_list = [t for t in data['tasks'] if isinstance(t, dict)]
            title = str(data.get('title') or '').strip()
            subtitle = str(data.get('subtitle') or '').strip()
            instructions = str(data.get('instructions') or '').strip()
            estimated_minutes = data.get('estimated_minutes')
            skills_checked = data.get('skills_checked') or []
            teacher_note = str(data.get('teacher_note') or '').strip()

            desc_parts = []
            if subtitle:
                desc_parts.append(subtitle)
            if instructions:
                desc_parts.append(instructions)
            if skills_checked and isinstance(skills_checked, list):
                skills_str = "Проверяемые навыки:\n" + "\n".join(f"• {s}" for s in skills_checked)
                desc_parts.append(skills_str)
            if teacher_note:
                desc_parts.append(f"Примечание преподавателю: {teacher_note}")

            assignment_meta = {
                'title': title,
                'subtitle': subtitle,
                'instructions': instructions,
                'time_limit': int(estimated_minutes) if estimated_minutes else None,
                'description': "\n\n".join(desc_parts).strip(),
                'skills_checked': skills_checked,
                'teacher_note': teacher_note,
            }
        else:
            # Одиночное задание
            raw_tasks_list = [data]
    elif isinstance(data, list):
        raw_tasks_list = [t for t in data if isinstance(t, dict)]

    if not raw_tasks_list:
        raise ValueError('В переданном JSON не найдено ни одного задания в ключе "tasks" или в корневом массиве')

    # 2. Определение курса
    resolved_course_id = None
    if course_id:
        c = Course.query.filter_by(id=course_id, is_active=True).first()
        if c:
            resolved_course_id = c.id
    if resolved_course_id is None:
        dc = Course.query.filter_by(is_active=True).order_by(Course.id.asc()).first()
        if dc:
            resolved_course_id = dc.id

    # 3. Конвертация каждого задания
    _fix_tasks_pk_sequence()
    created_tasks: list[Tasks] = []
    task_manual_flags: list[bool] = []
    task_scores: list[int] = []

    for idx, raw_t in enumerate(raw_tasks_list, start=1):
        task_num = _extract_task_number(raw_t, idx)
        title = str(raw_t.get('title') or '').strip()
        prompt = str(raw_t.get('prompt') or raw_t.get('condition') or raw_t.get('content') or raw_t.get('text') or '').strip()
        raw_type = str(raw_t.get('type') or raw_t.get('task_type') or 'short_answer').strip().lower()

        content_html = _build_task_content_html(title, prompt)

        answer: Optional[str] = None
        starter_code: Optional[str] = None
        answer_spec: Optional[dict[str, Any]] = None
        requires_manual_grading = False
        solution_text = str(raw_t.get('explanation') or raw_t.get('reference_solution') or raw_t.get('solution') or '').strip()
        hint_text = str(raw_t.get('teacher_hint') or raw_t.get('hint') or '').strip()

        # Тип: single_choice
        if raw_type in ('choice', 'single_choice', 'multiple_choice', 'select'):
            raw_opts = raw_t.get('options') or []
            options_list = []
            correct_val = str(raw_t.get('correct_option_id') or raw_t.get('correct_answer') or raw_t.get('answer') or '').strip()

            for opt_idx, opt in enumerate(raw_opts, start=1):
                if isinstance(opt, dict):
                    opt_val = str(opt.get('id') or opt.get('value') or opt_idx).strip()
                    opt_lbl = str(opt.get('text') or opt.get('label') or opt_val).strip()
                else:
                    opt_val = str(opt_idx)
                    opt_lbl = str(opt).strip()
                options_list.append({'value': opt_val, 'label': opt_lbl})

            if not correct_val and options_list:
                correct_val = options_list[0]['value']

            answer = correct_val
            answer_spec = {
                'type': 'single_choice',
                'options': options_list,
                'correct_value': correct_val,
            }

        # Тип: short_answer
        elif raw_type in ('short_answer', 'text', 'number'):
            answer = str(raw_t.get('correct_answer') or raw_t.get('answer') or '').strip()
            answer_spec = {'type': 'short_answer'}

        # Тип: extended_answer / long_answer
        elif raw_type in ('extended_answer', 'long_answer', 'open', 'free'):
            requires_manual_grading = True
            answer = None
            answer_spec = {'type': 'long_answer'}

            sample_ans = str(raw_t.get('sample_answer') or '').strip()
            rubric = raw_t.get('rubric') or []
            sol_blocks = []
            if sample_ans:
                sol_blocks.append(f"**Эталонный ответ:**\n{sample_ans}")
            if rubric:
                if isinstance(rubric, list):
                    rubric_text = "**Критерии проверки (рубрика):**\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(rubric, start=1))
                else:
                    rubric_text = f"**Критерии проверки:**\n{rubric}"
                sol_blocks.append(rubric_text)
            if solution_text:
                sol_blocks.append(solution_text)
            solution_text = "\n\n".join(sol_blocks).strip()

        # Тип: code
        elif raw_type in ('code', 'python', 'programming'):
            starter_code = str(raw_t.get('starter_code') or '').strip() or None
            tests = raw_t.get('tests') or raw_t.get('test_cases') or []
            ref_sol = str(raw_t.get('reference_solution') or raw_t.get('solution') or '').strip()
            answer = 'code'
            answer_spec = {
                'type': 'code',
                'starter_code': starter_code,
                'tests': tests,
                'reference_solution': ref_sol,
                'default_workspace_mode': 'code',
            }
            if ref_sol and not solution_text:
                solution_text = ref_sol

        # Тип: matching
        elif raw_type == 'matching':
            answer_spec = {
                'type': 'matching',
                'pairs': raw_t.get('pairs') or [],
                'options': raw_t.get('options') or [],
            }
            answer = str(raw_t.get('answer') or '') or None

        else:
            # Fallback к short_answer
            answer = str(raw_t.get('correct_answer') or raw_t.get('answer') or '').strip()
            answer_spec = {'type': 'short_answer'}

        points = int(raw_t.get('points') or raw_t.get('max_score') or raw_t.get('score') or 1)
        points = max(1, min(100, points))

        hints = [{'text': hint_text}] if hint_text else None

        # Создание записи в БД
        task = Tasks(
            course_id=resolved_course_id,
            task_number=task_num,
            site_task_id=f"manual:{uuid.uuid4()}",
            source_url=None,
            content_html=content_html,
            answer=answer,
            answer_spec=answer_spec,
            attached_files=None,
            created_by_id=user_id,
            bank_origin='manual',
            starter_code=starter_code,
            difficulty_level=1,
            max_score=points,
            hints=hints,
        )
        db.session.add(task)
        db.session.flush()

        if solution_text:
            sol = TaskSolution(
                task_id=task.task_id,
                solution_text=solution_text,
                source='manual',
                needs_manual_review=False,
            )
            db.session.add(sol)

        review = TaskReview(
            task_id=task.task_id,
            status='approved',
        )
        review.requires_manual_grading = requires_manual_grading
        db.session.add(review)

        created_tasks.append(task)
        task_manual_flags.append(requires_manual_grading)
        task_scores.append(points)

    db.session.commit()

    # 4. Формирование результирующего списка для конструктора
    serialized_tasks = []
    for task, is_manual, score in zip(created_tasks, task_manual_flags, task_scores):
        if task_payload_serializer:
            payload = task_payload_serializer(task, max_score=score, requires_manual_grading=is_manual)
        else:
            payload = {
                'task_id': task.task_id,
                'task_number': task.task_number,
                'max_score': score,
                'answer': task.answer or '',
                'content_html': task.content_html,
                'requires_manual_grading': is_manual,
                'course_id': task.course_id,
                'difficulty_level': task.difficulty_level,
                'starter_code': task.starter_code or '',
                'solution': solution_text or '',
                'hints': task.hints or [],
                'answer_spec': task.answer_spec,
                'attached_files': [],
                'can_edit': True,
            }
        serialized_tasks.append(payload)

    return {
        'success': True,
        'message': f'Успешно импортировано {len(serialized_tasks)} заданий',
        'count': len(serialized_tasks),
        'assignment_meta': assignment_meta,
        'tasks': serialized_tasks,
    }
