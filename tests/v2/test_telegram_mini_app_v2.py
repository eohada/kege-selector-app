"""Comprehensive automated test suite for BooStudy Telegram Mini App V2.

Verifies:
- HMAC signature calculation and validation (WebAppData secret key derivation)
- Anti-tampering and replay protection (expired auth_date, future drift)
- WebApp SPA shell HTML rendering (/tg-app/)
- API /tg-app/api/bootstrap:
  * Rejection of unauthenticated / forged requests (403 invalid_init_data)
  * Seamless bootstrap response for linked student: profile, context, today data, notifications
  * Dynamic role context resolution and safe context switching for creator (creator -> teacher)
  * RBAC privilege escalation prevention (student attempting creator context)
- API /tg-app/api/student/assignment/detail:
  * Homework details, submission status, percentage, teacher review comments
  * 404 isolation for non-existent / unauthorized homework IDs
- API /tg-app/api/teacher/schedule:
  * Teacher's agenda with topic, student name, and lesson room URL
- API /tg-app/api/parent/child/detail:
  * Child academic summary, upcoming lessons, and recent graded submissions
  * Strict IDOR isolation: 403 foreign_child_forbidden when parent requests unlinked/foreign child
- API /tg-app/api/operations/health:
  * RBAC guard: 403 admin_context_required for regular students
  * 200 ok for platform creator with system operational summary and deliveries health
- Bot V3 Mini App button integration:
  * Native WebAppInfo button for HTTPS endpoints
  * Browser fallback link for HTTP development servers
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import pytest

from core.db_models import (
    db, User, UserProfile, Student, FamilyTie, Lesson, Tasks,
    Assignment, Submission, TelegramDelivery,
)
from app.telegram.mini_app import validate_init_data
from app.telegram.v3.ui import build_mini_app_button


TEST_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567"


@pytest.fixture(autouse=True)
def enable_mini_app_for_suite(monkeypatch):
    monkeypatch.setenv("TELEGRAM_MINI_APP_ENABLED", "1")
    monkeypatch.delenv("TELEGRAM_MINI_APP_PILOT_ONLY", raising=False)



def generate_init_data(
    bot_token: str = TEST_BOT_TOKEN,
    user_id: int = 77701,
    auth_date: int | None = None,
    username: str = "testuser",
    first_name: str = "Test",
    extra: dict | None = None,
) -> str:
    """Helper to create a cryptographically valid Telegram initData query string."""
    if auth_date is None:
        auth_date = int(time.time())

    user_dict = {
        "id": user_id,
        "first_name": first_name,
        "username": username,
    }
    data: dict[str, str] = {
        "auth_date": str(auth_date),
        "user": json.dumps(user_dict, separators=(",", ":")),
    }
    if extra:
        data.update({k: str(v) for k, v in extra.items()})

    sorted_items = sorted(data.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    pairs = [f"{k}={quote(v)}" for k, v in data.items()]
    pairs.append(f"hash={sig}")
    return "&".join(pairs)


# ---------------------------------------------------------------------------
# 1. Cryptographic & Replay Protection Tests
# ---------------------------------------------------------------------------

def test_validate_init_data_success():
    """Valid HMAC signature returns parsed dict with nested user JSON."""
    init_data = generate_init_data(user_id=12345, username="student_user")
    parsed = validate_init_data(init_data, TEST_BOT_TOKEN)

    assert parsed is not None
    assert "user" in parsed
    assert parsed["user"]["id"] == 12345
    assert parsed["user"]["username"] == "student_user"


def test_validate_init_data_tampered_signature():
    """Tampering with query parameters or signature invalidates verification."""
    init_data = generate_init_data(user_id=12345)
    tampered = init_data.replace("12345", "99999")
    assert validate_init_data(tampered, TEST_BOT_TOKEN) is None

    tampered_sig = init_data[:-4] + "0000"
    assert validate_init_data(tampered_sig, TEST_BOT_TOKEN) is None


def test_validate_init_data_expired_replay():
    """Old initData proofs exceeding 24 hours (86400s) are rejected."""
    expired_auth_date = int(time.time()) - 90000
    init_data = generate_init_data(user_id=12345, auth_date=expired_auth_date)
    assert validate_init_data(init_data, TEST_BOT_TOKEN) is None


def test_validate_init_data_future_clock_drift():
    """initData proofs from the future (> 60s ahead) are rejected."""
    future_auth_date = int(time.time()) + 120
    init_data = generate_init_data(user_id=12345, auth_date=future_auth_date)
    assert validate_init_data(init_data, TEST_BOT_TOKEN) is None


# ---------------------------------------------------------------------------
# 2. SPA Shell Rendering
# ---------------------------------------------------------------------------

def test_mini_app_spa_shell_page(client):
    """GET /tg-app/ returns HTTP 200 with Telegram SDK and Mini App V2 container."""
    resp = client.get("/tg-app/", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "telegram-web-app.js" in html
    assert "app-root" in html
    assert "tma-loading" in html


# ---------------------------------------------------------------------------
# 3. Bootstrap & Context Resolution Tests
# ---------------------------------------------------------------------------

def test_bootstrap_unauthenticated(client):
    """POST /tg-app/api/bootstrap without valid initData returns 403 invalid_init_data."""
    resp = client.post("/tg-app/api/bootstrap", json={})
    assert resp.status_code == 403
    data = resp.get_json()
    assert data.get("ok") is False
    assert data.get("error") == "invalid_init_data"


def test_bootstrap_linked_student(client, app, monkeypatch):
    """Linked student receives full profile, context, today agenda, and notifications."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        u = User(username="tma_student", email="tma_st@test.org", role="student", is_active=True)
        db.session.add(u)
        db.session.flush()

        up = UserProfile(user_id=u.id, first_name="Алексей", last_name="Учеников", telegram_chat_id=50001)
        db.session.add(up)
        db.session.commit()

    init_data = generate_init_data(user_id=50001, username="tma_student")
    resp = client.post("/tg-app/api/bootstrap", json={"init_data": init_data})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["ok"] is True
    assert data["user"]["username"] == "tma_student"
    assert data["user"]["role"] == "student"
    assert data["context"]["active_context"] == "student"
    assert "student" in data["context"]["available_contexts"]
    assert "today" in data
    assert "notifications" in data


def test_bootstrap_creator_context_switch_and_escalation_guard(client, app, monkeypatch):
    """Creator can switch between creator and teacher context; student cannot escalate."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        creator = User(username="tma_creator", email="tma_cr@test.org", role="creator", is_active=True)
        student = User(username="tma_hacker", email="tma_hk@test.org", role="student", is_active=True)
        db.session.add_all([creator, student])
        db.session.flush()

        db.session.add(UserProfile(user_id=creator.id, first_name="Создатель", telegram_chat_id=50002))
        db.session.add(UserProfile(user_id=student.id, first_name="Студент", telegram_chat_id=50003))
        db.session.commit()

    # 1. Creator requests teacher context
    cr_init_data = generate_init_data(user_id=50002, username="tma_creator")
    resp = client.post("/tg-app/api/bootstrap", json={
        "init_data": cr_init_data,
        "active_context": "teacher",
    })
    assert resp.status_code == 200
    cr_data = resp.get_json()
    assert cr_data["context"]["active_context"] == "teacher"
    assert set(cr_data["context"]["available_contexts"]) == {"creator", "teacher"}

    # 2. Student attempts to request creator context (Escalation guard)
    st_init_data = generate_init_data(user_id=50003, username="tma_hacker")
    resp_st = client.post("/tg-app/api/bootstrap", json={
        "init_data": st_init_data,
        "active_context": "creator",
    })
    assert resp_st.status_code == 200
    st_data = resp_st.get_json()
    assert st_data["context"]["active_context"] == "student"
    assert st_data["context"]["available_contexts"] == ["student"]


# ---------------------------------------------------------------------------
# 4. Student Assignment Detail Endpoint
# ---------------------------------------------------------------------------

def test_student_assignment_detail_flow(client, app, monkeypatch):
    """Student can retrieve assignment details and submission status."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        u = User(username="hw_student", email="hw_st@test.org", role="student", is_active=True)
        db.session.add(u)
        db.session.flush()
        db.session.add(UserProfile(user_id=u.id, first_name="Иван", telegram_chat_id=50010))

        st = Student(name="Иван", user_id=u.id, is_active=True)
        db.session.add(st)
        db.session.flush()

        asg = Assignment(
            title="Домашняя работа №12",
            description="Решите задачу на Python",
            assignment_type="homework",
            created_by_id=u.id,
            deadline=datetime.now(timezone.utc) + timedelta(days=2),
        )
        db.session.add(asg)
        db.session.flush()

        sub = Submission(
            assignment_id=asg.assignment_id,
            student_id=st.student_id,
            status="GRADED",
            percentage=95.0,
            teacher_feedback="Отличный алгоритм! Сложность O(N).",
        )
        db.session.add(sub)
        db.session.commit()
        asg_id = asg.assignment_id

    init_data = generate_init_data(user_id=50010, username="hw_student")
    resp = client.post("/tg-app/api/student/assignment/detail", json={
        "init_data": init_data,
        "assignment_id": asg_id,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["assignment"]["title"] == "Домашняя работа №12"
    assert data["submission"]["percentage"] == 95.0
    assert "Отличный алгоритм" in data["submission"]["teacher_comment"]

    # Request non-existent assignment
    resp_404 = client.post("/tg-app/api/student/assignment/detail", json={
        "init_data": init_data,
        "assignment_id": 999999,
    })
    assert resp_404.status_code == 404


# ---------------------------------------------------------------------------
# 5. Teacher Schedule Endpoint
# ---------------------------------------------------------------------------

def test_teacher_schedule_flow(client, app, monkeypatch):
    """Teacher can fetch agenda with scheduled lessons and room URLs."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        teacher = User(username="t_mentor", email="t_mentor@test.org", role="tutor", is_active=True)
        st_user = User(username="t_stud", email="t_stud@test.org", role="student", is_active=True)
        db.session.add_all([teacher, st_user])
        db.session.flush()

        db.session.add(UserProfile(user_id=teacher.id, first_name="Пётр", telegram_chat_id=50020))
        st = Student(name="Студент Петров", user_id=st_user.id, mentor_id=teacher.id, is_active=True)
        db.session.add(st)
        db.session.flush()

        now = datetime.now(timezone.utc)
        lesson = Lesson(
            student_id=st.student_id,
            lesson_date=now + timedelta(hours=3),
            topic="Разбор динамического программирования",
            status="planned",
        )
        db.session.add(lesson)
        db.session.commit()

    init_data = generate_init_data(user_id=50020, username="t_mentor")
    resp = client.post("/tg-app/api/teacher/schedule", json={"init_data": init_data})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    lessons = data["schedule"]
    assert len(lessons) >= 1
    target = next((l for l in lessons if l["topic"] == "Разбор динамического программирования"), None)
    assert target is not None
    assert target["student_name"] == "Студент Петров"
    assert "lesson_url" in target


# ---------------------------------------------------------------------------
# 6. Parent Child Detail & IDOR Isolation
# ---------------------------------------------------------------------------

def test_parent_child_detail_and_idor_isolation(client, app, monkeypatch):
    """Parent accesses authorized child; access to stranger student is blocked with 403."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        parent = User(username="p_mother", email="p_mother@test.org", role="parent", is_active=True)
        child_user = User(username="p_daughter", email="p_daughter@test.org", role="student", is_active=True)
        stranger_user = User(username="p_stranger", email="p_stranger@test.org", role="student", is_active=True)
        db.session.add_all([parent, child_user, stranger_user])
        db.session.flush()

        db.session.add(UserProfile(user_id=parent.id, first_name="Елена", telegram_chat_id=50030))
        ch_st = Student(name="Мария Дочь", user_id=child_user.id, is_active=True)
        st_other = Student(name="Чужой Ребёнок", user_id=stranger_user.id, is_active=True)
        db.session.add_all([ch_st, st_other])
        db.session.flush()

        # Legitimate tie
        db.session.add(FamilyTie(parent_id=parent.id, student_id=ch_st.student_id, is_confirmed=True))
        db.session.commit()
        child_id = ch_st.student_id
        stranger_id = st_other.student_id

    init_data = generate_init_data(user_id=50030, username="p_mother")

    # 1. Authorized child detail
    resp_ok = client.post("/tg-app/api/parent/child/detail", json={
        "init_data": init_data,
        "student_id": child_id,
    })
    assert resp_ok.status_code == 200
    data = resp_ok.get_json()
    assert data["ok"] is True
    assert data["student"]["student_id"] == child_id
    assert data["student"]["name"] == "Мария Дочь"

    # 2. Unauthorized stranger IDOR check
    resp_forbidden = client.post("/tg-app/api/parent/child/detail", json={
        "init_data": init_data,
        "student_id": stranger_id,
    })
    assert resp_forbidden.status_code == 403
    assert resp_forbidden.get_json().get("error") == "foreign_child_forbidden"


# ---------------------------------------------------------------------------
# 7. Operations Health RBAC
# ---------------------------------------------------------------------------

def test_operations_health_rbac(client, app, monkeypatch):
    """Only Creator / Admin can query system operational health."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)

    with app.app_context():
        creator = User(username="sys_creator", email="sys_cr@test.org", role="creator", is_active=True)
        student = User(username="sys_student", email="sys_st@test.org", role="student", is_active=True)
        db.session.add_all([creator, student])
        db.session.flush()

        db.session.add(UserProfile(user_id=creator.id, telegram_chat_id=50040))
        db.session.add(UserProfile(user_id=student.id, telegram_chat_id=50041))
        db.session.commit()

    # 1. Student is forbidden
    st_init = generate_init_data(user_id=50041, username="sys_student")
    resp_st = client.post("/tg-app/api/operations/health", json={"init_data": st_init})
    assert resp_st.status_code == 403

    # 2. Creator gets operational stats
    cr_init = generate_init_data(user_id=50040, username="sys_creator")
    resp_cr = client.post("/tg-app/api/operations/health", json={"init_data": cr_init})
    assert resp_cr.status_code == 200
    data = resp_cr.get_json()
    assert data["ok"] is True
    assert "summary" in data
    assert "deliveries" in data


# ---------------------------------------------------------------------------
# 8. Bot V3 Mini App Button Builder
# ---------------------------------------------------------------------------

def test_bot_v3_mini_app_button_builder(monkeypatch):
    """Button switches between native WebAppInfo (HTTPS) and browser link (HTTP)."""
    # 1. HTTPS endpoint -> WebAppInfo
    monkeypatch.setenv("APP_URL", "https://boostudy.ru")
    monkeypatch.delenv("TELEGRAM_MINI_APP_URL", raising=False)
    btn_https = build_mini_app_button("Кабинет")
    assert btn_https is not None
    assert btn_https.web_app is not None
    assert btn_https.web_app.url == "https://boostudy.ru/tg-app"

    # 2. HTTP endpoint (local dev) -> fallback browser URL
    monkeypatch.setenv("APP_URL", "http://127.0.0.1:5000")
    btn_http = build_mini_app_button("Кабинет")
    assert btn_http is not None
    assert btn_http.web_app is None
    assert btn_http.url == "http://127.0.0.1:5000/tg-app"
    assert "(браузер)" in btn_http.text


# ---------------------------------------------------------------------------
# 9. Server-Side Telegram ID Allowlist Guard
# ---------------------------------------------------------------------------

def test_telegram_id_allowlist_guard(client, app, monkeypatch):
    """When allowlist is enforced, non-allowlisted Telegram IDs receive 403."""
    monkeypatch.setenv("TELEGRAM_DEV_BOT_TOKEN", TEST_BOT_TOKEN)
    monkeypatch.setenv("TELEGRAM_MINI_APP_ALLOWLIST_ONLY", "1")
    monkeypatch.setenv("TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS", "50050,50051")

    with app.app_context():
        u_allowed = User(username="al_allowed", email="al_al@test.org", role="student", is_active=True)
        u_blocked = User(username="al_blocked", email="al_bl@test.org", role="student", is_active=True)
        db.session.add_all([u_allowed, u_blocked])
        db.session.flush()

        db.session.add(UserProfile(user_id=u_allowed.id, telegram_chat_id=50050))
        db.session.add(UserProfile(user_id=u_blocked.id, telegram_chat_id=50099))
        db.session.commit()

    # 1. Allowlisted ID (50050) succeeds
    init_ok = generate_init_data(user_id=50050, username="al_allowed")
    resp_ok = client.post("/tg-app/api/bootstrap", json={"init_data": init_ok})
    assert resp_ok.status_code == 200

    # 2. Non-allowlisted ID (50099) is rejected with 403
    init_blocked = generate_init_data(user_id=50099, username="al_blocked")
    resp_blocked = client.post("/tg-app/api/bootstrap", json={"init_data": init_blocked})
    assert resp_blocked.status_code == 403
    assert resp_blocked.get_json()["error"] == "telegram_id_not_allowlisted"


# ---------------------------------------------------------------------------
# 10. Mini App Gateway Security Policy Tests
# ---------------------------------------------------------------------------

def test_gateway_path_whitelist_policy():
    """Verify reverse proxy path filter strictly allows Mini App and blocks the rest."""
    from scripts.mini_app_gateway import is_path_permitted, is_method_permitted

    # Permitted paths
    assert is_path_permitted("/tg-app/")[0] is True
    assert is_path_permitted("/tg-app/api/bootstrap")[0] is True
    assert is_path_permitted("/tg-app/api/student/assignment/detail")[0] is True
    assert is_path_permitted("/static/dist/boostudy.css")[0] is True
    assert is_path_permitted("/static/icons/BooStudyLogo1-Photoroom.png")[0] is True
    assert is_path_permitted("/healthz")[0] is True
    assert is_path_permitted("/")[0] is True

    # Blocked paths (Critical isolation check)
    assert is_path_permitted("/admin")[0] is False
    assert is_path_permitted("/admin/users")[0] is False
    assert is_path_permitted("/login")[0] is False
    assert is_path_permitted("/workspace/profile")[0] is False
    assert is_path_permitted("/api/courses")[0] is False
    assert is_path_permitted("/tasks/1")[0] is False
    assert is_path_permitted("/.env")[0] is False

    # Traversal attack prevention
    assert is_path_permitted("/tg-app/../admin")[0] is False
    assert is_path_permitted("/static/../../etc/passwd")[0] is False
    assert is_path_permitted("//admin")[0] is False

    # Method restrictions
    assert is_method_permitted("GET", "/tg-app/") is True
    assert is_method_permitted("HEAD", "/tg-app/") is True
    assert is_method_permitted("POST", "/tg-app/") is False
    assert is_method_permitted("POST", "/tg-app/api/bootstrap") is True
    assert is_method_permitted("DELETE", "/tg-app/api/bootstrap") is False
    assert is_method_permitted("PUT", "/tg-app/api/bootstrap") is False


def test_live_gateway_socket_proxy():
    """Verify live HTTP server of mini_app_gateway strictly enforces policy over socket."""
    import threading
    import urllib.request
    import urllib.error
    from scripts.mini_app_gateway import MiniAppGatewayServer, MiniAppGatewayHandler

    server = MiniAppGatewayServer(('127.0.0.1', 0), MiniAppGatewayHandler, upstream_url='http://127.0.0.1:5000')
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        # 1. /healthz must return 200
        req = urllib.request.Request(f"{base_url}/healthz")
        with opener.open(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "healthy"
            assert data["service"] == "boostudy-mini-app-gateway"

        # 2. /admin must return 403
        try:
            req_admin = urllib.request.Request(f"{base_url}/admin")
            opener.open(req_admin, timeout=5)
            raise AssertionError("/admin should be rejected")
        except urllib.error.HTTPError as e:
            assert e.code == 403
            err_data = json.loads(e.read().decode())
            assert err_data["error"] == "access_denied"

        # 3. /login must return 403
        try:
            req_login = urllib.request.Request(f"{base_url}/login")
            opener.open(req_login, timeout=5)
            raise AssertionError("/login should be rejected")
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # 4. Method restriction: DELETE /tg-app/ must return 405
        try:
            req_del = urllib.request.Request(f"{base_url}/tg-app/", method="DELETE")
            opener.open(req_del, timeout=5)
            raise AssertionError("DELETE should be rejected")
        except urllib.error.HTTPError as e:
            assert e.code == 405

        # 5. Root / must redirect to /tg-app/
        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        no_redirect_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirectHandler)
        try:
            no_redirect_opener.open(f"{base_url}/", timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 302
            assert e.headers.get("Location") == "/tg-app/"

    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# 6. Production Pilot & Feature Flag Security Tests
# ---------------------------------------------------------------------------

def test_mini_app_disabled_feature_flag(client, monkeypatch):
    """When TELEGRAM_MINI_APP_ENABLED=0, shell returns 403 and APIs return mini_app_disabled."""
    monkeypatch.setenv("TELEGRAM_MINI_APP_ENABLED", "0")

    # 1. Shell page
    resp_shell = client.get("/tg-app/")
    assert resp_shell.status_code == 403
    assert "Pilot Access Only" in resp_shell.get_data(as_text=True)

    # 2. Bootstrap API
    resp_api = client.post("/tg-app/api/bootstrap", json={})
    assert resp_api.status_code == 403
    data = resp_api.get_json()
    assert data["ok"] is False
    assert data["error"] == "mini_app_disabled"


def test_mini_app_different_bot_token_rejected(client, app, monkeypatch):
    """initData signed by a dev token or another bot is strictly rejected on production."""
    monkeypatch.setenv("TELEGRAM_MINI_APP_ENABLED", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")

    # Configure production token
    prod_token = "123456789:ProdTokenSecretKeyForBooStudy_prod"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", prod_token)
    monkeypatch.delenv("TELEGRAM_DEV_BOT_TOKEN", raising=False)

    # Attacker tries to use an initData signed by their own dev bot
    dev_token = "987654321:DifferentDevBotTokenAttacker"
    attacker_init_data = generate_init_data(bot_token=dev_token, user_id=854161398, username="creator")

    resp = client.post("/tg-app/api/bootstrap", json={"init_data": attacker_init_data})
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "invalid_init_data"


def test_mini_app_no_ambient_cookie_bypass(client, app, monkeypatch):
    """A valid Flask session cookie for an administrator/creator does NOT bypass Telegram initData."""
    monkeypatch.setenv("TELEGRAM_MINI_APP_ENABLED", "1")

    from app.models import User, db
    with app.app_context():
        creator = User.query.filter_by(role="creator").first()
        if not creator:
            creator = User(username="admin_test_cookie", role="creator", is_active=True)
            creator.set_password("Secret123!")
            db.session.add(creator)
            db.session.commit()
        creator_id = int(creator.id)

    # Login to Flask session
    with client.session_transaction() as sess:
        sess["_user_id"] = str(creator_id)
        sess["user_id"] = creator_id
        sess["_fresh"] = True

    # Attempt to call Mini App API with ambient cookie but no Telegram initData
    resp = client.post("/tg-app/api/bootstrap", json={})
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "invalid_init_data"


def test_cmd_miniapp_pilot_allowlist_guard(monkeypatch):
    """Production bot /miniapp command sends WebAppInfo only to allowlisted users."""
    import asyncio
    monkeypatch.setenv("TELEGRAM_MINI_APP_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_MINI_APP_PILOT_ONLY", "1")
    monkeypatch.setenv("TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS", "854161398")
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", "https://boostudy.ru/tg-app")

    from app.telegram.handlers import cmd_miniapp
    from unittest.mock import AsyncMock, MagicMock

    # 1. Non-allowlisted user (ID 12345)
    unauthorized_user = MagicMock(id=12345)
    unauth_message = MagicMock()
    unauth_message.reply_text = AsyncMock()
    unauth_update = MagicMock(effective_user=unauthorized_user, effective_message=unauth_message)

    asyncio.run(cmd_miniapp(unauth_update, MagicMock()))
    unauth_message.reply_text.assert_not_called()

    # 2. Allowlisted user (ID 854161398)
    authorized_user = MagicMock(id=854161398)
    auth_message = MagicMock()
    auth_message.reply_text = AsyncMock()
    auth_update = MagicMock(effective_user=authorized_user, effective_message=auth_message)

    asyncio.run(cmd_miniapp(auth_update, MagicMock()))
    auth_message.reply_text.assert_called_once()
    kwargs = auth_message.reply_text.call_args.kwargs
    assert kwargs.get("reply_markup") is not None
    button = kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.text == "📱 Открыть Mini App (Pilot)"
    assert button.web_app.url == "https://boostudy.ru/tg-app"



