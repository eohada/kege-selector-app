"""Role context resolution and management for BooStudy Bot V3."""
from __future__ import annotations

import logging
from typing import Tuple

from app.models import db, User
from app.telegram.application import (
    resolve_active_context,
    available_contexts,
)

logger = logging.getLogger(__name__)


def get_user_contexts(user: User) -> Tuple[str, ...]:
    """Get all legitimate, RBAC-verified role contexts available to the user."""
    return available_contexts(user)


def get_active_context(user: User, user_data: dict | None = None) -> str:
    """Determine the active role context, checking session preference and server RBAC."""
    preferred = None
    if user_data and "v3_active_context" in user_data:
        preferred = user_data.get("v3_active_context")
    return resolve_active_context(user, preferred)


def switch_context(user: User, target_context: str, user_data: dict | None = None) -> str:
    """Safely switch the active context for multi-role users or Creator mode.

    Server-side verification prevents any privilege escalation.
    """
    target = target_context.strip().lower()
    allowed = available_contexts(user)

    if target not in allowed:
        logger.warning(
            "User %s (roles=%s) attempted unauthorized context switch to %s",
            user.id, getattr(user, 'role', ''), target,
        )
        return resolve_active_context(user)

    # If user is creator switching between management and teaching:
    actual_roles = {str(r).lower() for r in (user.roles() if hasattr(user, "roles") else [user.role])}
    if "creator" in actual_roles:
        if target == "teacher":
            user.creator_bot_mode = "TEACHER"
        elif target == "creator":
            user.creator_bot_mode = "ADMIN"
        try:
            db.session.commit()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.debug("Failed to commit creator_bot_mode change for user %s: %s", user.id, e)

    resolved = resolve_active_context(user, target)
    if user_data is not None:
        user_data["v3_active_context"] = resolved
    return resolved


def toggle_creator_mode(user: User, user_data: dict | None = None) -> str:
    """Quick toggle for Creator between Creator management and Teacher modes."""
    current_mode = str(getattr(user, "creator_bot_mode", "")).upper()
    new_target = "creator" if current_mode == "TEACHER" else "teacher"
    return switch_context(user, new_target, user_data)
