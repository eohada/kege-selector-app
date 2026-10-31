"""Read-only adapter for explicitly allowlisted synthetic BooStudy lessons."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from flask import current_app, has_app_context

from app.ai_lab.config import setting
from app.ai_lab.provider import is_local_ai_lab_enabled
from core.db_models import Lesson


def _configured_ids(name: str) -> set[int]:
    if not has_app_context():
        return set()
    raw = current_app.config.get(name)
    if raw is None:
        raw = setting(name, "")
    values = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, (list, tuple, set)) else []
    result = set()
    for value in values:
        try:
            identifier = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if identifier > 0:
            result.add(identifier)
    return result


def resolve_synthetic_lesson_source(lesson_id: Any) -> dict[str, Any] | None:
    """Resolve an allowlisted BooStudy lesson only when it belongs to a demo student."""
    if not has_app_context() or not is_local_ai_lab_enabled():
        return None
    try:
        identifier = int(lesson_id)
    except (TypeError, ValueError, OverflowError):
        return None
    if identifier not in _configured_ids("AI_LAB_SYNTHETIC_LESSON_IDS"):
        return None
    student_ids = _configured_ids("AI_LAB_SYNTHETIC_LESSON_STUDENT_IDS")
    if not student_ids:
        return None

    lesson = Lesson.query.filter(
        Lesson.lesson_id == identifier,
        Lesson.student_id.in_(student_ids),
    ).first()
    student = lesson.student if lesson else None
    user = student.user if student else None
    if not lesson or not student or not user or not user.is_active:
        return None
    alias = str(user.username or "")
    if not alias.startswith("demo_student_"):
        return None

    source_content = {
        "topic": lesson.topic or "",
        "content": lesson.content or "",
        "homework": lesson.homework or "",
        "studio_scenario": lesson.studio_scenario or "",
    }
    source_revision = hashlib.sha256(
        json.dumps(source_content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "lesson_id": identifier,
        "lesson_ref": f"boostudy-lesson:{identifier}",
        "subject_id": f"platform-student:{user.id}",
        "title": str(lesson.topic or f"Урок BooStudy #{identifier}")[:300],
        "student_alias": alias[:80],
        "source_identity": {
            "source_table": "Lessons",
            "source_record_id": str(identifier),
            "source_revision_sha256": source_revision,
            "student_alias": alias[:80],
        },
    }


def list_synthetic_lesson_sources() -> list[dict[str, Any]]:
    """Return only explicitly allowlisted lesson/student pairs for the local AI Lab UI."""
    if not has_app_context() or not is_local_ai_lab_enabled():
        return []
    lesson_ids = sorted(_configured_ids("AI_LAB_SYNTHETIC_LESSON_IDS"))
    return [source for identifier in lesson_ids
            if (source := resolve_synthetic_lesson_source(identifier)) is not None]
