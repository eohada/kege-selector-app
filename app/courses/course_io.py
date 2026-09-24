from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import or_

from app import db
from core.db_models import (
    LearningTrajectory,
    TrajectoryModule,
    ExamSkill,
    Lesson,
    LearningItem,
    Course,
)


def _parse_target_score(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    nums = re.findall(r'\d+', str(raw))
    if not nums:
        return None
    val0 = int(nums[0])
    return val0 if val0 >= 40 else int(nums[-1])


def import_course_from_data(data: Dict[str, Any], user_id: Optional[int] = None) -> Tuple[LearningTrajectory, Dict[str, int]]:
    """
    Импортирует структуру курса (Мастер-курс / Базовую программу) из словаря/JSON.
    Создает или обновляет связанные ExamSkill, TrajectoryModule, Lesson и LearningItem.
    """
    if not isinstance(data, dict):
        raise ValueError("Некорректная структура данных: ожидается JSON-объект.")

    title = (data.get('title') or '').strip()
    if not title:
        raise ValueError("Отсутствует обязательное поле 'title' курса.")

    subject = (data.get('subject') or 'Информатика').strip()
    target_score = _parse_target_score(data.get('target_score'))
    goal = (data.get('goal') or data.get('learning_goal') or '').strip() or None
    result = (data.get('result') or data.get('expected_result') or '').strip() or None
    description = (data.get('description') or goal or '').strip() or None
    is_template = bool(data.get('is_template', True))
    default_duration = int(data.get('default_lesson_duration') or 60)

    # Определение ExamCourse (ЕГЭ Информатика и т.п.)
    exam_course_id = data.get('exam_course_id')
    if not exam_course_id:
        matched_course = Course.query.filter(
            or_(
                Course.slug == 'ege_informatics',
                Course.title.ilike(f'%{subject}%')
            )
        ).first()
        if matched_course:
            exam_course_id = matched_course.id

    # 1. Создание Мастер-курса
    trajectory = LearningTrajectory(
        is_template=is_template,
        student_id=None if is_template else data.get('student_id'),
        created_by_user_id=user_id,
        title=title,
        subject=subject,
        description=description,
        learning_goal=goal,
        expected_result=result,
        target_score=target_score,
        default_lesson_duration=default_duration,
        exam_course_id=exam_course_id,
        status='active',
    )
    db.session.add(trajectory)
    db.session.flush()

    # 2. Обработка навыков (Skills)
    skill_map: Dict[str, ExamSkill] = {}
    skills_data: List[Dict[str, Any]] = data.get('skills', []) or []
    skills_count = 0

    for s_info in skills_data:
        topic_code = str(s_info.get('topic_code') or '').strip().upper()
        if not topic_code:
            continue

        skill_title = str(s_info.get('name') or s_info.get('title') or topic_code).strip()
        section = str(s_info.get('section') or s_info.get('topic') or '').strip()
        task_num_raw = s_info.get('exam_task_number') or s_info.get('task_number')
        task_number = int(task_num_raw) if task_num_raw is not None and str(task_num_raw).isdigit() else None

        existing_skill = ExamSkill.query.filter_by(topic_code=topic_code).first()
        if existing_skill:
            existing_skill.title = skill_title
            if section:
                existing_skill.topic = section
            if task_number is not None:
                existing_skill.task_number = task_number
            if not existing_skill.exam_course_id and exam_course_id:
                existing_skill.exam_course_id = exam_course_id
            existing_skill.is_active = True
            skill_map[topic_code] = existing_skill
        else:
            new_skill = ExamSkill(
                topic_code=topic_code,
                title=skill_title,
                topic=section or subject,
                task_number=task_number,
                exam_course_id=exam_course_id,
                is_active=True,
            )
            db.session.add(new_skill)
            db.session.flush()
            skill_map[topic_code] = new_skill
        skills_count += 1

    # 3. Обработка модулей и уроков
    modules_data: List[Dict[str, Any]] = data.get('modules', []) or []
    modules_count = 0
    lessons_count = 0

    for m_idx, m_info in enumerate(modules_data, start=1):
        mod_title = str(m_info.get('name') or m_info.get('title') or f'Модуль {m_idx}').strip()
        mod_order = int(m_info.get('order') or m_info.get('order_index') or (m_idx * 10))
        mod_desc = (m_info.get('description') or '').strip() or None
        mod_res = (m_info.get('result') or m_info.get('learning_result') or '').strip() or None
        is_ctrl = bool(m_info.get('is_control_exam', False))

        module = TrajectoryModule(
            course_id=trajectory.course_id,
            title=mod_title,
            description=mod_desc,
            learning_result=mod_res,
            order_index=mod_order,
            is_control_exam=is_ctrl,
        )
        db.session.add(module)
        db.session.flush()
        modules_count += 1

        lessons_data: List[Dict[str, Any]] = m_info.get('lessons', []) or []
        for l_idx, l_info in enumerate(lessons_data, start=1):
            les_title = str(l_info.get('title') or l_info.get('topic') or f'Урок {l_idx}').strip()
            les_order = int(l_info.get('order') or l_info.get('course_order_index') or (mod_order + l_idx))
            les_format = str(l_info.get('lesson_format') or 'Теория + Практика').strip()
            duration = int(l_info.get('duration_minutes') or l_info.get('duration') or default_duration)
            scenario = (l_info.get('studio_scenario') or '').strip() or None
            content = (l_info.get('theory_content') or l_info.get('content') or '').strip() or None
            homework = (l_info.get('homework_content') or l_info.get('homework') or '').strip() or None

            lesson = Lesson(
                learning_trajectory_id=trajectory.course_id,
                course_module_id=module.module_id,
                student_id=trajectory.student_id,
                exam_course_id=trajectory.exam_course_id,
                topic=les_title,
                course_order_index=les_order,
                duration=duration,
                lesson_format=les_format,
                studio_scenario=scenario,
                content=content,
                homework=homework,
                status='planned',
            )
            db.session.add(lesson)
            db.session.flush()

            # Привязка навыков
            codes = l_info.get('topic_codes', []) or []
            matched_skills = []
            for code in codes:
                code_norm = str(code).strip().upper()
                if code_norm in skill_map:
                    matched_skills.append(skill_map[code_norm])
                else:
                    found_sk = ExamSkill.query.filter_by(topic_code=code_norm).first()
                    if found_sk:
                        skill_map[code_norm] = found_sk
                        matched_skills.append(found_sk)
            lesson.skills = matched_skills

            # LearningItem для отслеживания прогресса
            item = LearningItem(
                course_id=trajectory.course_id,
                module_id=module.module_id,
                lesson_id=lesson.lesson_id,
                item_type='lesson',
                title=lesson.topic,
                status='planned',
                order_index=lesson.course_order_index,
            )
            db.session.add(item)
            lessons_count += 1

    db.session.commit()

    stats = {
        'modules': modules_count,
        'lessons': lessons_count,
        'skills': skills_count,
    }
    return trajectory, stats


def export_course_to_dict(trajectory: LearningTrajectory) -> Dict[str, Any]:
    """
    Экспортирует траекторию или базовый мастер-курс в каноничный JSON-словарь.
    """
    # Собираем навыки курса
    skills_map: Dict[str, ExamSkill] = {}
    for lesson in trajectory.lessons:
        for sk in lesson.skills:
            if sk.topic_code:
                skills_map[sk.topic_code] = sk

    # Если у курса есть exam_course_id, также дополняем активными навыками
    if trajectory.exam_course_id and not skills_map:
        for sk in ExamSkill.query.filter_by(exam_course_id=trajectory.exam_course_id, is_active=True).all():
            if sk.topic_code:
                skills_map[sk.topic_code] = sk

    skills_list = []
    for code, sk in sorted(skills_map.items(), key=lambda x: (x[1].task_number or 99, x[0])):
        skills_list.append({
            'topic_code': sk.topic_code,
            'name': sk.title,
            'section': sk.topic,
            'exam_task_number': sk.task_number,
        })

    # Сортировка модулей
    sorted_modules = sorted(trajectory.modules, key=lambda m: m.order_index or 0)
    modules_list = []

    for mod in sorted_modules:
        sorted_lessons = sorted(mod.lessons, key=lambda l: l.course_order_index or 0)
        lessons_list = []
        for les in sorted_lessons:
            lessons_list.append({
                'order': les.course_order_index,
                'title': les.topic,
                'lesson_format': les.lesson_format or 'Теория + Практика',
                'duration_minutes': les.duration or 60,
                'topic_codes': [sk.topic_code for sk in les.skills if sk.topic_code],
                'studio_scenario': les.studio_scenario or '',
                'theory_content': les.content or '',
                'homework_content': les.homework or '',
            })

        modules_list.append({
            'order': mod.order_index,
            'name': mod.title,
            'result': mod.learning_result or '',
            'description': mod.description or '',
            'is_control_exam': bool(mod.is_control_exam),
            'lessons': lessons_list,
        })

    return {
        'title': trajectory.title,
        'subject': trajectory.subject or 'Информатика',
        'is_template': bool(trajectory.is_template),
        'target_score': trajectory.target_score,
        'goal': trajectory.learning_goal or '',
        'result': trajectory.expected_result or '',
        'description': trajectory.description or '',
        'skills': skills_list,
        'modules': modules_list,
    }
