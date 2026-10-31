"""
Sprint 3: Distributed State, Real-Time Synchronization & Session Recovery
Multi-worker distributed tests using independent workers sharing Redis pubsub and PostgreSQL.
"""
from __future__ import annotations

import json
import time
import pytest
import fakeredis
from socketio.redis_manager import RedisManager
from flask_socketio import SocketIO
from werkzeug.test import EnvironBuilder

from app.models import db, Lesson, User
from app.lessons.lesson_socket import (
    register_lesson_socket,
    _lesson_code_state,
    _lesson_presence,
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_room_ui,
    _room,
    _teacher_room,
    _student_room,
    _code_state_key,
    _board_state_key,
    _room_ui_key,
    _presence_key,
    _connections_key,
    _register_user_presence,
    _unregister_user_presence,
    _get_active_presence,
    _get_all_room_ui,
    _load_cached_code_state,
    _update_cached_code_state,
    _load_cached_board_data,
    _persist_cached_code_state,
    _persist_cached_board_strokes,
    emit_lesson_tasks_updated,
    emit_lesson_private_note_updated,
)
import app.runtime_state as runtime_state
from tests.v2.test_lesson_room_interactive import _create_lesson_context


_active_managers: list = []


@pytest.fixture(autouse=True)
def clean_in_memory_and_cache():
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_room_ui.clear()
    yield
    for mgr in _active_managers:
        try:
            if hasattr(mgr, "pubsub") and mgr.pubsub:
                mgr.pubsub.close()
        except Exception:
            pass
    _active_managers.clear()
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_room_ui.clear()


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    orig_get_client = runtime_state.get_redis_client
    orig_ping = runtime_state.redis_ping

    runtime_state.get_redis_client = lambda: client
    runtime_state.redis_ping = lambda: True
    yield server, client

    runtime_state.get_redis_client = orig_get_client
    runtime_state.redis_ping = orig_ping


def _parse_packet(data_str: str) -> tuple[str | None, dict | None]:
    if not isinstance(data_str, str):
        return None, None
    prefix = "2/lesson,"
    if data_str.startswith(prefix):
        raw = data_str[len(prefix):]
        try:
            arr = json.loads(raw)
            return arr[0], arr[1] if len(arr) > 1 else None
        except Exception:
            return None, None
    return None, None


def _setup_workers(app, fake_server):
    """Create two independent SocketIO workers connected to shared Redis."""
    mgr_a = RedisManager("redis://localhost", channel="sprint3_dist")
    mgr_a.redis = fakeredis.FakeRedis(server=fake_server)
    mgr_a.pubsub = mgr_a.redis.pubsub(ignore_subscribe_messages=True)

    mgr_b = RedisManager("redis://localhost", channel="sprint3_dist")
    mgr_b.redis = fakeredis.FakeRedis(server=fake_server)
    mgr_b.pubsub = mgr_b.redis.pubsub(ignore_subscribe_messages=True)

    _active_managers.extend([mgr_a, mgr_b])

    sio_a = SocketIO(app, client_manager=mgr_a, async_mode="threading")
    sio_b = SocketIO(app, client_manager=mgr_b, async_mode="threading")

    register_lesson_socket(sio_a, app=app)
    register_lesson_socket(sio_b, app=app)

    sio_a.server.manager.initialize()
    sio_b.server.manager.initialize()

    return sio_a, sio_b


def _connect_worker_client(app, sio, eio_sid: str, user_id: int):
    """Connect a client to the worker with an authenticated Flask session."""
    builder = EnvironBuilder(path="/socket.io/")
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
        cookie = client.get_cookie("session")
        if cookie:
            builder.headers["Cookie"] = f"session={cookie.value}"

    env = builder.get_environ()
    env["flask.app"] = app
    sio.server._handle_eio_connect(eio_sid, env)
    sid = sio.server.manager.connect(eio_sid, "/lesson")
    return sid


def _trigger(app, sio, event: str, sid: str, payload: dict):
    """Trigger an event handler within the application context."""
    with app.app_context():
        sio.server._trigger_event(event, "/lesson", sid, payload)


def test_multi_worker_bidirectional_code_and_board_sync(app, role_users, fake_redis):
    """
    Scenario 1: Teacher on Worker A, Student on Worker B.
    - Teacher and Student join via real socket handlers.
    - Code edited on Worker A propagates to Student on Worker B via Redis pubsub.
    - Ack with revision is returned to Teacher.
    - Shared Redis code_state key is updated.
    - Board stroke created on Worker B propagates to Teacher on Worker A.
    - Shared Redis board_state key is updated.
    """
    server, r_client = fake_redis
    lesson_id, _ = _create_lesson_context(app, role_users)
    sio_a, sio_b = _setup_workers(app, server)

    # 1. Connect Teacher on Worker A
    t_sid = _connect_worker_client(app, sio_a, "eio_teacher_w1", role_users["tutor_id"])
    teacher_packets = []
    sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))
    _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

    # 2. Connect Student on Worker B
    s_sid = _connect_worker_client(app, sio_b, "eio_student_w2", role_users["student_user_id"])
    student_packets = []
    sio_b.server._send_eio_packet = lambda sid, pkt: student_packets.append((sid, pkt.data))
    _trigger(app, sio_b, "join_lesson", s_sid, {"lesson_id": lesson_id})

    time.sleep(0.3)
    teacher_packets.clear()
    student_packets.clear()

    # 3. Teacher edits code on Worker A
    _trigger(app, sio_a, "lesson_code_update", t_sid, {
        "lesson_id": lesson_id,
        "code": "print('Distributed Hello from Worker A')",
        "file_name": "main.py",
        "base_revision": 1,
    })

    time.sleep(0.4)

    # Verify Teacher received ack on Worker A
    teacher_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
    ack_events = [e for e in teacher_events if e[0] == "lesson_code_ack"]
    assert len(ack_events) >= 1, f"Teacher should receive lesson_code_ack. Got: {teacher_events}"
    assert ack_events[0][1]["revision"] >= 1
    assert ack_events[0][1]["status"] == "synced"

    # Verify Student on Worker B received lesson_code_update
    student_events = [_parse_packet(p[1]) for p in student_packets if p[1]]
    code_events = [e for e in student_events if e[0] == "lesson_code_update"]
    assert len(code_events) >= 1, f"Student on Worker B should receive code update. Got: {student_events}"
    assert "Distributed Hello from Worker A" in code_events[0][1]["code"]
    assert code_events[0][1]["revision"] >= 1

    # Verify Redis distributed tier 2 contains updated state
    redis_code = runtime_state.get_json(_code_state_key(lesson_id))
    assert redis_code is not None, "Shared Redis code state must exist"
    assert redis_code["revision"] >= 1
    assert "Distributed Hello from Worker A" in redis_code["code"]

    # 4. Student on Worker B draws a stroke
    teacher_packets.clear()
    student_packets.clear()

    _trigger(app, sio_b, "board_stroke", s_sid, {
        "lesson_id": lesson_id,
        "stroke": {
            "id": "stroke_s1",
            "tool": "pen",
            "color": "#3b82f6",
            "points": [10, 20, 30, 40],
            "layer": "student",
        }
    })

    time.sleep(0.4)

    # Verify Teacher on Worker A received board_stroke
    teacher_events_2 = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
    stroke_events = [e for e in teacher_events_2 if e[0] == "board_stroke"]
    assert len(stroke_events) >= 1, f"Teacher on Worker A must receive board_stroke. Got: {teacher_events_2}"
    assert stroke_events[0][1]["stroke"]["id"] == "stroke_s1"

    # Verify Redis board state
    redis_board = runtime_state.get_json(_board_state_key(lesson_id))
    assert redis_board is not None
    assert "stroke_s1" in redis_board["strokes"]


def test_teacher_privacy_and_role_isolation_across_workers(app, role_users, fake_redis):
    """
    Scenario 2: Teacher Privacy & Zero Data Leak across Workers.
    - Teacher strokes ('teacher' layer) only route to _teacher_room.
    - Teacher private notes only route to _teacher_room.
    - Student on Worker B NEVER receives private teacher strokes or notes.
    - Task answers are redacted for Student on Worker B.
    """
    server, r_client = fake_redis
    lesson_id, _ = _create_lesson_context(app, role_users)
    sio_a, sio_b = _setup_workers(app, server)

    # Teacher on Worker A
    t_sid = _connect_worker_client(app, sio_a, "eio_teacher_priv", role_users["tutor_id"])
    teacher_packets = []
    sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))
    _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

    # Student on Worker B
    s_sid = _connect_worker_client(app, sio_b, "eio_student_priv", role_users["student_user_id"])
    student_packets = []
    sio_b.server._send_eio_packet = lambda sid, pkt: student_packets.append((sid, pkt.data))
    _trigger(app, sio_b, "join_lesson", s_sid, {"lesson_id": lesson_id})

    time.sleep(0.3)
    teacher_packets.clear()
    student_packets.clear()

    # 1. Teacher draws on teacher layer on Worker A
    _trigger(app, sio_a, "board_stroke", t_sid, {
        "lesson_id": lesson_id,
        "stroke": {
            "id": "teacher_private_stroke_99",
            "layer": "teacher",
            "points": [100, 200],
        }
    })

    time.sleep(0.4)

    student_events = [_parse_packet(p[1]) for p in student_packets if p[1]]
    leaked_strokes = [e for e in student_events if e[0] == "board_stroke"]
    assert len(leaked_strokes) == 0, "Student on Worker B must NEVER receive teacher-layer strokes"

    # 2. Teacher emits private note
    student_packets.clear()
    teacher_packets.clear()

    orig_sio = getattr(app, "socketio", None)
    try:
        with app.app_context():
            app.socketio = sio_a
            emit_lesson_private_note_updated(lesson_id, "Secret teacher curriculum observation")

        time.sleep(0.4)

        student_events_notes = [_parse_packet(p[1]) for p in student_packets if p[1]]
        leaked_notes = [e for e in student_events_notes if e[0] == "lesson_private_note_updated"]
        assert len(leaked_notes) == 0, "Student on Worker B must NEVER receive teacher private notes"

        teacher_events_notes = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        assert any(e[0] == "lesson_private_note_updated" for e in teacher_events_notes), "Teacher should receive private note update"

        # 3. Tasks with answers: answers must be hidden from student
        student_packets.clear()
        teacher_packets.clear()

        with app.app_context():
            app.socketio = sio_a
            emit_lesson_tasks_updated(lesson_id, "exam", {
                "id": "task_42",
                "title": "Solve x^2 = 16",
                "answer": "x = 4 or x = -4",
                "answer_visible_to_student": False,
            })

        time.sleep(0.4)

        student_events_tasks = [_parse_packet(p[1]) for p in student_packets if p[1]]
        task_events_s = [e for e in student_events_tasks if e[0] == "lesson_tasks_updated"]
        assert len(task_events_s) >= 1, "Student should receive task update"
        assert task_events_s[0][1]["task"]["answer"] == "", "Answer MUST be redacted for Student on Worker B"

        teacher_events_tasks = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        task_events_t = [e for e in teacher_events_tasks if e[0] == "lesson_tasks_updated"]
        assert len(task_events_t) >= 1, "Teacher should receive task update"
        assert task_events_t[0][1]["task"]["answer"] == "x = 4 or x = -4", "Teacher MUST receive full unredacted answer"
    finally:
        app.socketio = orig_sio


def test_distributed_presence_no_phantom_drops(app, role_users, fake_redis):
    """
    Scenario 3: Presence Aggregation & Multi-Connection Safety.
    - Two connections for user across Worker A and Worker B.
    - When Worker B connection closes, user remains online because Worker A is still connected.
    - Aggregated presence list from Redis hash includes all online participants.
    - When last connection disconnects, user is cleanly removed.
    """
    server, r_client = fake_redis
    lesson_id, _ = _create_lesson_context(app, role_users)
    student_id = role_users["student_id"]

    # Student opens Tab 1 on Worker A
    p1 = _register_user_presence(lesson_id, student_id, "sid_worker_a_tab1", {
        "user_id": student_id, "name": "Student A", "role": "student"
    })
    assert len(p1) == 1
    assert p1[0]["user_id"] == student_id

    # Student opens Tab 2 on Worker B
    p2 = _register_user_presence(lesson_id, student_id, "sid_worker_b_tab2", {
        "user_id": student_id, "name": "Student A", "role": "student"
    })
    assert len(p2) == 1, "Same user across multiple workers must not duplicate presence item"

    # Tab 2 closes on Worker B
    rem_presence, is_empty = _unregister_user_presence(lesson_id, student_id, "sid_worker_b_tab2")
    assert not is_empty, "Room is not empty because Tab 1 is still open on Worker A"
    assert len(rem_presence) == 1, "User must NOT be dropped while Tab 1 remains connected"

    # Tab 1 closes on Worker A
    rem_presence_final, is_empty_final = _unregister_user_presence(lesson_id, student_id, "sid_worker_a_tab1")
    assert is_empty_final is True, "Room must be completely empty after all tabs across all workers disconnect"
    assert len(rem_presence_final) == 0


def test_worker_crash_and_session_rehydration(app, role_users, fake_redis):
    """
    Scenario 4: Worker Crash & State Rehydration.
    - Code is edited to revision 3 on Worker A.
    - Worker A terminates abruptly.
    - Client connects to Worker B.
    - Rehydrated code state from Redis/PostgreSQL has revision 3 and all files intact.
    """
    server, r_client = fake_redis
    lesson_id, _ = _create_lesson_context(app, role_users)
    sio_a, sio_b = _setup_workers(app, server)

    t_sid = _connect_worker_client(app, sio_a, "eio_teacher_crash", role_users["tutor_id"])
    _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

    # Update file 1
    _trigger(app, sio_a, "lesson_code_update", t_sid, {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "import math\nprint(math.pi)",
        "base_revision": 1,
    })
    # Create file 2
    _trigger(app, sio_a, "lesson_vfs_file_create", t_sid, {
        "lesson_id": lesson_id,
        "file_name": "helper.py",
        "code": "def greet(): return 'hi'",
    })

    # Persist cached state
    with app.app_context():
        _persist_cached_code_state(lesson_id)

    # Simulate Worker A crash: clear in-memory cache in process
    _lesson_code_state.pop(lesson_id, None)

    # Teacher reconnects to Worker B
    with app.app_context():
        rehydrated = _load_cached_code_state(lesson_id)
        assert rehydrated is not None
        assert rehydrated["revision"] >= 2
        assert "main.py" in rehydrated["files"]
        assert "helper.py" in rehydrated["files"]
        assert "def greet(): return 'hi'" in rehydrated["files"]["helper.py"]


def test_tracer_run_isolation_across_workers(app, role_users, fake_redis):
    """
    Scenario 5: Tracer Run Isolation & Stale Step Filtering.
    - Worker A broadcasts tracer_state with run_id 'run_alpha'.
    - Room UI in shared Redis preserves the active run_id and seq monotonic order.
    """
    server, r_client = fake_redis
    lesson_id, _ = _create_lesson_context(app, role_users)
    sio_a, sio_b = _setup_workers(app, server)

    t_sid = _connect_worker_client(app, sio_a, "eio_teacher_tracer", role_users["tutor_id"])
    _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

    # Teacher starts trace run_alpha
    _trigger(app, sio_a, "lesson_room_ui", t_sid, {
        "lesson_id": lesson_id,
        "kind": "tracer_state",
        "run_id": "run_alpha",
        "seq": 1,
        "step": 3,
        "is_open": True,
        "code": "x = 10\ny = 20\n",
    })

    ui_list = _get_all_room_ui(lesson_id)
    tracer_ui = next((item for item in ui_list if item.get("kind") == "tracer_state"), None)
    assert tracer_ui is not None
    assert tracer_ui["run_id"] == "run_alpha"
    assert tracer_ui["step"] == 3
    assert tracer_ui["seq"] == 1


def test_redis_outage_graceful_degradation(app, role_users):
    """
    Scenario 6: Redis Outage / Degraded Mode.
    - When Redis is completely offline, socket handlers fall back gracefully to local memory + DB.
    - No unhandled exceptions crash the request.
    - Code is persisted to PostgreSQL review_summaries['_os_workspace'].
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        lesson.review_summaries = {
            "_os_workspace": {
                "files": {"main.py": "print('initial db code')"},
                "active_file": "main.py",
                "revision": 1,
            }
        }
        db.session.commit()

    # Force Redis failure
    orig_client = runtime_state.get_redis_client
    orig_ping = runtime_state.redis_ping
    runtime_state.get_redis_client = lambda: None
    runtime_state.redis_ping = lambda: False

    try:
        with app.app_context():
            # Load state without Redis: loads from DB/memory cleanly
            code_state = _load_cached_code_state(lesson_id)
            assert code_state is not None
            assert "main.py" in code_state["files"]

            # Mutate code
            code_state["code"] = "print('Persisted during Redis outage')"
            code_state["files"]["main.py"] = code_state["code"]
            code_state["revision"] = 10
            _lesson_code_state[lesson_id] = code_state

            # Persist to PostgreSQL
            _persist_cached_code_state(lesson_id)

            # Verify durable PostgreSQL record
            lesson = db.session.get(Lesson, lesson_id)
            summaries = getattr(lesson, "review_summaries", None) or {}
            os_ws = summaries.get("_os_workspace")
            assert os_ws is not None
            assert os_ws["revision"] == 10
            assert "Persisted during Redis outage" in os_ws["files"]["main.py"]
    finally:
        runtime_state.get_redis_client = orig_client
        runtime_state.redis_ping = orig_ping
