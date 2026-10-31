"""Local source-backed knowledge base for Tutor Core and AI Lab review."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timezone
from typing import Any

from sqlalchemy import func

from app.ai_lab.knowledge_data import (
    DEEPENED_ENTRIES,
    FIPI_COVERAGE_2026,
    KNOWLEDGE_DATA_VERSION,
    SEED_ENTRIES,
    SOURCES,
)
from core.db_models import (
    AiLabKnowledgeEntry,
    AiLabKnowledgeReviewEvent,
    AiLabKnowledgeSource,
    AiLabKnowledgeVersion,
    db,
    utc_now,
)


RETRIEVAL_DECISIONS = frozenset({"source_checked", "reviewed", "approved"})
RETRIEVABLE_SOURCE_STATUSES = frozenset({
    "official_final", "official_methodical_guide", "primary_standard",
    "primary_documentation", "platform_snapshot",
})
EDITORIAL_DECISIONS = frozenset({"in_review", "rework", "reviewed", "approved", "rejected", "retired"})
EDITORIAL_CRITERIA = (
    {"key": "subject_accuracy", "label": "Предметная правильность"},
    {"key": "exam_alignment", "label": "Соответствие актуальному ЕГЭ"},
    {"key": "prerequisite_completeness", "label": "Полнота предпосылок"},
    {"key": "solution_correctness", "label": "Корректность решения"},
    {"key": "learner_explanation", "label": "Объяснение для ученика"},
    {"key": "teacher_explanation", "label": "Пояснение для преподавателя"},
    {"key": "misconception_realism", "label": "Реалистичность типичных ошибок"},
    {"key": "diagnostic_utility", "label": "Полезность диагностики"},
    {"key": "recommendation_basis", "label": "Обоснованность рекомендаций"},
    {"key": "applicability_boundary", "label": "Границы применимости"},
    {"key": "source_quality", "label": "Корректность источников"},
    {"key": "test_evidence", "label": "Наличие тестовых подтверждений"},
)
REVIEW_STATES = frozenset({"unchecked", "checked", "needs_work", "not_applicable"})
_GENERIC_SEARCH_TERMS = frozenset({
    "python", "числ", "значен", "дан", "решен", "пример", "задач", "услов", "провер",
    "таблиц", "маск", "файл", "код", "ответ", "метод", "вход", "выход", "систем", "ноль", "сравнен",
})
ENTRY_CONTENT_FIELDS = frozenset({
    "learning_goal", "explanation", "examples", "misconceptions", "diagnostics",
    "interventions", "assessment_boundary",
})
OPTIONAL_ENTRY_CONTENT_FIELDS = frozenset({"prerequisites", "lesson_links", "task_links", "platform_task_links"})
FULL_ENTRY_CONTENT_FIELDS = frozenset({
    "assessed_skill", "solution_steps", "student_explanation", "teacher_explanation",
    "diagnostic_patterns", "subject_checks", "curriculum_suggestions", "skill_progression",
})
OPTIONAL_ENTRY_CONTENT_FIELDS |= FULL_ENTRY_CONTENT_FIELDS
_STOP_WORDS = frozenset({
    "для", "или", "это", "как", "что", "при", "если", "над", "под", "все", "его", "её", "они",
    "почему",
    "with", "from", "that", "this", "the", "and", "for", "not", "are", "was", "use",
})


class KnowledgeBaseError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _status_for_version(version_id: int) -> tuple[str, dict[str, Any] | None]:
    event = (AiLabKnowledgeReviewEvent.query
             .filter_by(version_id=version_id)
             .order_by(AiLabKnowledgeReviewEvent.id.desc())
             .first())
    if event is None:
        return "draft", None
    return event.decision, {
        "decision": event.decision,
        "rationale": event.rationale,
        "details": event.review_details_json or {},
        "created_at": _iso(event.created_at),
        "reviewer_user_id": event.reviewer_user_id,
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def ensure_seeded_knowledge_base() -> None:
    """Insert missing pinned sources and first source-checked notes; never overwrite history."""
    for source_data in SOURCES:
        source = AiLabKnowledgeSource.query.filter_by(
            source_key=source_data["source_key"], edition=source_data["edition"],
        ).first()
        if source is None:
            db.session.add(AiLabKnowledgeSource(**source_data))
    db.session.flush()
    source_keys = {item.source_key for item in AiLabKnowledgeSource.query.all()}

    for seed in SEED_ENTRIES:
        if any(key not in source_keys for key in seed["source_refs"]):
            raise KnowledgeBaseError("seed_source_missing", "Для начальной записи не найден указанный источник.", 500)
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key=seed["stable_key"]).first()
        if entry is None:
            entry = AiLabKnowledgeEntry(
                stable_key=seed["stable_key"], codifier_codes_json=seed["codes"], entry_kind="concept",
            )
            db.session.add(entry)
            db.session.flush()
        first_version = AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=1).first()
        if first_version is None:
            content = seed["content"]
            _validate_content(content)
            digest = hashlib.sha256(_canonical_json({
                "title": seed["title"], "content": content,
                "source_refs": seed["source_refs"], "tags": seed["tags"],
            }).encode("utf-8")).hexdigest()
            version = AiLabKnowledgeVersion(
                entry_id=entry.id, version_no=1, title=seed["title"], content_json=content,
                source_refs_json=seed["source_refs"], tags_json=seed["tags"],
                content_sha256=digest,
                change_reason=f"Стартовый материал {KNOWLEDGE_DATA_VERSION}; педагогическая апробация не заявляется.",
            )
            db.session.add(version)
            db.session.flush()
            db.session.add(AiLabKnowledgeReviewEvent(
                version_id=version.id,
                decision="source_checked",
                reviewer_user_id=None,
                rationale=("Первичная сверка фактических опор с указанными источниками и локальными примерами. "
                           "Это не экспертная педагогическая оценка и не разрешение на публикацию ученикам."),
            ))

    for seed in DEEPENED_ENTRIES:
        if any(key not in source_keys for key in seed["source_refs"]):
            raise KnowledgeBaseError("seed_source_missing", "Для углублённой записи не найден указанный источник.", 500)
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key=seed["stable_key"]).first()
        if entry is None:
            entry = AiLabKnowledgeEntry(
                stable_key=seed["stable_key"], codifier_codes_json=seed["codes"], entry_kind="concept",
            )
            db.session.add(entry)
            db.session.flush()
        version_no = int(seed["version_no"])
        if AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=version_no).first() is not None:
            continue
        content = _validate_content(seed["content"])
        digest = hashlib.sha256(_canonical_json({
            "title": seed["title"], "content": content,
            "source_refs": seed["source_refs"], "tags": seed["tags"],
        }).encode("utf-8")).hexdigest()
        version = AiLabKnowledgeVersion(
            entry_id=entry.id, version_no=version_no, title=seed["title"], content_json=content,
            source_refs_json=seed["source_refs"], tags_json=seed["tags"], content_sha256=digest,
            change_reason=seed["change_reason"],
        )
        db.session.add(version)
        db.session.flush()
        db.session.add(AiLabKnowledgeReviewEvent(
            version_id=version.id, decision="source_checked", reviewer_user_id=None,
            rationale=("Системная проверка фактических формулировок и локальных вычислительных примеров "
                       "по перечисленным первичным источникам. Связи с уроками подтверждают только "
                       "структуру курса; ссылки на задания отмечены предварительными. Это не "
                       "экспертная педагогическая оценка и не разрешение на публикацию ученикам."),
        ))
    db.session.commit()


def ensure_tutor_core3_knowledge() -> None:
    """Seed only Tutor Core 3.0 revisions without changing frozen KB controls."""
    from app.ai_lab.knowledge_data import TUTOR_CORE3_ENTRIES

    source_keys = {item.source_key for item in AiLabKnowledgeSource.query.all()}
    for seed in TUTOR_CORE3_ENTRIES:
        missing = sorted(set(seed["source_refs"]) - source_keys)
        if missing:
            raise KnowledgeBaseError(
                "tutor_core3_source_missing",
                "Для Tutor Core 3.0 не найдены источники: " + ", ".join(missing) + ".",
                500,
            )
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key=seed["stable_key"]).first()
        if entry is None:
            entry = AiLabKnowledgeEntry(
                stable_key=seed["stable_key"],
                codifier_codes_json=seed["codes"],
                entry_kind="concept",
            )
            db.session.add(entry)
            db.session.flush()
        version_no = int(seed["version_no"])
        if AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id, version_no=version_no).first() is not None:
            continue
        content = _validate_content(seed["content"])
        digest = hashlib.sha256(_canonical_json({
            "title": seed["title"], "content": content,
            "source_refs": seed["source_refs"], "tags": seed["tags"],
        }).encode("utf-8")).hexdigest()
        version = AiLabKnowledgeVersion(
            entry_id=entry.id,
            version_no=version_no,
            title=seed["title"],
            content_json=content,
            source_refs_json=seed["source_refs"],
            tags_json=seed["tags"],
            content_sha256=digest,
            change_reason=seed["change_reason"],
        )
        db.session.add(version)
        db.session.flush()
        db.session.add(AiLabKnowledgeReviewEvent(
            version_id=version.id,
            decision="source_checked",
            reviewer_user_id=None,
            rationale=(
                "Tutor Core 3.0: отдельная системная проверка фактов и примеров. "
                "Это не экспертная педагогическая оценка и не разрешение на публикацию. "
                "Ссылки на проект ФИПИ-2027 остаются проектными и не получают статус approved."
            ),
        ))
    db.session.commit()


def _validate_content(content: Any) -> dict[str, Any]:
    if (not isinstance(content, dict)
            or not ENTRY_CONTENT_FIELDS.issubset(content)
            or set(content) - ENTRY_CONTENT_FIELDS - OPTIONAL_ENTRY_CONTENT_FIELDS):
        raise KnowledgeBaseError("invalid_content_shape", "Заполните цель, объяснение, примеры, заблуждения, диагностику, вмешательства и границы применимости.")
    expanded_fields = set(content) & FULL_ENTRY_CONTENT_FIELDS
    if expanded_fields and expanded_fields != FULL_ENTRY_CONTENT_FIELDS:
        missing = ", ".join(sorted(FULL_ENTRY_CONTENT_FIELDS - expanded_fields))
        raise KnowledgeBaseError("incomplete_pedagogical_card", f"Полноценная карточка должна включать все педагогические поля: {missing}.")
    result: dict[str, Any] = {}
    for field in ("learning_goal", "explanation", "assessment_boundary"):
        value = content.get(field)
        limit = 2_000 if field == "explanation" else 700
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise KnowledgeBaseError("invalid_content_text", f"Поле «{field}» должно содержать текст не длиннее {limit} символов.")
        result[field] = value.strip()
    list_fields = {
        "examples": (6, {"prompt", "reasoning", "answer", "checks"}),
        "misconceptions": (8, {"belief", "counterexample", "correction"}),
        "diagnostics": (6, {"prompt", "signals"}),
        "interventions": (6, {"signal", "action"}),
    }
    for field, (maximum, keys) in list_fields.items():
        values = content.get(field)
        if not isinstance(values, list) or not values or len(values) > maximum:
            raise KnowledgeBaseError("invalid_content_list", f"Поле «{field}» должно содержать от 1 до {maximum} элементов.")
        normalized = []
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict) or set(item) != keys:
                raise KnowledgeBaseError("invalid_content_item", f"Элемент {index} в «{field}» имеет неверную структуру.")
            row = {}
            for key, value in item.items():
                if key == "checks":
                    if not isinstance(value, list) or not value or len(value) > 8 or any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in value):
                        raise KnowledgeBaseError("invalid_content_item", f"У примера {index} список checks должен содержать 1–8 коротких пунктов.")
                    row[key] = [x.strip() for x in value]
                elif not isinstance(value, str) or not value.strip() or len(value) > 900:
                    raise KnowledgeBaseError("invalid_content_item", f"Поле «{key}» элемента {index} должно содержать короткий текст.")
                else:
                    row[key] = value.strip()
            normalized.append(row)
        result[field] = normalized
    result["prerequisites"] = _string_refs(content.get("prerequisites", []), "prerequisites", 8)
    result["lesson_links"] = _knowledge_links(content.get("lesson_links", []), "lesson_links", has_lesson=True)
    result["task_links"] = _knowledge_links(content.get("task_links", []), "task_links", has_lesson=False)
    result["platform_task_links"] = _platform_task_links(content.get("platform_task_links", []))
    if expanded_fields:
        skill = content["assessed_skill"]
        skill_keys = {"skill_key", "name", "observable_actions"}
        if (not isinstance(skill, dict) or set(skill) != skill_keys
                or not isinstance(skill.get("skill_key"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,159}", skill["skill_key"])
                or not isinstance(skill.get("name"), str) or not skill["name"].strip()
                or len(skill["name"]) > 240):
            raise KnowledgeBaseError("invalid_assessed_skill", "Укажите стабильный ключ, название и наблюдаемые действия проверяемого навыка.")
        skill_actions = _short_string_list(skill.get("observable_actions"), "observable_actions", 6, 300)
        if not skill_actions:
            raise KnowledgeBaseError("invalid_assessed_skill", "Добавьте хотя бы одно наблюдаемое действие навыка.")
        result["assessed_skill"] = {
            "skill_key": skill["skill_key"], "name": skill["name"].strip(),
            "observable_actions": skill_actions,
        }
        result["solution_steps"] = _short_string_list(content["solution_steps"], "solution_steps", 8, 700, minimum=2)
        for field in ("student_explanation", "teacher_explanation"):
            value = content[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 2_000:
                raise KnowledgeBaseError("invalid_pedagogical_explanation", f"Поле «{field}» должно содержать текст не длиннее 2000 символов.")
            result[field] = value.strip()
        patterns = content["diagnostic_patterns"]
        pattern_keys = {"response_pattern", "interpretation", "follow_up"}
        if not isinstance(patterns, list) or not patterns or len(patterns) > 8:
            raise KnowledgeBaseError("invalid_diagnostic_patterns", "Укажите от 1 до 8 различимых диагностических паттернов.")
        result["diagnostic_patterns"] = []
        for index, item in enumerate(patterns, 1):
            if not isinstance(item, dict) or set(item) != pattern_keys:
                raise KnowledgeBaseError("invalid_diagnostic_patterns", f"Диагностический паттерн {index} имеет неверную структуру.")
            row = {}
            for key in pattern_keys:
                value = item[key]
                if not isinstance(value, str) or not value.strip() or len(value) > 700:
                    raise KnowledgeBaseError("invalid_diagnostic_patterns", f"Поле «{key}» паттерна {index} должно содержать короткое пояснение.")
                row[key] = value.strip()
            result["diagnostic_patterns"].append(row)
        checks = content["subject_checks"]
        check_keys = {"test_id", "method", "scope"}
        if not isinstance(checks, list) or not checks or len(checks) > 8:
            raise KnowledgeBaseError("invalid_subject_checks", "Свяжите материал хотя бы с одной независимой предметной проверкой.")
        result["subject_checks"] = []
        for index, item in enumerate(checks, 1):
            if (not isinstance(item, dict) or set(item) != check_keys
                    or not isinstance(item.get("test_id"), str)
                    or not re.fullmatch(r"kb-[a-z0-9][a-z0-9-]{2,100}", item["test_id"])):
                raise KnowledgeBaseError("invalid_subject_checks", f"Предметная проверка {index} имеет неверный идентификатор или структуру.")
            row = {"test_id": item["test_id"]}
            for key in ("method", "scope"):
                value = item[key]
                if not isinstance(value, str) or not value.strip() or len(value) > 500:
                    raise KnowledgeBaseError("invalid_subject_checks", f"Поле «{key}» проверки {index} должно содержать пояснение.")
                row[key] = value.strip()
            result["subject_checks"].append(row)
        result["curriculum_suggestions"] = _short_string_list(
            content["curriculum_suggestions"], "curriculum_suggestions", 8, 500,
        )
        progression = content["skill_progression"]
        expected_stages = ("concept", "routine", "choice", "transfer", "verification")
        if (not isinstance(progression, list) or len(progression) != len(expected_stages)
                or any(not isinstance(item, dict) or set(item) != {"stage_key", "description"}
                       for item in progression)
                or tuple(item["stage_key"] for item in progression) != expected_stages
                or any(not isinstance(item["description"], str) or not item["description"].strip()
                       or len(item["description"]) > 500 for item in progression)):
            raise KnowledgeBaseError("invalid_skill_progression", "Укажите пять последовательных ступеней: понятие, стандартное действие, выбор метода, перенос и проверка.")
        result["skill_progression"] = [{
            "stage_key": item["stage_key"], "description": item["description"].strip(),
        } for item in progression]
    return result


def _short_string_list(value: Any, field: str, maximum: int, item_limit: int, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise KnowledgeBaseError("invalid_content_list", f"Поле «{field}» должно содержать от {minimum} до {maximum} элементов.")
    if any(not isinstance(item, str) or not item.strip() or len(item) > item_limit for item in value):
        raise KnowledgeBaseError("invalid_content_list", f"Поле «{field}» содержит пустой или слишком длинный элемент.")
    return list(dict.fromkeys(item.strip() for item in value))


def _string_refs(value: Any, field: str, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise KnowledgeBaseError("invalid_content_refs", f"Поле «{field}» должно содержать не более {maximum} ссылок.")
    refs = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,159}", item):
            raise KnowledgeBaseError("invalid_content_refs", f"Поле «{field}» содержит недопустимый стабильный ключ.")
        refs.append(item)
    return list(dict.fromkeys(refs))


def _knowledge_links(value: Any, field: str, *, has_lesson: bool) -> list[dict[str, Any]]:
    maximum = 12
    required = {"course_id", "skill_id", "relationship", "rationale"}
    required.add("lesson_id" if has_lesson else "task_number")
    if not isinstance(value, list) or len(value) > maximum:
        raise KnowledgeBaseError("invalid_content_links", f"Поле «{field}» должно содержать не более {maximum} связей.")
    rows = []
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise KnowledgeBaseError("invalid_content_links", f"Поле «{field}» имеет неверную структуру.")
        course_id = item.get("course_id")
        entity_id = item.get("lesson_id" if has_lesson else "task_number")
        skill_id = item.get("skill_id")
        relationship = item.get("relationship")
        rationale = item.get("rationale")
        if (not isinstance(course_id, int) or course_id <= 0
                or not isinstance(entity_id, int) or entity_id <= 0
                or not isinstance(skill_id, str) or not re.fullmatch(r"exam-skill:[1-9][0-9]*", skill_id)
                or relationship not in {"curriculum", "preliminary"}
                or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 500):
            raise KnowledgeBaseError("invalid_content_links", f"Поле «{field}» содержит недопустимую связь.")
        rows.append({
            "course_id": course_id,
            "lesson_id" if has_lesson else "task_number": entity_id,
            "skill_id": skill_id,
            "relationship": relationship,
            "rationale": rationale.strip(),
        })
    return rows


def _platform_task_links(value: Any) -> list[dict[str, Any]]:
    required = {
        "task_id", "content_fingerprint", "source_key", "course_id", "course_version",
        "lesson_id", "skill_id", "relationship", "rationale",
    }
    if not isinstance(value, list) or len(value) > 20:
        raise KnowledgeBaseError("invalid_content_links", "Поле «platform_task_links» должно содержать не более 20 связей.")
    rows = []
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise KnowledgeBaseError("invalid_content_links", "Поле «platform_task_links» имеет неверную структуру.")
        integer_fields = ("task_id", "course_id", "course_version", "lesson_id")
        if (any(type(item.get(field)) is not int or item[field] <= 0 for field in integer_fields)
                or not isinstance(item.get("content_fingerprint"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", item["content_fingerprint"])
                or not isinstance(item.get("source_key"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", item["source_key"])
                or not isinstance(item.get("skill_id"), str)
                or not re.fullmatch(r"exam-skill:[1-9][0-9]*", item["skill_id"])
                or item.get("relationship") != "source_checked"
                or not isinstance(item.get("rationale"), str)
                or not item["rationale"].strip() or len(item["rationale"]) > 500):
            raise KnowledgeBaseError("invalid_content_links", "Поле «platform_task_links» содержит недопустимую точную связь.")
        rows.append({**item, "rationale": item["rationale"].strip()})
    return rows


def _latest_versions() -> list[tuple[AiLabKnowledgeEntry, AiLabKnowledgeVersion]]:
    max_versions = (db.session.query(
        AiLabKnowledgeVersion.entry_id.label("entry_id"),
        func.max(AiLabKnowledgeVersion.version_no).label("version_no"),
    ).group_by(AiLabKnowledgeVersion.entry_id).subquery())
    rows = (db.session.query(AiLabKnowledgeEntry, AiLabKnowledgeVersion)
            .join(max_versions, AiLabKnowledgeEntry.id == max_versions.c.entry_id)
            .join(AiLabKnowledgeVersion, (AiLabKnowledgeVersion.entry_id == max_versions.c.entry_id)
                  & (AiLabKnowledgeVersion.version_no == max_versions.c.version_no))
            .order_by(AiLabKnowledgeEntry.stable_key.asc()).all())
    return rows


def _source_map(keys: list[str] | None = None) -> dict[str, AiLabKnowledgeSource]:
    query = AiLabKnowledgeSource.query
    if keys is not None:
        if not keys:
            return {}
        query = query.filter(AiLabKnowledgeSource.source_key.in_(set(keys)))
    return {source.source_key: source for source in query.all()}


def _entry_snapshot(
    entry: AiLabKnowledgeEntry,
    version: AiLabKnowledgeVersion,
    include_content: bool = True,
    include_review_history: bool = False,
) -> dict[str, Any]:
    decision, last_review = _status_for_version(version.id)
    source_refs = version.source_refs_json or []
    sources = _source_map(source_refs)
    result = {
        "id": entry.id,
        "stable_key": entry.stable_key,
        "kind": entry.entry_kind,
        "codifier_codes": entry.codifier_codes_json or [],
        "version_id": version.id,
        "version_no": version.version_no,
        "title": version.title,
        "status": decision,
        "source_refs": [{
            "source_key": source.source_key,
            "edition": source.edition,
            "title": source.title,
            "publisher": source.publisher,
            "url": source.url,
            "source_status": source.source_status,
        } for source in (sources[key] for key in source_refs if key in sources)],
        "tags": version.tags_json or [],
        "content_sha256": version.content_sha256,
        "change_reason": version.change_reason,
        "created_at": _iso(version.created_at),
        "latest_review": last_review,
    }
    if include_content:
        result["content"] = version.content_json
    if include_review_history:
        events = (AiLabKnowledgeReviewEvent.query.filter_by(version_id=version.id)
                  .order_by(AiLabKnowledgeReviewEvent.id.desc()).all())
        result["review_history"] = [{
            "decision": event.decision,
            "rationale": event.rationale,
            "details": event.review_details_json or {},
            "reviewer_user_id": event.reviewer_user_id,
            "created_at": _iso(event.created_at),
        } for event in events]
    return result


def list_knowledge_entries(include_content: bool = True) -> list[dict[str, Any]]:
    rows = _latest_versions()
    return [_entry_snapshot(entry, version, include_content=include_content) for entry, version in rows]


def knowledge_snapshot() -> dict[str, Any]:
    from app.ai_lab.knowledge_audit import audit_results_for, expert_pilot_dossiers_for

    ensure_seeded_knowledge_base()
    entries = list_knowledge_entries()
    technical_audits = audit_results_for(entries)
    expert_pilot_dossiers = expert_pilot_dossiers_for(entries)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for code in entry["codifier_codes"]:
            by_code.setdefault(code, []).append(entry)
    verified_bindings = source_checked_platform_task_bindings()
    verified_binding_keys = {item["knowledge_stable_key"] for item in verified_bindings}
    entry_keys = {item["stable_key"] for item in entries}
    contents = [item["content"] for item in entries]
    full_structural_cards = sum(
        bool(content.get("assessed_skill") and content.get("solution_steps")
             and content.get("student_explanation") and content.get("teacher_explanation")
             and content.get("diagnostic_patterns"))
        for content in contents
    )
    coverage = []
    for code, title, included in FIPI_COVERAGE_2026:
        linked = by_code.get(code, [])
        linked_keys = {item["stable_key"] for item in linked}
        code_audit_history = [item for item in technical_audits if item["stable_key"] in linked_keys]
        code_audits = [item for item in code_audit_history if item["matches_current_version"]]
        states = [item["status"] for item in linked]
        all_content = [item["content"] for item in linked]
        full_cards = [
            item for item in all_content
            if item.get("assessed_skill") and item.get("solution_steps")
            and item.get("student_explanation") and item.get("teacher_explanation")
            and item.get("diagnostic_patterns")
        ]
        reviewed_count = sum(status in {"reviewed", "approved"} for status in states)
        approved_count = sum(status == "approved" for status in states)
        coverage.append({
            "code": code,
            "title": title,
            "in_fipi_2026_kim": included,
            "status": "has_material" if linked else "not_developed",
            "entry_count": len(linked),
            "entry_titles": [entry["title"] for entry in linked],
            "materials": [{
                "stable_key": item["stable_key"],
                "title": item["title"],
                "version_no": item["version_no"],
                "status": item["status"],
            } for item in linked],
            "quality": {
                "full_card_count": len(full_cards),
                "example_count": sum(len(content.get("examples") or []) for content in all_content),
                "examples_with_authored_checks": sum(
                    bool(example.get("checks"))
                    for content in all_content for example in (content.get("examples") or [])
                ),
                "diagnostic_count": sum(
                    len(content.get("diagnostics") or []) + len(content.get("diagnostic_patterns") or [])
                    for content in all_content
                ),
                "prerequisite_map_count": sum(bool(content.get("prerequisites")) for content in all_content),
                "machine_check_status": "current" if code_audits else (
                    "outdated" if code_audit_history else "not_recorded"
                ),
                "machine_check_case_count": len(code_audits),
                "machine_check_outdated_count": len(code_audit_history) - len(code_audits),
                "reviewed_count": reviewed_count,
                "approved_count": approved_count,
                "preliminary_task_link_count": sum(
                    len(content.get("task_links") or []) for content in all_content
                ),
                "verified_task_binding_count": sum(
                    sum(
                        binding["knowledge_stable_key"] == item["stable_key"]
                        for binding in verified_bindings
                    ) for item in linked
                ),
            },
        })
    sources = [{
        "source_key": source.source_key, "edition": source.edition, "title": source.title,
        "publisher": source.publisher, "url": source.url, "source_status": source.source_status,
        "content_sha256": source.content_sha256, "metadata": source.metadata_json or {},
    } for source in AiLabKnowledgeSource.query.order_by(AiLabKnowledgeSource.source_key.asc()).all()]
    section_titles = {
        "1": "Цифровая грамотность",
        "2": "Теоретические основы информатики",
        "3": "Алгоритмы и программирование",
        "4": "Информационные технологии",
    }
    coverage_groups = [{
        "code": section,
        "title": title,
        "items": [row for row in coverage if row["code"].startswith(f"{section}.")],
    } for section, title in section_titles.items()]
    return {
        "data_version": KNOWLEDGE_DATA_VERSION,
        "sources": sources,
        "coverage": coverage,
        "coverage_groups": coverage_groups,
        "entries": entries,
        "technical_audits": technical_audits,
        "expert_pilot_dossiers": expert_pilot_dossiers,
        "counts": {
            "coverage_items": len(coverage),
            "included_in_2026": sum(1 for row in coverage if row["in_fipi_2026_kim"]),
            "content_started": sum(1 for row in coverage if row["status"] != "not_developed"),
            "content_gaps": sum(1 for row in coverage if row["status"] == "not_developed"),
            "materials": len(entries),
            "full_structural_cards": full_structural_cards,
            "authored_examples": sum(len(content.get("examples") or []) for content in contents),
            "examples_with_authored_checks": sum(
                bool(example.get("checks"))
                for content in contents for example in (content.get("examples") or [])
            ),
            "diagnostics": sum(
                len(content.get("diagnostics") or []) + len(content.get("diagnostic_patterns") or [])
                for content in contents
            ),
            "prerequisite_maps": sum(bool(content.get("prerequisites")) for content in contents),
            "machine_check_results_recorded": len(technical_audits),
            "machine_check_results_current": sum(item["matches_current_version"] for item in technical_audits),
            "machine_check_results_outdated": sum(not item["matches_current_version"] for item in technical_audits),
            "expert_pilot_dossiers": len(expert_pilot_dossiers),
            "expert_pilot_dossiers_current": sum(item["matches_current_version"] for item in expert_pilot_dossiers),
            "reviewed_materials": sum(item["status"] in {"reviewed", "approved"} for item in entries),
            "approved_for_student_use": sum(1 for item in entries if item["status"] == "approved"),
            "pending_review_materials": sum(
                item["status"] in {"draft", "source_checked", "in_review", "rework", "reviewed"} for item in entries
            ),
            "awaiting_owner_decision": sum(item["status"] == "reviewed" for item in entries),
            "verified_task_bindings": sum(binding["knowledge_stable_key"] in entry_keys for binding in verified_bindings),
            "sources": len(sources),
        },
        "status_labels": {
            "not_developed": "Нет учебного материала",
            "has_material": "Есть связь с материалом",
            "draft": "Черновик",
            "in_review": "Проверка начата",
            "rework": "Возвращено на доработку",
            "source_checked": "Источники сверены · без педагогического утверждения",
            "reviewed": "Экспертно проверено",
            "approved": "Утверждено владельцем",
            "rejected": "Отклонено",
            "retired": "Снято с использования",
        },
        "editorial_criteria": list(EDITORIAL_CRITERIA),
    }


def knowledge_entry_history(entry_id: int) -> dict[str, Any]:
    entry = db.session.get(AiLabKnowledgeEntry, entry_id)
    if entry is None:
        raise KnowledgeBaseError("entry_not_found", "Материал не найден.", 404)
    versions = (AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id)
                .order_by(AiLabKnowledgeVersion.version_no.desc()).all())
    return {
        "stable_key": entry.stable_key,
        "versions": [_entry_snapshot(entry, version, include_review_history=True) for version in versions],
    }


def create_knowledge_version(actor_id: int, payload: Any) -> AiLabKnowledgeVersion:
    if not isinstance(payload, dict):
        raise KnowledgeBaseError("invalid_payload", "Ожидался объект материала.")
    stable_key = str(payload.get("stable_key") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,159}", stable_key):
        raise KnowledgeBaseError("invalid_stable_key", "Стабильный ключ: латиница, цифры, точка, дефис или подчёркивание; от 3 до 160 символов.")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 240:
        raise KnowledgeBaseError("invalid_title", "Заголовок обязателен и не должен превышать 240 символов.")
    reason = payload.get("change_reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) < 8 or len(reason.strip()) > 500:
        raise KnowledgeBaseError("invalid_change_reason", "Укажите причину изменения длиной 8–500 символов.")
    content = _validate_content(payload.get("content"))
    source_refs = payload.get("source_refs")
    tags = payload.get("tags")
    if not isinstance(source_refs, list) or not source_refs or any(not isinstance(x, str) for x in source_refs):
        raise KnowledgeBaseError("source_required", "Добавьте хотя бы один подтверждающий источник.")
    source_refs = list(dict.fromkeys(x.strip() for x in source_refs if x.strip()))
    sources = _source_map(source_refs)
    if len(sources) != len(source_refs):
        raise KnowledgeBaseError("unknown_source", "Один из выбранных источников отсутствует в проверенном каталоге.")
    if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in tags):
        raise KnowledgeBaseError("invalid_tags", "Укажите не более 30 коротких ключевых слов.")
    tags = list(dict.fromkeys(x.strip() for x in tags))

    entry = AiLabKnowledgeEntry.query.filter_by(stable_key=stable_key).first()
    if entry is None:
        codes = payload.get("codifier_codes", [])
        known_codes = {item[0] for item in FIPI_COVERAGE_2026}
        if not isinstance(codes, list) or any(code not in known_codes for code in codes):
            raise KnowledgeBaseError("invalid_codes", "Свяжите материал только с кодами кодификатора ЕГЭ 2026.")
        entry = AiLabKnowledgeEntry(
            stable_key=stable_key,
            codifier_codes_json=list(dict.fromkeys(codes)),
            entry_kind="concept",
        )
        db.session.add(entry)
        db.session.flush()
        version_no = 1
    else:
        version_no = int(db.session.query(func.max(AiLabKnowledgeVersion.version_no))
                         .filter_by(entry_id=entry.id).scalar() or 0) + 1
    digest = hashlib.sha256(_canonical_json({
        "stable_key": stable_key, "version_no": version_no, "title": title.strip(),
        "content": content, "source_refs": source_refs, "tags": tags,
    }).encode("utf-8")).hexdigest()
    version = AiLabKnowledgeVersion(
        entry_id=entry.id, version_no=version_no, title=title.strip(), content_json=content,
        source_refs_json=source_refs, tags_json=tags, content_sha256=digest,
        change_reason=reason.strip(), created_by_user_id=actor_id,
    )
    db.session.add(version)
    db.session.commit()
    return version


def _normalize_review_details(details: Any, decision: str) -> dict[str, dict[str, str]]:
    if details is None:
        details = {}
    if not isinstance(details, dict) or len(details) > len(EDITORIAL_CRITERIA):
        raise KnowledgeBaseError("invalid_review_details", "Замечания должны быть объектом с полями редакционной проверки.")
    allowed_keys = {criterion["key"] for criterion in EDITORIAL_CRITERIA}
    if set(details) - allowed_keys:
        raise KnowledgeBaseError("invalid_review_details", "Замечания содержат неизвестный раздел; обновите редактор и повторите сохранение.")
    normalized: dict[str, dict[str, str]] = {}
    for criterion in EDITORIAL_CRITERIA:
        key = criterion["key"]
        item = details.get(key, {})
        if not isinstance(item, dict):
            raise KnowledgeBaseError("invalid_review_details", f"Некорректный раздел проверки «{criterion['label']}».")
        status = str(item.get("status") or "unchecked")
        comment = str(item.get("comment") or "").strip()
        if status not in REVIEW_STATES or len(comment) > 1_200:
            raise KnowledgeBaseError("invalid_review_details", f"Проверьте состояние и длину замечания раздела «{criterion['label']}».")
        if status == "needs_work" and len(comment) < 10:
            raise KnowledgeBaseError("review_comment_required", f"Для раздела «{criterion['label']}» укажите конкретное замечание.")
        if status == "not_applicable" and len(comment) < 6:
            raise KnowledgeBaseError("review_comment_required", f"Поясните, почему раздел «{criterion['label']}» неприменим.")
        normalized[key] = {"status": status, "comment": comment}

    if decision in {"reviewed", "approved"}:
        incomplete = [
            criterion["label"] for criterion in EDITORIAL_CRITERIA
            if normalized[criterion["key"]]["status"] == "unchecked"
        ]
        if incomplete:
            raise KnowledgeBaseError(
                "review_checklist_incomplete",
                "Нельзя завершить проверку: заполните все разделы или обоснованно отметьте неприменимые.",
            )
        if any(item["status"] == "needs_work" for item in normalized.values()):
            raise KnowledgeBaseError(
                "review_has_open_issues",
                "Есть разделы, требующие доработки. Сохраните замечания и верните материал автору.",
            )
    if decision == "rework" and not any(item["status"] == "needs_work" for item in normalized.values()):
        raise KnowledgeBaseError("rework_issue_required", "Чтобы вернуть материал на доработку, отметьте проблемный раздел и поясните замечание.")
    return normalized


def review_knowledge_version(
    actor_id: int,
    version_id: int,
    decision: str,
    rationale: str,
    review_details: Any = None,
) -> AiLabKnowledgeReviewEvent:
    if decision not in EDITORIAL_DECISIONS:
        raise KnowledgeBaseError("invalid_decision", "Недопустимое решение редактора.")
    rationale = rationale.strip() if isinstance(rationale, str) else ""
    if len(rationale) < 10 or len(rationale) > 2_000:
        raise KnowledgeBaseError("review_reason_required", "Укажите обоснование решения длиной 10–2000 символов.")
    version = db.session.get(AiLabKnowledgeVersion, version_id)
    if version is None:
        raise KnowledgeBaseError("version_not_found", "Версия материала не найдена.", 404)
    latest = (db.session.query(func.max(AiLabKnowledgeVersion.version_no))
              .filter_by(entry_id=version.entry_id).scalar())
    if version.version_no != latest:
        raise KnowledgeBaseError("stale_version", "Это уже не последняя версия; решение нельзя записать в её прошлый снимок.", 409)
    if decision in {"reviewed", "approved"}:
        refs = version.source_refs_json or []
        if not refs or len(_source_map(refs)) != len(refs):
            raise KnowledgeBaseError("sources_not_verified", "Нельзя отметить материал проверенным без доступных источников.")
        _validate_content(version.content_json)
    details = _normalize_review_details(review_details, decision)
    event = AiLabKnowledgeReviewEvent(
        version_id=version.id, decision=decision, reviewer_user_id=actor_id, rationale=rationale,
        review_details_json=details,
    )
    db.session.add(event)
    db.session.commit()
    return event


def retrieve_knowledge(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Conservative lexical retrieval over the latest source-checked/reviewed versions."""
    query_terms = _terms(query)
    if not query_terms:
        return []
    documents = []
    for entry, version in _latest_versions():
        status, _ = _status_for_version(version.id)
        if status not in RETRIEVAL_DECISIONS:
            continue
        snapshot = _entry_snapshot(entry, version)
        if not snapshot["source_refs"] or any(
            source["source_status"] not in RETRIEVABLE_SOURCE_STATUSES
            for source in snapshot["source_refs"]
        ):
            continue
        title_terms = _terms(snapshot["title"])
        tag_terms = _terms(" ".join(snapshot["tags"]))
        code_terms = _terms(" ".join(snapshot["codifier_codes"]))
        body_terms = _terms(_canonical_json(snapshot["content"]))
        documents.append((snapshot, title_terms, tag_terms, code_terms, body_terms))

    candidates = []
    for snapshot, title_terms, tag_terms, code_terms, body_terms in documents:
        specific_terms = (title_terms | tag_terms | code_terms) - _GENERIC_SEARCH_TERMS
        specific_overlap = query_terms & specific_terms
        generic_core_overlap = query_terms & ((title_terms | tag_terms | code_terms) & _GENERIC_SEARCH_TERMS)
        body_overlap = query_terms & body_terms
        tag_overlap = query_terms & tag_terms
        phrase_bonus = sum(
            2 for term in snapshot["tags"]
            if len(term) > 3 and _terms(term).issubset(query_terms)
        )
        score = (
            4 * len(specific_overlap)
            + 0.6 * len(generic_core_overlap)
            + sum(1.3 if term not in _GENERIC_SEARCH_TERMS else 0.6 for term in body_overlap)
            + 1.5 * len(tag_overlap & specific_overlap)
            + phrase_bonus
        )
        if specific_overlap or score >= 2.5:
            candidates.append((score, snapshot))
    candidates.sort(key=lambda item: (-item[0], item[1]["stable_key"]))
    if candidates:
        best_score = candidates[0][0]
        candidates = [item for item in candidates if item[0] >= max(2.5, best_score * 0.5)]
    retrieved = []
    for score, snapshot in candidates[:max(1, min(int(limit), 5))]:
        body = snapshot["content"]
        # Only authored factual fields are sent to the model; source text is never ingested.
        excerpt = {
            "learning_goal": body["learning_goal"],
            "explanation": body["explanation"][:1_500],
            "examples": body["examples"][:2],
            "misconceptions": body["misconceptions"][:2],
            "assessed_skill": body.get("assessed_skill"),
            "skill_progression": body.get("skill_progression", [])[:5],
            "solution_steps": body.get("solution_steps", [])[:8],
            "student_explanation": body.get("student_explanation", ""),
            "teacher_explanation": body.get("teacher_explanation", ""),
            "diagnostics": body.get("diagnostics", [])[:4],
            "diagnostic_patterns": body.get("diagnostic_patterns", [])[:6],
            "interventions": body.get("interventions", [])[:4],
            "assessment_boundary": body["assessment_boundary"],
            "prerequisites": body.get("prerequisites", []),
            "lesson_links": body.get("lesson_links", [])[:6],
            "task_links": body.get("task_links", [])[:6],
            "platform_task_links": body.get("platform_task_links", [])[:20],
        }
        retrieved.append({
            "knowledge_ref": f"knowledge:{snapshot['stable_key']}:v{snapshot['version_no']}",
            "stable_key": snapshot["stable_key"],
            "version_no": snapshot["version_no"],
            "title": snapshot["title"],
            "status": snapshot["status"],
            "content_sha256": snapshot["content_sha256"],
            "source_refs": snapshot["source_refs"],
            "content": excerpt,
            "retrieval_score": score,
            "scope_note": (
                "Материал ограничивает объяснение; набор неполон и не доказывает владение темой. "
                "Статус source_checked не равен экспертному педагогическому утверждению; ссылки на предметные "
                "тесты в редакторе не являются результатом выполнения в этом запросе."
            ),
        })
    return retrieved


def source_checked_platform_task_bindings() -> list[dict[str, Any]]:
    """Return exact task mappings only from the latest source-checked KB versions."""
    bindings = []
    for entry, version in _latest_versions():
        status, _ = _status_for_version(version.id)
        if status not in RETRIEVAL_DECISIONS:
            continue
        content = _validate_content(version.content_json)
        if not content["platform_task_links"]:
            continue
        source_refs = _source_map(version.source_refs_json or [])
        for binding in content["platform_task_links"]:
            source = next((item for item in source_refs.values()
                           if int((item.metadata_json or {}).get("task_id") or 0) == binding["task_id"]
                           and (item.metadata_json or {}).get("platform_source_key") == binding["source_key"]
                           and item.content_sha256 == binding["content_fingerprint"]
                           and item.source_status == "platform_snapshot"), None)
            if source is None:
                continue
            bindings.append({
                **binding,
                "knowledge_stable_key": entry.stable_key,
                "knowledge_version": int(version.version_no),
                "knowledge_content_sha256": version.content_sha256,
                "knowledge_status": status,
            })
    return bindings


def _terms(value: str) -> set[str]:
    return {
        normalized for normalized in (
            _normalize_search_term(term)
            for term in re.findall(r"[a-zа-яё0-9_./%&+-]+", (value or "").casefold())
        )
        if len(normalized) > 2 and normalized not in _STOP_WORDS
    }


def _normalize_search_term(term: str) -> str:
    term = term.replace("ё", "е")
    if not re.fullmatch(r"[а-я]+", term):
        return term
    for suffix in (
        "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ых", "их",
        "ая", "яя", "ое", "ее", "ые", "ие", "ой", "ый", "ий", "ов", "ев", "ей",
        "ам", "ям", "ом", "ем", "ах", "ях", "а", "я", "ы", "и", "о", "е", "ь",
    ):
        if term.endswith(suffix) and len(term) - len(suffix) >= 4:
            return term[:-len(suffix)]
    return term
