"""EventContext, self-notification suppression, and semantic deduplication policy.

Ensures that:
1. Actors never receive redundant Telegram notifications for actions they initiated themselves.
2. If actor is unknown/None, we never guess the recipient as actor.
3. Multi-role users (e.g. Creator + Admin + Teacher) receive at most one notification per semantic event.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from core.db_models import utc_now

logger = logging.getLogger(__name__)

# Events where the actor already knows they took the action and does NOT want a Telegram echo
_SELF_SUPPRESSED_KINDS = frozenset({
    "lesson_scheduled",
    "lesson_rescheduled",
    "lesson_cancelled",
    "homework_submitted",
    "assignment_submitted",
    "homework_checked",
    "assignment_graded",
    "homework_returned",
    "assignment_returned",
    "assignment_assigned",
})

# Role specificity order when resolving multi-role recipients for an educational event
ROLE_SPECIFICITY_ORDER = ("student", "teacher", "parent", "admin", "creator")


@dataclass(frozen=True)
class EventContext:
    """Carries full provenance of an educational or system event."""
    event_kind: str
    actor_user_id: Optional[int] = None
    actor_role: Optional[str] = None
    subject_user_id: Optional[int] = None
    entity_type: Optional[str] = None  # lesson, submission, task, billing, etc.
    entity_id: Optional[int] = None
    batch_id: Optional[str] = None
    source: str = "web"  # web, bot, scheduler, celery, admin_action
    occurred_at: datetime = field(default_factory=utc_now)


def should_suppress_notification(
    event_ctx: EventContext,
    recipient_user_id: int,
    recipient_role: Optional[str] = None,
) -> tuple[bool, str]:
    """Decide whether a notification should be suppressed.

    Returns:
        (should_suppress: bool, reason: str)
    """
    if recipient_user_id is None:
        return True, "recipient_user_id_missing"

    # Rule 1: Never guess recipient as actor if actor is unknown
    if event_ctx.actor_user_id is None:
        return False, "ok_actor_unknown"

    # Rule 2: Suppress self-notifications for actor-initiated actions
    if int(event_ctx.actor_user_id) == int(recipient_user_id):
        kind = (event_ctx.event_kind or "").strip().lower()
        if kind in _SELF_SUPPRESSED_KINDS:
            reason = f"self_action_suppressed: actor {event_ctx.actor_user_id} performed {kind}"
            logger.info(
                "telegram_delivery_suppressed_self_action recipient_user_id=%s actor_id=%s kind=%s",
                recipient_user_id,
                event_ctx.actor_user_id,
                kind,
            )
            return True, reason

    return False, "ok_allowed"


def make_semantic_dedupe_key(
    recipient_user_id: int,
    event_ctx: EventContext,
) -> str:
    """Build a deterministic semantic deduplication key for an event.

    Ensures that for a specific business event and recipient, only one message is delivered
    regardless of how many roles the recipient possesses.
    """
    kind = (event_ctx.event_kind or "generic").lower().strip()
    e_type = (event_ctx.entity_type or "none").lower().strip()
    e_id = str(event_ctx.entity_id or "0")
    batch = str(event_ctx.batch_id or "")
    return f"telegram:semantic:{recipient_user_id}:{kind}:{e_type}:{e_id}:{batch}"


def resolve_recipients_and_deduplicate(
    candidate_recipients: list[dict[str, Any]],
    event_ctx: EventContext,
) -> list[dict[str, Any]]:
    """Filter out suppressed recipients and deduplicate multi-role deliveries to the same user.

    candidate_recipients: list of dicts with at least:
        {'user_id': int, 'role': str, ...}
    Returns:
        list of filtered, deduplicated recipient dicts with the most appropriate role context.
    """
    # Group by user_id
    by_user: dict[int, list[dict[str, Any]]] = {}
    for cand in candidate_recipients:
        uid = cand.get("user_id")
        if uid is None:
            continue
        uid = int(uid)
        by_user.setdefault(uid, []).append(cand)

    result: list[dict[str, Any]] = []

    for uid, roles_list in by_user.items():
        # 1. Check self-suppression
        suppress, reason = should_suppress_notification(event_ctx, uid)
        if suppress:
            logger.info("Skipping recipient %s for %s due to %s", uid, event_ctx.event_kind, reason)
            continue

        # 2. Pick the most specific role context for this user
        chosen = _select_primary_role_context(roles_list, event_ctx)
        if chosen:
            # Attach semantic dedupe key to chosen item
            chosen["semantic_dedupe_key"] = make_semantic_dedupe_key(uid, event_ctx)
            result.append(chosen)

    return result


def _select_primary_role_context(
    candidates: list[dict[str, Any]],
    event_ctx: EventContext,
) -> dict[str, Any]:
    """Select the single most relevant recipient candidate for a multi-role user."""
    if len(candidates) == 1:
        return dict(candidates[0])

    # If event targets a subject_user_id, match it first
    if event_ctx.subject_user_id is not None:
        for c in candidates:
            if c.get("role") == "student" and c.get("user_id") == event_ctx.subject_user_id:
                return dict(c)

    # Sort by specificity order
    def _rank(cand: dict[str, Any]) -> int:
        role = str(cand.get("role", "")).lower()
        if role in ROLE_SPECIFICITY_ORDER:
            return ROLE_SPECIFICITY_ORDER.index(role)
        return len(ROLE_SPECIFICITY_ORDER) + 1

    sorted_candidates = sorted(candidates, key=_rank)
    return dict(sorted_candidates[0])
