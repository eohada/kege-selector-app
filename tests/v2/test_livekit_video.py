"""
Tests for LiveKit WebRTC video integration in BooStudy lessons.
Validates JWT token generation, role grants, access boundaries, and admin controls.
"""
import jwt
from datetime import datetime, timezone
from app.services.livekit_service import LiveKitService
from tests.v2.test_role_lifecycle_recovery import login_as


def _lesson_fixture(app, role_users):
    from app import db
    from app.models import Lesson

    with app.app_context():
        lesson = Lesson(
            student_id=role_users['student_id'],
            lesson_date=datetime.now(timezone.utc),
            duration=60,
            status='in_progress',
            topic='Тест LiveKit видео',
        )
        db.session.add(lesson)
        db.session.commit()
        return lesson.lesson_id


def test_livekit_service_token_payload():
    """Verify standard JWT claims conform to LiveKit server specifications."""
    room = 'lesson-999'
    identity = 'user-42'
    name = 'Тестовый Учитель'

    token = LiveKitService.create_token(
        room_name=room,
        identity=identity,
        name=name,
        is_teacher=True,
        valid_seconds=3600,
        metadata={'role': 'teacher', 'user_id': 42}
    )

    secret = LiveKitService.get_api_secret()
    payload = jwt.decode(token, secret, algorithms=['HS256'])

    assert payload['iss'] == LiveKitService.get_api_key()
    assert payload['sub'] == identity
    assert payload['name'] == name
    assert payload['exp'] > payload['iat']

    video = payload['video']
    assert video['room'] == room
    assert video['roomJoin'] is True
    assert video['canPublish'] is True
    assert video['canSubscribe'] is True
    assert video['roomAdmin'] is True


def test_livekit_token_endpoint_for_teacher_and_student(app, client, role_users):
    """Teacher and student of the lesson obtain properly scoped LiveKit tokens."""
    lesson_id = _lesson_fixture(app, role_users)

    # 1. Teacher joins
    login_as(client, role_users['tutor_id'], 'tutor')
    resp = client.post(f'/lesson/{lesson_id}/livekit/token')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['room_name'] == f'lesson-{lesson_id}'
    assert data['is_teacher'] is True
    assert 'token' in data
    assert 'url' in data

    # Verify teacher grants
    t_payload = jwt.decode(data['token'], LiveKitService.get_api_secret(), algorithms=['HS256'])
    assert t_payload['video']['roomAdmin'] is True
    assert t_payload['video']['room'] == f'lesson-{lesson_id}'

    # 2. Student joins
    login_as(client, role_users['student_id'], 'student')
    s_resp = client.post(f'/lesson/{lesson_id}/livekit/token')
    assert s_resp.status_code == 200
    s_data = s_resp.get_json()
    assert s_data['success'] is True
    assert s_data['is_teacher'] is False

    # Verify student grants
    s_payload = jwt.decode(s_data['token'], LiveKitService.get_api_secret(), algorithms=['HS256'])
    assert s_payload['video']['roomAdmin'] is False
    assert s_payload['video']['canPublish'] is True
    assert s_payload['video']['canSubscribe'] is True


def test_livekit_token_blocks_unauthorized_user(app, client, role_users):
    """An unrelated user cannot obtain tokens for someone else's lesson room."""
    from app import db
    from app.models import User

    lesson_id = _lesson_fixture(app, role_users)

    with app.app_context():
        outsider = User(username='outsider_student', role='student', email='outsider@example.com')
        db.session.add(outsider)
        db.session.commit()
        outsider_id = outsider.id

    login_as(client, outsider_id, 'student')
    resp = client.post(f'/lesson/{lesson_id}/livekit/token')
    assert resp.status_code == 403


def test_livekit_admin_controls_require_teacher_role(app, client, role_users, monkeypatch):
    """Students cannot trigger administrative room actions (mute/remove/end)."""
    lesson_id = _lesson_fixture(app, role_users)

    # Mock admin calls to avoid hitting offline LiveKit server during unit test
    monkeypatch.setattr(
        LiveKitService,
        'admin_mute_participant',
        lambda room, identity, track, muted: (True, 'Mock muted')
    )
    monkeypatch.setattr(
        LiveKitService,
        'admin_delete_room',
        lambda room: (True, 'Mock ended')
    )

    # Student attempts mute -> 403 Forbidden
    login_as(client, role_users['student_id'], 'student')
    mute_resp = client.post(f'/lesson/{lesson_id}/livekit/admin/mute', json={
        'identity': 'user-123',
        'track_sid': 'TR_123',
        'muted': True
    })
    assert mute_resp.status_code == 403

    # Teacher executes mute -> 200 OK
    login_as(client, role_users['tutor_id'], 'tutor')
    t_mute_resp = client.post(f'/lesson/{lesson_id}/livekit/admin/mute', json={
        'identity': 'user-123',
        'track_sid': 'TR_123',
        'muted': True
    })
    assert t_mute_resp.status_code == 200
    assert t_mute_resp.get_json()['success'] is True

    # Teacher executes end -> 200 OK
    end_resp = client.post(f'/lesson/{lesson_id}/livekit/admin/end')
    assert end_resp.status_code == 200
    assert end_resp.get_json()['success'] is True


def test_lesson_room_renders_livekit_os_window_and_scripts(app, client, role_users):
    """Verify BooStudy OS room includes video-window, floating PiP, dock icons, and LiveKit assets."""
    lesson_id = _lesson_fixture(app, role_users)

    login_as(client, role_users['tutor_id'], 'tutor')
    resp = client.get(f'/lesson/{lesson_id}/room')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # 1. Native Video Window in BooStudy OS
    assert 'id="video-window"' in html
    assert 'lesson-video-titlebar' in html
    assert 'id="livekit-view-lobby"' in html
    assert 'id="livekit-view-call"' in html
    assert 'id="livekit-preview-video"' in html
    assert 'id="livekit-remote-video"' in html
    assert 'id="livekit-local-video"' in html
    assert 'id="livekit-screenshare-view"' in html

    # 2. Controls Toolbar
    assert 'id="livekit-btn-mic"' in html
    assert 'id="livekit-btn-cam"' in html
    assert 'id="livekit-btn-screen"' in html
    assert 'id="livekit-btn-pip"' in html
    assert 'id="livekit-btn-hangup"' in html

    # 3. Floating PiP Widget
    assert 'id="video-floating-pip"' in html
    assert 'id="video-pip-video"' in html
    assert 'id="video-pip-restore"' in html

    # 4. Dock & Header Launchers
    assert 'id="dock-icon-video-window"' in html
    assert 'id="video-window"' in html

    # 5. Local Scripts & Styles (Zero external CDN)
    assert 'lesson-video.css' in html
    assert 'livekit-client.umd.min.js' in html
    assert 'lesson-livekit-os.js' in html
    assert "'video-window'" in html
