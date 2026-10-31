"""Regression coverage for the canonical V2 individual lesson room."""

from datetime import datetime, timezone

from app.task_workspace.service import _normalize_assignment_task_heading
from tests.v2.test_role_lifecycle_recovery import login_as


def test_assignment_task_heading_matches_assignment_type():
    condition = '<p>Классная · альтернативные кратчайшие пути</p>'

    assert _normalize_assignment_task_heading(condition, 'HOMEWORK') == (
        '<p>Домашняя · альтернативные кратчайшие пути</p>'
    )
    assert _normalize_assignment_task_heading(condition, 'classwork') == condition
    assert _normalize_assignment_task_heading('<p>Условие задачи</p>', 'homework') == (
        '<p>Условие задачи</p>'
    )


def test_canonical_lesson_room_renders_all_real_workspaces(app, client, role_users):
    from app import db
    from app.models import Lesson, LessonTask, Tasks

    with app.app_context():
        task = Tasks(
            task_number=9,
            content_html='<p>Найдите значение выражения.</p>',
            answer='42',
            starter_code='print(42)',
            is_active=True,
        )
        lesson = Lesson(
            student_id=role_users['student_id'],
            lesson_date=datetime.now(timezone.utc),
            duration=60,
            status='in_progress',
            topic='Полная проверка V2-комнаты',
        )
        db.session.add_all([task, lesson])
        db.session.flush()
        db.session.add(LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type='classwork',
            status='pending',
        ))
        db.session.commit()
        lesson_id = lesson.lesson_id

    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.get(f'/lesson/{lesson_id}/room')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'lesson-os-system-bar' in html
    assert 'id="code-editor-textarea"' in html
    assert 'id="whiteboard-canvas-viewport"' in html
    assert 'id="board-tool-rail"' in html
    assert 'id="board-command-bar"' in html
    assert 'homework-os-room.css' not in html
    assert 'homework-os-room.js' not in html
    assert 'data-boostudy-mode="lesson"' in html
    assert 'boostudy-mode-lesson' in html
    assert 'room-lesson-os boostudy-mode-lesson' in html
    assert 'boostudy-mode-homework' not in html
    assert 'boostudy-mode-review' not in html
    assert 'homework-os boostudy-mode-homework' not in html
    assert 'id="dock-icon-code-window"' in html
    assert 'id="dock-icon-task-window"' in html
    assert 'id="dock-icon-theory-window"' in html
    assert 'id="dock-icon-terminal-window"' in html
    assert 'boostudy_lesson_os_windows_v7_' in html
    assert "(!compact && id === 'task-window')" in html
    assert 'id="task-current-content"' in html
    assert 'id="theory-window-body"' in html
    assert 'id="room-work-mode-switcher"' not in html
    assert '/sandbox/lesson_room/' not in html
    assert 'id="lesson-open-completion"' in html
    assert 'onclick="openLessonCompletionPanel()"' in html
    assert 'Math.min(520, window.innerWidth - 20)' in html
    assert "panel.style.setProperty('left', '10px', 'important')" in html
    assert "target?.scrollIntoView({ block: 'center' })" in html
    assert 'data-lesson-completion-label>Итоги и завершение</span>' in html
    assert '"balance_deducted": false' in html
    assert 'Подтверждение доступно после закрытия комнаты' in html
    assert 'id="lesson-outcome-save-btn"' in html
    assert 'id="lesson-room-close-btn"' in html
    assert 'id="lesson-conducted-confirmation-controls" class="grid gap-2"' in html
    assert 'id="lesson-conducted-confirm-btn"' in html
    assert 'таймер сам по себе ничего не подтверждает.' in html

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        lesson.status = 'completed'
        lesson.balance_deducted = True
        db.session.commit()

    completed_response = client.get(f'/lesson/{lesson_id}/room')
    completed_html = completed_response.get_data(as_text=True)
    assert completed_response.status_code == 200
    assert 'data-lesson-completion-label>Итоги урока</span>' in completed_html
    assert '"balance_deducted": true' in completed_html
    assert 'Проведение подтверждено. Списано одно занятие.' in completed_html
    assert 'Итог можно сохранить отдельно; это не изменит статус и не повторит списание.' in completed_html
    assert 'Занятие завершено; педагогический итог не записан.' in completed_html
    assert 'id="lesson-conducted-confirmation-controls" class="grid gap-2" hidden' in completed_html
    assert 'id="lesson-room-close-btn" type="button"' in completed_html
    assert 'id="lesson-room-close-btn" type="button" class="py-2 px-3 rounded-xl border border-slate-300 bg-white hover:bg-slate-50 text-slate-800 font-bold text-xs w-full shadow-xs transition-all cursor-pointer" hidden' in completed_html
    assert "const terminalStatus = ['completed', 'cancelled'].includes(normalizedStatus);" in completed_html

    login_as(client, role_users['student_user_id'], 'student')
    student_response = client.get(f'/lesson/{lesson_id}/room')
    student_html = student_response.get_data(as_text=True)
    assert student_response.status_code == 200
    assert 'id="lesson-open-completion"' not in student_html
    assert 'id="lesson-outcome-save-btn"' not in student_html
    assert 'id="lesson-room-close-btn"' not in student_html
    assert 'id="lesson-conducted-confirm-btn"' not in student_html


def test_homework_review_room_renders_review_grade_window(app, client, role_users):
    from app import db
    from app.models import Assignment, AssignmentTask, Submission, Tasks

    with app.app_context():
        task = Tasks(
            task_number=24,
            content_html='<p>Задание 24 на строки.</p>',
            answer='120',
            starter_code="with open('24.txt') as f: pass",
            is_active=True,
        )
        db.session.add(task)
        db.session.flush()

        asg = Assignment(
            title='Домашка №1',
            assignment_type='HOMEWORK',
            deadline=datetime.now(timezone.utc),
            created_by_id=role_users['tutor_id'],
            is_active=True,
        )
        db.session.add(asg)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=asg.assignment_id,
            task_id=task.task_id,
            order_index=1,
            max_score=1,
        )
        db.session.add(at)
        db.session.flush()

        sub = Submission(
            assignment_id=asg.assignment_id,
            student_id=role_users['student_id'],
            status='SUBMITTED',
        )
        db.session.add(sub)
        db.session.flush()

        sub_id = sub.submission_id
        at_id = at.assignment_task_id
        db.session.commit()

    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.get(f'/task-workspace/?context_type=submission_task&context_id={sub_id}&assignment_task_id={at_id}&review=1')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'homework-os-room.css' in html
    assert 'homework-os-room.js' in html
    assert 'data-boostudy-mode="review"' in html
    assert 'boostudy-mode-review' in html
    assert 'boostudy-mode-homework' in html
    assert 'homework-os boostudy-mode-homework' in html
    assert 'boostudy-mode-lesson' not in html
    assert 'room-lesson-os boostudy-mode-lesson' not in html


def test_homework_student_room_mode_isolation(app, client, role_users):
    from app import db
    from app.models import Assignment, AssignmentTask, Submission, Tasks

    with app.app_context():
        task = Tasks(
            task_number=25,
            content_html='<p>Задание 25 на маски.</p>',
            answer='12345',
            starter_code="print('student')",
            is_active=True,
        )
        db.session.add(task)
        db.session.flush()

        asg = Assignment(
            title='Домашка ученика №2',
            assignment_type='HOMEWORK',
            deadline=datetime.now(timezone.utc),
            created_by_id=role_users['tutor_id'],
            is_active=True,
        )
        db.session.add(asg)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=asg.assignment_id,
            task_id=task.task_id,
            order_index=1,
            max_score=1,
        )
        db.session.add(at)
        db.session.flush()

        sub = Submission(
            assignment_id=asg.assignment_id,
            student_id=role_users['student_id'],
            status='IN_PROGRESS',
        )
        db.session.add(sub)
        db.session.flush()

        sub_id = sub.submission_id
        at_id = at.assignment_task_id
        db.session.commit()

    login_as(client, role_users['student_user_id'], 'student')
    response = client.get(f'/task-workspace/?context_type=submission_task&context_id={sub_id}&assignment_task_id={at_id}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'homework-os-room.css' in html
    assert 'homework-os-room.js' in html
    assert 'data-boostudy-mode="homework"' in html
    assert 'boostudy-mode-homework' in html
    assert 'homework-os boostudy-mode-homework' in html
    assert 'boostudy-mode-lesson' not in html
    assert 'room-lesson-os boostudy-mode-lesson' not in html
    assert 'boostudy-mode-review' not in html


def test_lesson_room_with_candidate_homework_does_not_500(app, client, role_users):
    """P0 Regression: opening lesson room as teacher/tutor when lesson or student

    has assignments previously threw HTTP 500 BuildError for 'assignments.assignment_grade'.
    Verify both teacher and student get HTTP 200 with valid rendered HTML.
    """
    from app import db
    from app.models import Assignment, AssignmentTask, Lesson, Submission, Tasks

    with app.app_context():
        task = Tasks(
            task_number=24,
            content_html='<p>Текстовый файл 24.txt</p>',
            answer='123',
            is_active=True,
        )
        db.session.add(task)
        db.session.flush()

        lesson = Lesson(
            student_id=role_users['student_id'],
            lesson_date=datetime.now(timezone.utc),
            duration=60,
            status='in_progress',
            topic='Тест интеграции домашних заданий',
        )
        db.session.add(lesson)
        db.session.flush()

        asg = Assignment(
            title='Домашнее задание к уроку',
            assignment_type='homework',
            lesson_id=lesson.lesson_id,
            deadline=datetime.now(timezone.utc),
            created_by_id=role_users['tutor_id'],
            is_active=True,
        )
        db.session.add(asg)
        db.session.flush()

        at = AssignmentTask(
            assignment_id=asg.assignment_id,
            task_id=task.task_id,
            order_index=0,
            max_score=1,
        )
        db.session.add(at)
        db.session.flush()

        sub = Submission(
            assignment_id=asg.assignment_id,
            student_id=role_users['student_id'],
            status='IN_PROGRESS',
        )
        db.session.add(sub)
        db.session.commit()

        lesson_id = lesson.lesson_id
        sub_id = sub.submission_id

    # 1. Tutor/Teacher perspective (triggers candidate_assignments and full_review_url resolution)
    login_as(client, role_users['tutor_id'], 'tutor')
    response_teacher = client.get(f'/lesson/{lesson_id}/room')
    assert response_teacher.status_code == 200
    html_teacher = response_teacher.get_data(as_text=True)
    assert 'lesson-os-system-bar' in html_teacher
    assert f'/submissions/{sub_id}/grade' in html_teacher

    # 2. Student perspective
    login_as(client, role_users['student_user_id'], 'student')
    response_student = client.get(f'/lesson/{lesson_id}/room')
    assert response_student.status_code == 200
    html_student = response_student.get_data(as_text=True)
    assert 'id="code-editor-textarea"' in html_student or 'student' in html_student

