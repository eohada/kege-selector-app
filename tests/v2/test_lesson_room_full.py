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
    assert 'room-view-work' in html
    assert 'room-view-theory' in html
    assert 'room-view-board' in html
    assert 'room-view-materials' in html
    assert 'os-board-viewport' in html
    assert 'os-material-dropzone' in html
    assert 'room-task-toggle' in html
    assert 'os-focus-toggle' in html
    assert '/sandbox/lesson_room/' not in html
