"""Versioned, explicitly approved reuse contracts for local synthetic Python tasks."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect

from app import db
from app.ai_lab.code_judge import list_python_assignments
from app.ai_lab.family_templates import template_manifest
from app.ai_lab.scenarios import get_python_assignment_source
from core.db_models import (
    AiLabAssignmentFamilyVersion,
    AiLabCodeJudgeRun,
    AiLabCodeJudgeTestSet,
    AiLabRubricVersion,
)


class AssignmentFamilyError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def family_storage_ready() -> bool:
    inspector = inspect(db.engine)
    return inspector.has_table("AiLabAssignmentFamilyVersions") and inspector.has_table("AiLabAssignmentVariants")


_FAMILY_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,119}$")
_PARAMETER_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_CONTRACT_BYTES = 32 * 1024


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_text(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise AssignmentFamilyError(f"Поле «{field}» должно быть текстом.")
    text = value.strip()
    if required and not text:
        raise AssignmentFamilyError(f"Заполните поле «{field}».")
    if len(text) > limit:
        raise AssignmentFamilyError(f"Поле «{field}» превышает {limit} символов.")
    return text


def validate_family_contract(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssignmentFamilyError("Контракт семейства должен быть корректным JSON.") from exc
    if not isinstance(raw, dict):
        raise AssignmentFamilyError("Контракт семейства должен быть объектом.")
    try:
        encoded_size = len(json.dumps(raw, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssignmentFamilyError("Контракт семейства должен содержать только JSON-значения.") from exc
    if encoded_size > _MAX_CONTRACT_BYTES:
        raise AssignmentFamilyError("Контракт семейства превышает 32 КБ.")

    raw_requirements = raw.get("requirements")
    raw_parameters = raw.get("variant_parameters", [])
    raw_sources = raw.get("source_refs")
    if not isinstance(raw_requirements, list) or not 1 <= len(raw_requirements) <= 20:
        raise AssignmentFamilyError("Укажите от 1 до 20 проверяемых требований.")
    if not isinstance(raw_parameters, list) or len(raw_parameters) > 20:
        raise AssignmentFamilyError("Список параметров варианта должен содержать не более 20 элементов.")
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 40:
        raise AssignmentFamilyError("Укажите от 1 до 40 ссылок на источники задания.")

    requirements = []
    seen_requirement_ids: set[str] = set()
    seen_criterion_ids: set[str] = set()
    for index, item in enumerate(raw_requirements, 1):
        if not isinstance(item, dict):
            raise AssignmentFamilyError(f"Требование №{index} должно быть объектом.")
        requirement_id = _bounded_text(item.get("id"), f"ID требования №{index}", 80)
        criterion_id = _bounded_text(item.get("criterion_id"), f"ID критерия №{index}", 80)
        description = _bounded_text(item.get("description"), f"Требование №{index}", 1000)
        refs = item.get("source_refs")
        if requirement_id in seen_requirement_ids:
            raise AssignmentFamilyError(f"ID требования «{requirement_id}» повторяется.")
        if criterion_id in seen_criterion_ids:
            raise AssignmentFamilyError(f"Критерий «{criterion_id}» должен иметь ровно одно требование семейства.")
        seen_requirement_ids.add(requirement_id)
        seen_criterion_ids.add(criterion_id)
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() or len(ref) > 180 for ref in refs):
            raise AssignmentFamilyError(f"Для требования «{requirement_id}» укажите ссылки на исходные доказательства.")
        requirements.append({"id": requirement_id, "criterion_id": criterion_id,
                             "description": description, "source_refs": list(dict.fromkeys(ref.strip() for ref in refs))})

    sources = []
    seen_source_refs: set[str] = set()
    for index, item in enumerate(raw_sources, 1):
        if not isinstance(item, dict):
            raise AssignmentFamilyError(f"Источник №{index} должен быть объектом.")
        source_ref = _bounded_text(item.get("source_ref"), f"ID источника №{index}", 180)
        try:
            source_version = int(item.get("version"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AssignmentFamilyError(f"Для источника «{source_ref}» укажите версию.") from exc
        digest = str(item.get("sha256") or "").strip().lower()
        if source_ref in seen_source_refs or source_version < 1 or not _SHA256.fullmatch(digest):
            raise AssignmentFamilyError(f"Источник «{source_ref}» должен иметь уникальный ID, версию и SHA-256.")
        seen_source_refs.add(source_ref)
        sources.append({"source_ref": source_ref, "version": source_version, "sha256": digest})

    source_ids = {item["source_ref"] for item in sources}
    for requirement in requirements:
        if not set(requirement["source_refs"]) <= source_ids:
            raise AssignmentFamilyError(f"Требование «{requirement['id']}» ссылается на источник вне контракта.")

    parameters = []
    seen_parameter_names: set[str] = set()
    for index, item in enumerate(raw_parameters, 1):
        if not isinstance(item, dict):
            raise AssignmentFamilyError(f"Параметр варианта №{index} должен быть объектом.")
        name = str(item.get("name") or "")
        kind = str(item.get("type") or "")
        if not _PARAMETER_ID.fullmatch(name) or name in seen_parameter_names or kind not in {"integer", "number", "string", "boolean", "enum"}:
            raise AssignmentFamilyError(f"Проверьте уникальное имя и тип параметра варианта №{index}.")
        seen_parameter_names.add(name)
        required = item.get("required", True)
        if type(required) is not bool:
            raise AssignmentFamilyError(f"Параметр «{name}»: required должен быть boolean.")
        spec = {"name": name, "type": kind, "required": required}
        if kind in {"integer", "number"}:
            low, high = item.get("minimum"), item.get("maximum")
            if isinstance(low, bool) or isinstance(high, bool):
                raise AssignmentFamilyError(f"Параметр «{name}»: границы должны быть числами.")
            try:
                low, high = float(low), float(high)
            except (TypeError, ValueError, OverflowError) as exc:
                raise AssignmentFamilyError(f"Параметр «{name}»: задайте обе границы.") from exc
            if not math.isfinite(low) or not math.isfinite(high) or low > high:
                raise AssignmentFamilyError(f"Параметр «{name}»: диапазон некорректен.")
            if kind == "integer" and (not low.is_integer() or not high.is_integer()):
                raise AssignmentFamilyError(f"Параметр «{name}»: целочисленный диапазон должен иметь целые границы.")
            spec.update(minimum=int(low) if kind == "integer" else low,
                        maximum=int(high) if kind == "integer" else high)
        elif kind == "string":
            try:
                maximum_length = int(item.get("max_length"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise AssignmentFamilyError(f"Параметр «{name}»: задайте max_length.") from exc
            if not 1 <= maximum_length <= 2000:
                raise AssignmentFamilyError(f"Параметр «{name}»: max_length должен быть от 1 до 2000.")
            spec["max_length"] = maximum_length
        elif kind == "enum":
            values = item.get("values")
            if not isinstance(values, list) or not 1 <= len(values) <= 100 or len(set(map(str, values))) != len(values):
                raise AssignmentFamilyError(f"Параметр «{name}»: enum должен содержать уникальные значения.")
            spec["values"] = values
        if "default" in item:
            spec["default"] = item["default"]
            validate_variant_parameters({"variant_parameters": [spec]}, {name: item["default"]})
        parameters.append(spec)

    compatibility = raw.get("compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("rule") != "exact_assignment_contract":
        raise AssignmentFamilyError("Правило совместимости должно явно задавать exact_assignment_contract.")
    try:
        schema_version = int(raw.get("schema_version") or 1)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssignmentFamilyError("Версия схемы контракта семейства некорректна.") from exc
    normalized = {"schema_version": schema_version, "requirements": requirements,
                  "variant_parameters": parameters, "source_refs": sources,
                  "compatibility": {"rule": "exact_assignment_contract"}}
    template_id = raw.get("template_id")
    if template_id is not None:
        try:
            manifest = template_manifest(str(template_id))
        except ValueError as exc:
            raise AssignmentFamilyError(str(exc)) from exc
        template_version = raw.get("template_version")
        template_hash = str(raw.get("template_sha256") or "")
        if (normalized["schema_version"] != 2 or template_version != manifest["version"]
                or template_hash != manifest["template_sha256"]):
            raise AssignmentFamilyError("Снимок генератора семейства устарел или не соответствует доверенному шаблону.", 409)
        expected_parameters = manifest["parameter_schema"]
        if parameters != expected_parameters:
            raise AssignmentFamilyError("Схема параметров отличается от утверждённого генератора.", 409)
        expected_requirements = manifest["requirements"]
        if [(item["id"], item["criterion_id"], item["description"]) for item in requirements] != [
            (item["id"], item["criterion_id"], item["description"]) for item in expected_requirements
        ]:
            raise AssignmentFamilyError("Требования отличаются от проверенного генератора семейства.", 409)
        normalized.update({"template_id": str(template_id), "template_version": manifest["version"],
                           "template_sha256": manifest["template_sha256"], "template_manifest": manifest})
    return normalized


def _canonical_family_sources(template_id: str, assignment_id: str, assignment_version: int,
                              rubric: AiLabRubricVersion, test_set: AiLabCodeJudgeTestSet,
                              reference_run: AiLabCodeJudgeRun) -> list[dict[str, Any]]:
    manifest = template_manifest(template_id)
    assignment_source = get_python_assignment_source(assignment_id, assignment_version)
    if assignment_source is None:
        raise AssignmentFamilyError("Каноническая версия синтетического задания больше недоступна.", 409)
    rubric_source = {
        "assignment_id": rubric.assignment_id, "assignment_version": rubric.assignment_version,
        "version_no": rubric.version_no, "task": rubric.task_json, "criteria": rubric.criteria_json,
        "status": rubric.status,
    }
    test_set_source = {
        "scenario_id": test_set.scenario_id, "title": test_set.title,
        "description": test_set.description, "mode": test_set.mode,
        "function_name": test_set.function_name, "comparator": test_set.comparator,
        "tolerance": test_set.tolerance, "starter_code": test_set.starter_code,
        "test_cases": test_set.test_cases, "rubric_json": test_set.rubric_json,
        "assignment_id": test_set.assignment_id, "assignment_version": test_set.assignment_version,
        "test_set_version": test_set.test_set_version, "rubric_version": test_set.rubric_version,
    }
    reference_source = {
        "test_set_id": reference_run.test_set_id, "test_set_version": reference_run.test_set_version,
        "run_type": reference_run.run_type, "status": reference_run.status,
        "code_hash": reference_run.code_hash, "runner_version": reference_run.runner_version,
        "result": reference_run.result_json,
    }
    return [
        {"source_ref": f"template:{template_id}", "version": manifest["version"],
         "sha256": manifest["template_sha256"]},
        {"source_ref": f"assignment:{assignment_id}", "version": assignment_version,
         "sha256": _canonical_hash(assignment_source)},
        {"source_ref": f"rubric:{rubric.id}", "version": rubric.version_no,
         "sha256": _canonical_hash(rubric_source)},
        {"source_ref": f"test-set:{test_set.id}", "version": test_set.test_set_version,
         "sha256": _canonical_hash(test_set_source)},
        {"source_ref": f"reference-run:{reference_run.id}", "version": 1,
         "sha256": _canonical_hash(reference_source)},
    ]


def _build_template_contract(template_id: str, assignment_id: str, assignment_version: int,
                             rubric: AiLabRubricVersion, test_set: AiLabCodeJudgeTestSet,
                             reference_run: AiLabCodeJudgeRun) -> dict[str, Any]:
    manifest = template_manifest(template_id)
    sources = _canonical_family_sources(template_id, assignment_id, assignment_version,
                                        rubric, test_set, reference_run)
    source_refs = [item["source_ref"] for item in sources]
    requirements = [
        {**requirement, "source_refs": source_refs}
        for requirement in manifest["requirements"]
    ]
    return validate_family_contract({
        "schema_version": 2, "template_id": template_id, "template_version": manifest["version"],
        "template_sha256": manifest["template_sha256"], "requirements": requirements,
        "variant_parameters": manifest["parameter_schema"], "source_refs": sources,
        "compatibility": {"rule": "exact_assignment_contract"},
    })


def _family_content_hash(*, family_id: str, title: str, assignment_id: str,
                         assignment_version: int, rubric_version_id: int, rubric_version_no: int,
                         test_set_id: int, test_set_version: int, reference_run_id: int,
                         contract: dict[str, Any]) -> str:
    return _canonical_hash({"family_id": family_id, "title": title, "assignment_id": assignment_id,
                            "assignment_version": assignment_version, "rubric_version_id": rubric_version_id,
                            "rubric_version_no": rubric_version_no, "test_set_id": test_set_id,
                            "test_set_version": test_set_version, "reference_run_id": reference_run_id,
                            "contract": contract})


def _serialize(item: AiLabAssignmentFamilyVersion) -> dict[str, Any]:
    return {"id": item.id, "family_id": item.family_id, "version_no": item.version_no,
            "title": item.title, "assignment_id": item.assignment_id,
            "assignment_version": item.assignment_version, "rubric_version_id": item.rubric_version_id,
            "rubric_version_no": item.rubric_version_no, "test_set_id": item.test_set_id,
            "test_set_version": item.test_set_version, "reference_run_id": item.reference_run_id,
            "contract": item.contract_json, "compatibility": item.compatibility_json,
            "content_sha256": item.content_sha256, "validation": item.validation_json,
            "status": item.status, "approved_at": item.approved_at.isoformat() if item.approved_at else None}


def list_family_versions(*, approved_only: bool = False) -> list[dict[str, Any]]:
    query = AiLabAssignmentFamilyVersion.query
    if approved_only:
        query = query.filter_by(status="approved")
    rows = query.order_by(AiLabAssignmentFamilyVersion.family_id.asc(),
                          AiLabAssignmentFamilyVersion.version_no.desc()).all()
    return [_serialize(item) for item in rows
            if not approved_only or not _validate_family_links(item)]


def create_family_version(raw: Any, actor_user_id: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AssignmentFamilyError("Запрос должен быть объектом.")
    family_id = _bounded_text(raw.get("family_id"), "ID семейства", 120).lower()
    if not _FAMILY_ID.fullmatch(family_id):
        raise AssignmentFamilyError("Используйте стабильный ID семейства из латинских букв, цифр, точек, двоеточий, подчёркиваний или дефисов.")
    title = _bounded_text(raw.get("title"), "название семейства", 180)
    template_id = str(raw.get("template_id") or "").strip()
    template = None
    if template_id:
        try:
            template = template_manifest(template_id)
        except ValueError as exc:
            raise AssignmentFamilyError(str(exc)) from exc
        if family_id != template["family_id"] or title != template["title"]:
            raise AssignmentFamilyError("ID и название для этого типа семейства задаёт доверенный шаблон.", 409)
    try:
        assignment_version = int(raw.get("assignment_version"))
        rubric_version_id = int(raw.get("rubric_version_id"))
        test_set_id = int(raw.get("test_set_id"))
        reference_run_id = int(raw.get("reference_run_id"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssignmentFamilyError("Выберите точные версии задания, рубрики, тестов и проверенный эталонный запуск.") from exc
    assignment_id = _bounded_text(raw.get("assignment_id"), "ID задания", 120)
    contract = None if template else validate_family_contract(raw.get("contract"))
    known_assignment = next((item for item in list_python_assignments()
                             if item.get("assignment_id") == assignment_id
                             and item.get("assignment_version") == assignment_version), None)
    if known_assignment is None:
        raise AssignmentFamilyError("Связать можно только точную версию синтетического Python-задания.")
    rubric = db.session.get(AiLabRubricVersion, rubric_version_id)
    test_set = db.session.get(AiLabCodeJudgeTestSet, test_set_id)
    reference_run = db.session.get(AiLabCodeJudgeRun, reference_run_id)
    if not rubric or not test_set or not reference_run:
        raise AssignmentFamilyError("Связанная рубрика, набор тестов или эталонный запуск не найдены.", 404)
    if rubric.status != "approved":
        raise AssignmentFamilyError("Семейство можно связать только с явно утверждённой рубрикой.", 409)
    if (rubric.assignment_id != assignment_id or rubric.assignment_version != assignment_version
            or test_set.assignment_id != assignment_id or test_set.assignment_version != assignment_version):
        raise AssignmentFamilyError("Задание, утверждённая рубрика и набор тестов должны иметь один точный ID и версию.", 409)
    if reference_run.actor_user_id != actor_user_id or reference_run.run_type != "submit" or reference_run.status != "accepted":
        raise AssignmentFamilyError("Эталон должен быть успешно проверенным запуском Code Judge, созданным этим администратором.", 409)
    if reference_run.test_set_id != test_set.id or reference_run.test_set_version != test_set.test_set_version:
        raise AssignmentFamilyError("Эталонный запуск использует другую версию тестового набора.", 409)
    if (test_set.rubric_version or 1) != rubric.version_no:
        raise AssignmentFamilyError("Версия тестов не связана с выбранной версией рубрики.", 409)

    if template:
        if assignment_id != template["assignment_id"] or assignment_version != template["assignment_version"]:
            raise AssignmentFamilyError("Выбранное задание не соответствует доверенному типу семейства.", 409)
        expected_ids = {item["criterion_id"] for item in template["requirements"]}
        rubric_ids = {str(item.get("id")) for item in (rubric.criteria_json or [])}
        test_rubric_ids = {str(item.get("assignment_criterion_id")) for item in (test_set.rubric_json or [])}
        if rubric_ids != expected_ids or test_rubric_ids != expected_ids:
            raise AssignmentFamilyError("Рубрика и набор Code Judge должны точно покрывать критерии выбранного шаблона.", 409)
        contract = _build_template_contract(
            template_id, assignment_id, assignment_version, rubric, test_set, reference_run,
        )

    latest = AiLabAssignmentFamilyVersion.query.filter_by(family_id=family_id).order_by(
        AiLabAssignmentFamilyVersion.version_no.desc()).first()
    version_no = latest.version_no + 1 if latest else 1
    digest = _family_content_hash(family_id=family_id, title=title, assignment_id=assignment_id,
                                  assignment_version=assignment_version, rubric_version_id=rubric.id,
                                  rubric_version_no=rubric.version_no, test_set_id=test_set.id,
                                  test_set_version=test_set.test_set_version, reference_run_id=reference_run.id,
                                  contract=contract)
    if latest and latest.content_sha256 == digest:
        return _serialize(latest)
    item = AiLabAssignmentFamilyVersion(
        family_id=family_id, version_no=version_no, title=title, assignment_id=assignment_id,
        assignment_version=assignment_version, rubric_version_id=rubric.id,
        rubric_version_no=rubric.version_no, test_set_id=test_set.id,
        test_set_version=test_set.test_set_version, reference_run_id=reference_run.id,
        contract_json=contract, compatibility_json={"rule": "exact_assignment_contract"},
        content_sha256=digest, validation_json={"status": "not_checked"}, status="draft",
        created_by_user_id=actor_user_id,
    )
    db.session.add(item)
    db.session.commit()
    return _serialize(item)


def _validate_family_links(item: AiLabAssignmentFamilyVersion) -> list[str]:
    errors: list[str] = []
    rubric = db.session.get(AiLabRubricVersion, item.rubric_version_id)
    test_set = db.session.get(AiLabCodeJudgeTestSet, item.test_set_id)
    reference_run = db.session.get(AiLabCodeJudgeRun, item.reference_run_id)
    if not rubric or rubric.status != "approved":
        errors.append("Утверждённая рубрика больше недоступна.")
    if not test_set:
        errors.append("Набор Code Judge больше недоступен.")
    if not reference_run:
        errors.append("Эталонный запуск Code Judge больше недоступен.")
    if errors:
        return errors
    assert rubric and test_set and reference_run
    if (rubric.assignment_id != item.assignment_id or rubric.assignment_version != item.assignment_version
            or rubric.version_no != item.rubric_version_no):
        errors.append("Версия задания в рубрике отличается от семейства.")
    if (test_set.assignment_id != item.assignment_id or test_set.assignment_version != item.assignment_version
            or test_set.test_set_version != item.test_set_version or test_set.rubric_version != item.rubric_version_no):
        errors.append("Снимок тестов или рубрики изменился после создания семейства.")
    if (reference_run.status != "accepted" or reference_run.test_set_id != test_set.id
            or reference_run.run_type != "submit" or reference_run.test_set_version != item.test_set_version
            or reference_run.actor_user_id != item.created_by_user_id):
        errors.append("Эталонный запуск не подтверждает сохранённую версию тестов.")
    snapshot = (reference_run.result_json or {}).get("test_set_snapshot") or {}
    if (snapshot.get("assignment_id") != item.assignment_id
            or snapshot.get("assignment_version") != item.assignment_version
            or snapshot.get("test_set_version") != item.test_set_version):
        errors.append("Снимок эталонного запуска относится к другой версии задания или тестов.")

    rubric_criteria = {str(value.get("id")): value for value in (rubric.criteria_json or []) if value.get("id")}
    linked_criteria = {str(value.get("assignment_criterion_id")): value
                       for value in (test_set.rubric_json or []) if value.get("assignment_criterion_id")}
    if (not rubric_criteria or len(rubric_criteria) != len(rubric.criteria_json or [])
            or len(linked_criteria) != len(test_set.rubric_json or [])
            or set(rubric_criteria) != set(linked_criteria)):
        errors.append("Каждый критерий рубрики должен быть привязан к отдельному критерию Code Judge.")
    for criterion_id, definition in rubric_criteria.items():
        mapped = linked_criteria.get(criterion_id)
        if mapped and (abs(float(definition.get("max_score") or 0) - float(mapped.get("max_score") or 0)) > 0.001
                       or not mapped.get("checks")):
            errors.append(f"Критерий «{criterion_id}» имеет другой максимум или не связан с тестами.")
    try:
        contract = validate_family_contract(item.contract_json)
        requirement_ids = [value["criterion_id"] for value in contract["requirements"]]
        if len(requirement_ids) != len(set(requirement_ids)) or set(requirement_ids) != set(rubric_criteria):
            errors.append("Требования семейства должны покрывать каждый утверждённый критерий ровно один раз.")
    except AssignmentFamilyError as exc:
        errors.append(str(exc))
    expected_hash = _family_content_hash(
        family_id=item.family_id, title=item.title, assignment_id=item.assignment_id,
        assignment_version=item.assignment_version, rubric_version_id=item.rubric_version_id,
        rubric_version_no=item.rubric_version_no, test_set_id=item.test_set_id,
        test_set_version=item.test_set_version, reference_run_id=item.reference_run_id,
        contract=item.contract_json,
    )
    if expected_hash != item.content_sha256:
        errors.append("Хеш контракта семейства не совпадает с сохранённой версией.")
    if item.contract_json.get("template_id"):
        try:
            canonical_sources = _canonical_family_sources(
                item.contract_json["template_id"], item.assignment_id, item.assignment_version,
                rubric, test_set, reference_run,
            )
            if canonical_sources != item.contract_json.get("source_refs"):
                errors.append("Содержимое задания, рубрики, тестов или эталона изменилось после сохранения версии семейства.")
            manifest = template_manifest(item.contract_json["template_id"])
            if manifest["family_id"] != item.family_id or manifest["template_sha256"] != item.contract_json.get("template_sha256"):
                errors.append("Доверенный генератор семейства изменился; создайте новую версию шаблона.")
        except (AssignmentFamilyError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def verify_family_version(version_id: int) -> dict[str, Any]:
    item = db.session.get(AiLabAssignmentFamilyVersion, version_id)
    if item is None:
        raise AssignmentFamilyError("Версия семейства не найдена.", 404)
    if item.status != "draft":
        raise AssignmentFamilyError("Проверять можно только черновик новой версии семейства.", 409)
    errors = _validate_family_links(item)
    item.validation_json = {"status": "invalid" if errors else "verified",
                            "errors": errors, "checks": ["exact_assignment_version", "approved_rubric",
                            "criterion_mapping", "saved_test_version", "accepted_reference_run", "content_hash"]}
    if not errors:
        item.status = "verified"
    db.session.commit()
    return _serialize(item)


def approve_family_version(version_id: int, actor_user_id: int) -> dict[str, Any]:
    item = db.session.get(AiLabAssignmentFamilyVersion, version_id)
    if item is None:
        raise AssignmentFamilyError("Версия семейства не найдена.", 404)
    if item.status != "verified":
        raise AssignmentFamilyError("Сначала успешно проверьте совместимость версии.", 409)
    latest = AiLabAssignmentFamilyVersion.query.filter_by(family_id=item.family_id).order_by(
        AiLabAssignmentFamilyVersion.version_no.desc()).first()
    if latest is None or latest.id != item.id:
        raise AssignmentFamilyError("Утвердить можно только последнюю версию семейства.", 409)
    errors = _validate_family_links(item)
    if errors:
        item.status = "draft"
        item.validation_json = {"status": "invalid", "errors": errors}
        db.session.commit()
        raise AssignmentFamilyError("Связанные версии изменились; заново проверьте семейство.", 409)
    item.status = "approved"
    item.approved_by_user_id = actor_user_id
    item.approved_at = datetime.now(timezone.utc)
    db.session.commit()
    return _serialize(item)


def validate_variant_parameters(contract: dict[str, Any], raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AssignmentFamilyError("Параметры варианта должны быть объектом.")
    schema = {item["name"]: item for item in contract["variant_parameters"]}
    unknown = set(raw) - set(schema)
    if unknown:
        raise AssignmentFamilyError("Вариант содержит параметры, которых нет в утверждённом контракте.")
    values: dict[str, Any] = {}
    for name, spec in schema.items():
        if name not in raw:
            if "default" in spec:
                values[name] = spec["default"]
                continue
            if spec["required"]:
                raise AssignmentFamilyError(f"Укажите параметр варианта «{name}».")
            continue
        value = raw[name]
        kind = spec["type"]
        if kind == "integer":
            if type(value) is not int or not spec["minimum"] <= value <= spec["maximum"]:
                raise AssignmentFamilyError(f"Параметр «{name}» должен быть целым числом в утверждённом диапазоне.")
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not spec["minimum"] <= value <= spec["maximum"]:
                raise AssignmentFamilyError(f"Параметр «{name}» выходит за утверждённый числовой диапазон.")
        elif kind == "string":
            if not isinstance(value, str) or len(value) > spec["max_length"]:
                raise AssignmentFamilyError(f"Параметр «{name}» превышает допустимую длину.")
        elif kind == "boolean" and type(value) is not bool:
            raise AssignmentFamilyError(f"Параметр «{name}» должен быть логическим значением.")
        elif kind == "enum" and value not in spec["values"]:
            raise AssignmentFamilyError(f"Параметр «{name}» не входит в утверждённый список значений.")
        values[name] = value
    return values


def resolve_family_version(*, family_id: str, version_no: int, assignment_id: str,
                           assignment_version: int, variant_parameters: Any) -> dict[str, Any]:
    item = AiLabAssignmentFamilyVersion.query.filter_by(family_id=family_id, version_no=version_no).first()
    if item is None:
        raise AssignmentFamilyError("Указанная версия семейства не найдена.", 404)
    if item.status != "approved":
        raise AssignmentFamilyError("Семейство ещё не утверждено преподавателем.", 409)
    if item.assignment_id != assignment_id or item.assignment_version != assignment_version:
        raise AssignmentFamilyError("Версия семейства несовместима с выбранной версией задания.", 409)
    errors = _validate_family_links(item)
    if errors:
        raise AssignmentFamilyError("Семейство больше не совместимо со связанными версиями: " + " ".join(errors), 409)
    contract = validate_family_contract(item.contract_json)
    values = validate_variant_parameters(contract, variant_parameters)
    return {"family_id": item.family_id, "family_version": item.version_no,
            "family_title": item.title, "content_sha256": item.content_sha256,
            "assignment_id": item.assignment_id, "assignment_version": item.assignment_version,
            "rubric_version_id": item.rubric_version_id, "rubric_version": item.rubric_version_no,
            "test_set_id": item.test_set_id, "test_set_version": item.test_set_version,
            "variant_parameters": values, "criteria": contract["requirements"],
            "template_id": contract.get("template_id"),
            "template_sha256": contract.get("template_sha256"),
            "source_refs": contract["source_refs"], "compatibility_status": "exact_version_match"}


def compatible_families(assignment_id: str, assignment_version: int) -> list[dict[str, Any]]:
    rows = AiLabAssignmentFamilyVersion.query.filter_by(
        assignment_id=assignment_id, assignment_version=assignment_version, status="approved",
    ).order_by(AiLabAssignmentFamilyVersion.family_id.asc(), AiLabAssignmentFamilyVersion.version_no.desc()).all()
    return [_serialize(item) for item in rows if not _validate_family_links(item)]
