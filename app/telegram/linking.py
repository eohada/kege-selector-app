"""Canonical Telegram identity linking shared by web and bot surfaces."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_

from core.db_models import User, UserProfile


class TelegramLinkConflict(ValueError):
    """The Telegram identity is already attached to another active account."""


def _identity_conflict(session, user_id: int, chat_id: int):
    profile = (
        session.query(UserProfile)
        .filter(
            UserProfile.telegram_chat_id == int(chat_id),
            UserProfile.user_id != int(user_id),
        )
        .first()
    )
    if profile:
        return profile.user_id

    user = (
        session.query(User)
        .filter(
            User.id != int(user_id),
            or_(
                User.telegram_id == int(chat_id),
                User.telegram_chat_id == int(chat_id),
                User.tg_id == int(chat_id),
            ),
        )
        .first()
    )
    return user.id if user else None


def link_telegram_identity(
    session,
    *,
    user: User,
    profile: UserProfile,
    chat_id: int,
    telegram_username: str | None = None,
    telegram_user_id: int | None = None,
) -> None:
    """Write one consistent identity to the canonical and legacy columns.

    The caller owns the transaction. Ambiguous identities are rejected rather
    than silently moving a Telegram account between BooStudy users.
    """
    chat_id = int(chat_id)
    conflict_user_id = _identity_conflict(session, int(user.id), chat_id)
    if conflict_user_id is not None:
        raise TelegramLinkConflict('telegram_identity_already_linked')

    linked_at = datetime.now(timezone.utc)
    user.tg_id = chat_id
    user.telegram_id = chat_id
    user.telegram_chat_id = chat_id
    user.telegram_linked_at = linked_at

    profile.telegram_chat_id = chat_id
    username = (telegram_username or '').strip().lstrip('@')
    profile.telegram_id = f'@{username}' if username else str(telegram_user_id or chat_id)
    profile.telegram_link_code = None
    profile.telegram_link_code_expires = None
    profile.telegram_link_token = None
    profile.telegram_link_token_expires = None


def unlink_telegram_identity(session, *, user: User, profile: UserProfile | None = None) -> None:
    """Revoke the Telegram identity in every supported storage column."""
    user.tg_id = None
    user.telegram_id = None
    user.telegram_chat_id = None
    user.telegram_linked_at = None

    profile = profile or session.query(UserProfile).filter_by(user_id=user.id).first()
    if not profile:
        return
    profile.telegram_id = None
    profile.telegram_chat_id = None
    profile.telegram_link_code = None
    profile.telegram_link_code_expires = None
    profile.telegram_link_token = None
    profile.telegram_link_token_expires = None


def telegram_identity_is_linked(user: User | None, profile: UserProfile | None) -> bool:
    return bool(
        profile and profile.telegram_chat_id
    ) or bool(
        user and (user.telegram_chat_id or user.telegram_id or user.tg_id)
    )
