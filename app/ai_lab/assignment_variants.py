"""Persistence and bounded Runner verification for materialized family variants."""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app import db
from app.ai_lab.assignment_families import (
    AssignmentFamilyError,
    _canonical_hash,
    _validate_family_links,
    validate_variant_parameters,
)
from app.ai_lab.code_judge import CodeJudgeError, _serialize_test_set, validate_test_set
from app.ai_lab.family_templates import materialize_template, template_manifest
from core.db_models import AiLabAssignmentFamilyVersion, AiLabAssignmentVariant, AiLabCodeJudgeTestSet


def _test_set_content(test_set: AiLabCodeJudgeTestSet) -> dict[str, Any]:
    return {
        "scenario_id": test_set.scenario_id,
        "title": test_set.title,
        "description": test_set.description,
        "mode": test_set.mode,
        "function_name": test_set.function_name,
        "comparator": test_set.comparator,
        "tolerance": test_set.tolerance,
        "starter_code": test_set.starter_code,
        "test_cases": test_set.test_cases,
        "rubric_json": test_set.rubric_json,
        "assignment_id": test_set.assignment_id,
        "assignment_version": test_set.assignment_version,
        "test_set_version": test_set.test_set_version,
        "rubric_version": test_set.rubric_version,
    }


def _variant_content_hash(*, family: AiLabAssignmentFamilyVersion, parameters: dict,
                          task_snapshot: dict, test_set: AiLabCodeJudgeTestSet,
                          reference_code: str) -> str:
    return _canonical_hash({
        "family_id": family.family_id,
        "family_version": family.version_no,
        "family_content_sha256": family.content_sha256,
        "template_id": family.contract_json["template_id"],
        "parameters": parameters,
        "task": task_snapshot,
        "test_set": _test_set_content(test_set),
        "reference_code_sha256": hashlib.sha256(reference_code.encode("utf-8")).hexdigest(),
    })


def _serialize_variant(item: AiLabAssignmentVariant) -> dict[str, Any]:
    validation = item.validation_json or {}
    return {
        "id": item.id,
        "variant_id": item.variant_id,
        "family_id": item.family_id,
        "family_version_id": item.family_version_id,
        "family_version": item.family_version_no,
        "template_id": item.template_id,
        "parameters": item.parameters_json,
        "parameter_sha256": item.parameter_sha256,
        "assignment_id": item.assignment_id,
        "assignment_version": item.assignment_version,
        "scenario_id": item.scenario_id,
        "title": item.title,
        "condition": item.condition,
        "criteria": item.task_snapshot_json.get("criteria", []),
        "max_score": item.task_snapshot_json.get("max_score"),
        "metadata": item.task_snapshot_json.get("metadata", {}),
        "test_set_id": item.test_set_id,
        "test_set_version": item.test_set_version,
        "reference_run_id": item.reference_run_id,
        "content_sha256": item.content_sha256,
        "status": item.status,
        "validation": validation,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def list_family_variants(family_version_id: int | None = None) -> list[dict[str, Any]]:
    query = AiLabAssignmentVariant.query
    if family_version_id is not None:
        query = query.filter_by(family_version_id=family_version_id)
    return [_serialize_variant(item) for item in query.order_by(AiLabAssignmentVariant.created_at.desc()).limit(200).all()]


def _run_code(actor_user_id: int, variant: AiLabAssignmentVariant, code: str, purpose: str, bundle_no: int) -> dict[str, Any]:
    from app.ai_lab.code_judge import run_request

    test_set = db.session.get(AiLabCodeJudgeTestSet, variant.test_set_id)
    if test_set is None or test_set.test_set_version != variant.test_set_version:
        raise AssignmentFamilyError("Снимок тестов варианта изменился; повторная проверка запрещена.", 409)
    request_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"boostudy-family:{variant.variant_id}:{bundle_no}:{purpose}"))
    result, created = run_request(actor_user_id, {
        "request_key": request_key,
        "run_type": "submit",
        "code": code,
        "test_set_id": test_set.id,
        "test_set_version": test_set.test_set_version,
        "test_set": _serialize_test_set(test_set),
    })
    execution = result.get("result") or {}
    return {
        "purpose": purpose,
        "run_id": result.get("id"),
        "created": created,
        "status": result.get("status"),
        "passed": execution.get("passed", 0),
        "total": execution.get("total", 0),
        "complete": execution.get("complete") is True,
        "duration_ms": result.get("duration_ms"),
        "runner_version": result.get("runner_version"),
        "technical_error": result.get("technical_error"),
    }


def verify_family_variant(variant_id: int, actor_user_id: int) -> dict[str, Any]:
    item = db.session.get(AiLabAssignmentVariant, variant_id)
    if item is None:
        raise AssignmentFamilyError("Материализованный вариант не найден.", 404)
    if item.status == "available":
        return _serialize_variant(item)
    previous = item.validation_json or {}
    bundles = list(previous.get("bundles") or [])
    if len(bundles) >= 2:
        raise AssignmentFamilyError("Достигнут лимит двух комплектов проверок. Создайте новую версию шаблона для повторного исследования.", 409)
    family = db.session.get(AiLabAssignmentFamilyVersion, item.family_version_id)
    if not family or family.status != "approved" or _validate_family_links(family):
        raise AssignmentFamilyError("Семейство больше не прошло проверку совместимости.", 409)
    manifest = template_manifest(item.template_id)
    if manifest["template_sha256"] != family.contract_json.get("template_sha256"):
        raise AssignmentFamilyError("Генератор изменился после утверждения семейства.", 409)
    test_set = db.session.get(AiLabCodeJudgeTestSet, item.test_set_id)
    if test_set is None or test_set.test_set_version != item.test_set_version:
        raise AssignmentFamilyError("Тесты варианта устарели; требуется новая материализация.", 409)
    expected_hash = _variant_content_hash(
        family=family, parameters=item.parameters_json, task_snapshot=item.task_snapshot_json,
        test_set=test_set, reference_code=item.reference_code,
    )
    if expected_hash != item.content_sha256:
        raise AssignmentFamilyError("Содержимое варианта изменилось после создания.", 409)
    bundle_no = len(bundles) + 1
    generated = materialize_template(item.template_id, item.parameters_json)
    checks = []
    for purpose, code in (
        ("reference", generated["reference_code"]),
        ("alternative", generated["alternative_code"]),
        ("mutation", generated["mutant_code"]),
    ):
        checks.append(_run_code(actor_user_id, item, code, purpose, bundle_no))
    expected = {"reference": "accepted", "alternative": "accepted", "mutation": "wrong_answer"}
    accepted = all(
        check["status"] == expected[check["purpose"]]
        and check["complete"]
        and (check["passed"] == check["total"] if check["purpose"] != "mutation" else check["passed"] < check["total"])
        for check in checks
    )
    bundle = {"number": bundle_no, "checks": checks,
              "status": "passed" if accepted else "failed",
              "criteria_max_score": (test_set.rubric_json or []) and sum(float(c["max_score"]) for c in test_set.rubric_json)}
    bundles.append(bundle)
    item.validation_json = {
        "status": "passed" if accepted else "failed",
        "method": "Code Judge Runner: эталон, альтернативный алгоритм и контролируемая логическая ошибка.",
        "bundles": bundles,
        "limitations": ["Конечный набор тестов не доказывает корректность для всех допустимых входов."],
    }
    if accepted:
        item.reference_run_id = checks[0]["run_id"]
        item.status = "available"
    else:
        item.status = "validation_failed"
    db.session.commit()
    return _serialize_variant(item)


def materialize_family_variant(family_version_id: int, raw_parameters: Any,
                               actor_user_id: int) -> dict[str, Any]:
    family = db.session.get(AiLabAssignmentFamilyVersion, family_version_id)
    if family is None:
        raise AssignmentFamilyError("Версия семейства не найдена.", 404)
    if family.status != "approved":
        raise AssignmentFamilyError("Сначала утвердите версию семейства.", 409)
    errors = _validate_family_links(family)
    if errors:
        raise AssignmentFamilyError("Семейство устарело: " + " ".join(errors), 409)
    template_id = str(family.contract_json.get("template_id") or "")
    if not template_id:
        raise AssignmentFamilyError("Версия Sprint 9 не содержит доверенного генератора. Создайте новую версию семейства.", 409)
    values = validate_variant_parameters(family.contract_json, raw_parameters)
    parameter_sha = _canonical_hash(values)
    existing = AiLabAssignmentVariant.query.filter_by(
        family_version_id=family.id, parameter_sha256=parameter_sha,
    ).first()
    if existing:
        return _serialize_variant(existing)
    try:
        generated = materialize_template(template_id, values)
    except ValueError as exc:
        raise AssignmentFamilyError(str(exc)) from exc
    try:
        test_data = validate_test_set({
            "title": generated["title"], "description": generated["condition"],
            "mode": "function", "function_name": template_manifest(template_id)["function_name"],
            "starter_code": generated["starter_code"], "test_cases": generated["test_cases"],
            "rubric_json": generated["rubric_json"], "assignment_id": family.assignment_id,
            "assignment_version": family.assignment_version,
        })
    except CodeJudgeError as exc:
        raise AssignmentFamilyError(f"Генератор создал несовместимый набор Code Judge: {exc}", 409) from exc
    identity_hash = _canonical_hash({
        "family_id": family.family_id, "family_version": family.version_no,
        "family_sha256": family.content_sha256, "template_id": template_id,
        "parameters": values,
    })
    variant_id = f"{family.family_id}.v{family.version_no}.{identity_hash[:16]}"
    scenario_id = f"family-{identity_hash[:48]}"
    test_set = AiLabCodeJudgeTestSet(
        scenario_id=scenario_id,
        test_set_version=1,
        rubric_version=family.rubric_version_no,
        is_seeded=False,
        created_by_user_id=actor_user_id,
        **test_data,
    )
    db.session.add(test_set)
    db.session.flush()
    task_snapshot = {
        "type": "python", "subject": generated["metadata"]["subject"],
        "topic": generated["metadata"]["topic"], "difficulty": "Синтетическое",
        "condition": generated["condition"], "criteria": generated["criteria"],
        "assignment_criteria": [
            {"id": item["assignment_criterion_id"], "title": item["title"],
             "description": item["description"], "max_score": item["max_score"]}
            for item in test_data["rubric_json"]
        ],
        "max_score": sum(float(item["max_score"]) for item in test_data["rubric_json"]),
        "metadata": generated["metadata"],
        "family": {"family_id": family.family_id, "family_version": family.version_no,
                   "family_sha256": family.content_sha256,
                   "template_id": template_id, "parameter_sha256": parameter_sha},
    }
    variant = AiLabAssignmentVariant(
        variant_id=variant_id, family_version_id=family.id, family_id=family.family_id,
        family_version_no=family.version_no, template_id=template_id,
        parameter_sha256=parameter_sha, parameters_json=values,
        assignment_id=family.assignment_id, assignment_version=family.assignment_version,
        scenario_id=scenario_id, title=generated["title"], condition=generated["condition"],
        starter_code=generated["starter_code"], reference_code=generated["reference_code"],
        task_snapshot_json=task_snapshot, test_set_id=test_set.id,
        test_set_version=test_set.test_set_version, content_sha256="",
        validation_json={"status": "materialized", "bundles": []},
        status="materialized", created_by_user_id=actor_user_id,
    )
    variant.content_sha256 = _variant_content_hash(
        family=family, parameters=values, task_snapshot=task_snapshot,
        test_set=test_set, reference_code=generated["reference_code"],
    )
    db.session.add(variant)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = AiLabAssignmentVariant.query.filter_by(
            family_version_id=family.id, parameter_sha256=parameter_sha,
        ).first()
        if existing:
            return _serialize_variant(existing)
        raise
    return verify_family_variant(variant.id, actor_user_id)


def get_available_variant_scenario(scenario_id: str) -> dict[str, Any] | None:
    if not inspect(db.engine).has_table(AiLabAssignmentVariant.__tablename__):
        return None
    item = AiLabAssignmentVariant.query.filter_by(scenario_id=scenario_id, status="available").first()
    if item is None:
        return None
    family = db.session.get(AiLabAssignmentFamilyVersion, item.family_version_id)
    test_set = db.session.get(AiLabCodeJudgeTestSet, item.test_set_id)
    if not family or family.status != "approved" or test_set is None:
        return None
    if family.content_sha256 != item.task_snapshot_json.get("family", {}).get("family_sha256", family.content_sha256):
        return None
    if test_set.test_set_version != item.test_set_version:
        return None
    if _variant_content_hash(
        family=family, parameters=item.parameters_json, task_snapshot=item.task_snapshot_json,
        test_set=test_set, reference_code=item.reference_code,
    ) != item.content_sha256:
        return None
    if _validate_family_links(family):
        return None
    snapshot = dict(item.task_snapshot_json)
    snapshot.update({
        "id": item.scenario_id,
        "assignment_id": item.assignment_id,
        "assignment_version": item.assignment_version,
        "title": item.title,
        "condition": item.condition,
        "student_solution": "",
        "reference_answer": item.reference_code,
        "test_cases": test_set.test_cases or [],
        "family_variant_id": item.id,
        "family_variant": _serialize_variant(item),
        "expected": {"score": item.task_snapshot_json.get("max_score"), "human_review": True},
        "criteria": list(item.task_snapshot_json.get("criteria") or []),
    })
    return snapshot
