import io
from datetime import datetime, timezone
from pathlib import Path

from tests.v2.test_role_lifecycle_recovery import login_as


def _studio_fixture(app, role_users, *, task_number=1):
    from app import db
    from app.models import Lesson, LessonTask, Tasks

    with app.app_context():
        task = Tasks(
            task_number=task_number,
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
    assert 'room-v3-page-teacher' in teacher_html

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

    follow_state = client.post(
        f'/lesson/{lesson_id}/studio/state',
        json={'phase': 'practice', 'active_pane': 'board', 'follow_student': True},
    )
    assert follow_state.status_code == 200
    assert follow_state.get_json()['state']['active_pane'] == 'board'
    assert follow_state.get_json()['state']['follow_student'] is True

    login_as(client, role_users['student_user_id'], 'student')
    student_room = client.get(f'/lesson/{lesson_id}/room')
    student_html = student_room.get_data(as_text=True)
    assert student_room.status_code == 200
    assert 'room-v3-page-student' in student_html
    assert 'room-v3-page-teacher' not in student_html
    assert '<button id="os-finish"' not in student_html
    assert 'Личная заметка преподавателя' not in student_html
    assert 'teacher-note' not in student_html
    assert 'room-student-signal-current' in student_html
    assert 'aria-pressed="false"' in student_html
    assert 'room-student-homework' in student_html

    student_state = client.get(f'/lesson/{lesson_id}/studio/state')
    assert student_state.status_code == 200
    assert 'teacher_private_note' not in student_state.get_json()['state']
    assert student_state.get_json()['state']['guidance']['next_step'] == 'Сначала сформулируй входные данные.'

    forbidden = client.post(f'/lesson/{lesson_id}/studio/state', json={'phase': 'reflection'})
    assert forbidden.status_code == 403

    for selected_signal in ('need_hint', 'need_pause', 'ready'):
        signal = client.post(f'/lesson/{lesson_id}/studio/signal', json={'signal': selected_signal})
        assert signal.status_code == 200
        assert signal.get_json()['state']['student_signal'] == selected_signal
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
    assert board_stroke.get_json()['board']['strokes'][0]['coordinate_space'] == 'relative'

    board_clear_forbidden = client.post(f'/lesson/{lesson_id}/studio/board', json={'action': 'clear'})
    assert board_clear_forbidden.status_code == 403

    login_as(client, role_users['tutor_id'], 'tutor')
    stored = client.get(f'/lesson/{lesson_id}/studio/state')
    assert stored.status_code == 200
    assert stored.get_json()['state']['student_signal'] == 'ready'
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

    board_eraser = client.post(
        f'/lesson/{lesson_id}/studio/board',
        json={'action': 'append', 'stroke': {
            'tool': 'eraser', 'width': 18, 'coordinate_space': 'canvas',
            'points': [{'x': 12, 'y': 12}],
        }},
    )
    assert board_eraser.status_code == 200
    assert board_eraser.get_json()['board']['strokes'][-1]['tool'] == 'eraser'
    assert board_eraser.get_json()['board']['strokes'][-1]['coordinate_space'] == 'canvas'

    long_eraser = client.post(
        f'/lesson/{lesson_id}/studio/board',
        json={'action': 'append', 'stroke': {
            'tool': 'eraser', 'width': 18, 'coordinate_space': 'canvas',
            'points': [{'x': point, 'y': point} for point in range(700)],
        }},
    )
    assert long_eraser.status_code == 200
    assert len(long_eraser.get_json()['board']['strokes'][-1]['points']) == 700

    batch_eraser = client.post(
        f'/lesson/{lesson_id}/studio/board',
        json={'action': 'append_batch', 'strokes': [
            {'tool': 'eraser', 'width': 18, 'coordinate_space': 'canvas', 'points': [{'x': 700, 'y': 700}]},
            {'tool': 'eraser', 'width': 18, 'coordinate_space': 'canvas', 'points': [{'x': 710, 'y': 710}]},
        ]},
    )
    assert batch_eraser.status_code == 200
    assert [stroke['author'] for stroke in batch_eraser.get_json()['board']['strokes'][-2:]] == ['teacher', 'teacher']

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


def test_lesson_studio_workspace_run_executes_selected_task_code(app, client, role_users):
    _lesson_id, lesson_task_id = _studio_fixture(app, role_users)
    login_as(client, role_users['student_user_id'], 'student')

    response = client.post(
        '/task-workspace/api/run',
        json={
            'context_type': 'lesson_task',
            'context_id': lesson_task_id,
            'code': 'print(42)',
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['stdout'].strip() == '42'


def test_lesson_studio_keeps_sidebar_column_and_renders_selected_student_signal():
    root = Path(__file__).resolve().parents[2]
    css = (root / 'static' / 'lesson-studio-os.css').read_text(encoding='utf-8')
    script = (root / 'static' / 'lesson-studio-os.js').read_text(encoding='utf-8')
    template = (root / 'templates' / 'sandbox' / 'lesson_room.html').read_text(encoding='utf-8')

    assert '.room-canvas.tasks-collapsed{grid-template-columns:minmax(0,1fr) var(--room-right-width)}' in css
    assert '.room-canvas.panel-collapsed.tasks-collapsed{grid-template-columns:minmax(0,1fr)}' in css
    assert '--room-right-width:320px' in css
    assert "button.classList.toggle('is-selected',selected)" in script
    assert "button.setAttribute('aria-pressed',String(selected))" in script
    assert 'room-panel-hero' in template
    assert 'room-panel-accordion' in template
    assert 'data-student-signal="need_hint"' in template
    assert 'role="toolbar" aria-label="Инструменты доски"' in template
    assert 'data-board-context="pen line rectangle ellipse"' in template
    assert 'Бесконечное полотно' not in template
    assert "e.preventDefault();e.stopPropagation();" in script
    assert "control.hidden=!control.dataset.boardContext.split(' ').includes(board.tool)" in script
    assert 'BOARD_STROKE_CHUNK_SIZE=1000' in script
    assert "action:'append_batch'" in script


def test_workspace_switch_leaves_previous_task_room(app, client, role_users):
    from app import db
    from app.models import LessonTask, Tasks
    from app.task_workspace import socket as workspace_socket

    lesson_id, first_task_id = _studio_fixture(app, role_users)
    with app.app_context():
        second_task = Tasks(
            task_number=2,
            content_html='<p>Вторая задача.</p>',
            answer='7',
            starter_code='print(7)',
            is_active=True,
        )
        db.session.add(second_task)
        db.session.flush()
        lesson_task = LessonTask(
            lesson_id=lesson_id,
            task_id=second_task.task_id,
            assignment_type='classwork',
            status='pending',
        )
        db.session.add(lesson_task)
        db.session.commit()
        second_task_id = lesson_task.lesson_task_id

    login_as(client, role_users['student_user_id'], 'student')
    live_client = app.socketio.test_client(app, namespace='/task-workspace', flask_test_client=client)
    assert live_client.is_connected('/task-workspace')

    first_context = {'context_type': 'lesson_task', 'context_id': first_task_id, 'client_id': 'room-v3-switch'}
    second_context = {'context_type': 'lesson_task', 'context_id': second_task_id, 'client_id': 'room-v3-switch'}
    first_room = workspace_socket._room_key('lesson_task', first_task_id, None)
    second_room = workspace_socket._room_key('lesson_task', second_task_id, None)

    live_client.emit('join_workspace', first_context, namespace='/task-workspace')
    assert workspace_socket._workspace_rooms.get(first_room)

    live_client.emit('join_workspace', second_context, namespace='/task-workspace')
    assert not workspace_socket._workspace_rooms.get(first_room)
    assert workspace_socket._workspace_rooms.get(second_room)

    live_client.disconnect(namespace='/task-workspace')
    assert not workspace_socket._workspace_rooms.get(second_room)


def test_lesson_studio_state_broadcasts_to_the_joined_student(app, role_users):
    lesson_id, _ = _studio_fixture(app, role_users)
    teacher_client = app.test_client()
    student_client = app.test_client()
    login_as(teacher_client, role_users['tutor_id'], 'tutor')
    login_as(student_client, role_users['student_user_id'], 'student')

    teacher_socket = app.socketio.test_client(app, namespace='/lesson', flask_test_client=teacher_client)
    student_socket = app.socketio.test_client(app, namespace='/lesson', flask_test_client=student_client)
    assert teacher_socket.is_connected('/lesson')
    assert student_socket.is_connected('/lesson')
    teacher_socket.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
    student_socket.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
    teacher_socket.get_received('/lesson')
    student_socket.get_received('/lesson')

    updated = teacher_client.post(
        f'/lesson/{lesson_id}/studio/state',
        json={
            'phase': 'practice',
            'active_pane': 'board',
            'follow_student': True,
            'teacher_private_note': 'Не отправлять ученику',
        },
    )
    assert updated.status_code == 200

    events = student_socket.get_received('/lesson')
    update = next(event for event in events if event['name'] == 'lesson_studio_updated')
    state = update['args'][0]['state']
    assert state['phase'] == 'practice'
    assert state['active_pane'] == 'board'
    assert state['follow_student'] is True
    assert 'teacher_private_note' not in state

    teacher_socket.disconnect(namespace='/lesson')
    student_socket.disconnect(namespace='/lesson')


def test_lesson_studio_laser_pointer_reaches_the_joined_student(app, role_users):
    lesson_id, _ = _studio_fixture(app, role_users)
    teacher_client = app.test_client()
    student_client = app.test_client()
    login_as(teacher_client, role_users['tutor_id'], 'tutor')
    login_as(student_client, role_users['student_user_id'], 'student')

    teacher_socket = app.socketio.test_client(app, namespace='/lesson', flask_test_client=teacher_client)
    student_socket = app.socketio.test_client(app, namespace='/lesson', flask_test_client=student_client)
    teacher_socket.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
    student_socket.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
    teacher_socket.get_received('/lesson')
    student_socket.get_received('/lesson')

    sent = teacher_client.post(
        f'/lesson/{lesson_id}/studio/pointer',
        json={'kind': 'laser', 'x': 0.42, 'y': 0.58},
    )
    assert sent.status_code == 200
    events = student_socket.get_received('/lesson')
    pointer_event = next(event for event in events if event['name'] == 'lesson_studio_pointer')
    pointer = pointer_event['args'][0]['pointer']
    assert pointer == {
        'kind': 'laser',
        'x': 0.42,
        'y': 0.58,
        'author': 'teacher',
        'name': 'v2_tutor',
    }

    teacher_socket.disconnect(namespace='/lesson')
    student_socket.disconnect(namespace='/lesson')


def test_lesson_socket_switches_from_previous_lesson_room(app, client, role_users):
    from app.lessons import lesson_socket

    first_lesson_id, _ = _studio_fixture(app, role_users, task_number=31)
    second_lesson_id, _ = _studio_fixture(app, role_users, task_number=32)
    login_as(client, role_users['student_user_id'], 'student')
    live_client = app.socketio.test_client(app, namespace='/lesson', flask_test_client=client)

    live_client.emit('join_lesson', {'lesson_id': first_lesson_id}, namespace='/lesson')
    assert role_users['student_user_id'] in lesson_socket._lesson_presence[first_lesson_id]
    live_client.emit('join_lesson', {'lesson_id': second_lesson_id}, namespace='/lesson')

    assert role_users['student_user_id'] not in lesson_socket._lesson_presence.get(first_lesson_id, {})
    assert role_users['student_user_id'] in lesson_socket._lesson_presence[second_lesson_id]

    live_client.disconnect(namespace='/lesson')
    assert role_users['student_user_id'] not in lesson_socket._lesson_presence.get(second_lesson_id, {})


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

    legacy_video_room = client.get(f'/lesson/{lesson_id}/videocall/room', follow_redirects=False)
    assert legacy_video_room.status_code == 302
    assert legacy_video_room.headers['Location'].endswith(f'/lesson/{lesson_id}/room')

    legacy_video_join = client.post(f'/lesson/{lesson_id}/videocall/room', follow_redirects=False)
    assert legacy_video_join.status_code == 307
    assert legacy_video_join.headers['Location'].endswith(f'/lesson/{lesson_id}/studio/daily/join')

    material_delete = client.post(f'/lesson/{lesson_id}/material/delete', json={'url': '/private-file'})
    assert material_delete.status_code == 403


def test_studio_daily_join_uses_canonical_room_and_role_token(app, client, role_users, monkeypatch):
    lesson_id, _ = _studio_fixture(app, role_users)
    calls = []

    monkeypatch.setattr(
        'app.lessons.routes.DailyService.get_or_create_room',
        lambda room_name: calls.append(('room', room_name)) or f'https://example.daily.co/{room_name}',
    )
    monkeypatch.setattr(
        'app.lessons.routes.DailyService.create_meeting_token',
        lambda room_name, user_name, is_owner: calls.append(('token', room_name, user_name, is_owner)) or 'daily-token',
    )

    login_as(client, role_users['tutor_id'], 'tutor')
    teacher_response = client.post(f'/lesson/{lesson_id}/studio/daily/join')

    assert teacher_response.status_code == 200
    assert teacher_response.get_json()['room_url'] == f'https://example.daily.co/lesson-{lesson_id}'
    assert calls[0] == ('room', f'lesson-{lesson_id}')
    assert calls[1][0] == 'token'
    assert calls[1][1] == f'lesson-{lesson_id}'
    assert calls[1][3] is True

    calls.clear()
    login_as(client, role_users['student_user_id'], 'student')
    student_response = client.post(f'/lesson/{lesson_id}/studio/daily/join')

    assert student_response.status_code == 200
    assert calls[1][3] is False


def test_studio_daily_join_reports_missing_provider_configuration(app, client, role_users, monkeypatch):
    lesson_id, _ = _studio_fixture(app, role_users)
    monkeypatch.setattr(
        'app.lessons.routes.DailyService.get_or_create_room',
        lambda room_name: (_ for _ in ()).throw(ValueError('Daily API key is not configured')),
    )
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.post(f'/lesson/{lesson_id}/studio/daily/join')

    assert response.status_code == 503
    assert response.get_json()['success'] is False
    assert 'настроен' in response.get_json()['error']


def test_workspace_rejects_demo_and_missing_context(client, role_users):
    login_as(client, role_users['student_user_id'], 'student')

    assert client.get('/task-workspace/').status_code == 400
    assert client.get('/task-workspace/?context_type=demo').status_code == 404


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
