import io
from datetime import datetime, timezone

from tests.v2.test_role_lifecycle_recovery import login_as


def _studio_fixture(app, role_users):
    from app import db
    from app.models import Lesson, LessonTask, Tasks

    with app.app_context():
        task = Tasks(
            task_number=1,
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
            topic='Проверка Studio',
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


def test_individual_lesson_studio_separates_teacher_and_student_controls(app, client, role_users):
    lesson_id, lesson_task_id = _studio_fixture(app, role_users)

    login_as(client, role_users['tutor_id'], 'tutor')
    teacher_room = client.get(f'/lesson/{lesson_id}/room')
    teacher_html = teacher_room.get_data(as_text=True)
    assert teacher_room.status_code == 200
    assert 'ИНДИВИДУАЛЬНЫЙ УРОК' in teacher_html
    assert 'lesson-studio-os' in teacher_html

    updated = client.post(
        f'/lesson/{lesson_id}/studio/state',
        json={
            'phase': 'practice',
            'active_task_id': lesson_task_id,
            'agenda': [],
            'teacher_private_note': 'Только для преподавателя',
            'guidance': {
                'next_step': 'Сначала сформулируй входные данные.',
                'hints': ['Не пиши код до короткого плана.'],
            },
            'phase_timers': {'preparation': 600, 'practice': 2400, 'reflection': 600},
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()['state']['phase'] == 'practice'
    assert updated.get_json()['state']['teacher_private_note'] == 'Только для преподавателя'
    assert updated.get_json()['state']['phase_timers']['practice'] == 2400

    login_as(client, role_users['student_user_id'], 'student')
    student_room = client.get(f'/lesson/{lesson_id}/room')
    student_html = student_room.get_data(as_text=True)
    assert student_room.status_code == 200
    assert '<button id="os-finish"' not in student_html
    assert 'Личная заметка преподавателя' not in student_html
    assert 'teacher-note' not in student_html

    student_state = client.get(f'/lesson/{lesson_id}/studio/state')
    assert student_state.status_code == 200
    assert 'teacher_private_note' not in student_state.get_json()['state']
    assert student_state.get_json()['state']['guidance']['next_step'] == 'Сначала сформулируй входные данные.'

    forbidden = client.post(f'/lesson/{lesson_id}/studio/state', json={'phase': 'reflection'})
    assert forbidden.status_code == 403

    signal = client.post(f'/lesson/{lesson_id}/studio/signal', json={'signal': 'need_hint'})
    assert signal.status_code == 200
    assert signal.get_json()['state']['student_signal'] == 'need_hint'
    assert 'teacher_private_note' not in signal.get_json()['state']

    notes = client.post(
        f'/lesson/{lesson_id}/studio/student-notes',
        json={'notes': 'Сначала составить алгоритм, потом писать код.'},
    )
    assert notes.status_code == 200

    checkpoint = client.post(
        f'/lesson/{lesson_id}/studio/checkpoint',
        json={'understanding': 3, 'blocker': 'Не понимаю, как начать алгоритм.'},
    )
    assert checkpoint.status_code == 200
    assert checkpoint.get_json()['state']['student_checkpoint']['understanding'] == 3

    board_stroke = client.post(
        f'/lesson/{lesson_id}/studio/board',
        json={'action': 'append', 'stroke': {
            'color': '#2563eb', 'width': 4,
            'points': [{'x': 0.1, 'y': 0.1}, {'x': 0.2, 'y': 0.2}],
        }},
    )
    assert board_stroke.status_code == 200
    assert board_stroke.get_json()['board']['strokes'][0]['author'] == 'student'

    board_clear_forbidden = client.post(f'/lesson/{lesson_id}/studio/board', json={'action': 'clear'})
    assert board_clear_forbidden.status_code == 403

    login_as(client, role_users['tutor_id'], 'tutor')
    stored = client.get(f'/lesson/{lesson_id}/studio/state')
    assert stored.status_code == 200
    assert stored.get_json()['state']['student_signal'] == 'need_hint'
    assert stored.get_json()['state']['student_checkpoint']['blocker'] == 'Не понимаю, как начать алгоритм.'
    assert stored.get_json()['state']['board']['strokes'][0]['color'] == '#2563eb'

    board_text = client.post(
        f'/lesson/{lesson_id}/studio/board',
        json={'action': 'append', 'stroke': {
            'tool': 'text', 'color': '#312e81', 'width': 4, 'text': 'Разберём шаг 1',
            'points': [{'x': 0.3, 'y': 0.3}],
        }},
    )
    assert board_text.status_code == 200
    assert board_text.get_json()['board']['strokes'][-1]['tool'] == 'text'

    timer_state = client.post(
        f'/lesson/{lesson_id}/studio/state',
        json={
            'phase': 'practice',
            'timer': {'mode': 'phase', 'seconds': 1234, 'running': False},
            'phase_timers': {'preparation': 0, 'practice': 1234, 'reflection': 600},
            'phase_durations': {'preparation': 600, 'practice': 2400, 'reflection': 600},
        },
    )
    assert timer_state.status_code == 200
    assert timer_state.get_json()['state']['phase_timers']['preparation'] == 0
    assert timer_state.get_json()['state']['timer']['seconds'] == 1234


def test_teacher_finishes_lesson_and_student_receives_readonly_outcome(app, client, role_users, monkeypatch):
    from app import db
    from app.models import Lesson

    lesson_id, _ = _studio_fixture(app, role_users)
    notifications = []
    monkeypatch.setattr(
        'app.lessons.routes.notify_student_and_parents',
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )

    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(
        f'/lesson/{lesson_id}/studio/finish',
        json={
            'outcome': {
                'completed': ['Разобран вывод данных'],
                'repeat': ['Проверять вывод'],
                'homework': 'Решить две задачи',
            },
        },
    )
    assert response.status_code == 200
    assert response.get_json()['status'] == 'completed'
    assert notifications

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson.status == 'completed'
        assert lesson.homework == 'Решить две задачи'
        assert 'Разобран вывод данных' in lesson.notes

    login_as(client, role_users['student_user_id'], 'student')
    student_outcome = client.get(f'/lesson/{lesson_id}/studio/state')
    assert student_outcome.status_code == 200
    state = student_outcome.get_json()['state']
    assert state['outcome']['published'] is True
    assert state['outcome']['homework'] == 'Решить две задачи'
    assert 'teacher_private_note' not in state

    video_room = client.get(f'/lesson/{lesson_id}/videocall/room')
    assert video_room.status_code == 200
    assert video_room.get_json()['success'] is True
    assert video_room.get_json()['room_name'] == f'lesson-{lesson_id}'

    material_delete = client.post(f'/lesson/{lesson_id}/material/delete', json={'url': '/private-file'})
    assert material_delete.status_code == 403


def test_lesson_material_upload_persists_in_configured_storage(app, client, role_users, tmp_path):
    from app import db
    from app.models import Lesson

    lesson_id, _ = _studio_fixture(app, role_users)
    app.config['LESSON_UPLOAD_ROOT'] = str(tmp_path / 'lesson-materials')
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(
        f'/lesson/{lesson_id}/upload',
        data={'file': (io.BytesIO(b'lesson material'), 'plan.txt')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['material']['name'] == 'plan.txt'

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson.materials[0]['name'] == 'plan.txt'
        stored_name = lesson.materials[0]['url'].rsplit('/', 1)[-1]
        assert (tmp_path / 'lesson-materials' / str(lesson_id) / stored_name).is_file()
