"""
Sprint 3.1: Distributed Reliability Hardening & Real Failure Testing
- P0: Split-Brain Prevention & Degraded Mode
- P0: Real Multiprocess Failure Testing (separate OS processes over real TCP Redis)
- P1: Presence Lease Lifecycle & Crash Pruning
- P1: Atomic CAS Concurrency Protection (No Lost Updates)
- P1: PubSub Gap Detection & Resync
- P1: Redis -> PostgreSQL Transition & Dirty State Recovery
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import pytest
import fakeredis
import requests
import socketio
from socketio.redis_manager import RedisManager
from flask_socketio import SocketIO

import app.runtime_state as runtime_state
from app.models import db, Lesson, User
from app.lessons.lesson_socket import (
    register_lesson_socket,
    _lesson_code_state,
    _lesson_presence,
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_room_ui,
    _code_state_key,
    _board_state_key,
    _presence_key,
    _connections_key,
    _register_user_presence,
    _unregister_user_presence,
    _get_active_presence,
    _prune_stale_connections,
    _load_cached_code_state,
    _update_cached_code_state,
    _persist_cached_code_state,
    _revalidate_distributed_state,
    _room,
    _teacher_room,
    _student_room,
    _lesson_control_cache,
)
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_lesson_os_distributed_sprint3 import (
    _setup_workers,
    _connect_worker_client,
    _trigger,
    _parse_packet,
)


@pytest.fixture(autouse=True)
def clean_in_memory():
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_room_ui.clear()
    yield
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_room_ui.clear()


@pytest.fixture
def fake_redis_server():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    orig_client = runtime_state.get_redis_client
    orig_ping = runtime_state.redis_ping
    runtime_state.get_redis_client = lambda: client
    runtime_state.redis_ping = lambda: True
    yield server, client
    runtime_state.get_redis_client = orig_client
    runtime_state.redis_ping = orig_ping


# ---------------------------------------------------------------------------
# Test 1: P0 - Split-Brain Prevention & Fail-Closed Degraded Mode
# ---------------------------------------------------------------------------
def test_split_brain_prevention_fail_closed_degraded_mode(app, role_users, fake_redis_server):
    """
    When Redis fails in a distributed environment:
    - Multi-worker mode is detected.
    - Non-teacher collaborative updates (student code editing) are rejected with
      lesson_code_conflict and degraded status, preventing split-brain divergence.
    - Teacher edits receive ACK with status 'degraded' and are queued locally.
    - When Redis recovers, _revalidate_distributed_state aligns the cluster and emits lesson_sync_restored.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    t_sid = _connect_worker_client(app, sio_a, "eio_teacher_split", role_users["tutor_id"])
    _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

    s_sid = _connect_worker_client(app, sio_b, "eio_student_split", role_users["student_user_id"])
    _trigger(app, sio_b, "join_lesson", s_sid, {"lesson_id": lesson_id})

    # Enable student code editing in room control
    _lesson_control_cache[lesson_id] = (time.monotonic() + 100, {
        "code_sync": True,
        "student_code_editing": True,
    })
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        summaries = getattr(lesson, "review_summaries", None) or {}
        summaries.setdefault("_studio", {})["control"] = {
            "code_sync": True,
            "student_code_editing": True,
        }
        lesson.review_summaries = summaries
        db.session.commit()

    # Simulate Redis outage in distributed mode
    os.environ["BOOSTUDY_SINGLE_PROCESS"] = "0"
    orig_ping = runtime_state.redis_ping
    runtime_state.redis_ping = lambda: False

    student_packets = []
    sio_b.server._send_eio_packet = lambda sid, pkt: student_packets.append((sid, pkt.data))

    teacher_packets = []
    sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

    try:
        # 1. Student attempts edit on Worker B while Redis is down
        _trigger(app, sio_b, "lesson_code_update", s_sid, {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "print('Student split-brain attempt')",
            "base_revision": 1,
        })

        time.sleep(0.3)

        # Verify Student edit was rejected to prevent split-brain
        s_events = [_parse_packet(p[1]) for p in student_packets if p[1]]
        conflict_events = [e for e in s_events if e[0] == "lesson_code_conflict"]
        assert len(conflict_events) >= 1, "Student edit MUST be rejected during distributed runtime outage"
        assert "Синхронизация временно недоступна" in conflict_events[0][1]["message"]

        # 2. Teacher (authoritative owner) edits on Worker A during degraded mode
        _trigger(app, sio_a, "lesson_code_update", t_sid, {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "print('Teacher emergency degraded edit')",
            "base_revision": 1,
        })

        time.sleep(0.3)

        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        ack_events = [e for e in t_events if e[0] == "lesson_code_ack"]
        assert len(ack_events) >= 1
        assert ack_events[0][1]["status"] == "degraded", "Teacher ACK must explicitly indicate 'degraded' status"

        # 3. Redis recovers
        runtime_state.redis_ping = lambda: True
        student_packets.clear()

        # Teacher commits to PostgreSQL and revalidates distributed state
        with app.app_context():
            _persist_cached_code_state(lesson_id)
            _revalidate_distributed_state(lesson_id)

        # Allow pubsub delivery across worker threads
        sync_restored = []
        for _ in range(15):
            time.sleep(0.1)
            s_events_recovered = [_parse_packet(p[1]) for p in student_packets if p[1]]
            sync_restored = [e for e in s_events_recovered if e[0] == "lesson_sync_restored"]
            if sync_restored:
                break

        assert len(sync_restored) >= 1, f"lesson_sync_restored MUST be broadcast when Redis recovers. Got: {student_packets}"
        assert sync_restored[0][1]["lesson_id"] == lesson_id

    finally:
        if orig_sio is not None:
            app.socketio = orig_sio
        runtime_state.redis_ping = orig_ping
        os.environ.pop("BOOSTUDY_SINGLE_PROCESS", None)


# ---------------------------------------------------------------------------
# Test 2: P1 - Presence Lease Expiration & Crash Pruning
# ---------------------------------------------------------------------------
def test_presence_lease_expiration_and_crash_recovery(app, role_users, fake_redis_server):
    """
    When a worker crashes (SIGKILL) without calling disconnect:
    - SIDs associated with the crashed worker expire after their lease TTL.
    - _prune_stale_connections sweeps expired SIDs.
    - If user has another active tab on a live worker, user remains online (no phantom drop).
    - If user has no active tabs left, user is cleanly removed from online presence.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    user_id = role_users["student_id"]

    # Tab 1 connects with a 1-second short lease for testing
    runtime_state.set_connection_lease("tab1_crashed_sid", {"user_id": user_id, "lesson_id": lesson_id}, ttl_seconds=1)
    runtime_state.sadd(_connections_key(lesson_id, user_id), "tab1_crashed_sid")
    runtime_state.hset_json(_presence_key(lesson_id), str(user_id), {"user_id": user_id, "name": "Student MultiTab"})

    # Tab 2 connects with a longer lease (active connection on surviving worker)
    runtime_state.set_connection_lease("tab2_alive_sid", {"user_id": user_id, "lesson_id": lesson_id}, ttl_seconds=30)
    runtime_state.sadd(_connections_key(lesson_id, user_id), "tab2_alive_sid")

    # Immediate presence check: both connections exist, user is online
    presence = _get_active_presence(lesson_id)
    assert len(presence) == 1
    assert presence[0]["user_id"] == user_id

    # Simulate Worker 1 crash: Tab 1 lease expires after 1.1 seconds
    time.sleep(1.1)

    # Prune stale connections: Tab 1 is pruned, but Tab 2 remains active
    presence_after_prune = _get_active_presence(lesson_id)
    assert len(presence_after_prune) == 1, "User must stay online while Tab 2 lease is active"

    active_sids = runtime_state.smembers(_connections_key(lesson_id, user_id))
    assert "tab1_crashed_sid" not in active_sids, "Crashed SID must be pruned from connections set"
    assert "tab2_alive_sid" in active_sids

    # Tab 2 explicitly deletes its lease / disconnects
    runtime_state.delete_connection_lease("tab2_alive_sid")
    presence_final = _get_active_presence(lesson_id)
    assert len(presence_final) == 0, "User must be removed from presence when all leases expire"


# ---------------------------------------------------------------------------
# Test 3: P1 - Atomic CAS Concurrency Protection (No Lost Updates)
# ---------------------------------------------------------------------------
def test_atomic_cas_concurrency_no_lost_updates(app, role_users, fake_redis_server):
    """
    Two workers concurrently update the code with the same base_revision.
    atomic_cas_json prevents lost updates:
    - First worker successfully increments revision.
    - Second worker detects revision mismatch and aborts with conflict.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # Initial state at revision 1
    init_state = {
        "file_name": "main.py",
        "code": "print('initial')",
        "files": {"main.py": "print('initial')"},
        "open_tabs": ["main.py"],
        "revision": 1,
    }
    runtime_state.set_json(_code_state_key(lesson_id), init_state)

    def worker_update_fn(new_code, base_rev):
        def _updater(curr):
            c_dict = dict(curr or {})
            c_rev = int(c_dict.get("revision") or 0)
            if base_rev < c_rev:
                return {"conflict": True, "server_revision": c_rev}, True
            f_dict = dict(c_dict.get("files") or {})
            f_dict["main.py"] = new_code
            c_dict["files"] = f_dict
            c_dict["code"] = new_code
            c_dict["revision"] = c_rev + 1
            return c_dict, False
        return _updater

    # Worker A updates with base_revision=1
    res_a = runtime_state.atomic_cas_json(_code_state_key(lesson_id), worker_update_fn("Worker A Code", 1))
    assert res_a is not None
    assert res_a["revision"] == 2
    assert res_a["code"] == "Worker A Code"

    # Worker B tries to update concurrently with stale base_revision=1
    res_b = runtime_state.atomic_cas_json(_code_state_key(lesson_id), worker_update_fn("Worker B Code", 1))
    assert res_b is not None
    assert res_b.get("conflict") is True
    assert res_b["server_revision"] == 2

    # State in Redis remains Worker A's code without being lost/clobbered
    current_redis = runtime_state.get_json(_code_state_key(lesson_id))
    assert current_redis["revision"] == 2
    assert current_redis["code"] == "Worker A Code"


# ---------------------------------------------------------------------------
# Test 4: P1 - PubSub Gap Detection & Resync
# ---------------------------------------------------------------------------
def test_pubsub_gap_detection_and_code_resync(app, role_users, fake_redis_server):
    """
    When client misses an intermediate update (gap in revision),
    it sends lesson_code_resync, and the server returns the complete snapshot.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    orig_sio = getattr(app, "socketio", None)
    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_gap", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        # Prepare server state with revision 10
        state_rev10 = {
            "file_name": "main.py",
            "code": "print('rev 10 code')",
            "files": {"main.py": "print('rev 10 code')", "util.py": "x = 42"},
            "open_tabs": ["main.py", "util.py"],
            "revision": 10,
        }
        runtime_state.set_json(_code_state_key(lesson_id), state_rev10)

        teacher_packets = []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

        # Client requests resync
        _trigger(app, sio_a, "lesson_code_resync", t_sid, {"lesson_id": lesson_id})

        time.sleep(0.3)

        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        snapshots = [e for e in t_events if e[0] == "lesson_code_snapshot"]
        assert len(snapshots) >= 1
        assert snapshots[0][1]["revision"] == 10
        assert "util.py" in snapshots[0][1]["files"]
    finally:
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# Test 5: P1 - Dirty State Recovery Across Crashed Worker
# ---------------------------------------------------------------------------
def test_dirty_state_recovery_across_crashed_worker(app, role_users, fake_redis_server):
    """
    Worker A updates code to revision 5, marks dirty_code in Redis, and dies
    before flushing to PostgreSQL.
    Worker B loads the state, notices dirty_code > DB revision, and automatically
    persists it to PostgreSQL.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # In DB: revision is 1
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        lesson.review_summaries = {
            "_os_workspace": {
                "files": {"main.py": "print('db rev 1')"},
                "active_file": "main.py",
                "revision": 1,
            }
        }
        db.session.commit()

    # Worker A updated Redis to rev 5 and marked dirty, then crashed
    dirty_state = {
        "file_name": "main.py",
        "code": "print('redis rev 5 updated before crash')",
        "files": {"main.py": "print('redis rev 5 updated before crash')"},
        "open_tabs": ["main.py"],
        "active_file": "main.py",
        "revision": 5,
        "version": 5,
        "updated_at": int(time.time() * 1000),
    }
    runtime_state.set_json(_code_state_key(lesson_id), dirty_state)
    runtime_state.set_dirty_code(lesson_id, 5, role_users["tutor_id"])

    # Worker B loads cached state on client reconnect
    with app.app_context():
        loaded = _load_cached_code_state(lesson_id)
        assert loaded is not None
        assert loaded["revision"] == 5

        # Trigger scheduled flush
        _persist_cached_code_state(lesson_id)

        # Verify PostgreSQL now holds rev 5
        lesson_after = db.session.get(Lesson, lesson_id)
        os_ws = lesson_after.review_summaries.get("_os_workspace")
        assert os_ws is not None
        assert os_ws["revision"] == 5
        assert "redis rev 5 updated before crash" in os_ws["files"]["main.py"]

        # Verify dirty marker was cleared after successful PostgreSQL commit
        assert runtime_state.get_dirty_code(lesson_id) is None


# ---------------------------------------------------------------------------
# Test 6: P0 - Real Multiprocess Worker Failure and Sync over TCP Redis
# ---------------------------------------------------------------------------
def test_real_multiprocess_worker_failure_and_sync(app, role_users):
    """
    Real Multiprocess Test:
    - Authentic TCP Redis server on localhost.
    - Worker Process 1 on port 5031 (separate OS process).
    - Worker Process 2 on port 5032 (separate OS process).
    - Client 1 connects to Worker 1.
    - Client 2 connects to Worker 2.
    - Real OS processes communicate through Redis PubSub over TCP.
    - Worker 1 is killed with SIGKILL / p.kill().
    - Client 1 reconnects to Worker 2 and verifies state survival.
    """
    import fakeredis._clients._tcp_server as mod
    import socket
    import select
    orig_handle = mod.TCPFakeRequestHandler.handle
    orig_setup = mod.TCPFakeRequestHandler.setup

    def patched_handle(self):
        while not self.server._shutdown_event.is_set():
            try:
                if self.current_client.can_read():
                    response = self.current_client.read_response()
                    self.writer.dump(response)
                    continue
                try:
                    data = self.rfile.readline()
                except BlockingIOError:
                    data = b""
                if data == b"":
                    readable, _, _ = select.select([self.connection], [], [], 0.05)
                    if not readable:
                        continue
                    try:
                        data = self.rfile.readline()
                    except BlockingIOError:
                        data = b""
                    if data == b"":
                        try:
                            peek = self.connection.recv(1, socket.MSG_PEEK)
                            if peek == b"":
                                break
                        except Exception:
                            pass
                if data:
                    self.current_client.get_socket().sendall(data)
            except ConnectionError:
                break
            except Exception:
                break

    def patched_setup(self):
        orig_setup(self)
        self.connection.setblocking(False)

    mod.TCPFakeRequestHandler.setup = patched_setup
    mod.TCPFakeRequestHandler.handle = patched_handle

    real_redis_client = None
    tcp_redis = None
    try:
        import redis
        r_chk = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=1)
        if r_chk.ping():
            real_redis_client = redis.Redis(host="127.0.0.1", port=6379, db=14)
            real_redis_client.flushdb()
            redis_url = "redis://127.0.0.1:6379/14"
    except Exception:
        real_redis_client = None

    if real_redis_client is None:
        redis_port = 16391
        tcp_redis = fakeredis.TcpFakeServer(("127.0.0.1", redis_port))
        import threading
        t_redis = threading.Thread(target=tcp_redis.serve_forever, daemon=True)
        t_redis.start()
        time.sleep(0.3)
        redis_url = f"redis://127.0.0.1:{redis_port}/0"

    # Initialize shared SQLite database file for independent OS worker processes
    os.makedirs("instance", exist_ok=True)
    db_file = os.path.abspath("instance/sprint3_1_mp_test.db")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    db_uri = f"sqlite:///{db_file.replace(os.sep, '/')}"

    from app import create_app, db as init_db
    from app.models import User, Student, Lesson
    from app.lessons.whiteboard_service import get_or_create_board

    init_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": db_uri,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "sprint3_1_multiprocess_secret",
    })
    with init_app.app_context():
        init_db.create_all()
        tutor = User(email="mp_tutor@test.local", username="mp_tutor", role="tutor", is_active=True)
        student_user = User(email="mp_student@test.local", username="mp_student", role="student", is_active=True)
        init_db.session.add_all([tutor, student_user])
        init_db.session.flush()
        tutor_id = tutor.id
        student_user_id = student_user.id
        student = Student(name="MP Student", user_id=student_user_id, tutor_id=tutor_id, is_active=True)
        init_db.session.add(student)
        init_db.session.flush()
        student_id = student.student_id
        lesson = Lesson(
            student_id=student_id,
            status="in_progress",
            topic="Multiprocess Real Sync Lesson",
        )
        init_db.session.add(lesson)
        init_db.session.flush()
        lesson_id = lesson.lesson_id
        board = get_or_create_board(lesson_id)
        board.document_state = {
            "presentation": {
                "control": {
                    "code_sync": True,
                    "student_code_editing": True,
                }
            }
        }
        init_db.session.commit()

    # 1. Start Worker Process A on port 5031
    port_a = 5031
    proc_a = subprocess.Popen([
        sys.executable, "-m", "tests.v2.multiprocess_test_server",
        "--port", str(port_a),
        "--redis", redis_url,
        "--db", db_uri,
        "--channel", "sprint3_1_mp_test_chan",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Start Worker Process B on port 5032
    port_b = 5032
    proc_b = subprocess.Popen([
        sys.executable, "-m", "tests.v2.multiprocess_test_server",
        "--port", str(port_b),
        "--redis", redis_url,
        "--db", db_uri,
        "--channel", "sprint3_1_mp_test_chan",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        # HTTP session without system/env proxy interference
        s_sess_a = requests.Session()
        s_sess_a.trust_env = False
        s_sess_b = requests.Session()
        s_sess_b.trust_env = False

        # Wait for both workers to announce ready
        ready_a = False
        ready_b = False
        for _ in range(40):
            time.sleep(0.3)
            try:
                if not ready_a and s_sess_a.get(f"http://127.0.0.1:{port_a}/health", timeout=1).status_code == 200:
                    ready_a = True
            except Exception:
                pass
            try:
                if not ready_b and s_sess_b.get(f"http://127.0.0.1:{port_b}/health", timeout=1).status_code == 200:
                    ready_b = True
            except Exception:
                pass
            if ready_a and ready_b:
                break

        assert ready_a, "Worker Process A must be running and healthy"
        assert ready_b, "Worker Process B must be running and healthy"

        # Authenticate sessions via HTTP endpoint
        res_auth_a = s_sess_a.post(f"http://127.0.0.1:{port_a}/api/internal/auth_session", json={"user_id": tutor_id, "role": "teacher"})
        assert res_auth_a.status_code == 200
        cookie_a = "; ".join([f"{c.name}={c.value}" for c in s_sess_a.cookies])

        res_auth_b = s_sess_b.post(f"http://127.0.0.1:{port_b}/api/internal/auth_session", json={"user_id": student_user_id, "role": "student"})
        assert res_auth_b.status_code == 200
        cookie_b = "; ".join([f"{c.name}={c.value}" for c in s_sess_b.cookies])

        # Connect Socket.IO Client A to Worker A
        c_a = socketio.Client()
        c_a.eio.http = s_sess_a
        c_a_events = []
        @c_a.on("lesson_code_ack", namespace="/lesson")
        def on_ack_a(data):
            c_a_events.append(("ack", data))

        c_a.connect(
            f"http://127.0.0.1:{port_a}",
            headers={"Cookie": cookie_a},
            namespaces=["/lesson"],
            transports=["polling"],
            wait_timeout=5,
        )
        c_a.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

        # Connect Socket.IO Client B to Worker B
        c_b = socketio.Client()
        c_b.eio.http = s_sess_b
        c_b_events = []
        @c_b.on("lesson_code_update", namespace="/lesson")
        def on_code_b(data):
            c_b_events.append(("code_update", data))

        c_b.connect(
            f"http://127.0.0.1:{port_b}",
            headers={"Cookie": cookie_b},
            namespaces=["/lesson"],
            transports=["polling"],
            wait_timeout=5,
        )
        c_b.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

        time.sleep(0.5)

        # 3. Client A on Worker A emits code update
        c_a.emit("lesson_code_update", {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "print('Real Multiprocess Cross-Process Success!')",
            "base_revision": 1,
        }, namespace="/lesson")

        # Verify Client B on Worker B received the update across OS processes via Redis PubSub!
        b_updates = []
        for _ in range(30):
            time.sleep(0.1)
            b_updates = [e for e in c_b_events if e[0] == "code_update"]
            if b_updates:
                break
        assert len(b_updates) >= 1, f"Client B on Worker 2 must receive update from Worker 1. Got: {c_b_events}"
        assert "Real Multiprocess Cross-Process Success!" in b_updates[0][1]["code"]

        # 4. SIGKILL Worker Process A abruptly
        proc_a.kill()
        proc_a.wait(timeout=3)
        assert proc_a.poll() is not None, "Worker A must be terminated"

        # 5. Client A reconnects to Worker B on port 5032
        c_a.disconnect()
        c_a_reconnect_events = []
        @c_a.on("lesson_code_snapshot", namespace="/lesson")
        def on_snapshot_reconnect(data):
            c_a_reconnect_events.append(("snapshot", data))

        res_auth_a_b = s_sess_a.post(f"http://127.0.0.1:{port_b}/api/internal/auth_session", json={"user_id": tutor_id, "role": "teacher"})
        assert res_auth_a_b.status_code == 200
        cookie_a_b = "; ".join([f"{c.name}={c.value}" for c in s_sess_a.cookies])

        c_a = socketio.Client()
        c_a.eio.http = s_sess_a
        c_a.on("lesson_code_snapshot", namespace="/lesson")(on_snapshot_reconnect)

        c_a.connect(
            f"http://127.0.0.1:{port_b}",
            headers={"Cookie": cookie_a_b},
            namespaces=["/lesson"],
            transports=["polling"],
            wait_timeout=5,
        )
        c_a.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
        c_a.emit("lesson_code_resync", {"lesson_id": lesson_id}, namespace="/lesson")

        snapshots = []
        for _ in range(30):
            time.sleep(0.1)
            snapshots = [e for e in c_a_reconnect_events if e[0] == "snapshot"]
            if snapshots:
                break

        # Verify state rehydrated from Redis on surviving Worker B
        assert len(snapshots) >= 1, f"Client A must receive code snapshot from Worker B after Worker A crash. Got: {c_a_reconnect_events}"
        assert "Real Multiprocess Cross-Process Success!" in snapshots[0][1]["code"]

        c_a.disconnect()
        c_b.disconnect()

    finally:
        try:
            proc_a.kill()
        except Exception:
            pass
        try:
            proc_b.kill()
        except Exception:
            pass
        if tcp_redis is not None:
            tcp_redis.shutdown()
        if real_redis_client is not None:
            try:
                real_redis_client.flushdb()
            except Exception:
                pass
        mod.TCPFakeRequestHandler.setup = orig_setup
        mod.TCPFakeRequestHandler.handle = orig_handle
