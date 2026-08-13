"""Referral-code helpers backed exclusively by the production database."""

from __future__ import annotations

import secrets
import string

from app.models import db
from core.db_models import ReferralCode, ReferralUsage


class ReferralCodeError(ValueError):
    """A referral code cannot be used for the requested registration."""


def get_or_create_personal_referral_code(user):
    """Return the user's active personal code, creating one only when needed."""
    if not user or not getattr(user, "id", None):
        return None

    existing = ReferralCode.query.filter_by(creator_id=user.id, is_active=True).order_by(
        ReferralCode.created_at.asc(), ReferralCode.id.asc()
    ).first()
    if existing:
        return existing

    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        code = f"BS-{''.join(secrets.choice(alphabet) for _ in range(8))}"
        if not ReferralCode.query.filter_by(code=code).first():
            referral = ReferralCode(code=code, creator_id=user.id, is_active=True)
            db.session.add(referral)
            db.session.commit()
            return referral

    raise RuntimeError("Unable to generate a unique referral code")


def get_active_referral_code(raw_code: str | None):
    """Return a usable referral code or raise a domain error."""
    code = (raw_code or "").strip().upper()
    if not code:
        return None

    # Registration keeps this row locked until its enclosing transaction commits,
    # so a limited code cannot be consumed past its limit by concurrent requests.
    referral = ReferralCode.query.filter_by(code=code).with_for_update().first()
    if not referral or not referral.is_active:
        raise ReferralCodeError("Реферальный код не найден или отключён.")
    if referral.usage_limit is not None and referral.usage_count >= referral.usage_limit:
        raise ReferralCodeError("Лимит использований этого реферального кода исчерпан.")
    return referral


def apply_referral_code(user, referral: ReferralCode | None) -> bool:
    """Attach one referral usage without committing the caller transaction."""
    if not referral:
        return False
    if not user or not getattr(user, "id", None):
        raise ReferralCodeError("Не удалось применить реферальный код к аккаунту.")
    if referral.creator_id == user.id:
        raise ReferralCodeError("Нельзя применить собственный реферальный код.")
    if ReferralUsage.query.filter_by(referral_code_id=referral.id, user_id=user.id).first():
        return False
    if not referral.is_active or (
        referral.usage_limit is not None and referral.usage_count >= referral.usage_limit
    ):
        raise ReferralCodeError("Реферальный код больше недоступен.")

    referral.usage_count = int(referral.usage_count or 0) + 1
    db.session.add(ReferralUsage(referral_code_id=referral.id, user_id=user.id))

    # Награда за реферала: +50 XP приглашённому, +100 XP пригласившему
    try:
        from app.models import Student
        from app.utils.xp_service import add_xp_to_student
        from app.utils.achievement_service import check_and_grant_dynamic_achievements

        # Награда новому пользователю
        invitee_student = Student.query.filter_by(user_id=user.id).first()
        if invitee_student:
            add_xp_to_student(invitee_student, 50, commit=False)
            check_and_grant_dynamic_achievements(invitee_student, commit=False)

        # Награда рефереру
        if referral.creator_id:
            referrer_student = Student.query.filter_by(user_id=referral.creator_id).first()
            if referrer_student:
                add_xp_to_student(referrer_student, 100, commit=False)
                check_and_grant_dynamic_achievements(referrer_student, commit=False)
    except Exception:
        pass

    return True
