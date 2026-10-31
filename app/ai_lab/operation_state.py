"""Bounded, explicit retry handling for persisted AI Lab generation operations."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import update

from app.ai_lab.config import ai_lab_limits
from core.db_models import AiLabExperiment, db


DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_RUN_LEASE_SECONDS = 15 * 60
RETRYABLE_PROVIDER_CODES = frozenset({
    "connection_failed", "connection_timeout", "response_timeout", "network_error",
    "provider_unavailable", "provider_rate_limited", "queue_timeout", "queue_full",
    "queue_cancelled", "invalid_provider_response",
})


def initial_operation_state() -> dict[str, Any]:
    limits = ai_lab_limits()
    return {"attempt_count": 1, "max_attempts": limits.get("operation_max_attempts", DEFAULT_MAX_ATTEMPTS),
            "last_started_at": datetime.now(timezone.utc).isoformat(), "retryable": False}


def claim_retry(record: AiLabExperiment) -> bool:
    """Claim one explicit retry, or report that the saved operation should be reused.

    A fresh ``running`` row is never retried by a page refresh. A stale lease is
    treated as an interrupted attempt. The conditional update prevents two local
    requests from both claiming a failed/stale row.
    """
    if record.status == "succeeded":
        return False
    quality = copy.deepcopy(record.quality_json or {})
    operation = dict(quality.get("operation") or {})
    attempts = max(1, int(operation.get("attempt_count") or 1))
    now = datetime.now(timezone.utc)
    limits = ai_lab_limits()
    max_attempts = limits.get("operation_max_attempts", DEFAULT_MAX_ATTEMPTS)
    lease_seconds = limits.get("operation_lease_seconds", DEFAULT_RUN_LEASE_SECONDS)
    retryable = bool(operation.get("retryable"))
    if not operation and record.status in {"failed", "invalid_response"}:
        retryable = record.status == "invalid_response" or record.error_code in RETRYABLE_PROVIDER_CODES
    if record.status == "running":
        try:
            started = datetime.fromisoformat(str(operation.get("last_started_at") or ""))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            started = record.updated_at or record.created_at
            if started and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        if started and (now - started).total_seconds() < lease_seconds:
            return False
        retryable = True
    if not retryable or attempts >= max_attempts or record.updated_at is None:
        return False

    operation.update({"attempt_count": attempts + 1, "max_attempts": max_attempts,
                      "last_started_at": now.isoformat(), "retryable": False})
    quality["operation"] = operation
    claimed = db.session.execute(
        update(AiLabExperiment)
        .where(AiLabExperiment.id == record.id,
               AiLabExperiment.status == record.status,
               AiLabExperiment.updated_at == record.updated_at)
        .values(status="running", updated_at=now, quality_json=quality,
                error_code=None, error_message=None, validation_status="pending")
    )
    if claimed.rowcount != 1:
        db.session.rollback()
        db.session.refresh(record)
        return False
    db.session.commit()
    db.session.refresh(record)
    return True


def mark_operation_failure(record: AiLabExperiment, exc: Exception) -> bool:
    """Persist whether one user-requested retry is safe and still available."""
    quality = copy.deepcopy(record.quality_json or {})
    operation = dict(quality.get("operation") or initial_operation_state())
    code = str(getattr(exc, "code", ""))
    status_code = getattr(exc, "status_code", None)
    invalid_response = record.status == "invalid_response"
    retryable = code in RETRYABLE_PROVIDER_CODES or (isinstance(status_code, int) and status_code >= 500) or invalid_response
    attempts = max(1, int(operation.get("attempt_count") or 1))
    max_attempts = ai_lab_limits().get("operation_max_attempts", DEFAULT_MAX_ATTEMPTS)
    operation["max_attempts"] = max_attempts
    operation["retryable"] = bool(retryable and attempts < max_attempts)
    operation["last_error_code"] = code or record.error_code
    quality["operation"] = operation
    record.quality_json = quality
    return operation["retryable"]
