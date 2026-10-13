"""
Сервис интерактивной демоверсии BooStudy Demo Experience.
Управляет созданием изолированных данных, состоянием сессии и проверкой заданий.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

from flask import session
from flask_login import current_user, login_user
from werkzeug.security import generate_password_hash

from app.models import (
    Answer,
    Assignment,
    AssignmentTask,
    Course,
    GradebookEntry,
    Lesson,
    Student,
    StudentLearningPlanItem,
    StudentTaskStatistics,
    Submission,
    Tasks,
    TheoryBlock,
    TheoryGroup,
    User,
    UserRole,
    db,
)
from core.db_models import LearningTrajectory, TrajectoryModule, utc_now

logger = logging.getLogger(__name__)

SCENARIO_VERSION = 5
DEMO_TASK_SITE_ID = 'demo:trial:algorithm-trace_v2'
DEMO_CORRECT_ANSWER = '5'
DEMO_ASSIGNMENT_TITLE = 'Демо-задание: Первое испытание (След по алгоритму)'
DEMO_REVIEW_TITLE = 'Разбор ошибки: след по алгоритму'
DEMO_RETRY_TITLE = 'Исправление: след по алгоритму'
DEMO_THEORY_TASK_NUMBER = 1005
DEMO_THEORY_TITLE = 'Трассировка алгоритма: как читать программу по шагам'

STEP_RANKS = {
    'welcome': 0,
    'name_input': 1,
    'goal_selection': 2,
    'finish_ch1': 3,
    'dashboard_intro': 4,
    'chapter2_mission': 5,
    'chapter2_discovery': 6,
    'ready_for_trial': 7,
    'trial_intro': 8,
    'trial_input': 9,
    'trial_retry': 10,
    'victory': 11,
    'library_intro': 12,
    'library_opened': 13,
    'mistakes_intro': 14,
    'mistakes_opened': 15,
    'route_intro': 16,
    'route_opened': 17,
    'wins_intro': 18,
    'wins_opened': 19,
    'schedule_intro': 20,
    'schedule_opened': 21,
    'profile_intro': 22,
    'profile_opened': 23,
    'finale': 24,
}

CHAPTER_RANKS = {
    'chapter_1': 1,
    'chapter_2': 2,
    'chapter_3': 3,
    'chapter_4': 4,
    'chapter_5': 5,
    'chapter_6': 6,
    'chapter_7': 7,
    'chapter_8': 8,
    'chapter_9': 9,
    'chapter_10': 10,
}

STEP_CHAPTERS = {
    'welcome': 'chapter_1', 'name_input': 'chapter_1', 'goal_selection': 'chapter_1', 'finish_ch1': 'chapter_1',
    'dashboard_intro': 'chapter_2', 'chapter2_mission': 'chapter_2', 'chapter2_discovery': 'chapter_2', 'ready_for_trial': 'chapter_2',
    'trial_intro': 'chapter_3', 'trial_input': 'chapter_3', 'trial_retry': 'chapter_3', 'victory': 'chapter_3',
    'library_intro': 'chapter_4', 'library_opened': 'chapter_4',
    'mistakes_intro': 'chapter_5', 'mistakes_opened': 'chapter_5',
    'route_intro': 'chapter_6', 'route_opened': 'chapter_6',
    'wins_intro': 'chapter_7', 'wins_opened': 'chapter_7',
    'schedule_intro': 'chapter_8', 'schedule_opened': 'chapter_8',
    'profile_intro': 'chapter_9', 'profile_opened': 'chapter_9',
    'finale': 'chapter_10',
}

ALLOWED_STEP_TRANSITIONS = {
    'welcome': {'name_input', 'dashboard_intro'},
    'name_input': {'goal_selection', 'dashboard_intro'},
    'goal_selection': {'finish_ch1', 'dashboard_intro'},
    'finish_ch1': {'dashboard_intro'},
    'dashboard_intro': {'chapter2_mission'},
    'chapter2_mission': {'chapter2_discovery'},
    # «Посмотреть задание» из сцены находки ведёт сразу в Workspace; вариант
    # «Хочу ещё осмотреться» по-прежнему использует ready_for_trial.
    'chapter2_discovery': {'ready_for_trial', 'trial_intro'},
    'ready_for_trial': {'trial_intro'},
    'trial_intro': {'trial_input'},
    'trial_input': {'trial_retry', 'victory'},
    'trial_retry': {'trial_input', 'mistakes_intro'},
    'victory': {'mistakes_intro'},
    'library_intro': {'library_opened'},
    'library_opened': {'mistakes_intro'},
    'mistakes_intro': {'mistakes_opened'},
    'mistakes_opened': {'wins_intro'},
    'route_intro': {'route_opened'},
    'route_opened': {'wins_intro'},
    'wins_intro': {'wins_opened'},
    'wins_opened': {'schedule_intro'},
    'schedule_intro': {'schedule_opened'},
    'schedule_opened': {'profile_intro'},
    'profile_intro': {'profile_opened'},
    'profile_opened': {'finale'},
}


def is_demo_transition_allowed(state: dict[str, Any], step_id: str, chapter_id: Optional[str] = None) -> bool:
    """Validate the declarative scenario graph on the server.

    The browser may optimistically render a transition, but it must never be
    able to mint late chapters or a victory without completing its conditions.
    """
    if step_id not in STEP_CHAPTERS:
        return False
    target_chapter = chapter_id or STEP_CHAPTERS[step_id]
    if target_chapter != STEP_CHAPTERS[step_id]:
        return False
    current = state.get('step_id', 'welcome')
    if step_id == current:
        return target_chapter == state.get('chapter_id')
    if step_id not in ALLOWED_STEP_TRANSITIONS.get(current, set()):
        return False

    actions = set(state.get('completed_actions') or [])
    prerequisites = {
        'chapter2_mission': {'demo:chapter2:started'},
        'chapter2_discovery': {'demo:dashboard:lesson_explored', 'demo:dashboard:assignments_explored', 'demo:dashboard:program_explored'},
        'ready_for_trial': {'demo:chapter2:trial_discovered'},
        'trial_input': {'demo:chapter3:mode_prompted'},
        'victory': {'trial_completed'},
        'library_opened': {'demo:library:material_opened'},
        'mistakes_opened': {'demo:mistakes:review_opened'},
        'route_opened': {'demo:route:module_opened'},
        'wins_opened': {'demo:wins:analytics_opened'},
        'schedule_opened': {'demo:schedule:week_opened'},
        'profile_opened': {'demo:profile:achievements_opened'},
    }
    return prerequisites.get(step_id, set()).issubset(actions)


def is_demo_action_allowed(state: dict[str, Any], action_id: str) -> bool:
    """Allow only semantic events valid for the current scenario scene."""
    step_id = state.get('step_id', 'welcome')
    chapter_id = state.get('chapter_id', 'chapter_1')
    if action_id == 'transition_step':
        return True
    # Detours are first-class narrative choices. They enrich the session
    # history without unlocking a chapter or weakening the transition graph.
    if action_id.startswith('demo:branch:'):
        return chapter_id in {'chapter_2', 'chapter_3', 'chapter_4', 'chapter_5', 'chapter_6', 'chapter_7'}
    if action_id.startswith('choice_'):
        return chapter_id == 'chapter_1'
    if action_id.startswith('demo:finale:cta_'):
        return chapter_id == 'chapter_10' and step_id == 'finale'
    if action_id in {'demo:dashboard:explored', 'demo:assignments:opened'}:
        return chapter_id in {'chapter_2', 'chapter_5'}
    allowed = {
        'demo:chapter2:started': {'dashboard_intro'},
        'demo:dashboard:lesson_explored': {'chapter2_mission'},
        'demo:dashboard:assignments_explored': {'chapter2_mission'},
        'demo:dashboard:program_explored': {'chapter2_mission'},
        'demo:chapter2:module_opened': {'chapter2_mission'},
        'demo:chapter2:trial_discovered': {'chapter2_discovery'},
        'demo:trial:opened': {'trial_intro', 'trial_input'},
        'demo:chapter3:mode_prompted': {'trial_intro'},
        'trial_completed': {'trial_input'},
        'demo:library:material_opened': {'library_intro'},
        'demo:mistakes:review_opened': {'mistakes_intro'},
        'demo:route:module_opened': {'route_intro'},
        'demo:schedule:week_opened': {'schedule_intro'},
        'demo:profile:achievements_opened': {'profile_intro'},
        'demo:wins:analytics_opened': {'wins_intro'},
        'demo:finale:shown': {'finale'},
    }
    return step_id in allowed.get(action_id, set())


def get_or_create_demo_task() -> Tasks:
    """Возвращает или создает фиксированное демонстрационное задание."""
    task = Tasks.query.filter_by(site_task_id=DEMO_TASK_SITE_ID).first()
    if task:
        return task

    task = Tasks(
        site_task_id=DEMO_TASK_SITE_ID,
        task_number=1,
        source_url='https://boostudy.ru/demo',
        content_html=(
            "<p><strong>Демонстрационное испытание</strong> (След по алгоритму)</p>"
            "<p>Программа обрабатывает пять команд. Переменная <code>score</code> сначала равна <strong>0</strong>.</p>"
            "<pre>for command in ['UP', 'UP', 'RIGHT', 'DOWN', 'RIGHT']:\n"
            "    if command == 'UP':\n        score += 2\n"
            "    elif command == 'RIGHT':\n        score += 1\n"
            "    else:\n        score -= 1\n"
            "print(score)</pre>"
            "<p>Какое число напечатает программа? Реши задачу вручную, последовательно меняя значение <code>score</code>.</p>"
        ),
        answer=DEMO_CORRECT_ANSWER,
        difficulty_level=1,
    )
    db.session.add(task)
    db.session.commit()
    return task


def ensure_demo_theory_material(author_id: int) -> Optional[TheoryBlock]:
    """Provide the Chapter 4 article through the live theory model.

    The material is a reusable curriculum block, not a separate demo page;
    the demo only stores its deep link in its own isolated session state.
    """
    course = Course.query.filter_by(is_active=True).order_by(Course.id).first()
    if not course:
        course = Course.query.filter_by(slug='boostudy-demo-theory').first()
        if not course:
            course = Course(
                title='BooStudy: основы информатики',
                slug='boostudy-demo-theory',
                is_active=True,
            )
            db.session.add(course)
            db.session.flush()
    block = TheoryBlock.query.filter_by(
        course_id=course.id,
        task_number=DEMO_THEORY_TASK_NUMBER,
    ).first()
    if block:
        return block

    group = TheoryGroup.query.filter_by(course_id=course.id, name='Кодирование информации').first()
    if not group:
        group = TheoryGroup(
            course_id=course.id,
            name='Кодирование информации',
            description='Коды, двоичные деревья и принцип префиксности.',
            position=90,
            created_by=author_id,
        )
        db.session.add(group)
        db.session.flush()

    block = TheoryBlock(
        course_id=course.id,
        group_id=group.id,
        task_number=DEMO_THEORY_TASK_NUMBER,
        title=DEMO_THEORY_TITLE,
        description='Разбираем, как последовательно выполнять ветвления и не терять значение переменной.',
        read_minutes=8,
        position=90,
        author_id=author_id,
        content='''# Трассировка алгоритма: как читать программу по шагам

## Главная идея
Не пытайся угадать ответ по коду целиком. Заведи маленькую таблицу: после каждой команды записывай новое значение переменной.

## Ветвление
В конструкции `if / elif / else` на одном шаге срабатывает только одна ветка. Для `UP` прибавляем 2, для `RIGHT` — 1, а для `DOWN` вычитаем 1.

## Трассировка
Начинаем с `score = 0`: после двух `UP` получаем 4, затем `RIGHT` даёт 5, `DOWN` возвращает к 4, последний `RIGHT` приводит к 5.

## Проверяем себя
[CHECKPOINT key="algorithm-branch" question="Какое действие выполняется для команды `RIGHT`?" options="Прибавить 1|Прибавить 2|Вычесть 1" answer="Прибавить 1" explanation="Верно: вторая ветка `elif` добавляет к score единицу."]

Теперь ты видишь не только ответ, но и универсальный способ читать любой короткий алгоритм: одна команда — одно обновление состояния.''',
    )
    db.session.add(block)
    db.session.commit()
    return block


def ensure_demo_user_and_assignment(
    student_name: str = 'Демо-ученик',
    exam: str = 'ege',
    goal: str = 'ege',
    grade: str = '11',
) -> dict[str, Any]:
    """
    Создает или восстанавливает изолированного пользователя и демонстрационную работу.
    """
    clean_name = (student_name or 'Демо-ученик').strip()[:40] or 'Демо-ученик'
    if goal not in {'ege_80', 'ege_90', 'oge_5', 'programming', 'choosing'}:
        goal = 'oge_5' if exam == 'oge' else ('programming' if goal == 'programming' else 'ege_90')
    exam = 'oge' if goal == 'oge_5' else 'ege'
    if grade not in {'1-4', '5-8', '9', '10', '11', 'graduate'}:
        grade = '11'

    # Если уже авторизован демо-пользователь — используем его
    user = None
    if current_user.is_authenticated and getattr(current_user, 'is_demo_user', False):
        user = current_user
        student = Student.query.filter_by(user_id=user.id).first()
        if student and clean_name and student.name != clean_name:
            student.name = clean_name
            db.session.commit()
    else:
        demo_uid = uuid.uuid4().hex[:8]
        username = f"demo_{demo_uid}"
        pwd_hash = generate_password_hash(uuid.uuid4().hex)
        user = User(
            username=username,
            email=f"{username}@demo.boostudy.ru",
            password_hash=pwd_hash,
            role='student',
            is_demo_user=True,
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()

        db.session.add(UserRole(user_id=user.id, role='student'))
        student = Student(
            name=clean_name,
            user_id=user.id,
            is_active=True,
            email=f"{username}@demo.boostudy.ru",
        )
        db.session.add(student)
        db.session.commit()

        login_user(user, remember=True)

    if not student:
        student = Student.query.filter_by(user_id=user.id).first()

    now = utc_now()

    # 1. Наставник и профильные параметры ученика
    mentor = User.query.filter(User.role.in_(['teacher', 'tutor', 'creator'])).first()
    if not mentor:
        mentor = User.query.filter_by(username='demo_mentor').first()
        if not mentor:
            mentor = User(
                username='demo_mentor',
                email='mentor@demo.boostudy.ru',
                password_hash=generate_password_hash(uuid.uuid4().hex),
                role='teacher',
                is_active=True,
            )
            db.session.add(mentor)
            db.session.flush()
            db.session.add(UserRole(user_id=mentor.id, role='teacher'))
            db.session.commit()

    if mentor and not student.mentor_id:
        student.mentor_id = mentor.id

    student.target_score = (80 if goal == 'ege_80' else 90) if exam == 'ege' else (5 if exam == 'oge' else None)
    student.streak_days = 41
    student.xp = 1420
    student.level = 5
    student.lessons_balance = 8
    # These are display fixtures for this isolated demo account only; they
    # never grant achievements to an ordinary learner.
    try:
        from core.db_models import UserAchievement
        for achievement_key in ('streak_30', 'tasks_150', 'lvl_5', 'referral_copied', 'lesson_code_live'):
            exists = UserAchievement.query.filter_by(student_id=student.student_id, achievement_key=achievement_key).first()
            if not exists:
                db.session.add(UserAchievement(student_id=student.student_id, achievement_key=achievement_key))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Could not prepare demo achievement showcase')

    # 2. Создаем изолированное демонстрационное задание (Глава 3)
    task = get_or_create_demo_task()
    theory_block = ensure_demo_theory_material(user.id)

    # Retire only the obsolete demo records from the earlier Fano storyline.
    # They belong to the isolated demo user and must not compete with the
    # current chapter's single, programming-oriented first assignment.
    legacy_titles = (
        'Демо-задание: Первое испытание (Условие Фано)',
        'Разбор ошибки: условие Фано',
        'Исправление: условие Фано',
    )
    for legacy_sub in Submission.query.join(Assignment).filter(
        Submission.student_id == student.student_id,
        Submission.status == 'IN_PROGRESS',
        Assignment.title.in_(legacy_titles),
    ).all():
        legacy_sub.status = 'GRADED'
        legacy_sub.graded_at = now

    sub = Submission.query.join(Assignment).filter(
        Submission.student_id == student.student_id,
        Submission.status == 'IN_PROGRESS',
        Assignment.title == DEMO_ASSIGNMENT_TITLE,
    ).first()
    if not sub:
        assignment = Assignment(
            title=DEMO_ASSIGNMENT_TITLE,
            description='Пробное задание для знакомства с возможностями сдачи работ в BooStudy.',
            assignment_type='homework',
            deadline=now + timedelta(days=14),
            hard_deadline=False,
            hide_before_start=False,
            allow_separate_submission=True,
            created_by_id=user.id,
            is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=assignment.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
            answer_override=DEMO_CORRECT_ANSWER,
        )
        db.session.add(at)
        db.session.flush()

        sub = Submission(
            assignment_id=assignment.assignment_id,
            student_id=student.student_id,
            status='IN_PROGRESS',
            assigned_at=now,
            started_at=now,
            max_score=1,
        )
        db.session.add(sub)
        db.session.flush()
    assignment_task = AssignmentTask.query.filter_by(
        assignment_id=sub.assignment_id, task_id=task.task_id
    ).first()

    # 3. Завершённая работа с оценкой (для дашборда)
    completed_sub = Submission.query.filter_by(student_id=student.student_id, status='GRADED').first()
    if not completed_sub:
        as_completed = Assignment(
            title='Проверочная работа: Анализ графов (№1)',
            description='Анализ связности графов и сопоставление с таблицами расстояний.',
            assignment_type='homework',
            deadline=now - timedelta(days=2),
            hard_deadline=False,
            is_active=True,
            created_by_id=student.mentor_id or user.id,
        )
        db.session.add(as_completed)
        db.session.flush()

        at_c = AssignmentTask(
            assignment_id=as_completed.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=10,
        )
        db.session.add(at_c)
        db.session.flush()

        completed_sub = Submission(
            assignment_id=as_completed.assignment_id,
            student_id=student.student_id,
            status='GRADED',
            assigned_at=now - timedelta(days=6),
            submitted_at=now - timedelta(days=3),
            graded_at=now - timedelta(days=3),
            max_score=10,
        )
        db.session.add(completed_sub)
        db.session.flush()

        ans_c = Answer(
            submission_id=completed_sub.submission_id,
            assignment_task_id=at_c.assignment_task_id,
            value='24',
            score=10,
            max_score=10,
            is_correct=True,
            teacher_comment='Отличный разбор графа, всё верно!',
        )
        db.session.add(ans_c)

        gb = GradebookEntry(
            student_id=student.student_id,
            kind='assignment',
            category='homework',
            title='Проверочная работа: Анализ графов (№1)',
            score=10,
            max_score=10,
            grade_text='5',
            comment='Отличный разбор графа, всё верно!',
            submission_id=completed_sub.submission_id,
        )
        db.session.add(gb)

    # Отдельная проверенная работа для Главы 5.  В ней есть ошибка, комментарий
    # наставника и возможность вернуться к решению — это не подмена интерфейса,
    # а обычный Submission в изолированной демо-сессии.
    review_assignment = Assignment.query.filter_by(
        title=DEMO_REVIEW_TITLE,
        created_by_id=user.id,
    ).first()
    review_sub = None
    if review_assignment:
        review_sub = Submission.query.filter_by(
            assignment_id=review_assignment.assignment_id,
            student_id=student.student_id,
        ).first()
    if not review_sub:
        if not review_assignment:
            review_assignment = Assignment(
                title=DEMO_REVIEW_TITLE,
                description='Небольшая проверенная работа: открой комментарий и исправь ход рассуждений.',
                assignment_type='homework',
                deadline=now - timedelta(days=1),
                hard_deadline=False,
                is_active=True,
                created_by_id=user.id,
            )
            db.session.add(review_assignment)
            db.session.flush()
            review_task = AssignmentTask(
                assignment_id=review_assignment.assignment_id,
                task_id=task.task_id,
                order_index=0,
                max_score=1,
                answer_override=DEMO_CORRECT_ANSWER,
            )
            db.session.add(review_task)
            db.session.flush()
        else:
            review_task = AssignmentTask.query.filter_by(assignment_id=review_assignment.assignment_id).first()
        review_sub = Submission(
            assignment_id=review_assignment.assignment_id,
            student_id=student.student_id,
            status='GRADED',
            assigned_at=now - timedelta(days=5),
            submitted_at=now - timedelta(days=4),
            graded_at=now - timedelta(days=4),
            max_score=1,
        )
        db.session.add(review_sub)
        db.session.flush()
        db.session.add(Answer(
            submission_id=review_sub.submission_id,
            assignment_task_id=review_task.assignment_task_id,
            value='4',
            score=0,
            max_score=1,
            is_correct=False,
            teacher_comment='Хорошее начало. Попробуй записать значение score после каждой команды — так не потеряется ни одна ветка.',
        ))
        db.session.add(GradebookEntry(
            student_id=student.student_id,
            kind='assignment',
            category='homework',
            title=DEMO_REVIEW_TITLE,
            score=0,
            max_score=1,
            grade_text='Нужна доработка',
            comment='Разбор сохранён: можно исправить ход рассуждений и повторить попытку.',
            submission_id=review_sub.submission_id,
        ))

    # A separate, editable retry preserves the original graded mistake while
    # letting the learner correct it in the same real Workspace component.
    retry_assignment = Assignment.query.filter_by(
        title=DEMO_RETRY_TITLE,
        created_by_id=user.id,
    ).first()
    retry_sub = None
    if retry_assignment:
        retry_sub = Submission.query.filter_by(
            assignment_id=retry_assignment.assignment_id,
            student_id=student.student_id,
        ).first()
    if not retry_sub:
        if not retry_assignment:
            retry_assignment = Assignment(
                title=DEMO_RETRY_TITLE,
                description='Повторная попытка после разбора ошибки. Запиши новый ответ и проверь ход рассуждений.',
                assignment_type='homework',
                deadline=now + timedelta(days=7),
                hard_deadline=False,
                is_active=True,
                created_by_id=user.id,
            )
            db.session.add(retry_assignment)
            db.session.flush()
            db.session.add(AssignmentTask(
                assignment_id=retry_assignment.assignment_id,
                task_id=task.task_id,
                order_index=0,
                max_score=1,
                answer_override=DEMO_CORRECT_ANSWER,
            ))
            db.session.flush()
        retry_sub = Submission(
            assignment_id=retry_assignment.assignment_id,
            student_id=student.student_id,
            status='IN_PROGRESS',
            assigned_at=now,
            started_at=now,
            max_score=1,
        )
        db.session.add(retry_sub)
        db.session.flush()
    retry_assignment_task = AssignmentTask.query.filter_by(
        assignment_id=retry_sub.assignment_id, task_id=task.task_id
    ).first()

    # 4. Пройденные и предстоящие уроки
    next_lesson_msk = utc_now().astimezone(ZoneInfo('Europe/Moscow')) + timedelta(days=2)
    next_lesson_msk = next_lesson_msk.replace(hour=18, minute=0, second=0, microsecond=0)
    next_lesson_at = next_lesson_msk.astimezone(timezone.utc)
    has_lessons = Lesson.query.filter_by(student_id=student.student_id).first()
    if not has_lessons:
        l1 = Lesson(
            student_id=student.student_id,
            topic='Базовые алгоритмы теории графов (№1)',
            lesson_date=now - timedelta(days=10),
            status='completed',
            duration=60,
            lesson_format='Теория + Практика',
            homework_status='checked',
            homework_result_percent=100,
        )
        l2 = Lesson(
            student_id=student.student_id,
            topic='След по алгоритму и ветвления (№1)',
            lesson_date=now - timedelta(days=4),
            status='completed',
            duration=60,
            lesson_format='Теория + Практика',
            homework_status='checked',
            homework_result_percent=90,
        )
        l3 = Lesson(
            student_id=student.student_id,
            topic='Анализ программ и алгоритмов (№27)',
            lesson_date=next_lesson_at,
            status='planned',
            duration=60,
            lesson_format='Практикум',
        )
        db.session.add_all([l1, l2, l3])
    else:
        # Older demo accounts may still contain a historical Fano lesson from
        # the superseded storyline.  The guided exhibit is intentionally
        # programming-oriented, just like the trial task, so normalise only
        # those isolated legacy records rather than showing a contradictory
        # subject example in the new route.
        for legacy_lesson in Lesson.query.filter(
            Lesson.student_id == student.student_id,
            Lesson.topic.ilike('%Фано%'),
        ).all():
            legacy_lesson.topic = 'След по алгоритму и ветвления (№1)'
            legacy_lesson.lesson_format = 'Теория + Практика'
            legacy_lesson.homework_status = 'checked'
            legacy_lesson.homework_result_percent = 90
        next_lesson = Lesson.query.filter_by(student_id=student.student_id, status='planned').order_by(Lesson.lesson_date.asc()).first()
        if next_lesson:
            next_lesson.lesson_date = next_lesson_at

    # 5. Настоящая индивидуальная траектория для Главы 6.  Она привязана
    # исключительно к временному demo-student и поэтому не видна другим ученикам.
    track_name = 'основы программирования и логики' if grade == '1-4' else ('уверенная база и олимпиадное мышление' if grade == '5-8' else 'подготовка по информатике')
    goal_context = {
        'ege_80': (f'Цель: ЕГЭ 80+ · {track_name}', 'Стабильный результат выше 80 баллов', 80, 74),
        'ege_90': (f'Цель: ЕГЭ 90+ · {track_name}', 'Стабильный результат выше 90 баллов', 90, 74),
        'oge_5': (f'Цель: ОГЭ на 5 · {track_name}', 'Уверенно решать задания ОГЭ', 5, None),
        'programming': (f'Цель: научиться программировать · {track_name}', 'Самостоятельно писать и разбирать алгоритмы', None, None),
        'choosing': (f'Цель: пока выбираю · {track_name}', 'Понять свой следующий учебный шаг', None, None),
        'ege': ('Подготовиться к ЕГЭ по информатике на 90+', 'Стабильный результат выше 90 баллов', 90, 74),
        'oge': ('Подготовиться к ОГЭ по информатике на пятёрку', 'Уверенно решать задания ОГЭ', 5, None),
    }.get(goal, ('Познакомиться с возможностями платформы', 'Понять свой следующий учебный шаг', None, None))
    trajectory = LearningTrajectory.query.filter_by(
        student_id=student.student_id,
        title='Демо-маршрут: информатика',
    ).first()
    if not trajectory:
        trajectory = LearningTrajectory(
            student_id=student.student_id,
            created_by_user_id=student.mentor_id or user.id,
            title='Демо-маршрут: информатика',
            subject='Информатика',
            description='Персональная траектория для знакомства с возможностями BooStudy.',
            learning_goal=goal_context[0],
            expected_result=goal_context[1],
            target_score=goal_context[2],
            current_forecast=goal_context[3],
            status='active',
        )
        db.session.add(trajectory)
        db.session.flush()
        modules = [
            TrajectoryModule(course_id=trajectory.course_id, title='Основа уже пройдена', description='Базовые алгоритмы и графы', learning_result='Понимать типовые модели задач', order_index=1),
            TrajectoryModule(course_id=trajectory.course_id, title='Сейчас в фокусе', description='Ветвления и трассировка алгоритмов', learning_result='Читать короткие программы по шагам', order_index=2),
            TrajectoryModule(course_id=trajectory.course_id, title='Следующий шаг', description='Сети, маски и адресация', learning_result='Решать задания на подсети', order_index=3),
        ]
        db.session.add_all(modules)
    else:
        trajectory.learning_goal = goal_context[0]
        trajectory.expected_result = goal_context[1]
        trajectory.target_score = goal_context[2]
        trajectory.current_forecast = goal_context[3]
        modules = TrajectoryModule.query.filter_by(course_id=trajectory.course_id).order_by(TrajectoryModule.order_index.asc()).all()
        if modules:
            modules[0].learning_result = 'Осваивать ' + track_name
            if len(modules) > 1:
                modules[1].learning_result = 'Двигаться к цели: ' + goal_context[1].lower()
        db.session.flush()

    modules = TrajectoryModule.query.filter_by(course_id=trajectory.course_id).order_by(TrajectoryModule.order_index).all()
    demo_lessons = Lesson.query.filter_by(student_id=student.student_id).order_by(Lesson.lesson_date).all()
    for index, lesson in enumerate(demo_lessons):
        if modules and not lesson.learning_trajectory_id:
            lesson.learning_trajectory_id = trajectory.course_id
            lesson.course_module_id = modules[min(index, len(modules) - 1)].module_id
            lesson.course_order_index = index + 1

    # 6. Темы учебной траектории
    has_plan = StudentLearningPlanItem.query.filter_by(student_id=student.student_id).first()
    if not has_plan:
        p1 = StudentLearningPlanItem(
            student_id=student.student_id,
            title='Анализ графов и весовых таблиц (№1)',
            status='done',
            priority=3,
        )
        p2 = StudentLearningPlanItem(
            student_id=student.student_id,
            title='Ветвления и трассировка алгоритмов (№1)',
            status='in_progress',
            priority=2,
            due_date=now + timedelta(days=3),
        )
        p3 = StudentLearningPlanItem(
            student_id=student.student_id,
            title='Маски подсетей и адресация (№13)',
            status='planned',
            priority=1,
            due_date=now + timedelta(days=7),
        )
        db.session.add_all([p1, p2, p3])
    else:
        # Keep pre-existing isolated demo accounts consistent with the current
        # programming route; an older fixture exposed a Fano topic here.
        for legacy_plan in StudentLearningPlanItem.query.filter(
            StudentLearningPlanItem.student_id == student.student_id,
            StudentLearningPlanItem.title.ilike('%Фано%'),
        ).all():
            legacy_plan.title = 'Ветвления и трассировка алгоритмов (№1)'
            legacy_plan.status = 'in_progress'
            legacy_plan.priority = 2
            legacy_plan.due_date = now + timedelta(days=3)

    # 7. Статистика по номерам заданий
    has_stats = StudentTaskStatistics.query.filter_by(student_id=student.student_id).first()
    if not has_stats:
        s1 = StudentTaskStatistics(
            student_id=student.student_id,
            task_number=1,
            manual_correct=4,
            manual_incorrect=1,
        )
        s2 = StudentTaskStatistics(
            student_id=student.student_id,
            task_number=4,
            manual_correct=5,
            manual_incorrect=0,
        )
        db.session.add_all([s1, s2])

    db.session.commit()

    # Инициализация состояния сценария
    existing_state = session.get('demo_state') or {}
    if existing_state.get('version') != SCENARIO_VERSION:
        existing_state = {}
    # An identity makes browser persistence safe: local progress from an older
    # demo visitor must never win over the current signed demo session.
    demo_session_id = existing_state.get('demo_session_id') or session.get('demo_session_id') or uuid.uuid4().hex
    session['demo_session_id'] = demo_session_id
    state = {
        'version': SCENARIO_VERSION,
        'chapter_id': existing_state.get('chapter_id') or 'chapter_1',
        'step_id': existing_state.get('step_id') or 'welcome',
        'student_name': clean_name,
        'exam': exam,
        'goal': goal or existing_state.get('goal') or 'ege',
        'grade': grade,
        'six_month_demo': True,
        'completed_actions': existing_state.get('completed_actions') or [],
        'flags': existing_state.get('flags') or {},
        'history': existing_state.get('history') or [],
        'submission_id': sub.submission_id,
        'assignment_task_id': assignment_task.assignment_task_id if assignment_task else None,
        'assignment_id': sub.assignment_id,
        'task_id': task.task_id,
        'lesson_id': demo_lessons[-1].lesson_id if demo_lessons else None,
        'program_url': f'/student/{student.student_id}/courses',
        'analytics_url': f'/student/{student.student_id}/analytics',
        'schedule_url': '/schedule?timezone=Europe%2FMoscow&view=week',
        'profile_url': '/workspace/profile',
        'billing_url': '/billing/plans/public',
        'theory_url': f'/theory/topic/{theory_block.id}?course_id={theory_block.course_id}' if theory_block else '/theory',
        'mistake_submission_id': retry_sub.submission_id,
        'mistake_assignment_task_id': retry_assignment_task.assignment_task_id if retry_assignment_task else None,
        'demo_session_id': demo_session_id,
        'director_revision': int(existing_state.get('director_revision') or 0),
    }
    session['demo_state'] = state
    session.modified = True

    return state


def get_demo_state(user_id: Optional[int] = None) -> dict[str, Any]:
    """Возвращает текущее состояние сценария демосессии."""
    state = session.get('demo_state')
    if not state or not isinstance(state, dict):
        return {
            'version': SCENARIO_VERSION,
            'chapter_id': 'chapter_1',
            'step_id': 'welcome',
            'student_name': 'Демо-ученик',
            'exam': 'ege',
            'goal': 'ege',
            'completed_actions': [],
            'flags': {},
            'history': [],
            'demo_session_id': session.get('demo_session_id'),
            'director_revision': 0,
            'submission_id': None,
            'assignment_id': None,
        }
    # Each new demo journey follows the approved linear story. Never revive an
    # old checkpoint from the earlier branching prototype.
    if state.get('version') != SCENARIO_VERSION:
        state.update({
            'version': SCENARIO_VERSION,
            'chapter_id': 'chapter_1',
            'step_id': 'welcome',
            'completed_actions': [],
            'flags': {},
            'history': [],
        })
        session['demo_state'] = state
        session.modified = True
    return state


def update_demo_state(updates: dict[str, Any]) -> dict[str, Any]:
    """Безопасно обновляет поля состояния в сессии с защитой от отката шагов."""
    state = get_demo_state()
    requested_step = updates.get('step_id')
    requested_chapter = updates.get('chapter_id')
    if requested_step and not is_demo_transition_allowed(state, requested_step, requested_chapter):
        # Keep the authoritative state unchanged.  The caller can rehydrate its
        # optimistic UI from the returned value after a stale or forged request.
        return state
    for k, v in updates.items():
        if k == 'step_id' and v:
            curr_rank = STEP_RANKS.get(state.get('step_id', 'welcome'), 0)
            new_rank = STEP_RANKS.get(v, 0)
            # A declared graph edge may intentionally revisit a scene (for
            # example, retrying an answer after receiving a hint).
            if (new_rank >= curr_rank or v in ALLOWED_STEP_TRANSITIONS.get(state.get('step_id', ''), set())) and is_demo_transition_allowed(state, v, requested_chapter):
                state['step_id'] = v
        elif k == 'chapter_id' and v:
            curr_c_rank = CHAPTER_RANKS.get(state.get('chapter_id', 'chapter_1'), 1)
            new_c_rank = CHAPTER_RANKS.get(v, 1)
            if new_c_rank >= curr_c_rank:
                state['chapter_id'] = v
        elif k == 'completed_actions' and isinstance(v, list):
            current_actions = set(state.get('completed_actions', []))
            current_actions.update(v)
            state['completed_actions'] = sorted(list(current_actions))
        elif k == 'flags' and isinstance(v, dict):
            current_flags = state.get('flags', {})
            current_flags.update(v)
            state['flags'] = current_flags
        elif k == 'history' and isinstance(v, list):
            current_hist = state.get('history', [])
            current_hist.extend(v)
            state['history'] = current_hist[-50:]
        else:
            state[k] = v

    session['demo_state'] = state
    session.modified = True
    return state


def set_demo_scene(chapter_id: str, step_id: str, *, flags: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Move an already-validated server outcome to a scene atomically.

    This is used for outcomes such as answer checking, where the server—not a
    fragile browser click order—is the authority.  Incrementing the revision
    makes the browser discard any stale local checkpoint on the next render.
    """
    if STEP_CHAPTERS.get(step_id) != chapter_id:
        raise ValueError('scene does not belong to chapter')
    state = get_demo_state()
    state['chapter_id'] = chapter_id
    state['step_id'] = step_id
    if flags:
        state['flags'] = {**(state.get('flags') or {}), **flags}
    state['director_revision'] = int(state.get('director_revision') or 0) + 1
    session['demo_state'] = state
    session.modified = True
    return state


def record_demo_action(action_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Регистрирует выполненное действие с гарантией идемпотентности."""
    state = get_demo_state()
    completed = state.get('completed_actions', [])
    if action_id not in completed:
        completed.append(action_id)
        state['completed_actions'] = completed

    history = state.get('history', [])
    history.append({
        'action_id': action_id,
        'timestamp': utc_now().isoformat(),
        'payload': payload or {},
    })
    state['history'] = history[-50:]

    session['demo_state'] = state
    session.modified = True
    return state


def verify_demo_task_answer(submission_id: int, raw_answer: str) -> dict[str, Any]:
    """
    Проверяет ответ ученика на демонстрационное задание в изолированном контексте.
    """
    state = get_demo_state()
    clean_answer = (raw_answer or '').strip()

    is_correct = (clean_answer == DEMO_CORRECT_ANSWER)

    sub = db.session.get(Submission, submission_id)
    student = Student.query.filter_by(user_id=current_user.id).first() if current_user.is_authenticated else None
    if not sub or not student or not current_user.is_authenticated or not current_user.is_demo_user or sub.student_id != student.student_id:
        return {'success': False, 'error': 'submission not available for this demo session'}

    is_mistake_retry = bool(sub.assignment and sub.assignment.title == DEMO_RETRY_TITLE)
    if sub:
        # Сохраняем/обновляем ответ в БД для демонстрационного submission
        at = AssignmentTask.query.filter_by(assignment_id=sub.assignment_id).first()
        if at:
            existing_ans = Answer.query.filter_by(submission_id=sub.submission_id, assignment_task_id=at.assignment_task_id).first()
            if not existing_ans:
                existing_ans = Answer(
                    submission_id=sub.submission_id,
                    assignment_task_id=at.assignment_task_id,
                    value=clean_answer,
                    is_correct=is_correct,
                    score=1 if is_correct else 0,
                )
                db.session.add(existing_ans)
            else:
                existing_ans.value = clean_answer
                existing_ans.is_correct = is_correct
                existing_ans.score = 1 if is_correct else 0

        if is_correct:
            sub.status = 'GRADED'
            sub.graded_at = utc_now()
        else:
            sub.status = 'IN_PROGRESS'
        db.session.commit()

    if is_correct and is_mistake_retry:
        record_demo_action('demo:mistakes:corrected', {'answer': clean_answer, 'submission_id': sub.submission_id})
        set_demo_scene('chapter_5', 'mistakes_opened', flags={'mistakes_fixed': True})
        return {
            'success': True,
            'is_correct': True,
            'feedback': 'Отлично: ты исправил ход рассуждений, и результат обновлён до 1 из 1.',
            'chapter_completed': True,
            'next_step': 'mistakes_opened',
            'chapter_id': 'chapter_5',
            'companion_message': 'Ошибка превратилась в освоенный навык. Ты не просто нашёл ответ — ты понял, где изменился ход рассуждений.',
            'state': get_demo_state(),
        }
    if is_correct:
        # Reuse the normal achievement model for the temporary demo student
        # rather than creating a parallel cinematic badge.  The record is
        # removed with the isolated demo account on exit.
        from app.utils.achievement_service import grant_achievement

        achievement_unlocked = grant_achievement(student, 'first_step', award_xp=False)
        record_demo_action('trial_completed', {'answer': clean_answer})
        set_demo_scene('chapter_3', 'victory', flags={'trial_passed': True})
        return {
            'success': True,
            'is_correct': True,
            'feedback': 'Блестяще! Ты последовательно проследил алгоритм и получил 5. Задание решено верно!',
            'chapter_completed': True,
            'next_step': 'victory',
            'achievement_unlocked': achievement_unlocked,
            'state': get_demo_state(),
        }
    else:
        record_demo_action('trial_attempt_failed', {'answer': clean_answer})
        set_demo_scene('chapter_3', 'trial_retry', flags={'trial_attempts': int((state.get('flags') or {}).get('trial_attempts') or 0) + 1})
        return {
            'success': True,
            'is_correct': False,
            'feedback': 'Почти. Ошибка — обычная часть решения, сейчас разберём один конкретный шаг.',
            'hint': 'На четвёртой команде DOWN вычти 1 из текущего score. Запиши новое значение и продолжай.',
            'can_retry': True,
            'next_step': 'trial_retry',
            'chapter_id': 'chapter_3',
            'state': get_demo_state(),
        }


def reset_demo_session() -> None:
    """Полный сброс демо-сессии."""
    session.pop('demo_state', None)
    session.pop('demo_session_id', None)
    session.pop('cinema_demo_ids', None)
    session.modified = True
