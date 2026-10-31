"""Exact bridges between source skill identifiers and curriculum ExamSkills."""

from __future__ import annotations

import re
from typing import Any


_EXAM_SKILL_ID = re.compile(r"exam-skill:([1-9][0-9]*)\Z")


def resolve_course_skill_ids(
    source_skill_ids: list[str],
    course_skills: list[Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Resolve source IDs only through canonical IDs or an exact curated topic_code.

    No title, text similarity, subject, or suffix matching is used. Duplicate
    topic codes in the lesson remain ambiguous and are rejected.
    """
    from app.ai_lab.practice import practice_skill_topic_code

    all_by_id = {
        f"exam-skill:{int(skill.skill_id)}": skill
        for skill in course_skills
        if getattr(skill, "skill_id", None) is not None
    }
    active_by_id = {
        skill_id: skill for skill_id, skill in all_by_id.items()
        if getattr(skill, "is_active", True) is not False
    }
    by_topic_code: dict[str, dict[str, Any]] = {}
    for skill_id, skill in active_by_id.items():
        topic_code = str(getattr(skill, "topic_code", None) or "").strip()
        if topic_code:
            by_topic_code.setdefault(topic_code, {})[skill_id] = skill

    resolved_ids: list[str] = []
    details: list[dict[str, Any]] = []
    for source_id in sorted({str(value).strip() for value in source_skill_ids if str(value).strip()}):
        direct = _EXAM_SKILL_ID.fullmatch(source_id)
        if direct:
            if source_id in active_by_id:
                skill = active_by_id[source_id]
                topic_code = str(getattr(skill, "topic_code", None) or "").strip() or None
                resolved_ids.append(source_id)
                details.append({
                    "evidence_skill_id": source_id,
                    "course_skill_id": source_id,
                    "topic_code": topic_code,
                    "status": "resolved",
                    "method": "canonical_exam_skill_id",
                })
            elif source_id in all_by_id:
                details.append({
                    "evidence_skill_id": source_id,
                    "topic_code": None,
                    "status": "inactive_course_skill",
                    "reason": "Навык курса отключён и не может принимать новые свидетельства.",
                })
            else:
                details.append({
                    "evidence_skill_id": source_id,
                    "topic_code": None,
                    "status": "course_skill_not_linked",
                    "reason": "Этот навык не связан с проверяемым уроком.",
                })
            continue

        topic_code = practice_skill_topic_code(source_id)
        method = "curated_practice_topic_code" if topic_code else None
        if not topic_code and source_id in by_topic_code:
            topic_code = source_id
            method = "canonical_topic_code"
        if not topic_code:
            details.append({
                "evidence_skill_id": source_id,
                "topic_code": None,
                "status": "unmapped_source_skill",
                "reason": "Для этого идентификатора не задан точный topic_code; сопоставление по названию не выполняется.",
            })
            continue

        candidates = by_topic_code.get(topic_code, {})
        if len(candidates) == 1:
            course_skill_id = next(iter(candidates))
            resolved_ids.append(course_skill_id)
            details.append({
                "evidence_skill_id": source_id,
                "course_skill_id": course_skill_id,
                "topic_code": topic_code,
                "status": "resolved",
                "method": method,
            })
        elif len(candidates) > 1:
            details.append({
                "evidence_skill_id": source_id,
                "topic_code": topic_code,
                "candidate_course_skill_ids": sorted(candidates),
                "status": "ambiguous_topic_code",
                "reason": "В уроке несколько навыков с одинаковым topic_code; нужна явная связь.",
            })
        else:
            details.append({
                "evidence_skill_id": source_id,
                "topic_code": topic_code,
                "status": "topic_code_not_linked_to_lesson",
                "reason": "Код известен, но соответствующий ExamSkill не связан с этим уроком.",
            })

    return list(dict.fromkeys(resolved_ids)), details
