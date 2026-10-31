"""Versioned synthetic rubric proposals. No production assignments are read or changed."""
from __future__ import annotations

import json
import ast
import hashlib
import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db
from app.ai_lab.config import ai_lab_limits
from app.ai_lab.provider import GigaChatProvider, gigachat_request_queue, provider_settings
from core.db_models import AiLabExperiment, AiLabRubricVersion, AiLabRubricTestVerification, AiLabRubricReview

PROMPT_VERSION = "rubric-builder-0.3"
REPAIR_PROMPT_VERSION = "rubric-builder-repair-0.3"
ISSUE_CATEGORIES = {
    "duplicate", "point_allocation", "incomplete", "unverifiable",
    "invented_constraint", "ambiguous", "alternative_unfair", "reference_misread",
}
_GENERATION_LOCK = threading.Lock()
PROMPT = (
    "Ты создаёшь проект критериев для локального синтетического задания. "
    "Опирайся только на условие и явно указанные требования преподавателя. "
    "Не добавляй скрытых требований, не штрафуй альтернативные корректные алгоритмы. "
    "Сумма баллов критериев должна точно равняться максимуму задания. "
    "Для каждого критерия назначь стабильный ID, явно укажи правило all_or_nothing или proportional, "
    "полный и частичный балл, типовые ошибки, проверяемость и необходимые доказательства. "
    "Если условие неоднозначно или эталон ошибочен, сообщи об этом в предупреждениях. "
    "Не придумывай частичный балл внутри критерия: если преподаватель прямо не разрешил частичное начисление, "
    "поле partial_credit оставь пустым и используй all_or_nothing. Явный запрет частичного балла обязателен. "
    "Отдельные явно заданные критерии по одному баллу сохраняй раздельно, не дублируй проверяемое умение. "
    "Если для объективной оценки не хватает направления, формата или других правил, не превращай уточнение "
    "в требование к ученику: пометь непроверяемый аспект и объясни, что должен уточнить преподаватель. "
    "Если эталон кажется неверным, проверь вывод на нескольких простых положительных, отрицательных и нулевых входах "
    "прежде чем описывать границы ошибки; эталон не переопределяет условие. "
    "У каждого предложенного теста укажи стабильные ID теста и критерия; тесты — только черновики для последующей проверки в изолированном Code Judge."
)
REPAIR_PROMPT = (
    "Ты исправляешь черновик рубрики локальной AI Lab. Измени только перечисленные проблемные критерии. "
    "Не изменяй остальные критерии, их ID, веса и проверяемые требования. Если для исправления нужна "
    "перебалансировка, верни предупреждение и оставь прежние баллы: решение примет преподаватель. "
    "Опирайся только на условие и требования преподавателя; не вводи неоговорённых ограничений. "
    "Не штрафуй альтернативные корректные решения. Сохранённые тесты являются предложениями, а не доказательством. "
    "Сохраняй ID критериев и их правила начисления. Верни полную рубрику в заданной JSON-схеме; утверждение выполняет только администратор."
)


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


RUBRIC_SCHEMA = _obj({
    "criteria": {"type": "array", "items": _obj({
        "id": {"type": "string"},
        "title": {"type": "string"}, "description": {"type": "string"},
        "max_score": {"type": "number"}, "full_credit": {"type": "string"},
        "partial_credit": {"type": "string"}, "typical_errors": {"type": "array", "items": {"type": "string"}},
        "automatable": {"type": "boolean"}, "evidence": {"type": "string"},
        "manual_reason": {"type": "string"},
        "policy": {"type": "string", "enum": ["all_or_nothing", "proportional"]},
    })},
    "warnings": {"type": "array", "items": {"type": "string"}},
    "proposed_tests": {"type": "array", "items": _obj({
        "id": {"type": "string"}, "criterion_id": {"type": "string"},
        "name": {"type": "string"}, "input_json": {"type": "string"},
        "expected_json": {"type": "string"}, "criterion_title": {"type": "string"},
        "purpose": {"type": "string"},
    })},
})


class RubricError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _text(value: Any, label: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise RubricError(f"Поле «{label}» должно быть текстом.")
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise RubricError(f"Проверьте поле «{label}» (до {limit} символов).")
    return value


def validate_task(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RubricError("Заполните задание для генерации критериев.")
    task = {
        "subject": _text(raw.get("subject"), "Предмет", 120),
        "topic": _text(raw.get("topic"), "Тема", 200),
        "answer_type": _text(raw.get("answer_type"), "Тип ответа", 60),
        "condition": _text(raw.get("condition"), "Условие", 8000),
        "reference_answer": _text(raw.get("reference_answer", ""), "Эталон", 8000, False),
        "teacher_requirements": _text(raw.get("teacher_requirements", ""), "Требования", 4000, False),
        "title": _text(raw.get("title") or raw.get("topic"), "Название", 180),
    }
    if task["answer_type"] not in {"python", "text", "short_answer"}:
        raise RubricError("Выберите поддерживаемый тип ответа.")
    try:
        maximum = float(raw.get("max_score"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RubricError("Укажите максимальный балл задания.") from exc
    if not math.isfinite(maximum) or not 0 < maximum <= 100:
        raise RubricError("Максимальный балл должен быть от 0 до 100.")
    task["max_score"] = maximum
    assignment_id = raw.get("assignment_id")
    assignment_version = raw.get("assignment_version")
    if assignment_id not in (None, ""):
        assignment_id = _text(assignment_id, "Стабильный ID задания", 120)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", assignment_id):
            raise RubricError("Поле «Стабильный ID задания» допускает только латиницу, цифры, точку, подчёркивание, двоеточие и дефис.")
        if isinstance(assignment_version, bool) or not re.fullmatch(r"[1-9][0-9]{0,8}", str(assignment_version or "")):
            raise RubricError("Для стабильного ID укажите версию задания — целое число от 1 до 999999999.")
        task["assignment_id"] = assignment_id
        task["assignment_version"] = int(assignment_version)
    elif assignment_version not in (None, ""):
        raise RubricError("Версия задания требует стабильного ID задания.")
    return task


def _stable_rubric_key(task: dict[str, Any]) -> str | None:
    if not task.get("assignment_id"):
        return None
    identity = f"{task['assignment_id']}:{task['assignment_version']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"boostudy.ai-lab.rubric:{identity}"))


def _task_content(task: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items() if key not in {"assignment_id", "assignment_version"}}


def _next_rubric_version(rubric_key: str) -> int:
    latest = AiLabRubricVersion.query.filter_by(rubric_key=rubric_key).order_by(AiLabRubricVersion.version_no.desc()).first()
    return latest.version_no + 1 if latest else 1


def _generation_attempt_count(versions: list[AiLabRubricVersion]) -> int:
    attempts = set()
    for version in versions:
        generation = version.generation_json or {}
        request_key = generation.get("request_key")
        if request_key:
            attempts.add(("request", str(request_key)))
        elif version.status == "generation_error":
            attempts.add(("error", version.id))
        elif version.version_no == 1 and not generation.get("repair_request_key"):
            attempts.add(("rubric", version.rubric_key))
    return len(attempts)


def _find_reusable_rubric(task: dict[str, Any]) -> dict[str, Any] | None:
    rubric_key = _stable_rubric_key(task)
    if not rubric_key:
        return None
    versions = AiLabRubricVersion.query.filter_by(rubric_key=rubric_key).order_by(AiLabRubricVersion.version_no.desc()).all()
    for version in versions:
        if _task_content(version.task_json or {}) != _task_content(task):
            raise RubricError(
                f"Для задания «{task['assignment_id']}» версии {task['assignment_version']} уже сохранена другая формулировка. "
                "Увеличьте версию задания, чтобы создать отдельную рубрику.",
                409,
            )
    reusable = next((version for version in versions if version.status != "generation_error"), None)
    if not reusable:
        return None
    result = _serialize(reusable)
    result["reused"] = True
    return result


def _partial_credit_allowed(requirements: str) -> bool:
    lowered = requirements.casefold()
    if re.search(r"частич\w*\s+балл\w*\s+(?:не\s+предусмотр|не\s+допуст|запрещ)", lowered):
        return False
    return bool(re.search(r"частич\w*\s+балл\w*\s+(?:допуст|разреш|предусмотр)", lowered))


def validate_criteria(raw: Any, task: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
        raise RubricError("Нужно от 1 до 20 критериев.")
    errors: list[str] = []
    warnings: list[str] = []
    criteria: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RubricError(f"Критерий №{index} имеет неверный формат.")
        title = _text(item.get("title"), f"Название критерия №{index}", 200)
        description = _text(item.get("description"), f"Описание критерия №{index}", 1000)
        full_credit = _text(item.get("full_credit"), f"Полный балл №{index}", 1000)
        partial_credit = _text(item.get("partial_credit", ""), f"Частичный балл №{index}", 1000, False)
        evidence = _text(item.get("evidence"), f"Подтверждения №{index}", 1000)
        manual_reason = _text(item.get("manual_reason", ""), f"Ручная проверка №{index}", 1000, False)
        try:
            maximum = float(item.get("max_score"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RubricError(f"Укажите баллы критерия №{index}.") from exc
        if not math.isfinite(maximum) or maximum <= 0 or maximum > task["max_score"]:
            errors.append(f"Критерий «{title}»: некорректный максимум баллов.")
        criterion_id = item.get("id")
        if criterion_id is not None and (not isinstance(criterion_id, str) or not criterion_id.strip() or len(criterion_id.strip()) > 80):
            errors.append(f"Критерий «{title}»: укажите стабильный непустой ID до 80 символов.")
        criterion_id = str(criterion_id).strip() if criterion_id is not None else f"criterion-{index}"
        key = re.sub(r"\W+", "", title.casefold())
        if key in seen:
            errors.append(f"Повторяется критерий «{title}».")
        seen.add(key)
        automatable = item.get("automatable") is True
        policy = str(item.get("policy") or "all_or_nothing")
        if policy not in {"all_or_nothing", "proportional"}:
            errors.append(f"Критерий «{title}»: неизвестное правило начисления.")
        if policy == "proportional" and not _partial_credit_allowed(task["teacher_requirements"]):
            errors.append(f"Критерий «{title}»: частичное начисление не разрешено преподавателем.")
        if partial_credit and policy == "all_or_nothing" and not re.search(
            r"(?:не\s+(?:предусмотр|допуска|начис)|нет\s+частич)", partial_credit.casefold()
        ):
            errors.append(f"Критерий «{title}»: описание частичного балла противоречит правилу all_or_nothing.")
        if partial_credit and not _partial_credit_allowed(task["teacher_requirements"]):
            denial = re.search(r"(?:частич\w*\s+балл\w*\s+не\s+(?:предусмотр|допуска|начис)|нет\s+частич\w*\s+балл)", partial_credit.casefold())
            if not denial:
                errors.append(f"Критерий «{title}»: частичное начисление не разрешено преподавателем.")
        if not automatable and not manual_reason:
            errors.append(f"Критерий «{title}»: объясните, почему требуется ручная проверка.")
        if automatable and "ручн" in evidence.casefold():
            warnings.append(f"Критерий «{title}»: автоматическая проверка противоречит описанию подтверждений.")
        typical = item.get("typical_errors") or []
        if not isinstance(typical, list) or len(typical) > 10:
            raise RubricError(f"Критерий «{title}»: список типичных ошибок некорректен.")
        criteria.append({
            "id": criterion_id,
            "title": title, "description": description, "max_score": maximum,
            "full_credit": full_credit, "partial_credit": partial_credit,
            "typical_errors": [_text(value, "Типичная ошибка", 300) for value in typical],
            "automatable": automatable, "evidence": evidence, "manual_reason": manual_reason,
            "policy": policy,
        })
        if len(title) + len(description) + len(full_credit) + len(partial_credit) + 90 > 1000:
            errors.append(f"Критерий «{title}»: сократите описание правил до 1000 символов для AI Homework Studio.")
    if len({item["id"] for item in criteria}) != len(criteria):
        errors.append("Идентификаторы критериев должны быть уникальными.")
    total = sum(item["max_score"] for item in criteria)
    if abs(total - task["max_score"]) > 0.001:
        errors.append(f"Сумма критериев {total:g} не равна максимуму задания {task['max_score']:g}.")
    if len(criteria) == 1 and task["max_score"] > 1 and not criteria[0]["partial_credit"]:
        warnings.append("Для единственного многобалльного критерия не описан частичный балл.")
    requirements = task["teacher_requirements"].casefold()
    criterion_text = " ".join(item["title"] + " " + item["description"] + " " + item["full_credit"] for item in criteria).casefold()
    if task["max_score"] == 1 and len(criteria) > 1 and not _partial_credit_allowed(requirements):
        errors.append("Один балл разделён на несколько критериев без разрешения преподавателя на частичный балл.")
    if re.search(r"не\s+(?:задано|указано|определено)", requirements):
        if "направлен" in requirements and re.search(r"возрастан|убыван", criterion_text):
            errors.append("Направление сортировки не задано, но рубрика выбрала его без основания.")
        if "изменен" in requirements or "изменени" in requirements:
            if re.search(r"неизменн|не\s+измен|не\s+модифиц", criterion_text):
                errors.append("Изменение исходных данных не уточнено, но рубрика требует их сохранения.")
    if "эталон" in requirements and "ошиб" in requirements:
        warnings.append("Проверьте эталон вручную до утверждения: в требованиях указана возможная ошибка.")
    for item in criteria:
        if item["max_score"] <= 1 and not _partial_credit_allowed(requirements) and re.search(r"хотя\s+бы\s+одн", item["partial_credit"].casefold()):
            warnings.append(f"Критерий «{item['title']}»: частичный балл за один тест не задан преподавателем.")
    condition_words = set(re.findall(r"[\w]{5,}", (task["condition"] + " " + task["teacher_requirements"]).casefold()))
    for item in criteria:
        distinctive = set(re.findall(r"[\w]{6,}", (item["title"] + " " + item["description"]).casefold()))
        if distinctive and not (distinctive & condition_words):
            warnings.append(f"Проверьте, следует ли критерий «{item['title']}» из условия.")
    automated_count = sum(bool(item["automatable"]) for item in criteria)
    validation = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "total": total,
        "structural_status": "valid" if not errors else "invalid",
        "testability_status": "requires_sandbox_verification" if automated_count else "manual_evidence_required",
        "automatable_criteria": automated_count,
        "criterion_count": len(criteria),
        "content_correctness": "not_assessed_requires_expert_review",
    }
    return criteria, validation


def _validate_proposed_tests(raw: Any, criteria: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    if raw is None:
        return [], []
    if not isinstance(raw, list) or len(raw) > 30:
        return [], ["Предложенные тесты имеют неверный формат или превышают лимит 30."]
    known_criteria = {item["id"] for item in criteria}
    tests = []
    warnings = []
    seen = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            warnings.append(f"Тест №{index} пропущен: ожидался JSON-объект.")
            continue
        test_id = str(item.get("id") or "").strip()
        criterion_id = str(item.get("criterion_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", test_id) or test_id in seen:
            warnings.append(f"Тест №{index} пропущен: ID отсутствует, некорректен или повторяется.")
            continue
        if criterion_id not in known_criteria:
            warnings.append(f"Тест «{test_id}» не привязан к существующему критерию и не будет исполнен.")
            continue
        try:
            input_value = json.loads(_text(item.get("input_json"), f"Вход теста {test_id}", 4000))
            expected_value = json.loads(_text(item.get("expected_json"), f"Ожидаемый результат теста {test_id}", 4000))
            name = _text(item.get("name"), f"Название теста {test_id}", 160)
            purpose = _text(item.get("purpose"), f"Назначение теста {test_id}", 500)
        except (RubricError, ValueError) as exc:
            warnings.append(f"Тест «{test_id}» пропущен: input_json/expected_json должны быть корректным JSON ({exc}).")
            continue
        seen.add(test_id)
        tests.append({
            "id": test_id,
            "criterion_id": criterion_id,
            "criterion_title": next(item["title"] for item in criteria if item["id"] == criterion_id),
            "name": name,
            "input_json": json.dumps(input_value, ensure_ascii=False, separators=(",", ":")),
            "expected_json": json.dumps(expected_value, ensure_ascii=False, separators=(",", ":")),
            "purpose": purpose,
            "status": "unverified",
        })
    return tests, warnings


def _serialize(item: AiLabRubricVersion) -> dict[str, Any]:
    if item.status == "generation_error":
        current_validation = dict(item.validation_json or {})
    else:
        try:
            _, current_validation = validate_criteria(item.criteria_json, item.task_json)
            proposal_warnings = (item.raw_proposal_json or {}).get("warnings") or []
            if isinstance(proposal_warnings, list):
                current_validation["warnings"].extend(str(value)[:500] for value in proposal_warnings[:10])
        except RubricError as exc:
            current_validation = {"ok": False, "errors": [str(exc)], "warnings": []}
    review = AiLabRubricReview.query.filter_by(rubric_version_id=item.id).order_by(AiLabRubricReview.id.desc()).first()
    return {
        "id": item.id, "rubric_key": item.rubric_key, "version_no": item.version_no,
        "assignment_id": item.assignment_id, "assignment_version": item.assignment_version,
        "task": item.task_json, "criteria": item.criteria_json,
        "proposed_tests": item.proposed_tests_json, "raw_proposal": item.raw_proposal_json,
        "edits": item.edits_json, "validation": item.validation_json,
        "current_validation": current_validation,
        "status": item.status, "model": item.model, "prompt_version": item.prompt_version,
        "generation": item.generation_json,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "expert_review": {"verdict": review.verdict, "issues": review.issues_json,
                          "note": review.note, "reviewed_at": review.created_at.isoformat()} if review else None,
        "parent_version": next((edit.get("from_version") for edit in reversed(item.edits_json or []) if isinstance(edit, dict) and "from_version" in edit), None),
    }


def list_rubrics(approved_only: bool = False, *, limit: int | None = 100) -> list[dict[str, Any]]:
    query = AiLabRubricVersion.query
    if approved_only:
        query = query.filter_by(status="approved")
    query = query.order_by(AiLabRubricVersion.id.desc())
    return [_serialize(item) for item in (query.limit(limit).all() if limit is not None else query.all())]


def get_rubric(version_id: int) -> dict[str, Any] | None:
    item = db.session.get(AiLabRubricVersion, version_id)
    return _serialize(item) if item else None


def review_rubric(version_id: int, raw: Any, actor_user_id: int) -> dict[str, Any]:
    item = db.session.get(AiLabRubricVersion, version_id)
    if not item:
        raise RubricError("Версия рубрики не найдена.", 404)
    if not isinstance(raw, dict) or raw.get("verdict") not in {"pass", "fail"}:
        raise RubricError("Выберите экспертный результат: прошла или не прошла.")
    issues = raw.get("issues") or []
    if not isinstance(issues, list) or len(issues) > 20:
        raise RubricError("Некорректный список замечаний.")
    known_ids = {criterion.get("id", f"criterion-{index}") for index, criterion in enumerate(item.criteria_json, 1)}
    cleaned = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("category") not in ISSUE_CATEGORIES:
            raise RubricError("Неизвестная категория ошибки рубрики.")
        criterion_id = str(issue.get("criterion_id") or "")
        if criterion_id and criterion_id not in known_ids:
            raise RubricError("Замечание относится к отсутствующему критерию.")
        cleaned.append({"category": issue["category"], "criterion_id": criterion_id,
                        "detail": _text(issue.get("detail"), "Замечание", 1000)})
    if raw["verdict"] == "fail" and not cleaned:
        raise RubricError("Для отклонённой рубрики укажите хотя бы одну конкретную ошибку.")
    note = _text(raw.get("note", ""), "Комментарий", 2000, False)
    db.session.add(AiLabRubricReview(rubric_version_id=item.id, actor_user_id=actor_user_id,
                                    verdict=raw["verdict"], issues_json=cleaned, note=note))
    db.session.commit()
    return _serialize(item)


def generate_rubric(raw_task: Any, model: str, actor_user_id: int, request_key: str | None = None) -> dict[str, Any]:
    task = validate_task(raw_task)
    if request_key is not None:
        try:
            request_key = str(uuid.UUID(request_key))
        except (TypeError, ValueError, AttributeError) as exc:
            raise RubricError("Ключ защиты от повторной генерации некорректен.") from exc
    with _GENERATION_LOCK:
        if request_key:
            existing = next((item for item in AiLabRubricVersion.query.filter_by(created_by_user_id=actor_user_id).order_by(AiLabRubricVersion.id.desc()).all()
                             if (item.generation_json or {}).get("request_key") == request_key), None)
            if existing:
                result = _serialize(existing)
                result["reused"] = True
                return result
        reusable = _find_reusable_rubric(task)
        if reusable:
            return reusable
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        admin_count = AiLabExperiment.query.filter(AiLabExperiment.actor_user_id == actor_user_id, AiLabExperiment.created_at >= since).count()
        admin_versions = AiLabRubricVersion.query.filter_by(created_by_user_id=actor_user_id).filter(AiLabRubricVersion.created_at >= since).all()
        admin_count += _generation_attempt_count(admin_versions)
        lab_count = AiLabExperiment.query.filter(AiLabExperiment.created_at >= since).count()
        lab_versions = AiLabRubricVersion.query.filter(AiLabRubricVersion.created_at >= since).all()
        lab_count += _generation_attempt_count(lab_versions)
        limits = ai_lab_limits()
        if admin_count >= limits["runs_per_admin_per_hour"] or lab_count >= limits["runs_per_lab_per_hour"]:
            raise RubricError("Достигнут локальный часовой лимит AI Lab. Попробуйте позже.", 429)
        return _generate_rubric(task, model, actor_user_id, request_key)


def _generate_rubric(raw_task: Any, model: str, actor_user_id: int, request_key: str | None) -> dict[str, Any]:
    task = validate_task(raw_task)
    settings = provider_settings()
    if not settings["configured"]:
        raise RubricError("GigaChat не настроен в локальной AI Lab.", 503)
    provider = GigaChatProvider(settings)
    with gigachat_request_queue.request("Генерация критериев"):
        available = provider.list_models()
        if model not in available:
            raise RubricError("Выбранная модель GigaChat сейчас недоступна.", 400)
        completion = provider.complete_structured(model, PROMPT, {"task": _task_content(task), "prompt_version": PROMPT_VERSION}, RUBRIC_SCHEMA)
    max_tokens = int((completion.generation_parameters or {}).get("max_tokens") or 0)
    truncated = str(completion.finish_reason or "").casefold() in {"length", "max_tokens", "token_limit"}
    truncated = truncated or bool(max_tokens and completion.output_tokens is not None and completion.output_tokens >= max_tokens)
    if truncated:
        return _save_generation_error(
            task, completion, actor_user_id, request_key,
            "Ответ генератора достиг ограничения токенов и был обрезан. Увеличьте AI_LAB_MAX_COMPLETION_TOKENS или сократите условие.",
            "generation_truncated",
        )
    try:
        proposal = json.loads(completion.content)
    except (TypeError, ValueError) as exc:
        if max_tokens and completion.output_tokens is not None and completion.output_tokens >= max_tokens:
            return _save_generation_error(
                task, completion, actor_user_id, request_key,
                "Ответ генератора достиг ограничения токенов и не образует полный JSON.",
                "generation_truncated",
            )
        raise RubricError("GigaChat вернул неразборчивую рубрику. Попробуйте повторить генерацию.", 502) from exc
    if not isinstance(proposal, dict):
        raise RubricError("GigaChat вернул некорректную структуру рубрики.", 502)
    try:
        criteria, validation = validate_criteria(proposal.get("criteria"), task)
    except RubricError as exc:
        criteria, validation = [], {"ok": False, "errors": [str(exc)], "warnings": [], "total": 0}
    tests, test_warnings = _validate_proposed_tests(proposal.get("proposed_tests"), criteria)
    validation["warnings"].extend(test_warnings)
    if tests:
        validation["testability_status"] = "proposed_tests_unverified"
    elif validation.get("automatable_criteria"):
        validation["testability_status"] = "no_linked_proposed_tests"
    warnings = proposal.get("warnings") or []
    if isinstance(warnings, list):
        validation["warnings"].extend(str(value)[:500] for value in warnings[:10])
    key = _stable_rubric_key(task) or str(uuid.uuid4())
    assignment_id = task.get("assignment_id") or f"ai-lab.rubric.{key}"
    assignment_version = int(task.get("assignment_version") or 1)
    item = AiLabRubricVersion(
        rubric_key=key, version_no=_next_rubric_version(key), assignment_id=assignment_id,
        assignment_version=assignment_version, task_json=task, criteria_json=criteria,
        proposed_tests_json=tests, raw_proposal_json=proposal, edits_json=[],
        validation_json=validation, status="draft", model=completion.model,
        prompt_version=PROMPT_VERSION,
        generation_json={"request_key": request_key, "payload_id": completion.payload_id, "payload_sha256": completion.payload_sha256,
                         "parameters": completion.generation_parameters,
                         "usage": {"prompt_tokens": completion.prompt_tokens,
                                   "precached_prompt_tokens": completion.precached_prompt_tokens,
                                   "completion_tokens": completion.output_tokens,
                                   "total_tokens": completion.total_tokens}},
        created_by_user_id=actor_user_id,
    )
    db.session.add(item)
    db.session.commit()
    return _serialize(item)


def _save_generation_error(task: dict[str, Any], completion, actor_user_id: int,
                           request_key: str | None, message: str, code: str) -> dict[str, Any]:
    key = _stable_rubric_key(task) or str(uuid.uuid4())
    assignment_id = task.get("assignment_id") or f"ai-lab.rubric.{key}"
    assignment_version = int(task.get("assignment_version") or 1)
    usage = {
        "prompt_tokens": completion.prompt_tokens,
        "precached_prompt_tokens": completion.precached_prompt_tokens,
        "completion_tokens": completion.output_tokens,
        "total_tokens": completion.total_tokens,
    }
    item = AiLabRubricVersion(
        rubric_key=key,
        version_no=_next_rubric_version(key),
        assignment_id=assignment_id,
        assignment_version=assignment_version,
        task_json=task,
        criteria_json=[],
        proposed_tests_json=[],
        raw_proposal_json={"truncated_completion": (completion.content or "")[:24_000]},
        edits_json=[],
        validation_json={
            "ok": False,
            "errors": [message],
            "warnings": [],
            "structural_status": "invalid",
            "testability_status": "not_available",
            "content_correctness": "not_assessed_requires_expert_review",
        },
        status="generation_error",
        model=completion.model,
        prompt_version=PROMPT_VERSION,
        generation_json={
            "request_key": request_key,
            "payload_id": completion.payload_id,
            "payload_sha256": completion.payload_sha256,
            "parameters": completion.generation_parameters or {},
            "finish_reason": completion.finish_reason,
            "usage": usage,
            "technical_error": {"code": code, "message": message},
        },
        created_by_user_id=actor_user_id,
    )
    db.session.add(item)
    db.session.commit()
    return _serialize(item)


def revise_rubric(version_id: int, raw: Any, actor_user_id: int) -> dict[str, Any]:
    source = db.session.get(AiLabRubricVersion, version_id)
    if not source:
        raise RubricError("Версия рубрики не найдена.", 404)
    latest = AiLabRubricVersion.query.filter_by(rubric_key=source.rubric_key).order_by(AiLabRubricVersion.version_no.desc()).first()
    if latest.id != source.id:
        raise RubricError("Откройте последнюю версию рубрики перед редактированием.", 409)
    if not isinstance(raw, dict):
        raise RubricError("Передайте изменения критериев.")
    task = validate_task(raw.get("task") or source.task_json)
    source_task = source.task_json or {}
    if source_task.get("assignment_id") and (
        task.get("assignment_id") != source_task.get("assignment_id")
        or task.get("assignment_version") != source_task.get("assignment_version")
        or _task_content(task) != _task_content(source_task)
    ):
        raise RubricError("Сохранённая версия связана с исходным условием. Для изменённого задания укажите новый номер версии и создайте отдельную рубрику.", 409)
    criteria, validation = validate_criteria(raw.get("criteria"), task)
    proposal_warnings = (source.raw_proposal_json or {}).get("warnings") or []
    if isinstance(proposal_warnings, list):
        validation["warnings"].extend(str(value)[:500] for value in proposal_warnings[:10])
    item = AiLabRubricVersion(
        rubric_key=source.rubric_key, version_no=source.version_no + 1,
        assignment_id=source.assignment_id,
        assignment_version=source.assignment_version if source_task.get("assignment_id") else source.assignment_version + 1,
        task_json=task, criteria_json=criteria,
        proposed_tests_json=source.proposed_tests_json,
        raw_proposal_json=source.raw_proposal_json,
        edits_json=[*(source.edits_json or []), {"from_version": source.version_no, "actor_user_id": actor_user_id,
                                                  "task": task, "criteria": criteria}],
        validation_json=validation, status="draft", model=source.model,
        prompt_version=source.prompt_version, generation_json=source.generation_json,
        created_by_user_id=actor_user_id,
    )
    db.session.add(item)
    db.session.commit()
    return _serialize(item)


def repair_rubric(version_id: int, raw: Any, actor_user_id: int) -> dict[str, Any]:
    source = db.session.get(AiLabRubricVersion, version_id)
    if not source:
        raise RubricError("Версия рубрики не найдена.", 404)
    if not isinstance(raw, dict) or not isinstance(raw.get("criterion_ids"), list):
        raise RubricError("Выберите проблемные критерии для исправления.")
    try:
        request_key = str(uuid.UUID(str(raw.get("request_key") or "")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RubricError("Ключ защиты от повторного исправления некорректен.") from exc
    previous = next((row for row in AiLabRubricVersion.query.filter_by(rubric_key=source.rubric_key).all()
                     if (row.generation_json or {}).get("repair_request_key") == request_key), None)
    if previous:
        return _serialize(previous)
    latest = AiLabRubricVersion.query.filter_by(rubric_key=source.rubric_key).order_by(AiLabRubricVersion.version_no.desc()).first()
    if latest.id != source.id:
        raise RubricError("Для исправления откройте последнюю версию рубрики.", 409)
    ids = {str(value) for value in raw["criterion_ids"]}
    known = {item["id"] for item in source.criteria_json}
    if not ids or len(ids) > 20 or not ids.issubset(known):
        raise RubricError("Выберите существующие проблемные критерии.")
    reason = _text(raw.get("reason", ""), "Причина исправления", 1000)
    settings = provider_settings()
    if not settings["configured"]:
        raise RubricError("GigaChat не настроен в локальной AI Lab.", 503)
    provider = GigaChatProvider(settings)
    model = str(raw.get("model") or source.model or settings["default_model"])
    with gigachat_request_queue.request("Исправление критериев"):
        if model not in provider.list_models():
            raise RubricError("Выбранная модель GigaChat сейчас недоступна.")
        completion = provider.complete_structured(model, REPAIR_PROMPT, {
            "task": source.task_json, "source_criteria": source.criteria_json,
            "problematic_criterion_ids": sorted(ids), "validator_errors": source.validation_json.get("errors", []),
            "validator_warnings": source.validation_json.get("warnings", []),
            "teacher_reason": reason, "prompt_version": REPAIR_PROMPT_VERSION,
        }, RUBRIC_SCHEMA)
    try:
        proposal = json.loads(completion.content)
        raw_criteria = proposal["criteria"]
    except (TypeError, ValueError, KeyError) as exc:
        raise RubricError("GigaChat вернул некорректное исправление.", 502) from exc
    if not isinstance(raw_criteria, list) or len(raw_criteria) != len(source.criteria_json):
        raise RubricError("Модель изменила число критериев. Исправление отклонено.", 502)
    patched = []
    for index, proposed in enumerate(raw_criteria):
        if not isinstance(proposed, dict):
            raise RubricError("Модель вернула некорректный критерий.", 502)
        original = source.criteria_json[index]
        criterion_id = original["id"]
        if proposed.get("id", criterion_id) != criterion_id:
            raise RubricError("Модель изменила идентификаторы критериев. Исправление отклонено.", 502)
        if criterion_id not in ids:
            patched.append(original)
            continue
        patched.append({**original, **proposed, "id": criterion_id})
    try:
        criteria, validation = validate_criteria(patched, source.task_json)
    except RubricError as exc:
        criteria, validation = source.criteria_json, {"ok": False, "errors": [str(exc)], "warnings": [], "total": 0}
    warnings = proposal.get("warnings") or []
    if isinstance(warnings, list):
        validation["warnings"].extend(str(value)[:500] for value in warnings[:10])
    item = AiLabRubricVersion(
        rubric_key=source.rubric_key, version_no=source.version_no + 1,
        assignment_id=source.assignment_id,
        assignment_version=source.assignment_version if (source.task_json or {}).get("assignment_id") else source.assignment_version + 1,
        task_json=source.task_json, criteria_json=criteria,
        proposed_tests_json=source.proposed_tests_json, raw_proposal_json=proposal,
        edits_json=[*(source.edits_json or []), {"from_version": source.version_no, "actor_user_id": actor_user_id,
                     "kind": "model_repair", "criterion_ids": sorted(ids), "reason": reason,
                     "before": source.criteria_json, "after": criteria}],
        validation_json=validation, status="draft", model=completion.model,
        prompt_version=REPAIR_PROMPT_VERSION,
        generation_json={"repair_request_key": request_key, "payload_id": completion.payload_id, "payload_sha256": completion.payload_sha256,
                         "parameters": completion.generation_parameters,
                         "usage": {"prompt_tokens": completion.prompt_tokens,
                                   "precached_prompt_tokens": completion.precached_prompt_tokens,
                                   "completion_tokens": completion.output_tokens,
                                   "total_tokens": completion.total_tokens}},
        created_by_user_id=actor_user_id,
    )
    db.session.add(item)
    db.session.commit()
    return _serialize(item)


def approve_rubric(version_id: int, actor_user_id: int, *, acknowledge_warnings: bool = False) -> dict[str, Any]:
    item = db.session.get(AiLabRubricVersion, version_id)
    if not item:
        raise RubricError("Версия рубрики не найдена.", 404)
    if item.status != "draft":
        raise RubricError("Эта версия уже утверждена.", 409)
    if AiLabRubricVersion.query.filter_by(rubric_key=item.rubric_key).order_by(AiLabRubricVersion.version_no.desc()).first().id != item.id:
        raise RubricError("Утвердить можно только последнюю версию рубрики.", 409)
    criteria, validation = validate_criteria(item.criteria_json, item.task_json)
    proposal_warnings = (item.raw_proposal_json or {}).get("warnings") or []
    if isinstance(proposal_warnings, list):
        validation["warnings"].extend(str(value)[:500] for value in proposal_warnings[:10])
    if not validation["ok"]:
        raise RubricError("Исправьте ошибки проверки: " + " ".join(validation["errors"]), 409)
    if validation["warnings"] and not acknowledge_warnings:
        raise RubricError("Прочитайте предупреждения и подтвердите их проверку перед утверждением.", 409)
    item.criteria_json = criteria
    validation["warning_acknowledged"] = acknowledge_warnings
    item.validation_json = validation
    item.status = "approved"
    item.approved_by_user_id = actor_user_id
    item.approved_at = datetime.now(timezone.utc)
    db.session.commit()
    return _serialize(item)


def latest_test_verification(version_id: int) -> dict[str, Any] | None:
    record = AiLabRubricTestVerification.query.filter_by(rubric_version_id=version_id).order_by(AiLabRubricTestVerification.id.desc()).first()
    return {"id": record.id, **record.report_json} if record else None


def verify_proposed_tests(version_id: int, raw: Any, actor_user_id: int) -> dict[str, Any]:
    """Execute the teacher-confirmed reference only inside the secured Code Judge runner."""
    item = db.session.get(AiLabRubricVersion, version_id)
    if not item:
        raise RubricError("Версия рубрики не найдена.", 404)
    if item.task_json["answer_type"] != "python":
        raise RubricError("Проверка исполнения доступна для Python-заданий.")
    if not isinstance(raw, dict) or raw.get("reference_confirmed") is not True:
        raise RubricError("Подтвердите, что эталонный код проверен преподавателем.")
    reference = _text(raw.get("reference_code", ""), "Доверенный эталон", 20_000)
    try:
        tree = ast.parse(reference)
    except SyntaxError as exc:
        raise RubricError(f"Синтаксическая ошибка в эталоне: строка {exc.lineno}.") from exc
    function_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    functions = [node.name for node in function_nodes]
    if len(functions) != 1:
        raise RubricError("Для проверки укажите эталон с одной верхнеуровневой функцией.")
    extra = raw.get("edge_cases")
    if not isinstance(extra, list) or not 1 <= len(extra) <= 10:
        raise RubricError("Добавьте от 1 до 10 дополнительных граничных примеров преподавателя.")
    suggested = item.proposed_tests_json or []
    if not suggested:
        raise RubricError("В этой версии нет предложенных Python-тестов.")
    cases = []
    for index, proposed in enumerate([*suggested, *extra], 1):
        try:
            args = json.loads(proposed["input_json"]) if isinstance(proposed.get("input_json"), str) else proposed["args"]
            expected = json.loads(proposed["expected_json"]) if isinstance(proposed.get("expected_json"), str) else proposed["expected"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RubricError(f"Тест №{index}: вход или ожидаемый ответ не является корректным JSON.") from exc
        if isinstance(args, dict):
            if set(args) == {"args"}:
                args = args["args"]
            else:
                parameter_names = [parameter.arg for parameter in function_nodes[0].args.args]
                if set(args) == set(parameter_names):
                    args = [args[name] for name in parameter_names]
        if isinstance(expected, dict) and set(expected) == {"result"}:
            expected = expected["result"]
        if not isinstance(args, list):
            raise RubricError(f"Тест №{index}: вход должен быть JSON-массивом аргументов.")
        cases.append({"id": f"rubric-{index}", "name": str(proposed.get("name") or f"Тест {index}")[:120],
                      "visibility": "public", "args": args, "expected": expected})
    from app.ai_lab.code_judge import CodeJudgeError, _normalize_result, validate_test_set
    from app.ai_lab.code_judge_runner_client import RunnerUnavailable, run_isolated, runner_diagnostics
    from app.ai_lab.config import code_judge_limits

    try:
        data = validate_test_set({"title": "Проверка предложенных тестов", "mode": "function",
                                  "function_name": functions[0], "comparator": "exact", "tolerance": 0,
                                  "starter_code": "", "test_cases": cases, "rubric_json": []})
    except CodeJudgeError as exc:
        raise RubricError(str(exc)) from exc
    diagnostics = runner_diagnostics()
    if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
        raise RubricError("Изолированный Runner недоступен или профиль безопасности не подтверждён.", 503)
    try:
        raw_result = run_isolated({"code": reference, "mode": "function", "function_name": functions[0],
                                   "comparator": "exact", "tolerance": 0,
                                   "test_cases": data["test_cases"], "limits": code_judge_limits()})
        result = _normalize_result(raw_result, len(cases))
    except RunnerUnavailable as exc:
        raise RubricError(str(exc), 503) from exc
    statuses = [test["status"] for test in result["tests"]]
    complete = bool(result["complete"])
    all_passed = complete and len(statuses) == len(cases) and all(status == "passed" for status in statuses)
    report = {
        "rubric_version_id": version_id, "runner_version": raw_result.get("runner_version"),
        "function_name": functions[0], "reference_hash": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        "overall_ok": all_passed, "complete": complete,
        "suggested_count": len(suggested), "teacher_edge_count": len(extra),
        "tests": [{"name": case["name"], "origin": "model" if index < len(suggested) else "teacher_edge",
                   "status": statuses[index] if index < len(statuses) else "missing"}
                  for index, case in enumerate(cases)],
        "note": "Совпадение с одним эталоном и этими примерами не доказывает полноту тестов для всех решений.",
    }
    db.session.add(AiLabRubricTestVerification(rubric_version_id=version_id, actor_user_id=actor_user_id,
                                                reference_hash=report["reference_hash"], report_json=report))
    db.session.commit()
    return report
