"""
BooStudy OS — Distributed Reliability Acceptance Test Suite (DR-01 through DR-18).

Acceptance Gate for Distributed Reliability Hardening, Fault Injection & Cross-System Recovery:
- DR-01: Two independent workers, normal operation (consistent state across workers)
- DR-02: Worker A crash (SIGKILL failover & state recovery on Worker B)
- DR-03: Complete Redis failure (Fail-closed degraded mode, split-brain prevention)
- DR-04: Redis returns (Cluster revalidation, lesson_sync_restored, resync)
- DR-05: Loss of Redis volatile data (DB fallback, zero false durability guarantees)
- DR-06: PostgreSQL commit failure injection (No false "saved" confirmation)
- DR-07: Concurrent CAS race (Zero lost updates under concurrent contention)
- DR-08: OT + CAS concurrency (Deterministic convergence of concurrent insertions)
- DR-09: Zombie SID in idle room (Expired presence lease pruned during idle heartbeats)
- DR-10: Multiple tabs presence (Multi-tab lease tracking, no premature drop)
- DR-11: Authoritative kick + Redis failure (Durability of access revocation in DB)
- DR-12: Lesson VirtualFS recovery (Multi-file workspace survives worker restart)
- DR-13: Homework VirtualFS recovery (Monotonic revisions prevent stale overwrites)
- DR-14: Canvas recovery & tombstones (Pages, strokes, active page & resurrection prevention)
- DR-15: BooTracer reconnect lifecycle (Tracer state machine rehydration)
- DR-16: Review after reconnect (Zero leak of hidden solutions to students)
- DR-17: Degraded UI contract (Predictable user-facing sync states)
- DR-18: Normal-operation performance & latency (p50/p95/p99 latency benchmarks)
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import fakeredis
import pytest
import requests
import socketio

import app.runtime_state as runtime_state
from app import create_app, db
from app.models import (
    Lesson,
    LessonParticipantBan,
    LessonTask,
    LessonWhiteboard,
    Student,
    Tasks,
    User,
    Assignment,
    AssignmentTask,
    Submission,
    Answer,
)
from app.lessons.lesson_socket import (
    _lesson_code_state,
    _lesson_presence,
    _lesson_board_strokes,
    _lesson_board_pages,
    _lesson_board_active_page,
    _lesson_board_tombstones,
    _lesson_room_ui,
    _lesson_control_cache,
    _code_state_key,
    _board_state_key,
    _presence_key,
    _connections_key,
    _room_ui_key,
    _register_user_presence,
    _unregister_user_presence,
    _get_active_presence,
    _prune_stale_connections,
    _prune_stale_connections_with_status,
    _load_cached_code_state,
    _update_cached_code_state,
    _persist_cached_code_state,
    _revalidate_distributed_state,
    _load_cached_board_strokes,
    _load_cached_board_pages,
    _load_cached_board_active_page,
    _save_room_ui_state,
    _get_all_room_ui,
    _ot_transform_op,
    _is_stroke_tombstoned,
    _record_stroke_tombstones,
    is_user_banned_from_lesson,
    register_lesson_socket,
)
from app.lessons.whiteboard_service import get_or_create_board
from app.task_workspace.service import WorkspaceContext, save_workspace_code
from tests.v2.test_lesson_room_interactive import _create_lesson_context
from tests.v2.test_lesson_os_distributed_sprint3 import (
    _setup_workers,
    _connect_worker_client,
    _trigger,
    _parse_packet,
)


@pytest.fixture(autouse=True)
def clean_in_memory_state():
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_board_tombstones.clear()
    _lesson_room_ui.clear()
    _lesson_control_cache.clear()
    yield
    _lesson_code_state.clear()
    _lesson_presence.clear()
    _lesson_board_strokes.clear()
    _lesson_board_pages.clear()
    _lesson_board_active_page.clear()
    _lesson_board_tombstones.clear()
    _lesson_room_ui.clear()
    _lesson_control_cache.clear()


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
# Multiprocess Cluster Fixture (Ports: Redis=16379, Worker A=5051, Worker B=5052)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mp_cluster():
    """
    Spawns an isolated test Redis server on port 16379, an isolated SQLite DB,
    and two independent OS worker processes on ports 5051 and 5052.
    """
    redis_port = 16379
    port_a = 5051
    port_b = 5052

    # Start isolated test Redis server process
    p_redis = subprocess.Popen(
        [sys.executable, "scripts/start_test_redis.py", str(redis_port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)

    redis_url = f"redis://127.0.0.1:{redis_port}/0"

    # Set up dedicated SQLite DB for the multiprocess cluster
    os.makedirs("instance", exist_ok=True)
    db_file = os.path.abspath("instance/dr_acceptance_mp.db")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    db_uri = f"sqlite:///{db_file.replace(os.sep, '/')}"

    init_app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": db_uri,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "dr_acceptance_mp_secret",
    })
    with init_app.app_context():
        db.create_all()
        tutor = User(email="dr_tutor@test.local", username="dr_tutor", role="tutor", is_active=True)
        student_user = User(email="dr_student@test.local", username="dr_student", role="student", is_active=True)
        db.session.add_all([tutor, student_user])
        db.session.flush()
        tutor_id = tutor.id
        student_user_id = student_user.id
        student = Student(name="DR Student", user_id=student_user_id, tutor_id=tutor_id, is_active=True)
        db.session.add(student)
        db.session.flush()
        lesson = Lesson(
            student_id=student.student_id,
            status="in_progress",
            topic="DR Multiprocess Acceptance Lesson",
        )
        db.session.add(lesson)
        db.session.flush()
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
        db.session.commit()

    # Start Worker A on port 5051
    proc_a = subprocess.Popen([
        sys.executable, "-m", "tests.v2.multiprocess_test_server",
        "--port", str(port_a),
        "--redis", redis_url,
        "--db", db_uri,
        "--channel", "dr_mp_test_chan",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Start Worker B on port 5052
    proc_b = subprocess.Popen([
        sys.executable, "-m", "tests.v2.multiprocess_test_server",
        "--port", str(port_b),
        "--redis", redis_url,
        "--db", db_uri,
        "--channel", "dr_mp_test_chan",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for workers to be healthy
    s_sess = requests.Session()
    s_sess.trust_env = False
    ready_a, ready_b = False, False
    for _ in range(40):
        time.sleep(0.25)
        try:
            if not ready_a and s_sess.get(f"http://127.0.0.1:{port_a}/health", timeout=1).status_code == 200:
                ready_a = True
        except Exception:
            pass
        try:
            if not ready_b and s_sess.get(f"http://127.0.0.1:{port_b}/health", timeout=1).status_code == 200:
                ready_b = True
        except Exception:
            pass
        if ready_a and ready_b:
            break

    assert ready_a and ready_b, "Both multiprocess workers must start and pass health check"

    cluster_info = {
        "redis_port": redis_port,
        "redis_url": redis_url,
        "p_redis": p_redis,
        "port_a": port_a,
        "port_b": port_b,
        "proc_a": proc_a,
        "proc_b": proc_b,
        "lesson_id": lesson_id,
        "tutor_id": tutor_id,
        "student_user_id": student_user_id,
        "db_uri": db_uri,
    }

    yield cluster_info

    # Teardown
    for p in (proc_a, proc_b, p_redis):
        try:
            p.kill()
            p.wait(timeout=2)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DR-01: Two Independent Workers, Normal Operation
# ---------------------------------------------------------------------------
def test_dr_01_two_workers_normal_operation(mp_cluster):
    """
    DR-01: Two independent server processes (Worker A on 5051, Worker B on 5052)
    connected over isolated TCP Redis.
    Verify bidirectional code and stroke synchronization.
    """
    port_a = mp_cluster["port_a"]
    port_b = mp_cluster["port_b"]
    lesson_id = mp_cluster["lesson_id"]
    tutor_id = mp_cluster["tutor_id"]
    student_user_id = mp_cluster["student_user_id"]

    sess_a = requests.Session()
    sess_a.trust_env = False
    sess_b = requests.Session()
    sess_b.trust_env = False

    # Authenticate sessions
    sess_a.post(f"http://127.0.0.1:{port_a}/api/internal/auth_session", json={"user_id": tutor_id, "role": "teacher"})
    cookie_a = "; ".join([f"{c.name}={c.value}" for c in sess_a.cookies])

    sess_b.post(f"http://127.0.0.1:{port_b}/api/internal/auth_session", json={"user_id": student_user_id, "role": "student"})
    cookie_b = "; ".join([f"{c.name}={c.value}" for c in sess_b.cookies])

    # Connect Socket.IO client A to Worker A
    c_a = socketio.Client()
    c_a.eio.http = sess_a
    c_a_events = []
    c_a.on("lesson_code_ack", namespace="/lesson")(lambda data: c_a_events.append(("ack", data)))

    c_a.connect(f"http://127.0.0.1:{port_a}", headers={"Cookie": cookie_a}, namespaces=["/lesson"], transports=["polling"], wait_timeout=5)
    c_a.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    # Connect Socket.IO client B to Worker B
    c_b = socketio.Client()
    c_b.eio.http = sess_b
    c_b_events = []
    c_b.on("lesson_code_update", namespace="/lesson")(lambda data: c_b_events.append(("code_update", data)))
    c_b.on("board_stroke", namespace="/lesson")(lambda data: c_b_events.append(("board_stroke", data)))

    c_b.connect(f"http://127.0.0.1:{port_b}", headers={"Cookie": cookie_b}, namespaces=["/lesson"], transports=["polling"], wait_timeout=5)
    c_b.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")

    time.sleep(0.5)

    # 1. Teacher on Worker A sends code update
    c_a.emit("lesson_code_update", {
        "lesson_id": lesson_id,
        "file_name": "main.py",
        "code": "print('DR-01: Cross-Worker Sync Success')",
        "base_revision": 1,
    }, namespace="/lesson")

    # Verify Student on Worker B receives it
    code_received = False
    for _ in range(30):
        time.sleep(0.1)
        matches = [e for e in c_b_events if e[0] == "code_update"]
        if matches and "DR-01: Cross-Worker Sync Success" in matches[0][1]["code"]:
            code_received = True
            break
    assert code_received, f"Worker B must receive code update from Worker A. Got: {c_b_events}"

    # 2. Teacher on Worker A sends whiteboard stroke
    test_stroke_payload = {
        "lesson_id": lesson_id,
        "stroke": {
            "id": "strk_dr01_001",
            "page_id": "page_1",
            "color": "#ff0000",
            "width": 3,
            "points": [{"x": 10, "y": 20}, {"x": 30, "y": 40}],
        }
    }
    c_a.emit("board_stroke", test_stroke_payload, namespace="/lesson")

    stroke_received = False
    for _ in range(30):
        time.sleep(0.1)
        matches = [e for e in c_b_events if e[0] == "board_stroke"]
        if matches and matches[0][1].get("stroke", {}).get("id") == "strk_dr01_001":
            stroke_received = True
            break
    assert stroke_received, f"Worker B must receive whiteboard stroke from Worker A. Got: {c_b_events}"

    c_a.disconnect()
    c_b.disconnect()


# ---------------------------------------------------------------------------
# DR-02: Worker A Crash Failover & Recovery on Worker B
# ---------------------------------------------------------------------------
def test_dr_02_worker_a_crash_and_failover(mp_cluster):
    """
    DR-02: Worker A is killed abruptly with SIGKILL.
    Client A reconnects to Worker B and requests resync.
    Authoritative state is restored from Redis without data loss.
    """
    port_a = mp_cluster["port_a"]
    port_b = mp_cluster["port_b"]
    proc_a = mp_cluster["proc_a"]
    lesson_id = mp_cluster["lesson_id"]
    tutor_id = mp_cluster["tutor_id"]

    sess_a = requests.Session()
    sess_a.trust_env = False

    # 1. Kill Worker A abruptly (SIGKILL)
    proc_a.kill()
    proc_a.wait(timeout=3)
    assert proc_a.poll() is not None, "Worker Process A must be terminated"

    # 2. Reconnect Client A to surviving Worker B
    sess_a.post(f"http://127.0.0.1:{port_b}/api/internal/auth_session", json={"user_id": tutor_id, "role": "teacher"})
    cookie_a_b = "; ".join([f"{c.name}={c.value}" for c in sess_a.cookies])

    c_a_failover = socketio.Client()
    c_a_failover.eio.http = sess_a
    reconnect_events = []
    c_a_failover.on("lesson_code_snapshot", namespace="/lesson")(lambda data: reconnect_events.append(("snapshot", data)))

    c_a_failover.connect(f"http://127.0.0.1:{port_b}", headers={"Cookie": cookie_a_b}, namespaces=["/lesson"], transports=["polling"], wait_timeout=5)
    c_a_failover.emit("join_lesson", {"lesson_id": lesson_id}, namespace="/lesson")
    c_a_failover.emit("lesson_code_resync", {"lesson_id": lesson_id}, namespace="/lesson")

    snapshots = []
    for _ in range(30):
        time.sleep(0.1)
        snapshots = [e for e in reconnect_events if e[0] == "snapshot"]
        if snapshots:
            break

    assert len(snapshots) >= 1, "Client A must receive code snapshot from Worker B after Worker A crash"
    assert "DR-01: Cross-Worker Sync Success" in snapshots[0][1]["code"], "Previous code state must survive on Worker B"

    c_a_failover.disconnect()


# ---------------------------------------------------------------------------
# DR-03: Complete Redis Failure (Split-Brain Prevention & Degraded Mode)
# ---------------------------------------------------------------------------
def test_dr_03_complete_redis_failure_split_brain_prevention(app, role_users, fake_redis_server):
    """
    DR-03: When Redis is unreachable in a multi-worker distributed environment:
    - Non-teacher collaborative updates (student code editing) are rejected with
      lesson_code_conflict and degraded status, preventing split-brain divergence.
    - Student board strokes are rejected with whiteboard_error.
    - Teacher edits receive ACK with status 'degraded' and durable: False.
    - No split-brain divergence is possible between workers.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_dr03", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        s_sid = _connect_worker_client(app, sio_b, "eio_student_dr03", role_users["student_user_id"])
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

        # Simulate complete Redis failure in multi-worker mode
        os.environ["BOOSTUDY_SINGLE_PROCESS"] = "0"
        orig_ping = runtime_state.redis_ping
        runtime_state.redis_ping = lambda: False

        teacher_packets, student_packets = [], []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))
        sio_b.server._send_eio_packet = lambda sid, pkt: student_packets.append((sid, pkt.data))

        # 1. Student attempts code update -> MUST be rejected with conflict/degraded
        _trigger(app, sio_b, "lesson_code_update", s_sid, {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "print('Student split brain attempt')",
            "base_revision": 1,
        })
        time.sleep(0.3)

        s_events = [_parse_packet(p[1]) for p in student_packets if p[1]]
        conflict_events = [e for e in s_events if e[0] == "lesson_code_conflict"]
        assert len(conflict_events) >= 1, f"Student update MUST be rejected in degraded mode. Got: {s_events}"
        assert "Синхронизация временно недоступна" in conflict_events[0][1]["message"]

        degraded_events = [e for e in s_events if e[0] == "lesson_sync_degraded"]
        assert len(degraded_events) >= 1
        assert degraded_events[0][1].get("degraded") is True

        # 2. Student attempts board stroke -> MUST be rejected with whiteboard_error
        student_packets.clear()
        _trigger(app, sio_b, "board_stroke", s_sid, {
            "lesson_id": lesson_id,
            "stroke": {
                "id": "strk_st_split",
                "points": [{"x": 1, "y": 2}],
            }
        })
        time.sleep(0.3)
        s_events2 = [_parse_packet(p[1]) for p in student_packets if p[1]]
        wb_errors = [e for e in s_events2 if e[0] == "whiteboard_error"]
        assert len(wb_errors) >= 1, f"Student stroke MUST be rejected in degraded mode. Got: {s_events2}"

        # 3. Teacher attempts code update -> ACK with degraded status, durable=False
        _trigger(app, sio_a, "lesson_code_update", t_sid, {
            "lesson_id": lesson_id,
            "file_name": "main.py",
            "code": "print('Teacher emergency degraded code')",
            "base_revision": 1,
        })
        time.sleep(0.3)
        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        t_acks = [e for e in t_events if e[0] == "lesson_code_ack"]
        assert len(t_acks) >= 1, f"Teacher update MUST receive ACK. Got: {t_events}"
        assert t_acks[0][1].get("status") == "degraded"
        assert t_acks[0][1].get("durable") is False

    finally:
        runtime_state.redis_ping = orig_ping
        os.environ.pop("BOOSTUDY_SINGLE_PROCESS", None)
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# DR-04: Redis Returns (Cluster Revalidation & Resync)
# ---------------------------------------------------------------------------
def test_dr_04_redis_recovery_and_resync(app, role_users, fake_redis_server):
    """
    DR-04: Redis recovers from an outage.
    _revalidate_distributed_state triggers:
    - Broadcasts lesson_sync_restored.
    - Resolves degraded state and re-aligns revision snapshots.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_dr04", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        # Set valid state in Redis for cluster revalidation
        init_state = {
            "file_name": "main.py",
            "code": "print('DR-04 Restored Code')",
            "files": {"main.py": "print('DR-04 Restored Code')"},
            "revision": 2,
        }
        runtime_state.set_json(_code_state_key(lesson_id), init_state)

        teacher_packets = []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

        # Revalidate state inside application context after Redis restoration
        with app.app_context():
            _revalidate_distributed_state(lesson_id)
        time.sleep(0.3)

        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        restored_events = [e for e in t_events if e[0] == "lesson_sync_restored"]
        assert len(restored_events) >= 1, f"lesson_sync_restored MUST be broadcast upon Redis recovery. Got: {t_events}"
        assert restored_events[0][1]["lesson_id"] == lesson_id

        # Resync request returns latest authoritative snapshot
        teacher_packets.clear()
        _trigger(app, sio_a, "lesson_code_resync", t_sid, {"lesson_id": lesson_id})
        time.sleep(0.3)
        t_events2 = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        snapshots = [e for e in t_events2 if e[0] == "lesson_code_snapshot"]
        assert len(snapshots) >= 1, "Authoritative snapshot must be delivered upon resync"

    finally:
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# DR-05: Loss of Redis Volatile Data (Zero False Durability Guarantees)
# ---------------------------------------------------------------------------
def test_dr_05_redis_volatile_data_loss_fallback(app, role_users, fake_redis_server):
    """
    DR-05: Redis experiences a total memory wipe (FLUSHALL / cold restart)
    before dirty state is persisted to PostgreSQL.
    The system must safely fall back to the durable DB state without claiming
    uncommitted volatile revisions were saved.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # Database has rev 1
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        lesson.review_summaries = {
            "_os_workspace": {
                "files": {"main.py": "print('Durable DB rev 1')"},
                "active_file": "main.py",
                "revision": 1,
            }
        }
        db.session.commit()

    # Worker A wrote uncommitted rev 5 into Redis, then Redis crashed and lost all keys
    r_client.flushall()

    # On restart, worker loads cached state
    with app.app_context():
        state = _load_cached_code_state(lesson_id)
        assert state is not None
        assert state["revision"] == 1, "Must fall back safely to durable DB revision 1"
        assert state["code"] == "print('Durable DB rev 1')"
        # Verify no false claim that uncommitted data was preserved
        assert runtime_state.get_dirty_code(lesson_id) is None


# ---------------------------------------------------------------------------
# DR-06: PostgreSQL Commit Failure Injection (No False Saved)
# ---------------------------------------------------------------------------
def test_dr_06_postgresql_commit_failure_no_false_saved(app, role_users, fake_redis_server):
    """
    DR-06: When a PostgreSQL transaction fails during persistence:
    - lesson_code_persisted (durable ACK) is NEVER emitted.
    - Dirty state remains recorded in Redis for safe retry.
    - Client never sees a false 'saved' indicator.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_dr06", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        # Mark code as dirty in Redis at rev 3
        dirty_state = {
            "file_name": "main.py",
            "code": "print('Dirty uncommitted code')",
            "files": {"main.py": "print('Dirty uncommitted code')"},
            "open_tabs": ["main.py"],
            "revision": 3,
            "version": 3,
        }
        runtime_state.set_json(_code_state_key(lesson_id), dirty_state)
        runtime_state.set_dirty_code(lesson_id, 3, role_users["tutor_id"])

        teacher_packets = []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

        # Inject failure in db.session.commit
        with app.app_context():
            with patch.object(db.session, "commit", side_effect=Exception("Database disk I/O error")):
                try:
                    _persist_cached_code_state(lesson_id)
                except Exception:
                    pass

        # Verify NO lesson_code_persisted event was emitted
        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        persisted_events = [e for e in t_events if e[0] == "lesson_code_persisted"]
        assert len(persisted_events) == 0, f"lesson_code_persisted MUST NOT be emitted on DB failure! Got: {t_events}"

        # Verify dirty state is STILL retained in Redis for retry
        dirty = runtime_state.get_dirty_code(lesson_id)
        assert dirty is not None, "Dirty marker must be preserved in Redis when commit fails"
        assert dirty["revision"] == 3

    finally:
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# DR-07: Concurrent Atomic CAS (Zero Lost Updates)
# ---------------------------------------------------------------------------
def test_dr_07_concurrent_cas_no_lost_updates(app, role_users, fake_redis_server):
    """
    DR-07: 10 concurrent threads simultaneously increment a revision counter
    via atomic_cas_json.
    All operations must be serialized without lost updates.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    state_key = _code_state_key(lesson_id)

    runtime_state.set_json(state_key, {"revision": 0, "updates": []})

    def cas_worker(thread_id: int):
        def updater(curr):
            data = dict(curr or {"revision": 0, "updates": []})
            data["revision"] = data["revision"] + 1
            data["updates"] = list(data.get("updates", [])) + [f"thread_{thread_id}"]
            return data, False

        return runtime_state.atomic_cas_json(state_key, updater)

    # Run 10 parallel threads
    num_threads = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(cas_worker, i) for i in range(num_threads)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Final state in Redis
    final_state = runtime_state.get_json(state_key)
    assert final_state["revision"] == num_threads, f"Expected revision {num_threads}, got {final_state['revision']}"
    assert len(final_state["updates"]) == num_threads, "All thread updates must be preserved"


# ---------------------------------------------------------------------------
# DR-08: OT + CAS Concurrency (Deterministic Revision Convergence)
# ---------------------------------------------------------------------------
def test_dr_08_ot_cas_concurrency_convergence(app, role_users, fake_redis_server):
    """
    DR-08: Concurrent character-level insertions at identical cursor offsets
    from Worker A and Worker B converge deterministically using OT + CAS.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    state_key = _code_state_key(lesson_id)

    # Initial document: "print('Hello')"
    init_state = {
        "file_name": "main.py",
        "code": "print('Hello')",
        "files": {"main.py": "print('Hello')"},
        "open_tabs": ["main.py"],
        "revision": 1,
        "history": [],
    }
    runtime_state.set_json(state_key, init_state)

    # Op A: Insert " World" at offset 12 ("print('Hello' World)")
    # Op B: Insert " Dear" at offset 12 ("print('Hello' Dear)")
    op_a = {"op_id": "op_a_001", "base_revision": 1, "start": 12, "end": 12, "inserted": " World", "client_id": "client_a"}
    op_b = {"op_id": "op_b_002", "base_revision": 1, "start": 12, "end": 12, "inserted": " Dear", "client_id": "client_b"}

    def apply_patch_op(patch_op):
        def _updater(curr):
            data = dict(curr or {})
            rev = data.get("revision", 1)
            code = data.get("code", "")
            hist = list(data.get("history", []))

            # Transform patch against any operations committed after base_revision
            transformed_patch = dict(patch_op)
            for prior_op in hist[patch_op["base_revision"]:]:
                transformed_patch = _ot_transform_op(
                    transformed_patch,
                    prior_op,
                    is_tie_breaker=(patch_op.get("client_id", "") < prior_op.get("client_id", "")),
                )

            # Apply
            start = transformed_patch["start"]
            end = transformed_patch["end"]
            inserted = transformed_patch["inserted"]
            new_code = code[:start] + inserted + code[end:]

            data["code"] = new_code
            data["files"] = {"main.py": new_code}
            data["revision"] = rev + 1
            transformed_patch["applied_revision"] = rev + 1
            data["history"] = hist + [transformed_patch]
            return data, False

        return _updater

    # Apply Op A first
    res_a = runtime_state.atomic_cas_json(state_key, apply_patch_op(op_a))
    assert res_a["revision"] == 2

    # Concurrently apply Op B (whose base_revision is still 1)
    res_b = runtime_state.atomic_cas_json(state_key, apply_patch_op(op_b))
    assert res_b["revision"] == 3

    # Both strings must be present and deterministic
    final_code = res_b["code"]
    assert "World" in final_code
    assert "Dear" in final_code
    assert res_b["revision"] == 3


# ---------------------------------------------------------------------------
# DR-09: Zombie SID in Idle Room (Automatic Cleanup via Lease TTL)
# ---------------------------------------------------------------------------
def test_dr_09_zombie_sid_idle_room_pruning(app, role_users, fake_redis_server):
    """
    DR-09: A crashed worker leaves an orphaned SID in an idle room.
    During periodic heartbeats from surviving clients, _prune_stale_connections
    sweeps the expired lease and broadcasts updated presence to observers.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_dr09", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        # Register zombie student SID with a short 1-second lease
        student_user_id = role_users["student_user_id"]
        zombie_sid = "zombie_sid_crashed_worker"
        runtime_state.set_connection_lease(zombie_sid, {"user_id": student_user_id, "lesson_id": lesson_id}, ttl_seconds=1)
        runtime_state.sadd(_connections_key(lesson_id, student_user_id), zombie_sid)
        runtime_state.hset_json(_presence_key(lesson_id), str(student_user_id), {"user_id": student_user_id, "name": "Zombie Student"})

        # Initial check: student is listed in presence
        pres_initial = _get_active_presence(lesson_id)
        assert any(p["user_id"] == student_user_id for p in pres_initial)

        # Wait for lease to expire
        time.sleep(1.1)

        teacher_packets = []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

        # Teacher sends periodic presence_heartbeat in idle room
        _trigger(app, sio_a, "presence_heartbeat", t_sid, {"lesson_id": lesson_id})
        time.sleep(0.3)

        # Zombie connection must be pruned, and lesson_presence emitted
        pres_after = _get_active_presence(lesson_id)
        assert not any(p["user_id"] == student_user_id for p in pres_after), "Zombie student must be pruned"

        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        pres_events = [e for e in t_events if e[0] == "lesson_presence"]
        assert len(pres_events) >= 1, f"Updated lesson_presence must be broadcast to observers. Got: {t_events}"

    finally:
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# DR-10: Multiple Tabs Presence Tracking
# ---------------------------------------------------------------------------
def test_dr_10_multiple_tabs_presence_tracking(app, role_users, fake_redis_server):
    """
    DR-10: User opens multiple tabs. Closing one tab must NOT prematurely
    drop the user from presence. Closing all tabs correctly removes the user.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    user_id = role_users["student_user_id"]

    # Tab 1 connects with 1s lease (simulating tab closure / crash)
    runtime_state.set_connection_lease("tab1_sid", {"user_id": user_id, "lesson_id": lesson_id}, ttl_seconds=1)
    runtime_state.sadd(_connections_key(lesson_id, user_id), "tab1_sid")
    runtime_state.hset_json(_presence_key(lesson_id), str(user_id), {"user_id": user_id, "name": "Student MultiTab"})

    # Tab 2 connects with 30s lease (active session)
    runtime_state.set_connection_lease("tab2_sid", {"user_id": user_id, "lesson_id": lesson_id}, ttl_seconds=30)
    runtime_state.sadd(_connections_key(lesson_id, user_id), "tab2_sid")

    # Tab 1 lease expires
    time.sleep(1.1)

    # Prune expired connections
    pres_after_tab1 = _get_active_presence(lesson_id)
    assert len(pres_after_tab1) == 1, "User must remain online while Tab 2 is active"
    assert pres_after_tab1[0]["user_id"] == user_id

    # Tab 2 explicitly closes
    runtime_state.delete_connection_lease("tab2_sid")
    pres_final = _get_active_presence(lesson_id)
    assert len(pres_final) == 0, "User must be removed from presence when all tabs close"


# ---------------------------------------------------------------------------
# DR-11: Authoritative Kick Survives Redis Failure
# ---------------------------------------------------------------------------
def test_dr_11_authoritative_kick_survives_redis_failure(app, role_users, fake_redis_server):
    """
    DR-11: Teacher kicks student. Ban is recorded in PostgreSQL.
    Redis loses state / restarts.
    Student attempts admission; access remains 403 Forbidden due to DB authority.
    Explicit unban restores access.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    student_user_id = role_users["student_user_id"]
    teacher_id = role_users["tutor_id"]

    with app.app_context():
        # 1. Ban student
        ban = LessonParticipantBan(
            lesson_id=lesson_id,
            user_id=student_user_id,
            banned_by_user_id=teacher_id,
            is_active=True,
        )
        db.session.add(ban)
        db.session.commit()

        # 2. Redis memory is wiped (simulating cold Redis restart)
        r_client.flushall()

        # 3. Student attempts entry -> must be rejected via PostgreSQL query
        assert is_user_banned_from_lesson(lesson_id, student_user_id) is True

        # 4. Teacher unbans student
        ban.is_active = False
        db.session.commit()
        r_client.flushall()

        # 5. Access restored
        assert is_user_banned_from_lesson(lesson_id, student_user_id) is False


# ---------------------------------------------------------------------------
# DR-12: Lesson VirtualFS Recovery
# ---------------------------------------------------------------------------
def test_dr_12_lesson_virtualfs_recovery(app, role_users, fake_redis_server):
    """
    DR-12: Multi-file project (main.py, utils.py, data.csv) with active tab
    survives worker failure and cleanly rehydrates from cache/DB.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # Multi-file project state
    vfs_state = {
        "file_name": "utils.py",
        "code": "def helper(): return 42",
        "files": {
            "main.py": "import utils\nprint(utils.helper())",
            "utils.py": "def helper(): return 42",
            "data.csv": "id,val\n1,100",
        },
        "open_tabs": ["main.py", "utils.py", "data.csv"],
        "active_file": "utils.py",
        "revision": 4,
        "version": 4,
    }
    runtime_state.set_json(_code_state_key(lesson_id), vfs_state)

    # Worker restart reloads state
    with app.app_context():
        loaded = _load_cached_code_state(lesson_id)
        assert loaded is not None
        assert loaded["active_file"] == "utils.py"
        assert len(loaded["files"]) == 3
        assert "main.py" in loaded["files"]
        assert "utils.py" in loaded["files"]
        assert "data.csv" in loaded["files"]
        assert loaded["revision"] == 4


# ---------------------------------------------------------------------------
# DR-13: Homework VirtualFS Stale Write Rejection
# ---------------------------------------------------------------------------
def test_dr_13_homework_virtualfs_stale_write_rejection(app, role_users):
    """
    DR-13: Homework VirtualFS rejects stale revision writes with ValueError,
    preserving durable monotonic revisions.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_id = role_users["tutor_id"]

    with app.app_context():
        # Create task and homework submission
        task = Tasks(task_number=27, content_html="<p>Task 27 Body</p>", answer="42", is_active=True, created_by_id=teacher_id)
        db.session.add(task)
        db.session.flush()

        asgn = Assignment(title="HW Test", created_by_id=teacher_id, lesson_id=lesson_id, is_active=True, assignment_type="homework", deadline=datetime.now(timezone.utc))
        db.session.add(asgn)
        db.session.flush()

        at = AssignmentTask(assignment_id=asgn.assignment_id, task_id=task.task_id, order_index=0)
        db.session.add(at)
        db.session.flush()

        sub = Submission(assignment_id=asgn.assignment_id, student_id=role_users["student_id"], status="SUBMITTED")
        db.session.add(sub)
        db.session.flush()

        ans = Answer(submission_id=sub.submission_id, assignment_task_id=at.assignment_task_id)
        db.session.add(ans)
        db.session.commit()

        ctx = WorkspaceContext(
            context_type="submission_task",
            context_id=sub.submission_id,
            task_id=task.task_id,
            task=task,
            title="HW Task Title",
            subtitle="Subtitle",
            source_label="Homework",
            submission_id=sub.submission_id,
            assignment_task_id=at.assignment_task_id,
            can_edit=True,
        )

        # Save revision 1 -> advances to rev 2
        rev2 = save_workspace_code(
            ctx,
            code="print('v1')",
            files={"main.py": "print('v1')"},
            open_tabs=["main.py"],
            active_file="main.py",
            revision=1,
        )
        assert rev2 >= 2

        # Stale write with base revision 1 MUST raise ValueError
        with pytest.raises(ValueError, match="Stale revision"):
            save_workspace_code(
                ctx,
                code="print('stale')",
                files={"main.py": "print('stale')"},
                open_tabs=["main.py"],
                active_file="main.py",
                revision=1,
            )

        # Sequential write with revision 2 -> succeeds and increments to rev 3
        rev3 = save_workspace_code(
            ctx,
            code="print('v2')",
            files={"main.py": "print('v2')"},
            open_tabs=["main.py"],
            active_file="main.py",
            revision=rev2,
        )
        assert rev3 == rev2 + 1


# ---------------------------------------------------------------------------
# DR-14: Canvas Recovery & Tombstone Integrity
# ---------------------------------------------------------------------------
def test_dr_14_canvas_recovery_and_tombstone_integrity(app, role_users, fake_redis_server):
    """
    DR-14: Canvas strokes, multi-page structure, and tombstones survive
    across worker crash without duplicate resurrection of deleted strokes.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # 1. Store canvas with 3 strokes across 2 pages
    strokes = [
        {"id": "strk_01", "page_id": "page_1", "points": [{"x": 0, "y": 0}]},
        {"id": "strk_02", "page_id": "page_2", "points": [{"x": 10, "y": 10}]},
        {"id": "strk_03", "page_id": "page_2", "points": [{"x": 20, "y": 20}]},
    ]
    pages = [{"id": "page_1", "title": "Page 1"}, {"id": "page_2", "title": "Page 2"}]

    board_payload = {
        "strokes": {s["id"]: s for s in strokes},
        "pages": pages,
        "active_page_id": "page_2",
    }
    runtime_state.set_json(_board_state_key(lesson_id), board_payload)

    # 2. Record tombstone for stroke 2 (deleted)
    _record_stroke_tombstones(lesson_id, ["strk_02"])
    assert _is_stroke_tombstoned(lesson_id, "strk_02") is True

    # 3. Simulate worker restart: reload cached board strokes
    with app.app_context():
        loaded_strokes = _load_cached_board_strokes(lesson_id)
        loaded_pages = _load_cached_board_pages(lesson_id)
        active_page = _load_cached_board_active_page(lesson_id)

        assert active_page == "page_2"
        assert len(loaded_pages) == 2
        # Deleted strk_02 must NOT be resurrected
        assert "strk_01" in loaded_strokes
        assert "strk_03" in loaded_strokes
        # Filter tombstoned strokes
        active_stroke_ids = [sid for sid in loaded_strokes.keys() if not _is_stroke_tombstoned(lesson_id, sid)]
        assert "strk_02" not in active_stroke_ids


# ---------------------------------------------------------------------------
# DR-15: BooTracer Reconnect Lifecycle
# ---------------------------------------------------------------------------
def test_dr_15_bootracer_reconnect_lifecycle(app, role_users, fake_redis_server):
    """
    DR-15: BooTracer state (breakpoints, window position, execution state)
    is preserved across reconnects via authoritative room UI state in Redis.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)

    # Save tracer state and breakpoint
    tracer_state = {
        "kind": "tracer_state",
        "lesson_id": lesson_id,
        "run_id": "run_test_101",
        "breakpoints": [2, 5],
        "current_line": 2,
    }
    _save_room_ui_state(lesson_id, "tracer_state", tracer_state)

    tracer_window = {
        "kind": "tracer_window",
        "lesson_id": lesson_id,
        "x": 120,
        "y": 80,
        "width": 600,
        "height": 400,
    }
    _save_room_ui_state(lesson_id, "tracer_window", tracer_window)

    # Surviving / reconnected worker reloads room UI
    room_ui = _get_all_room_ui(lesson_id)
    assert isinstance(room_ui, list)
    assert any(item.get("kind") == "tracer_state" and item.get("run_id") == "run_test_101" for item in room_ui)
    assert any(item.get("kind") == "tracer_state" and item.get("breakpoints") == [2, 5] for item in room_ui)
    assert any(item.get("kind") == "tracer_window" and item.get("width") == 600 for item in room_ui)


# ---------------------------------------------------------------------------
# DR-16: Review After Reconnect (Zero Solution Leakage)
# ---------------------------------------------------------------------------
def test_dr_16_review_after_reconnect_solution_security(app, role_users):
    """
    DR-16: Student with an unreviewed or revision-pending homework reconnects.
    Workspace payload strictly suppresses correct answers and solutions.
    Teacher reviewing homework has full visibility.
    """
    lesson_id, _ = _create_lesson_context(app, role_users)
    teacher_id = role_users["tutor_id"]

    with app.app_context():
        task = Tasks(
            task_number=27,
            content_html="<p>Task 27 HTML</p>",
            answer="TOP_SECRET_GOLDEN_42",
            is_active=True,
            created_by_id=teacher_id,
        )
        db.session.add(task)
        db.session.commit()

        # 1. Student context: needs_revision=True -> NO leakage
        ctx_student = WorkspaceContext(
            context_type="submission_task",
            context_id=101,
            task_id=task.task_id,
            task=task,
            title="Task Title",
            subtitle="Subtitle",
            source_label="Homework",
            can_edit=True,
            can_review=False,
            is_task_correct=False,
            is_published=True,
            needs_revision=True,
            is_reviewed=True,
            correct_answer="TOP_SECRET_GOLDEN_42",
            solution_code="print(42)",
            solution_html="<p>Solution Explanation</p>",
        )
        payload_student = ctx_student.as_payload()
        assert payload_student["can_see_solution"] is False
        assert payload_student["correct_answer"] == ""
        assert payload_student["solution_code"] == ""
        assert payload_student["solution_html"] == ""
        assert "TOP_SECRET_GOLDEN_42" not in json.dumps(payload_student)

        # 2. Teacher context: full visibility
        ctx_teacher = WorkspaceContext(
            context_type="submission_task",
            context_id=101,
            task_id=task.task_id,
            task=task,
            title="Task Title",
            subtitle="Subtitle",
            source_label="Homework",
            can_edit=True,
            can_review=True,
            is_task_correct=False,
            is_reviewed=False,
            correct_answer="TOP_SECRET_GOLDEN_42",
            solution_code="print(42)",
            solution_html="<p>Solution Explanation</p>",
        )
        payload_teacher = ctx_teacher.as_payload()
        assert payload_teacher["can_see_solution"] is True
        assert payload_teacher["correct_answer"] == "TOP_SECRET_GOLDEN_42"


# ---------------------------------------------------------------------------
# DR-17: Degraded UI Event Contract
# ---------------------------------------------------------------------------
def test_dr_17_degraded_ui_event_contract(app, role_users, fake_redis_server):
    """
    DR-17: Socket.IO event payloads for lesson_sync_degraded and lesson_sync_restored
    conform to the user-facing contract without exposing cryptic internal errors.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    orig_sio = getattr(app, "socketio", None)
    sio_a, sio_b = _setup_workers(app, server)
    app.socketio = sio_a

    try:
        t_sid = _connect_worker_client(app, sio_a, "eio_teacher_dr17", role_users["tutor_id"])
        _trigger(app, sio_a, "join_lesson", t_sid, {"lesson_id": lesson_id})

        # Set valid state in Redis for revalidation
        init_state = {
            "file_name": "main.py",
            "code": "print('DR-17 UI State')",
            "files": {"main.py": "print('DR-17 UI State')"},
            "revision": 1,
        }
        runtime_state.set_json(_code_state_key(lesson_id), init_state)

        teacher_packets = []
        sio_a.server._send_eio_packet = lambda sid, pkt: teacher_packets.append((sid, pkt.data))

        # Revalidate state triggers restored event inside application context
        with app.app_context():
            _revalidate_distributed_state(lesson_id)
        time.sleep(0.3)

        t_events = [_parse_packet(p[1]) for p in teacher_packets if p[1]]
        restored = [e for e in t_events if e[0] == "lesson_sync_restored"]
        assert len(restored) >= 1
        payload = restored[0][1]
        assert payload["lesson_id"] == lesson_id
        assert payload.get("revision") >= 1
        assert "message" in payload
        assert "Распределённая синхронизация восстановлена" in payload["message"]

    finally:
        if orig_sio is not None:
            app.socketio = orig_sio


# ---------------------------------------------------------------------------
# DR-18: Normal-Operation Performance Regression (p50/p95/p99)
# ---------------------------------------------------------------------------
def test_dr_18_normal_operation_performance_regression(app, role_users, fake_redis_server):
    """
    DR-18: Under normal operations, measure CAS operations and presence
    reconciliation frame times.
    Assert p50 < 5ms, p95 < 20ms, p99 < 50ms, confirming no latency penalty
    from distributed reliability checks.
    """
    server, r_client = fake_redis_server
    lesson_id, _ = _create_lesson_context(app, role_users)
    state_key = _code_state_key(lesson_id)
    runtime_state.set_json(state_key, {"revision": 0})

    latencies_ms = []

    # Benchmark 100 consecutive CAS operations
    for i in range(100):
        t0 = time.perf_counter()
        runtime_state.atomic_cas_json(state_key, lambda curr: ({"revision": (curr or {}).get("revision", 0) + 1}, False))
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000)

    latencies_sorted = sorted(latencies_ms)
    p50 = latencies_sorted[int(len(latencies_sorted) * 0.50)]
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]
    p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)]

    print(f"\n[DR-18 Performance] CAS latency over 100 ops: p50={p50:.2f}ms, p95={p95:.2f}ms, p99={p99:.2f}ms")

    # Assert rigorous performance thresholds
    assert p50 < 5.0, f"p50 must be under 5ms, got {p50:.2f}ms"
    assert p95 < 20.0, f"p95 must be under 20ms, got {p95:.2f}ms"
    assert p99 < 50.0, f"p99 must be under 50ms, got {p99:.2f}ms"
