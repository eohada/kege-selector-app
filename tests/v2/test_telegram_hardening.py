import hashlib
import hmac
import json
import time
from urllib.parse import quote


def test_production_celery_rejects_non_redis(monkeypatch):
    monkeypatch.setenv('CELERY_BROKER_URL', 'memory://')
    monkeypatch.setenv('CELERY_RESULT_BACKEND', '')
    from celery_app import validate_celery_runtime_config

    try:
        validate_celery_runtime_config('production')
    except RuntimeError as exc:
        assert 'CELERY_BROKER_URL' in str(exc)
    else:
        raise AssertionError('production memory broker must be rejected')


def test_polling_preserves_pending_updates_by_default(monkeypatch):
    monkeypatch.delenv('TELEGRAM_POLLING_DROP_PENDING_UPDATES', raising=False)
    from app.telegram.polling import _drop_pending_updates

    assert _drop_pending_updates() is False
    monkeypatch.setenv('TELEGRAM_POLLING_DROP_PENDING_UPDATES', 'true')
    assert _drop_pending_updates() is True


def test_raw_tma_telegram_id_is_rejected(client):
    response = client.post('/api/tma/auth', json={'telegram_id': 12345678})
    assert response.status_code == 403


def test_legacy_webhook_requires_secret(monkeypatch, client):
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('TELEGRAM_WEBHOOK_SECRET', raising=False)
    response = client.post('/webhook/telegram', json={'update_id': 1})
    assert response.status_code == 403


def test_mini_app_rejects_expired_init_data():
    from app.telegram.mini_app import validate_init_data

    token = 'test-token'
    auth_date = int(time.time()) - 90000
    raw_user = json.dumps({'id': 7}, separators=(',', ':'))
    unsigned = f'auth_date={auth_date}&user={quote(raw_user)}'
    check = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    signature = hmac.new(check, f'auth_date={auth_date}\nuser={raw_user}'.encode(), hashlib.sha256).hexdigest()
    assert validate_init_data(f'{unsigned}&hash={signature}', token) is None


def test_linking_service_keeps_user_and_profile_consistent(app):
    from app import db
    from app.models import User, UserProfile
    from app.telegram.linking import link_telegram_identity, unlink_telegram_identity

    with app.app_context():
        user = User(username='link-hardening', email='link-hardening@example.test', role='student', is_active=True)
        db.session.add(user)
        db.session.flush()
        profile = UserProfile(user_id=user.id)
        db.session.add(profile)
        db.session.flush()
        link_telegram_identity(db.session, user=user, profile=profile, chat_id=777001, telegram_username='tester')
        db.session.commit()
        assert user.telegram_id == 777001
        assert user.telegram_chat_id == 777001
        assert user.tg_id == 777001
        assert profile.telegram_chat_id == 777001
        unlink_telegram_identity(db.session, user=user, profile=profile)
        db.session.commit()
        assert not user.telegram_id and not profile.telegram_chat_id
