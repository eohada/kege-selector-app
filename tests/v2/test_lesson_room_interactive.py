"""Release regression coverage for the live V2 individual lesson room."""

import io
from datetime import datetime, timezone

from tests.v2.test_role_lifecycle_recovery import login_as


def _create_lesson_context(app, role_users, *, private_note='Только для преподавателя'):
    from app import db
    from app.models import Lesson, LessonTask, Tasks

    with app.app_context():
        task = Tasks(
            task_number=7,
            content_html='<p>Проверьте рабочее поле.</p>',
            answer='42',
            starter_code='print(42)',
            is_active=True,
        )
        lesson = Lesson(
            student_id=role_users['student_id'],
            lesson_date=datetime.now(timezone.utc),
            duration=60,
            status='in_progress',
            topic='Release lesson room',
            review_summaries={
                '_studio': {
                    'phase': 'practice',
                    'active_pane': 'work',
                    'follow_student': True,
                    'timer': {'mode': 'phase', 'seconds': 900, 'running': True, 'updated_at': None},
                    'phase_timers': {'preparation': 600, 'practice': 900, 'reflection': 600},
                    'phase_durations': {'preparation': 600, 'practice': 2400, 'reflection': 600},
                    'agenda': [],
                    'teacher_private_note': private_note,
                    'guidance': {'next_step': 'Составь короткий план.', 'hints': ['Начни со входных данных.']},
                    'board': {'strokes': [], 'revision': 0},
                },
            },
        )
        db.session.add_all([task, lesson])
        db.session.flush()
        lesson_task = LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task.task_id,
            assignment_type='classwork',
            status='pending',
        )
        db.session.add(lesson_task)
        db.session.commit()
        return lesson.lesson_id, lesson_task.lesson_task_id


def test_student_room_hides_private_teacher_state_and_preserves_shared_board(app, client, role_users):
    lesson_id, _lesson_task_id = _create_lesson_context(app, role_users)
    login_as(client, role_users['student_user_id'], 'student')

    state = client.get(f'/lesson/{lesson_id}/studio/state')
    assert state.status_code == 200
    payload = state.get_json()
    assert payload['is_teacher'] is False
    assert 'teacher_private_note' not in payload['state']
    assert payload['state']['guidance']['next_step'] == 'Составь короткий план.'

    assert client.post(f'/lesson/{lesson_id}/studio/state', json={'phase': 'reflection'}).status_code == 403
    stroke = client.post(f'/lesson/{lesson_id}/studio/board', json={
        'action': 'append',
        'stroke': {
            'tool': 'line', 'color': '#2563eb', 'width': 4,
            'points': [{'x': 0.1, 'y': 0.1}, {'x': 0.2, 'y': 0.2}],
        },
    })
    assert stroke.status_code == 200
    assert stroke.get_json()['board']['strokes'][-1]['author'] == 'student'
    assert client.post(f'/lesson/{lesson_id}/studio/board', json={'action': 'clear'}).status_code == 403

    signal = client.post(f'/lesson/{lesson_id}/studio/signal', json={'signal': 'need_hint'})
    assert signal.status_code == 200
    assert 'teacher_private_note' not in signal.get_json()['state']


def test_tutor_room_can_manage_materials_and_task_comments(app, client, role_users, tmp_path):
    lesson_id, lesson_task_id = _create_lesson_context(app, role_users)
    app.config['LESSON_UPLOAD_ROOT'] = str(tmp_path / 'lesson-materials')
    login_as(client, role_users['tutor_id'], 'tutor')

    state = client.get(f'/lesson/{lesson_id}/studio/state')
    assert state.status_code == 200
    assert state.get_json()['is_teacher'] is True
    assert state.get_json()['state']['teacher_private_note'] == 'Только для преподавателя'

    rejected = client.post(
        f'/lesson/{lesson_id}/studio/board/image',
        data={'file': (io.BytesIO(b'not-a-real-png-but-an-upload-fixture'), 'board.png')},
        content_type='multipart/form-data',
    )
    assert rejected.status_code == 400

    uploaded = client.post(
        f'/lesson/{lesson_id}/studio/board/image',
        data={'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'fixture'), 'board.png')},
        content_type='multipart/form-data',
    )
    assert uploaded.status_code == 200, uploaded.get_json()
    assert uploaded.get_json()['url'].startswith(f'/files/lessons/{lesson_id}/')

    created = client.post(
        f'/lesson/{lesson_id}/task/{lesson_task_id}/teacher-comment/add',
        json={'body': 'Проверь границы цикла.'},
    )
    assert created.status_code == 200
    comment_id = created.get_json()['comment']['comment_id']
    updated = client.post(f'/lesson/teacher-comment/{comment_id}/update', json={'body': 'Проверь границы и результат.'})
    assert updated.status_code == 200
    assert updated.get_json()['body'] == 'Проверь границы и результат.'
    assert client.post(f'/lesson/teacher-comment/{comment_id}/delete').status_code == 200


def test_unrelated_student_cannot_open_lesson_room(app, client, role_users):
    from app import db
    from app.models import Student, User

    lesson_id, _lesson_task_id = _create_lesson_context(app, role_users)
    with app.app_context():
        outsider = User(username='lesson_room_outsider', email='lesson_room_outsider@example.test', role='student', is_active=True)
        db.session.add(outsider)
        db.session.flush()
        db.session.add(Student(name='Lesson room outsider', user_id=outsider.id, is_active=True))
        db.session.commit()
        outsider_id = outsider.id

    login_as(client, outsider_id, 'student')
    assert client.get(f'/lesson/{lesson_id}/room').status_code == 403
