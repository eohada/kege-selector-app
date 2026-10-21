"""Regression coverage for the canonical V2 individual lesson room."""

from datetime import datetime, timezone

from tests.v2.test_role_lifecycle_recovery import login_as


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

