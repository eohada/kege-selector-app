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
    assert 'id="dock-icon-code-window"' in html
    assert 'id="dock-icon-task-window"' in html
    assert 'id="dock-icon-theory-window"' in html
    assert 'id="dock-icon-terminal-window"' in html
    assert 'boostudy_lesson_os_windows_v7_' in html
    assert "(!compact && ['task-window', 'terminal-window', 'theory-window', 'lesson-info-window'].includes(id))" in html
    assert 'id="task-current-content"' in html
    assert 'id="theory-window-body"' in html
    assert 'id="room-work-mode-switcher"' not in html
    assert '/sandbox/lesson_room/' not in html
