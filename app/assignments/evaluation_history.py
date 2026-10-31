"""Append-only, explicit provenance for answer evaluations."""
from __future__ import annotations

from typing import Any

from core.db_models import AnswerEvaluationRevision, db, utc_now


_METHODS = {
    "teacher_manual",
    "teacher_reviewed_without_score",
    "automatic_answer_checker",
    "python_test_suite",
    "code_judge",
    "awaiting_teacher_review",
    "automatic_check_unavailable",
}
_STATES = {"current", "voided"}


def current_answer_evaluation(answer_id: int) -> AnswerEvaluationRevision | None:
    return (AnswerEvaluationRevision.query
            .filter_by(answer_id=int(answer_id), state="current")
            .order_by(AnswerEvaluationRevision.revision_no.desc())
            .first())


def record_answer_evaluation(answer: Any, *, method: str, actor_user_id: int | None,
                             score: int | None, max_score: int | None,
                             is_correct: bool | None, teacher_comment: str | None = None,
                             state: str = "current") -> AnswerEvaluationRevision:
    """Supersede the prior current result and record the new explicit source."""
    if method not in _METHODS or state not in _STATES:
        raise ValueError("Неизвестный способ или статус происхождения оценки.")
    if answer.answer_id is None:
        db.session.flush()
    answer_id = int(answer.answer_id)
    latest = (AnswerEvaluationRevision.query.filter_by(answer_id=answer_id)
              .order_by(AnswerEvaluationRevision.revision_no.desc())
              .with_for_update().first())
    if (latest and latest.state == state and latest.method == method
            and latest.actor_user_id == actor_user_id and latest.score == score
            and latest.max_score == max_score and latest.is_correct == is_correct
            and latest.teacher_comment == teacher_comment):
        return latest

    now = utc_now()
    current_rows = AnswerEvaluationRevision.query.filter_by(answer_id=answer_id, state="current").with_for_update().all()
    for row in current_rows:
        row.state = "superseded"
        row.superseded_at = now
    revision = AnswerEvaluationRevision(
        answer_id=answer_id,
        revision_no=(int(latest.revision_no) + 1) if latest else 1,
        method=method,
        actor_user_id=int(actor_user_id) if actor_user_id is not None else None,
        score=score,
        max_score=max_score,
        is_correct=is_correct,
        teacher_comment=teacher_comment,
        state=state,
        supersedes_revision_id=int(latest.revision_id) if latest else None,
        created_at=now,
    )
    db.session.add(revision)
    db.session.flush()
    return revision
