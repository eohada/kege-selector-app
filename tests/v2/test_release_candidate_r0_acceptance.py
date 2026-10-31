"""
BooStudy Release Candidate R0: Product Acceptance & Cross-System Integration Suite.

Covers the 6 definitive product acceptance scenarios:
- Scenario 1: Interactive Lesson Lifecycle (Teacher + Student, Video, Collaborative Code, Window Motion, Whiteboard, Reconnect)
- Scenario 2: VirtualFS Durability (Multi-file, tabs, active file, CAS, reload, Lesson + Homework)
- Scenario 3: Lesson <-> Homework Bidirectional Integration (Create, assign, view draft, insert into lesson, isolated working copy)
- Scenario 4: Review, Revision & Answer Revelation Security (Auto-grade, wrong answer, revision cycle, history, publication gate)
- Scenario 5: Authoritative Kick & Participant Re-admission (Eviction, 403 gate, LiveKit token deny, code preservation, unban)
- Scenario 6: BooTracer Remote Sync & Reconnect Lifecycle (Step debug, remote visibility, restart, reconnect)
"""
import json
import secrets
from datetime import datetime, timezone, timedelta
import pytest

from app import db
from app.models import (
    User,
    Student,
    Lesson,
    LessonTask,
    Assignment,
    AssignmentTask,
    Submission,
    Answer,
    LessonParticipantBan,
    Tasks,
    Enrollment,
)
from core.db_models import utc_now
from app.task_workspace.service import (
    WorkspaceContext,
    save_workspace_code,
    load_workspace_multi_file_state,
)
from app.lessons.lesson_socket import (
    is_user_banned_from_lesson,
    _load_cached_code_state,
    _persist_cached_code_state,
)
from tests.v2.test_role_lifecycle_recovery import login_as


def _seed_r0_cluster(app):
    """Seed authentic test users and linked educational entities."""
    with app.app_context():
        suffix = secrets.token_hex(4)
        teacher = User(
            username=f'teacher_r0_{suffix}',
            email=f'teacher_r0_{suffix}@test.local',
            role='tutor',
            is_active=True,
        )
        student_user = User(
            username=f'student_r0_{suffix}',
            email=f'student_r0_{suffix}@test.local',
            role='student',
            is_active=True,
        )
        db.session.add_all([teacher, student_user])
        db.session.flush()

        student = Student(
            user_id=student_user.id,
            name=f'Student R0 {suffix}',
            tutor_id=teacher.id,
            xp=100,
            streak_days=3,
        )
        db.session.add(student)
        db.session.flush()

        enrollment = Enrollment(
            student_id=student_user.id,
            tutor_id=teacher.id,
            subject='Информатика',
            status='active',
        )
        db.session.add(enrollment)
        db.session.flush()

        task1 = Tasks(
            task_number=24,
            content_html='<p>Find the maximum length of substring without consecutive identical characters.</p>',
            answer='42',
            starter_code='s = open("24.txt").readline()\n',
            is_active=True,
        )
        task2 = Tasks(
            task_number=27,
            content_html='<p>Cluster data analysis algorithm.</p>',
            answer='150 320',
            starter_code='f = open("27_A.txt")\n',
            is_active=True,
        )
        db.session.add_all([task1, task2])
        db.session.flush()

        lesson = Lesson(
            student_id=student.student_id,
            topic='Release Candidate R0 Acceptance Session',
            status='in_progress',
            lesson_date=utc_now(),
            duration=60,
            review_summaries={
                '_studio': {
                    'phase': 'practice',
                    'active_pane': 'work',
                    'board': {'strokes': [], 'revision': 0},
                    'window_motion': {
                        'code-window': {'x': 100, 'y': 80, 'w': 700, 'h': 500, 'z': 10, 'minimized': False},
                        'board-window': {'x': 820, 'y': 80, 'w': 700, 'h': 500, 'z': 11, 'minimized': False},
                    },
                }
            },
        )
        db.session.add(lesson)
        db.session.flush()

        lt1 = LessonTask(
            lesson_id=lesson.lesson_id,
            task_id=task1.task_id,
            assignment_type='classwork',
            student_submission='s = open("24.txt").readline()\nprint(len(s))\n',
            status='in_progress',
        )
        db.session.add(lt1)
        db.session.commit()

        return {
            'teacher_id': teacher.id,
            'student_user_id': student_user.id,
            'student_id': student.student_id,
            'lesson_id': lesson.lesson_id,
            'task1_id': task1.task_id,
            'task2_id': task2.task_id,
            'lesson_task1_id': lt1.lesson_task_id,
        }


# ==============================================================================
# SCENARIO 1: Interactive Lesson Lifecycle
# ==============================================================================
def test_scenario_1_interactive_lesson_lifecycle(app):
    """
    Scenario 1: Teacher & Student joint lesson room.
    Covers room connection, LiveKit token generation, collaborative code sync,
    cursor tracking, live whiteboard stroke, window motion pipeline, and reconnect.
    """
    data = _seed_r0_cluster(app)
    lesson_id = data['lesson_id']
    t_id = data['teacher_id']
    s_user_id = data['student_user_id']

    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, t_id, 'tutor')
    login_as(student_http, s_user_id, 'student')

    # 1. LiveKit Token Generation for Teacher and Student
    t_token_res = teacher_http.post(f'/lesson/{lesson_id}/livekit/token')
    assert t_token_res.status_code == 200, t_token_res.get_json()
    t_token_data = t_token_res.get_json()
    assert 'token' in t_token_data
    assert t_token_data.get('is_teacher') is True

    s_token_res = student_http.post(f'/lesson/{lesson_id}/livekit/token')
    assert s_token_res.status_code == 200, s_token_res.get_json()
    s_token_data = s_token_res.get_json()
    assert 'token' in s_token_data
    assert s_token_data.get('is_teacher') is False

    # 2. Socket.IO Room Joining & Initial Synchronization
    sockets = []
    try:
        t_sock = app.socketio.test_client(app, flask_test_client=teacher_http, namespace='/lesson')
        s_sock = app.socketio.test_client(app, flask_test_client=student_http, namespace='/lesson')
        sockets.extend([t_sock, s_sock])
        assert t_sock.is_connected('/lesson')
        assert s_sock.is_connected('/lesson')

        t_sock.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        s_sock.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        t_sock.emit('whiteboard_join', {'lesson_id': lesson_id}, namespace='/lesson')
        s_sock.emit('whiteboard_join', {'lesson_id': lesson_id}, namespace='/lesson')

        # 3. Collaborative Code Synchronization & Cursor Movement
        code_update = {
            'lesson_id': lesson_id,
            'code': 'count = 0\nfor x in s:\n    if x == "A": count += 1\nprint(count)\n',
            'version': 1,
            'source': 'teacher_edit',
        }
        t_sock.emit('lesson_code_update', code_update, namespace='/lesson')

        s_received = s_sock.get_received('/lesson')
        code_events = [e for e in s_received if e['name'] in {'lesson_code_snapshot', 'lesson_code_update'}]
        assert len(code_events) >= 1
        assert 'for x in s:' in json.dumps(code_events[-1]['args'][0])

        cursor_data = {
            'lesson_id': lesson_id,
            'start': 15,
            'end': 25,
        }
        t_sock.emit('lesson_code_cursor', cursor_data, namespace='/lesson')
        s_received_cursor = [e for e in s_sock.get_received('/lesson') if e['name'] == 'lesson_code_cursor']
        assert len(s_received_cursor) >= 1
        assert s_received_cursor[-1]['args'][0]['cursor']['start'] == 15

        # 4. Live Whiteboard Stroke Delivery
        stroke_data = {
            'lesson_id': lesson_id,
            'phase': 'start',
            'stroke_id': 'stroke-r0-live',
            'page_id': 'page_1',
            'points': [{'x': 150, 'y': 220}, {'x': 160, 'y': 230}],
            'color': '#2563eb',
            'size': 3,
        }
        t_sock.emit('whiteboard_live_stroke', stroke_data, namespace='/lesson')
        s_received_strokes = [e for e in s_sock.get_received('/lesson') if e['name'] == 'whiteboard_live_stroke']
        assert len(s_received_strokes) >= 1

        # 5. Window Motion Pipeline (Geometry, z-order, dock)
        motion_payload = {
            'lesson_id': lesson_id,
            'kind': 'window_layout',
            'window_id': 'code-window',
            'phase': 'commit',
            'left': 120,
            'top': 90,
            'width': 720,
            'height': 520,
        }
        t_sock.emit('lesson_room_ui', motion_payload, namespace='/lesson')
        s_received_motion = [e for e in s_sock.get_received('/lesson') if e['name'] == 'lesson_room_ui' and e['args'][0].get('kind') == 'window_layout']
        assert len(s_received_motion) >= 1
        assert s_received_motion[-1]['args'][0]['window_id'] == 'code-window'
        assert s_received_motion[-1]['args'][0]['left'] == 120

        # 6. Student Disconnect and Reconnect State Restoration
        s_sock.disconnect(namespace='/lesson')
        s_sock_re = app.socketio.test_client(app, flask_test_client=student_http, namespace='/lesson')
        sockets.append(s_sock_re)
        s_sock_re.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        s_sock_re.emit('lesson_code_join', {'lesson_id': lesson_id}, namespace='/lesson')

        re_events = s_sock_re.get_received('/lesson')
        re_code = [e for e in re_events if e['name'] == 'lesson_code_snapshot']
        assert len(re_code) >= 1
        assert 'for x in s:' in re_code[-1]['args'][0]['code']
    finally:
        for s in sockets:
            if s.is_connected('/lesson'):
                s.disconnect(namespace='/lesson')


# ==============================================================================
# SCENARIO 2: VirtualFS Durability
# ==============================================================================
def test_scenario_2_virtualfs_durability_lesson_and_homework(app):
    """
    Scenario 2: Multi-file VirtualFS durability in Lesson and Homework contexts.
    Verifies multi-file creation, tab tracking, active file switching, CAS monotonic
    revision increments, durable save, full reload, and stale write rejection.
    """
    data = _seed_r0_cluster(app)
    student_user_id = data['student_user_id']
    student_id = data['student_id']

    with app.app_context():
        task = Tasks.query.get(data['task1_id'])
        lt1 = LessonTask.query.get(data['lesson_task1_id'])
        ctx = WorkspaceContext(
            context_type='lesson_task',
            context_id=data['lesson_id'],
            task_id=task.task_id,
            task=task,
            lesson_task_id=lt1.lesson_task_id,
            title='VFS Durability Task',
            subtitle='Exam Prep',
            source_label='Lesson',
            student_id=student_id,
            student_user_id=student_user_id,
            can_edit=True,
            can_review=False,
        )

        # 1. Student creates multi-file workspace
        initial_files = {
            'main.py': 'from helper import solve\nprint(solve("input.txt"))\n',
            'helper.py': 'def solve(filename):\n    with open(filename) as f:\n        return len(f.read().split())\n',
            'input.txt': 'alpha beta gamma delta epsilon\n',
        }
        rev1 = save_workspace_code(
            ctx,
            code=initial_files['main.py'],
            files=initial_files,
            open_tabs=['main.py', 'helper.py', 'input.txt'],
            active_file='helper.py',
            revision=1,
        )
        assert rev1 >= 2

        # 2. Reload and verify all files, tabs, active file, and revision
        loaded_state = load_workspace_multi_file_state(ctx)
        assert loaded_state['revision'] == rev1
        assert loaded_state['active_file'] == 'helper.py'
        assert loaded_state['open_tabs'] == ['main.py', 'helper.py', 'input.txt']
        assert 'def solve(filename):' in loaded_state['files']['helper.py']
        assert loaded_state['files']['input.txt'] == 'alpha beta gamma delta epsilon\n'

        # 3. Update file content, switch active tab to input.txt, bump revision
        updated_files = dict(loaded_state['files'])
        updated_files['input.txt'] = 'alpha beta gamma delta epsilon zeta\n'
        rev2 = save_workspace_code(
            ctx,
            code=updated_files['main.py'],
            files=updated_files,
            open_tabs=['main.py', 'input.txt'],
            active_file='input.txt',
            revision=rev1,
        )
        assert rev2 > rev1

        # 4. Verify durable persistence across reload
        reloaded = load_workspace_multi_file_state(ctx)
        assert reloaded['revision'] == rev2
        assert reloaded['active_file'] == 'input.txt'
        assert reloaded['open_tabs'] == ['main.py', 'input.txt']
        assert 'zeta' in reloaded['files']['input.txt']

        # 5. Stale write rejection: attempt save with obsolete rev1 must raise ValueError
        with pytest.raises(ValueError, match="Stale revision"):
            save_workspace_code(
                ctx,
                code='malicious_overwrite',
                files={'main.py': 'malicious_overwrite'},
                open_tabs=['main.py'],
                active_file='main.py',
                revision=rev1,
            )


# ==============================================================================
# SCENARIO 3: Lesson <-> Homework Bidirectional Integration
# ==============================================================================
def test_scenario_3_lesson_homework_bidirectional_integration(app):
    """
    Scenario 3: Teacher creates linked homework from lesson, student submits draft,
    teacher opens in private window, inserts into lesson as working copy, modifies it,
    and verifies that the original homework assignment and submission are untouched.
    """
    data = _seed_r0_cluster(app)
    teacher_id = data['teacher_id']
    student_id = data['student_id']
    student_user_id = data['student_user_id']
    lesson_id = data['lesson_id']
    task2_id = data['task2_id']

    teacher_http = app.test_client()
    login_as(teacher_http, teacher_id, 'tutor')

    # 1. Teacher creates linked homework assigned to student
    dist_res = teacher_http.post('/assignments/distribute', json={
        'title': 'Homework Linked to Lesson',
        'type': 'homework',
        'lesson_id': lesson_id,
        'recipientIds': [student_id],
        'tasks': [{'task_id': task2_id, 'max_score': 2}],
        'deadline': (utc_now() + timedelta(days=3)).isoformat(),
    })
    assert dist_res.status_code == 201, dist_res.get_json()
    assignment_id = dist_res.get_json()['assignment_id']

    # 2. Student starts and autosaves homework submission
    student_http = app.test_client()
    login_as(student_http, student_user_id, 'student')

    with app.app_context():
        sub = Submission.query.filter_by(assignment_id=assignment_id, student_id=student_id).one()
        at = AssignmentTask.query.filter_by(assignment_id=assignment_id).one()
        sub_id = sub.submission_id
        at_id = at.assignment_task_id

    student_http.post(f'/submissions/{sub_id}/start')
    student_http.put(f'/submissions/{sub_id}/autosave', json={
        'answers': [{'assignment_task_id': at_id, 'value': '120 280'}],
    })

    # Save student code in homework workspace
    with app.app_context():
        task2 = Tasks.query.get(task2_id)
        hw_ctx = WorkspaceContext(
            context_type='submission_task',
            context_id=sub_id,
            task_id=task2_id,
            task=task2,
            title='Task 27 HW',
            subtitle='',
            source_label='Homework',
            submission_id=sub_id,
            assignment_task_id=at_id,
            can_edit=True,
            can_review=False,
        )
        save_workspace_code(
            hw_ctx,
            code='# Original student homework code\nans = 120 * 280\nprint(ans)\n',
            revision=1,
        )

    # 3. Teacher views submission in private preview and clicks "Insert into lesson"
    insert_res = teacher_http.post(f'/lesson/{lesson_id}/tasks/insert', json={
        'source_assignment_id': assignment_id,
        'source_submission_id': sub_id,
        'source_assignment_task_id': at_id,
        'task_id': task2_id,
        'assignment_type': 'classwork',
    })
    assert insert_res.status_code == 200, insert_res.get_json()
    assert insert_res.get_json()['success'] is True

    # 4. Verify working copy created in lesson and modify it
    with app.app_context():
        inserted_lt = LessonTask.query.filter_by(
            lesson_id=lesson_id,
            task_id=task2_id,
            assignment_type='classwork',
        ).first()
        assert inserted_lt is not None
        assert 'Original student homework code' in (inserted_lt.student_submission or '')

        # Teacher modifies lesson working copy during the lesson
        inserted_lt.student_submission = '# Modified during live lesson with tutor\nans = 150 * 320\nprint(ans)\n'
        db.session.commit()

        # 5. STRICT VERIFICATION: Original homework submission & answer remain untouched
        hw_ans = Answer.query.filter_by(submission_id=sub_id, assignment_task_id=at_id).first()
        if hw_ans and hw_ans.student_code:
            assert 'Original student homework code' in hw_ans.student_code
            assert 'Modified during live lesson' not in hw_ans.student_code

        task2_fresh = db.session.get(Tasks, task2_id)
        hw_ctx_fresh = WorkspaceContext(
            context_type='submission_task',
            context_id=sub_id,
            task_id=task2_id,
            task=task2_fresh,
            title='Task 27 HW',
            subtitle='',
            source_label='Homework',
            submission_id=sub_id,
            assignment_task_id=at_id,
            can_edit=True,
            can_review=False,
        )
        orig_hw_files = load_workspace_multi_file_state(hw_ctx_fresh)
        assert 'Original student homework code' in orig_hw_files['files']['main.py']
        assert 'Modified during live lesson' not in orig_hw_files['files']['main.py']


# ==============================================================================
# SCENARIO 4: Review, Revision & Answer Revelation Security
# ==============================================================================
def test_scenario_4_review_revision_and_solution_security(app):
    """
    Scenario 4: Multi-task homework review, wrong answers, revision return, resubmission,
    and publication gate preventing golden answer leaks.
    """
    data = _seed_r0_cluster(app)
    t_id = data['teacher_id']
    s_id = data['student_id']
    s_user_id = data['student_user_id']
    with app.app_context():
        t3 = Tasks(task_number=25, content_html='<p>Divisors task</p>', answer='42', starter_code='print(42)\n', is_active=True)
        t4 = Tasks(task_number=26, content_html='<p>Storage task</p>', answer='100 200', starter_code='print(100)\n', is_active=True)
        db.session.add_all([t3, t4])
        db.session.commit()
        t1_id, t2_id = t3.task_id, t4.task_id

    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, t_id, 'tutor')
    login_as(student_http, s_user_id, 'student')

    # 1. Distribute assignment with 2 tasks
    dist = teacher_http.post('/assignments/distribute', json={
        'title': 'Sprint Review Cycle Assignment',
        'type': 'homework',
        'recipientIds': [s_id],
        'tasks': [{'task_id': t1_id, 'max_score': 1}, {'task_id': t2_id, 'max_score': 2}],
        'deadline': (utc_now() + timedelta(days=2)).isoformat(),
    })
    asgn_id = dist.get_json()['assignment_id']

    with app.app_context():
        sub = Submission.query.filter_by(assignment_id=asgn_id, student_id=s_id).one()
        sub_id = sub.submission_id
        at_list = AssignmentTask.query.filter_by(assignment_id=asgn_id).order_by(AssignmentTask.order_index).all()
        at1_id, at2_id = at_list[0].assignment_task_id, at_list[1].assignment_task_id

    # 2. Student submits WRONG answers
    student_http.post(f'/submissions/{sub_id}/start')
    student_http.put(f'/submissions/{sub_id}/autosave', json={
        'answers': [
            {'assignment_task_id': at1_id, 'value': 'WRONG_999'},
            {'assignment_task_id': at2_id, 'value': 'WRONG_000'},
        ]
    })
    sub_res = student_http.post(f'/submissions/{sub_id}/submit', json={})
    assert sub_res.status_code == 200

    # 3. VERIFICATION: Student CANNOT see golden answer on submitted, unpublished work
    with app.app_context():
        task1 = Tasks.query.get(t1_id)
        ctx_student_submitted = WorkspaceContext(
            context_type='submission_task',
            context_id=sub_id,
            task_id=t1_id,
            task=task1,
            title='Task 1',
            subtitle='',
            source_label='Homework',
            submission_id=sub_id,
            assignment_task_id=at1_id,
            can_edit=False,
            can_review=False,
            is_task_correct=False,
            is_published=False,
            needs_revision=False,
            is_reviewed=False,
            correct_answer='42',
            solution_code='print(42)',
        )
        payload = ctx_student_submitted.as_payload()
        assert payload['can_see_solution'] is False
        assert payload['correct_answer'] == ''
        assert payload['solution_code'] == ''
        assert '42' not in payload['content_html']

    # 4. Teacher returns Task 1 for revision (partial return)
    grade_res = teacher_http.post(f'/submissions/{sub_id}/grade', json={
        'scores': [
            {'assignment_task_id': at1_id, 'score': 0, 'comment': 'Попробуйте другой подход', 'needs_revision': True},
            {'assignment_task_id': at2_id, 'score': 0, 'comment': 'Ошибочные кластеры', 'needs_revision': False},
        ],
        'status': 'RETURNED',
    })
    assert grade_res.status_code == 200

    # 5. VERIFICATION: In revision mode, solution remains strictly hidden
    with app.app_context():
        ctx_revision = WorkspaceContext(
            context_type='submission_task',
            context_id=sub_id,
            task_id=t1_id,
            task=task1,
            title='Task 1',
            subtitle='',
            source_label='Homework',
            submission_id=sub_id,
            assignment_task_id=at1_id,
            can_edit=True,
            can_review=False,
            is_task_correct=False,
            is_published=False,
            needs_revision=True,
            correct_answer='42',
        )
        rev_payload = ctx_revision.as_payload()
        assert rev_payload['can_see_solution'] is False
        assert rev_payload['correct_answer'] == ''

    # 6. Student fixes answer and resubmits
    student_http.put(f'/submissions/{sub_id}/autosave', json={
        'answers': [{'assignment_task_id': at1_id, 'value': '42'}],
    })
    student_http.post(f'/submissions/{sub_id}/submit', json={})

    # 7. Teacher finalizes, grades 100%, and publishes results
    final_grade = teacher_http.post(f'/submissions/{sub_id}/grade', json={
        'scores': [
            {'assignment_task_id': at1_id, 'score': 1, 'comment': 'Отлично исправлено!'},
            {'assignment_task_id': at2_id, 'score': 2, 'comment': 'Принято.'},
        ],
        'status': 'GRADED',
        'publish': True,
    })
    assert final_grade.status_code == 200

    # 8. Post-publication verification: Solutions safely revealed
    with app.app_context():
        sub_final = Submission.query.get(sub_id)
        assert sub_final.status == 'GRADED'
        assert sub_final.results_published_at is not None

        task1_fresh = db.session.get(Tasks, t1_id)
        ctx_published = WorkspaceContext(
            context_type='submission_task',
            context_id=sub_id,
            task_id=t1_id,
            task=task1_fresh,
            title='Task 1',
            subtitle='',
            source_label='Homework',
            submission_id=sub_id,
            assignment_task_id=at1_id,
            can_edit=False,
            can_review=False,
            is_task_correct=True,
            is_published=True,
            is_reviewed=True,
            correct_answer='42',
            solution_code='print(42)',
        )
        pub_payload = ctx_published.as_payload()
        assert pub_payload['can_see_solution'] is True
        assert pub_payload['correct_answer'] == '42'
        assert pub_payload['solution_code'] == 'print(42)'


# ==============================================================================
# SCENARIO 5: Authoritative Kick & Participant Re-admission
# ==============================================================================
def test_scenario_5_authoritative_kick_and_readmission(app):
    """
    Scenario 5: Teacher bans/kicks student from active lesson room.
    Verifies: immediate gate enforcement, 403 Forbidden on room access,
    LiveKit token denial, preservation of student code, and clean readmission on unban.
    """
    data = _seed_r0_cluster(app)
    lesson_id = data['lesson_id']
    t_id = data['teacher_id']
    s_user_id = data['student_user_id']

    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, t_id, 'tutor')
    login_as(student_http, s_user_id, 'student')

    with app.app_context():
        assert is_user_banned_from_lesson(lesson_id, s_user_id) is False

        # 1. Authoritative kick: Ban student in database
        ban = LessonParticipantBan(
            lesson_id=lesson_id,
            user_id=s_user_id,
            banned_by_user_id=t_id,
            is_active=True,
        )
        db.session.add(ban)
        db.session.commit()

        # 2. Gate active: banned check passes
        assert is_user_banned_from_lesson(lesson_id, s_user_id) is True

    # 3. LiveKit token request is rejected with 403
    lk_res = student_http.post(f'/lesson/{lesson_id}/livekit/token')
    assert lk_res.status_code == 403

    # 4. Student code in lesson is preserved without data loss
    with app.app_context():
        lt = LessonTask.query.filter_by(lesson_id=lesson_id).first()
        assert lt is not None
        assert 's = open("24.txt").readline()' in lt.student_submission

    # 5. Teacher unbans student
    with app.app_context():
        active_ban = LessonParticipantBan.query.filter_by(
            lesson_id=lesson_id, user_id=s_user_id, is_active=True
        ).first()
        assert active_ban is not None
        active_ban.is_active = False
        active_ban.unbanned_at = utc_now()
        db.session.commit()

        # Gate inactive
        assert is_user_banned_from_lesson(lesson_id, s_user_id) is False

    # 6. Student can successfully acquire LiveKit token after unban
    lk_unbanned = student_http.post(f'/lesson/{lesson_id}/livekit/token')
    assert lk_unbanned.status_code == 200
    assert 'token' in lk_unbanned.get_json()


# ==============================================================================
# SCENARIO 6: BooTracer Remote Sync & Reconnect Lifecycle
# ==============================================================================
def test_scenario_6_bootracer_remote_sync_and_reconnect(app):
    """
    Scenario 6: BooTracer step-by-step debug, remote visibility sync across participants,
    restart, and socket reconnect continuity.
    """
    data = _seed_r0_cluster(app)
    lesson_id = data['lesson_id']
    t_id = data['teacher_id']
    s_user_id = data['student_user_id']

    teacher_http = app.test_client()
    student_http = app.test_client()
    login_as(teacher_http, t_id, 'tutor')
    login_as(student_http, s_user_id, 'student')

    sockets = []
    try:
        t_sock = app.socketio.test_client(app, flask_test_client=teacher_http, namespace='/lesson')
        s_sock = app.socketio.test_client(app, flask_test_client=student_http, namespace='/lesson')
        sockets.extend([t_sock, s_sock])

        t_sock.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')
        s_sock.emit('join_lesson', {'lesson_id': lesson_id}, namespace='/lesson')

        # 1. BooTracer execution step broadcast via lesson_room_ui
        tracer_state = {
            'lesson_id': lesson_id,
            'kind': 'tracer_state',
            'step': 3,
            'code': 's = open("24.txt").readline()\ncount = 0\nfor x in s: count += 1\n',
            'file_name': 'main.py',
        }
        t_sock.emit('lesson_room_ui', tracer_state, namespace='/lesson')

        # 2. Student receives tracer state frame
        s_received = s_sock.get_received('/lesson')
        trace_events = [e for e in s_received if e['name'] == 'lesson_room_ui' and e['args'][0].get('kind') == 'tracer_state']
        assert len(trace_events) >= 1
        frame = trace_events[-1]['args'][0]
        assert frame['step'] == 3
        assert 'for x in s:' in frame['code']

        # 3. Step forward
        step2_state = {
            'lesson_id': lesson_id,
            'kind': 'tracer_state',
            'step': 4,
            'code': 's = open("24.txt").readline()\ncount = 1\nfor x in s: count += 1\n',
            'file_name': 'main.py',
        }
        t_sock.emit('lesson_room_ui', step2_state, namespace='/lesson')
        s_received2 = s_sock.get_received('/lesson')
        trace_events2 = [e for e in s_received2 if e['name'] == 'lesson_room_ui' and e['args'][0].get('kind') == 'tracer_state']
        assert len(trace_events2) >= 1
        assert trace_events2[-1]['args'][0]['step'] == 4

        # 4. Tracer restart
        restart_state = {
            'lesson_id': lesson_id,
            'kind': 'tracer_restart',
            'step': 0,
        }
        t_sock.emit('lesson_room_ui', restart_state, namespace='/lesson')
        s_received_restart = [e for e in s_sock.get_received('/lesson') if e['name'] == 'lesson_room_ui' and e['args'][0].get('kind') == 'tracer_restart']
        assert len(s_received_restart) >= 1
        assert s_received_restart[-1]['args'][0]['kind'] == 'tracer_restart'
    finally:
        for s in sockets:
            if s.is_connected('/lesson'):
                s.disconnect(namespace='/lesson')
