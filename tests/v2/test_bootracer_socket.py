"""Unit & integration test for BooTracer collaborative socket synchronization."""

from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_role_lifecycle_recovery import login_as


def test_bootracer_bidirectional_sync(app, role_users):
    """Test full real-time collaborative synchronization of BooTracer between teacher and student."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http, student_http = app.test_client(), app.test_client()
    login_as(teacher_http, role_users['tutor_id'], 'tutor')
    login_as(student_http, role_users['student_user_id'], 'student')
    sockets = []

    def connect(http):
        connection = app.socketio.test_client(app, flask_test_client=http, namespace='/lesson')
        sockets.append(connection)
        assert connection.is_connected('/lesson')
        connection.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        connection.emit('whiteboard_join', {'lesson_id': lesson_id}, namespace='/lesson')
        return connection

    def event(connection, name):
        matches = [item for item in connection.get_received('/lesson') if item['name'] == name]
        assert matches, f'Missing {name}'
        return matches[-1]['args'][0]

    try:
        teacher, student = connect(teacher_http), connect(student_http)

        # 1. Teacher emits tracer_state -> Student receives it with all fields intact
        teacher.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'tracer_state',
            'step': 4,
            'playing': False,
            'speed': 2.0,
            'file_name': 'solution.py',
            'is_open': True,
            'is_detached': False,
            'breakpoints': [3, 10],
            'code': 'x = 10\ny = 20\n',
            'inputs': ['100', '200'],
        }, namespace='/lesson')

        tracer_ev = event(student, 'lesson_room_ui')
        assert tracer_ev['kind'] == 'tracer_state'
        assert tracer_ev['step'] == 4
        assert tracer_ev['playing'] is False
        assert tracer_ev['speed'] == 2.0
        assert tracer_ev['file_name'] == 'solution.py'
        assert tracer_ev['is_open'] is True
        assert tracer_ev['is_detached'] is False
        assert tracer_ev['breakpoints'] == [3, 10]
        assert tracer_ev['code'] == 'x = 10\ny = 20\n'
        assert tracer_ev['inputs'] == ['100', '200']

        # 2. Student emits tracer_state (e.g. stepping to frame 5 and playing) -> Teacher receives it
        student.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'tracer_state',
            'step': 5,
            'playing': True,
            'speed': 2.0,
            'file_name': 'solution.py',
            'is_open': True,
            'breakpoints': [3, 10, 15],
        }, namespace='/lesson')

        teacher_tracer_ev = event(teacher, 'lesson_room_ui')
        assert teacher_tracer_ev['kind'] == 'tracer_state'
        assert teacher_tracer_ev['step'] == 5
        assert teacher_tracer_ev['playing'] is True
        assert teacher_tracer_ev['breakpoints'] == [3, 10, 15]

        # 3. Floating window tracer-window layout sync
        teacher.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'window_layout',
            'window_id': 'tracer-window',
            'left': 220,
            'top': 150,
            'width': 850,
            'height': 600,
            'is_maximized': False,
        }, namespace='/lesson')

        win_layout_ev = event(student, 'lesson_room_ui')
        assert win_layout_ev['kind'] == 'window_layout'
        assert win_layout_ev['window_id'] == 'tracer-window'
        assert win_layout_ev['left'] == 220
        assert win_layout_ev['top'] == 150
        assert win_layout_ev['width'] == 850
        assert win_layout_ev['height'] == 600

        # 3b. Student emits tracer-window position -> Teacher receives it without whiteboard_error
        student.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'window_layout',
            'window_id': 'tracer-window',
            'left': 310,
            'top': 190,
            'width': 700,
            'height': 500,
            'is_maximized': False,
        }, namespace='/lesson')

        student_win_layout_ev = event(teacher, 'lesson_room_ui')
        assert student_win_layout_ev['kind'] == 'window_layout'
        assert student_win_layout_ev['window_id'] == 'tracer-window'
        assert student_win_layout_ev['left'] == 310
        assert student_win_layout_ev['top'] == 190

        # 4. Student reconnects -> gets persisted tracer_state via lesson_room_ui_state
        student.disconnect(namespace='/lesson')
        student2 = connect(student_http)
        received_events = student2.get_received('/lesson')
        ui_states = [e['args'][0] for e in received_events if e['name'] == 'lesson_room_ui_state']
        tracer_persisted = next((s for s in ui_states if s.get('kind') == 'tracer_state'), None)
        assert tracer_persisted is not None
        assert tracer_persisted['step'] == 5
        assert tracer_persisted['breakpoints'] == [3, 10, 15]

    finally:
        for connection in sockets:
            if connection.is_connected('/lesson'):
                connection.disconnect(namespace='/lesson')


def test_vfs_multi_file_and_tracer_interactive_sync(app, role_users):
    """Test full multi-file VirtualFS sync and interactive tracer input submit sync between participants."""
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_http, student_http = app.test_client(), app.test_client()
    login_as(teacher_http, role_users['tutor_id'], 'tutor')
    login_as(student_http, role_users['student_user_id'], 'student')
    sockets = []

    def connect(http):
        connection = app.socketio.test_client(app, flask_test_client=http, namespace='/lesson')
        sockets.append(connection)
        assert connection.is_connected('/lesson')
        connection.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        connection.emit('whiteboard_join', {'lesson_id': lesson_id}, namespace='/lesson')
        return connection

    def event(connection, name):
        matches = [item for item in connection.get_received('/lesson') if item['name'] == name]
        assert matches, f'Missing {name}'
        return matches[-1]['args'][0]

    try:
        teacher = connect(teacher_http)

        # 1. Teacher joins code session with full virtualFS dictionary and tabs
        teacher.emit('lesson_code_join', {
            'lesson_id': lesson_id,
            'file_name': 'main.py',
            'code': 'print("hello main")',
            'files': {
                'main.py': 'print("hello main")',
                'task_1.py': 'x = 42',
            },
            'open_tabs': ['main.py', 'task_1.py'],
        }, namespace='/lesson')

        # 2. Student connects -> receives full snapshot with both files and open tabs
        student = connect(student_http)
        student.emit('lesson_code_join', {
            'lesson_id': lesson_id,
            'file_name': 'main.py',
        }, namespace='/lesson')

        snap = event(student, 'lesson_code_snapshot')
        assert 'main.py' in snap['files']
        assert 'task_1.py' in snap['files']
        assert snap['open_tabs'] == ['main.py', 'task_1.py']

        # 3. Create new file on the fly (e.g. task_2.py)
        teacher.emit('lesson_vfs_file_create', {
            'lesson_id': lesson_id,
            'file_name': 'task_2.py',
            'code': '# task_2\n',
        }, namespace='/lesson')

        create_ev = event(student, 'lesson_vfs_file_create')
        assert create_ev['file_name'] == 'task_2.py'
        assert create_ev['code'] == '# task_2\n'
        assert 'task_2.py' in create_ev['open_tabs']

        # 4. Rename file (task_2.py -> solution.py)
        teacher.emit('lesson_vfs_file_rename', {
            'lesson_id': lesson_id,
            'old_name': 'task_2.py',
            'new_name': 'solution.py',
        }, namespace='/lesson')

        rename_ev = event(student, 'lesson_vfs_file_rename')
        assert rename_ev['old_name'] == 'task_2.py'
        assert rename_ev['new_name'] == 'solution.py'
        assert 'solution.py' in rename_ev['open_tabs']
        assert 'task_2.py' not in rename_ev['open_tabs']

        # 5. Tab switch sync
        teacher.emit('lesson_vfs_tab_switch', {
            'lesson_id': lesson_id,
            'file_name': 'solution.py',
        }, namespace='/lesson')

        tab_ev = event(student, 'lesson_vfs_tab_switch')
        assert tab_ev['file_name'] == 'solution.py'

        # 6. Delete file
        teacher.emit('lesson_vfs_file_delete', {
            'lesson_id': lesson_id,
            'file_name': 'solution.py',
        }, namespace='/lesson')

        del_ev = event(student, 'lesson_vfs_file_delete')
        assert del_ev['file_name'] == 'solution.py'
        assert 'solution.py' not in del_ev['open_tabs']

        # 7. Tracer step input submit sync
        student.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'tracer_input_submit',
            'input_val': '99',
            'inputs': ['10', '99'],
        }, namespace='/lesson')

        tracer_input_ev = event(teacher, 'lesson_room_ui')
        assert tracer_input_ev['kind'] == 'tracer_input_submit'
        assert tracer_input_ev['input_val'] == '99'
        assert tracer_input_ev['inputs'] == ['10', '99']

        # 8. Tracer window layout sync across canvas
        teacher.emit('lesson_room_ui', {
            'lesson_id': lesson_id,
            'kind': 'window_layout',
            'window_id': 'tracer-window',
            'left': 450,
            'top': 180,
            'width': 600,
            'height': 650,
        }, namespace='/lesson')

        tracer_win_ev = event(student, 'lesson_room_ui')
        assert tracer_win_ev['kind'] == 'window_layout'
        assert tracer_win_ev['window_id'] == 'tracer-window'
        assert tracer_win_ev['left'] == 450
        assert tracer_win_ev['top'] == 180

        # 9. Code cursor hide signal broadcast
        teacher.emit('lesson_code_cursor', {
            'lesson_id': lesson_id,
            'file_name': 'main.py',
            'start': -1,
            'end': -1,
            'hidden': True,
        }, namespace='/lesson')

        cursor_ev = event(student, 'lesson_code_cursor')
        assert cursor_ev['hidden'] is True
        assert cursor_ev['cursor']['start'] == -1
        assert cursor_ev['cursor']['end'] == -1

        # 10. Student whiteboard viewport sync (Visibility outline)
        student.emit('whiteboard_viewport', {
            'lesson_id': lesson_id,
            'page_id': 'page_1',
            'mode': 'board',
            'world_x': 120.5,
            'world_y': 80.0,
            'world_w': 1024.0,
            'world_h': 768.0,
        }, namespace='/lesson')

        viewport_ev = event(teacher, 'whiteboard_viewport')
        assert viewport_ev['lesson_id'] == lesson_id
        assert viewport_ev['mode'] == 'board'
        assert viewport_ev['viewport']['world_x'] == 120.5
        assert viewport_ev['viewport']['world_y'] == 80.0
        assert viewport_ev['viewport']['world_w'] == 1024.0
        assert viewport_ev['viewport']['world_h'] == 768.0

    finally:
        for connection in sockets:
            if connection.is_connected('/lesson'):
                connection.disconnect(namespace='/lesson')
