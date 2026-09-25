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
        title = str(raw_t.get('title') or raw_t.get('name') or raw_t.get('header') or '').strip()
        prompt = str(
            raw_t.get('prompt')
            or raw_t.get('condition')
            or raw_t.get('content')
            or raw_t.get('question')
            or raw_t.get('text')
            or raw_t.get('description')
            or ''
        ).strip()
        raw_type = str(raw_t.get('type') or raw_t.get('task_type') or 'short_answer').strip().lower()

        content_html = _build_task_content_html(title, prompt)

        answer: Optional[str] = None
        starter_code: Optional[str] = None
        answer_spec: Optional[dict[str, Any]] = None
        requires_manual_grading = False
        solution_text = str(raw_t.get('explanation') or raw_t.get('reference_solution') or raw_t.get('solution') or '').strip()
        hint_text = str(raw_t.get('teacher_hint') or raw_t.get('hint') or '').strip()

        # Тип: single_choice
        if raw_type in ('choice', 'single_choice', 'select'):
            raw_opts = raw_t.get('options') or raw_t.get('choices') or raw_t.get('items') or []
            options_list = []
            correct_val = str(raw_t.get('correct_option_id') or raw_t.get('correct_answer') or raw_t.get('answer') or '').strip()

            for opt_idx, opt in enumerate(raw_opts, start=1):
                if isinstance(opt, dict):
                    opt_val = str(opt.get('id') or opt.get('value') or opt_idx).strip()
                    opt_lbl = str(opt.get('text') or opt.get('label') or opt.get('title') or opt_val).strip()
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

        # Тип: multiple_choice
        elif raw_type in ('multiple_choice', 'multi_select', 'multiple'):
            raw_opts = raw_t.get('options') or raw_t.get('choices') or raw_t.get('items') or []
            options_list = []
            raw_correct = raw_t.get('correct_option_ids') or raw_t.get('correct_answers') or raw_t.get('correct_answer') or raw_t.get('answer') or []
            if isinstance(raw_correct, (list, tuple)):
                correct_vals = [str(x).strip() for x in raw_correct if str(x).strip()]
            elif isinstance(raw_correct, str) and raw_correct.strip():
                try:
                    c_loaded = json.loads(raw_correct)
                    correct_vals = [str(x).strip() for x in c_loaded if str(x).strip()] if isinstance(c_loaded, list) else [raw_correct.strip()]
                except Exception:
                    correct_vals = [s.strip() for s in raw_correct.split(',') if s.strip()]
            else:
                correct_vals = []

            for opt_idx, opt in enumerate(raw_opts, start=1):
                if isinstance(opt, dict):
                    opt_val = str(opt.get('id') or opt.get('value') or opt_idx).strip()
                    opt_lbl = str(opt.get('text') or opt.get('label') or opt.get('title') or opt_val).strip()
                else:
                    opt_val = str(opt_idx)
                    opt_lbl = str(opt).strip()
                options_list.append({'value': opt_val, 'label': opt_lbl})

            answer = json.dumps(sorted(correct_vals), ensure_ascii=False) if correct_vals else None
            answer_spec = {
                'type': 'multiple_choice',
                'options': options_list,
                'correct_values': sorted(correct_vals),
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

        # Тип: matching (сопоставление)
        elif raw_type in ('matching', 'match', 'pairs', 'sootvetstvie', 'сопоставление'):
            raw_left = (
                raw_t.get('left_items')
                or raw_t.get('pairs')
                or raw_t.get('left')
                or raw_t.get('items')
                or raw_t.get('premises')
                or []
            )
            pairs = []
            for p_idx, item in enumerate(raw_left, start=1):
                if isinstance(item, dict):
                    k = str(item.get('id') or item.get('key') or chr(64 + p_idx)).strip()
                    l_text = str(item.get('text') or item.get('left') or item.get('label') or k).strip()
                else:
                    k = str(chr(64 + p_idx) if p_idx <= 26 else p_idx)
                    l_text = str(item).strip()
                if k and l_text:
                    pairs.append({'key': k, 'left': l_text})

            raw_right = (
                raw_t.get('right_items')
                or raw_t.get('options')
                or raw_t.get('right')
                or raw_t.get('choices')
                or raw_t.get('targets')
                or []
            )
            options = []
            for opt_idx, item in enumerate(raw_right, start=1):
                if isinstance(item, dict):
                    v = str(item.get('id') or item.get('value') or item.get('key') or opt_idx).strip()
                    lbl = str(item.get('text') or item.get('label') or item.get('right') or v).strip()
                else:
                    v = str(opt_idx)
                    lbl = str(item).strip()
                if v and lbl:
                    options.append({'value': v, 'label': lbl})

            raw_matches = (
                raw_t.get('correct_matches')
                or raw_t.get('matches')
                or raw_t.get('correct_pairs')
                or raw_t.get('pairs_mapping')
                or raw_t.get('mapping')
                or raw_t.get('answer')
                or raw_t.get('correct_answer')
            )
            match_dict: dict[str, str] = {}
            if isinstance(raw_matches, dict):
                match_dict = {str(k).strip(): str(v).strip() for k, v in raw_matches.items()}
            elif isinstance(raw_matches, list):
                for m in raw_matches:
                    if isinstance(m, dict):
                        k = m.get('left_id') or m.get('left') or m.get('left_key') or m.get('key')
                        v = m.get('right_id') or m.get('right') or m.get('right_value') or m.get('value')
                        if k is not None and v is not None:
                            match_dict[str(k).strip()] = str(v).strip()
                    elif isinstance(m, (list, tuple)) and len(m) >= 2:
                        match_dict[str(m[0]).strip()] = str(m[1]).strip()
            elif isinstance(raw_matches, str) and raw_matches.strip():
                try:
                    loaded = json.loads(raw_matches)
                    if isinstance(loaded, dict):
                        match_dict = {str(k).strip(): str(v).strip() for k, v in loaded.items()}
                    elif isinstance(loaded, list):
                        for m in loaded:
                            if isinstance(m, dict):
                                k = m.get('left_id') or m.get('left') or m.get('left_key') or m.get('key')
                                v = m.get('right_id') or m.get('right') or m.get('right_value') or m.get('value')
                                if k is not None and v is not None:
                                    match_dict[str(k).strip()] = str(v).strip()
                except Exception:
                    for part in raw_matches.split(','):
                        if ':' in part:
                            k_p, v_p = part.split(':', 1)
                            match_dict[k_p.strip()] = v_p.strip()
                        elif '-' in part:
                            k_p, v_p = part.split('-', 1)
                            match_dict[k_p.strip()] = v_p.strip()

            answer = json.dumps(match_dict, ensure_ascii=False) if match_dict else None
            answer_spec = {
                'type': 'matching',
                'pairs': pairs,
                'options': options,
                'correct_matches': match_dict,
                'correct_answer': match_dict,
            }
            requires_manual_grading = False

        else:
            # Fallback к short_answer
            answer = str(raw_t.get('correct_answer') or raw_t.get('answer') or '').strip()
            answer_spec = {'type': 'short_answer'}

        raw_pts = raw_t.get('points') or raw_t.get('max_score') or raw_t.get('score')
        try:
            points = int(raw_pts) if raw_pts is not None else 1
        except (ValueError, TypeError):
            points = 1
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
