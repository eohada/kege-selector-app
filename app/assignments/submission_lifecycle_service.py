"""
Centralized submission lifecycle helpers.
"""

from __future__ import annotations

from app.constants import SubmissionStatus


class SubmissionLifecycleError(ValueError):
    """Raised when a status transition is not allowed."""


def normalize_legacy_status(status: str | None) -> str | None:
    """Normalize legacy statuses to canonical ones."""
    if status is None:
        return None
    normalized = str(status).strip().upper()
    if normalized == 'LATE':
        return SubmissionStatus.SUBMITTED
    if normalized == 'AUTO_GRADED':
        return SubmissionStatus.GRADED
    return normalized


def ensure_canonical_status(status: str | None) -> str:
    normalized = normalize_legacy_status(status)
    if normalized not in SubmissionStatus.ALL:
        raise SubmissionLifecycleError(f'Unknown submission status: {status!r}')
    return normalized


def can_transition(current_status: str | None, next_status: str | None) -> bool:
    current = ensure_canonical_status(current_status)
    target = ensure_canonical_status(next_status)
    if current == target:
        return True
    return target in SubmissionStatus.ALLOWED_TRANSITIONS.get(current, set())


def transition_submission_status(submission, next_status: str, *, force: bool = False) -> str:
    """
    Change submission status with transition guard.

    Returns applied canonical status.
    """
    current = ensure_canonical_status(getattr(submission, 'status', None))
    target = ensure_canonical_status(next_status)
    if not force and not can_transition(current, target):
        raise SubmissionLifecycleError(f'Transition not allowed: {current} -> {target}')
    submission.status = target
    return target
