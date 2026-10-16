"""
Automated tests for local BooStudy Telegram polling and account linking workflows.
Covers: code generation, verification, SQLite synchronization, unlinking, re-linking,
case/prefix tolerance, expiration, and conflict isolation.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.models import User, UserProfile
from app.telegram.linking import (
    TelegramLinkConflict,
    link_telegram_identity,
    unlink_telegram_identity,
    telegram_identity_is_linked,
)


@pytest.fixture()
def test_user(app):
    with app.app_context():
        from app import db
        user = User(
            username='local_student_test',
            email='local_student@boostudy.test',
            role='student',
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()

        profile = UserProfile(user_id=user.id)
        db.session.add(profile)
        db.session.commit()

        yield user.id


def test_flask_generates_valid_link_code(client, app, test_user):
    """1. Генерация кода локальным Flask эндпоинтом /api/telegram/link-code."""
    with app.app_context():
        from flask_login import login_user
        from app import db
        user = db.session.get(User, test_user)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user)
        sess['_fresh'] = True

    response = client.post('/api/telegram/link-code')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['code'].startswith('BS-')
    assert len(data['code']) in (9, 10)  # 'BS-' + 6 hex chars
    assert data['expires_in'] == 900

    with app.app_context():
        from app import db
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        assert profile.telegram_link_code == data['code']
        assert profile.telegram_link_code_expires is not None


def test_telegram_process_reads_and_links_code(app, test_user):
    """2. Чтение кода Telegram-процессом и 3. Успешная привязка с синхронизацией колонок."""
    from app.telegram.handlers import _try_link_by_code
    from app import db

    code_val = "BS-A1B2C3"
    with app.app_context():
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        profile.telegram_link_code = code_val
        profile.telegram_link_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.commit()

    # Create mock Telegram Update
    mock_update = MagicMock()
    mock_update.effective_chat.id = 99887766
    mock_update.effective_user.id = 99887766
    mock_update.effective_user.username = "local_tester_tg"
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    import asyncio
    with app.app_context():
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, code_val))
        assert res is True

        user = db.session.get(User, test_user)
        profile = UserProfile.query.filter_by(user_id=test_user).first()

        # All canonical and legacy columns must be consistent
        assert user.tg_id == 99887766
        assert user.telegram_id == 99887766
        assert user.telegram_chat_id == 99887766
        assert user.telegram_linked_at is not None
        assert profile.telegram_chat_id == 99887766
        assert profile.telegram_id == "@local_tester_tg"

        # Code must be cleared so it cannot be re-used
        assert profile.telegram_link_code is None
        assert profile.telegram_link_code_expires is None


def test_used_code_cannot_be_reused(app, test_user):
    """4. Повторное использование использованного кода запрещено."""
    from app.telegram.handlers import _try_link_by_code

    mock_update = MagicMock()
    mock_update.effective_chat.id = 99887766
    mock_update.effective_user.id = 99887766
    mock_update.effective_user.username = "local_tester_tg"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    import asyncio
    with app.app_context():
        # Code does not exist in DB (or already consumed)
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, "BS-CONSUMED"))
        assert res is False
        mock_update.message.reply_text.assert_called_once()
        assert "не найден или недействителен" in mock_update.message.reply_text.call_args[0][0]


def test_unlink_and_relink_flow(app, test_user):
    """5. Отвязка и 6. Повторная привязка новым кодом."""
    from app import db
    from app.telegram.handlers import _try_link_by_code
    import asyncio

    with app.app_context():
        user = db.session.get(User, test_user)
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        link_telegram_identity(
            db.session,
            user=user,
            profile=profile,
            chat_id=12345001,
            telegram_username="student_1",
        )
        db.session.commit()

        assert telegram_identity_is_linked(user, profile) is True

        # Perform unlink
        unlink_telegram_identity(db.session, user=user, profile=profile)
        db.session.commit()

        assert telegram_identity_is_linked(user, profile) is False
        assert user.tg_id is None
        assert profile.telegram_chat_id is None

        # Generate new link code
        profile.telegram_link_code = "BS-NEWLINK"
        profile.telegram_link_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.commit()

    # Relink with new code
    mock_update = MagicMock()
    mock_update.effective_chat.id = 12345001
    mock_update.effective_user.id = 12345001
    mock_update.effective_user.username = "student_1"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with app.app_context():
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, "BS-NEWLINK"))
        assert res is True
        user = db.session.get(User, test_user)
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        assert user.tg_id == 12345001
        assert profile.telegram_chat_id == 12345001


def test_expired_code_is_rejected(app, test_user):
    """Истекший код отклоняется с предупреждением об истечении срока."""
    from app import db
    from app.telegram.handlers import _try_link_by_code
    import asyncio

    with app.app_context():
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        profile.telegram_link_code = "BS-EXPIRED"
        # Expired 1 hour ago
        profile.telegram_link_code_expires = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.commit()

    mock_update = MagicMock()
    mock_update.effective_chat.id = 555555
    mock_update.effective_user.id = 555555
    mock_update.effective_user.username = "late_user"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with app.app_context():
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, "BS-EXPIRED"))
        assert res is False
        assert "истек" in mock_update.message.reply_text.call_args[0][0].lower()


def test_case_insensitive_and_bare_code_tolerance(app, test_user):
    """Пользователь может ввести код в нижнем регистре или без префикса BS-."""
    from app import db
    from app.telegram.handlers import _try_link_by_code
    import asyncio

    with app.app_context():
        profile = UserProfile.query.filter_by(user_id=test_user).first()
        profile.telegram_link_code = "BS-99AA88"
        profile.telegram_link_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.commit()

    mock_update = MagicMock()
    mock_update.effective_chat.id = 444333
    mock_update.effective_user.id = 444333
    mock_update.effective_user.username = "case_user"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with app.app_context():
        # User typed lowercase without BS- prefix: "99aa88"
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, "99aa88"))
        assert res is True
        user = db.session.get(User, test_user)
        assert user.tg_id == 444333


def test_telegram_link_conflict_handled_gracefully(app, test_user):
    """Конфликт привязки (chat_id уже занят другим аккаунтом) выводит понятное сообщение."""
    from app import db
    from app.telegram.handlers import _try_link_by_code
    import asyncio

    with app.app_context():
        # Create a second user who already holds chat_id 777111
        user_two = User(
            username='existing_tg_holder',
            email='holder@boostudy.test',
            role='student',
            tg_id=777111,
            telegram_id=777111,
            telegram_chat_id=777111,
        )
        db.session.add(user_two)
        db.session.flush()
        profile_two = UserProfile(user_id=user_two.id, telegram_chat_id=777111)
        db.session.add(profile_two)

        # Give test_user a link code
        profile_one = UserProfile.query.filter_by(user_id=test_user).first()
        profile_one.telegram_link_code = "BS-CONFLICT"
        profile_one.telegram_link_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.commit()

    mock_update = MagicMock()
    mock_update.effective_chat.id = 777111
    mock_update.effective_user.id = 777111
    mock_update.effective_user.username = "someone_else"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    with app.app_context():
        res = asyncio.run(_try_link_by_code(mock_update, mock_context, "BS-CONFLICT"))
        assert res is False
        assert "уже привязан" in mock_update.message.reply_text.call_args[0][0]


def test_dev_token_precedence(monkeypatch):
    """8. Отказ от запуска при небезопасном использовании общего токена:
    TELEGRAM_DEV_BOT_TOKEN имеет приоритет над боевым токеном."""
    import importlib
    monkeypatch.setenv('TELEGRAM_DEV_BOT_TOKEN', '1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '2222222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB')
    monkeypatch.setenv('MAIN_BOT_TOKEN', '3333333333:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC')

    import app.telegram.config as tg_conf
    importlib.reload(tg_conf)

    assert tg_conf.MAIN_BOT_TOKEN == '1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'


def test_check_telegram_status_diagnostics(monkeypatch):
    """Диагностический скрипт возвращает корректную структуру данных."""
    from scripts.check_telegram_status import get_diagnostics
    diag = get_diagnostics()

    assert 'token_source' in diag
    assert 'is_dev_token' in diag
    assert 'masked_token' in diag
    assert 'db_exists' in diag
    assert 'db_path' in diag
    assert 'backend_running' in diag
