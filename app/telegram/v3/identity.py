"""Identity resolution and user tracking for BooStudy Bot V3."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Tuple

from sqlalchemy import or_

from app.models import db, User, UserProfile
from core.db_models import TelegramStartLead
from app.telegram.linking import telegram_identity_is_linked

logger = logging.getLogger(__name__)


def resolve_user_identity(chat_id: int) -> Tuple[User | None, UserProfile | None]:
    """Find the linked User and UserProfile for a given Telegram chat ID.

    Checks canonical UserProfile.telegram_chat_id first, then falls back to User columns.
    """
    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if profile and profile.user:
            return profile.user, profile

        # Fallback to User model legacy columns
        user = User.query.filter(
            or_(
                User.telegram_chat_id == chat_id,
                User.telegram_id == chat_id,
                User.tg_id == chat_id,
            )
        ).first()

        if user:
            prof = getattr(user, 'profile', None) or UserProfile.query.filter_by(user_id=user.id).first()
            return user, prof

        return None, None
    except Exception as e:
        logger.error("Error resolving identity for chat_id=%s: %s", chat_id, e, exc_info=True)
        return None, None


def touch_interaction(chat_id: int) -> None:
    """Record user activity timestamp without throwing errors."""
    try:
        profile = UserProfile.query.filter_by(telegram_chat_id=chat_id).first()
        if profile:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            profile.telegram_last_interaction_at = now_utc
            if getattr(profile, "telegram_blocked_at", None) is not None:
                profile.telegram_blocked_at = None
                logger.info("telegram_user_unblocked_bot chat_id=%s: cleared block status", chat_id)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.debug("touch_interaction failed for chat_id=%s: %s", chat_id, e)


def record_start_lead(
    chat_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    user_id: int | None = None,
) -> None:
    """Record Telegram lead for conversion tracking and audit."""
    try:
        lead = TelegramStartLead.query.filter_by(telegram_chat_id=chat_id).first()
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if not lead:
            lead = TelegramStartLead(
                telegram_chat_id=chat_id,
                telegram_username=username,
                first_name=first_name,
                last_name=last_name,
                assigned_user_id=user_id,
                is_authorized=bool(user_id),
                first_interaction_at=now_utc,
                last_interaction_at=now_utc,
            )
            db.session.add(lead)
        else:
            lead.last_interaction_at = now_utc
            if username:
                lead.telegram_username = username
            if first_name:
                lead.first_name = first_name
            if last_name:
                lead.last_name = last_name
            if user_id:
                lead.assigned_user_id = user_id
                lead.is_authorized = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.debug("record_start_lead failed for chat_id=%s: %s", chat_id, e)


def get_display_name(user: User, profile: UserProfile | None = None) -> str:
    """Get a clean, human-friendly display name for the user."""
    if profile and profile.first_name:
        if profile.last_name:
            return f"{profile.first_name} {profile.last_name}".strip()
        return profile.first_name.strip()
    full_name = getattr(user, 'full_name', None)
    if full_name and full_name.strip():
        return full_name.strip()
    return user.username or "пользователь"
