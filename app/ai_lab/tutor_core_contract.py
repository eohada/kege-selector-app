"""Versioned, tool-independent Python contract over the existing Tutor Core."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from app.ai_lab.learning_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    EvidenceContractError,
    merge_evidence_events,
    validate_evidence_event,
)


TUTOR_CORE_CLIENT_CONTRACT = "boostudy.tutor-core-client.v1"
CLIENT_EVENT_SCENARIO = "tutor-core-client-learning-event-v1"
_CLIENT_ID_RE = re.compile(r"[a-z][a-z0-9_.-]{1,63}")
_SUBJECT_ID_RE = re.compile(r"platform-student:([1-9][0-9]*)")
_CONFIRMED = {"technical_confirmed", "expert_confirmed"}
_EVENT_WRITE_LOCK = threading.Lock()


class TutorCoreContractError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ClientAdapter:
    source_modules: frozenset[str]
    resolve_event: Callable[[int, str, str], dict[str, Any] | None]
    resolve_skill: Callable[[str, str], dict[str, Any] | None]
    list_candidates: Callable[[str, str, str], Iterable[dict[str, Any]]] | None = None


class TutorCoreV1:
    """Server-side facade; source adapters remain responsible for authoritative reads."""

    contract_version = TUTOR_CORE_CLIENT_CONTRACT

    def __init__(self) -> None:
        self._clients: dict[str, ClientAdapter] = {}

    def register_client(self, client_id: str, adapter: ClientAdapter) -> None:
        if not isinstance(client_id, str) or not _CLIENT_ID_RE.fullmatch(client_id):
            raise TutorCoreContractError("invalid_client_id", "Укажите стабильный идентификатор клиента Tutor Core.")
        if client_id in self._clients:
            raise TutorCoreContractError("client_already_registered", "Такой клиент Tutor Core уже зарегистрирован.", 409)
        if (not isinstance(adapter, ClientAdapter) or not adapter.source_modules
                or not adapter.source_modules.issubset({
                    "ai_homework", "ai_classwork", "ai_analytics", "ai_practice",
                    "ai_course", "ai_lesson_intelligence", "ai_tutor_core",
                })
                or not callable(adapter.resolve_event) or not callable(adapter.resolve_skill)
                or adapter.list_candidates is not None and not callable(adapter.list_candidates)):
            raise TutorCoreContractError("invalid_client_adapter", "Адаптер клиента не соответствует контракту Tutor Core.")
        self._clients[client_id] = adapter

    def client(self, client_id: str) -> "TutorCoreClientV1":
        self._adapter(client_id)
        return TutorCoreClientV1(self, client_id)

    def _adapter(self, client_id: str) -> ClientAdapter:
        adapter = self._clients.get(client_id)
        if adapter is None:
            raise TutorCoreContractError("unknown_client", "Клиент не зарегистрирован в Tutor Core.", 403)
        return adapter

    def _require_safe_local_runtime(self) -> None:
        from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
        from app.ai_lab.provider import is_local_ai_lab_enabled

        if not is_local_ai_lab_enabled() or not has_verified_safe_ai_lab_db():
            raise TutorCoreContractError(
                "safe_local_runtime_required",
                "Этот адаптер v1 разрешён только в локальной AI Lab с подтверждённой synthetic SQLite.",
                503,
            )

    def _authorize_subject(self, actor_user_id: int, subject_id: str):
        self._require_safe_local_runtime()
        match = _SUBJECT_ID_RE.fullmatch(str(subject_id or ""))
        if not match:
            raise TutorCoreContractError("invalid_subject", "Укажите platform-student ID синтетического ученика.")

        from app.ai_lab.platform_homework import _allowlisted_actor_ids, _allowlisted_user_ids
        from app.utils.relationship_scope import can_user_access_student
        from core.db_models import Student, User, db

        subject_user_id = int(match.group(1))
        actor = db.session.get(User, int(actor_user_id))
        student_user = db.session.get(User, subject_user_id)
        student = Student.query.filter_by(user_id=subject_user_id).first()
        if (not actor or not actor.is_active or not student_user or not student_user.is_active
                or str(student_user.role or "").casefold() != "student" or not student or not student.is_active
                or subject_user_id not in _allowlisted_user_ids()
                or not str(student_user.username or "").casefold().startswith(("demo_", "synthetic_"))):
            raise TutorCoreContractError("subject_not_allowed", "Субъект не входит в разрешённый synthetic allowlist.", 403)

        actor_role = str(actor.role or "").casefold()
        if actor.id == subject_user_id:
            return actor, student
        if (actor_role in {"admin", "creator", "superadmin", "super_admin", "tutor", "teacher"}
                and int(actor.id) in _allowlisted_actor_ids()
                and can_user_access_student(actor, student_user_id=subject_user_id,
                                            student_platform_id=int(student.student_id))):
            return actor, student
        raise TutorCoreContractError("subject_access_denied", "У пользователя нет доступа к этому ученику.", 403)

    def record_learning_event(
        self, client_id: str, actor_user_id: int, subject_id: str, source_record_id: str,
    ) -> dict[str, Any]:
        """Resolve an authoritative source record, validate it, and persist idempotently."""
        adapter = self._adapter(client_id)
        self._authorize_subject(actor_user_id, subject_id)
        if not isinstance(source_record_id, str) or not source_record_id.strip() or len(source_record_id) > 240:
            raise TutorCoreContractError("invalid_source_record", "Укажите стабильный ID исходной попытки.")

        raw = adapter.resolve_event(int(actor_user_id), subject_id, source_record_id.strip())
        if not isinstance(raw, dict):
            raise TutorCoreContractError("source_event_unavailable", "Источник не подтвердил эту учебную попытку.", 404)
        try:
            event = validate_evidence_event(raw)
        except EvidenceContractError as exc:
            raise TutorCoreContractError("invalid_evidence", str(exc)) from exc
        if (raw.get("contract_version") != EVIDENCE_CONTRACT_VERSION
                or event["subject_id"] != subject_id
                or event["source_record_id"] != source_record_id.strip()
                or event["source_module"] not in adapter.source_modules):
            raise TutorCoreContractError(
                "source_event_mismatch", "Подтверждённая запись не совпадает с субъектом, источником или ID запроса.", 409,
            )
        if event["evidence_status"] in _CONFIRMED:
            provenance = event.get("provenance") or {}
            if (not provenance.get("source_ref") or not provenance.get("method")
                    or not re.fullmatch(r"[0-9a-f]{64}", provenance.get("payload_hash", ""))):
                raise TutorCoreContractError(
                    "unverifiable_source", "Подтверждённому результату нужны источник, метод проверки и SHA-256 payload.",
                )
            if event["evidence_status"] == "expert_confirmed" and not provenance.get("evaluation_revision"):
                raise TutorCoreContractError(
                    "missing_expert_revision", "Экспертный результат требует явной ревизии и автора оценки.",
                )

        from core.db_models import AiLabExperiment, db
        from sqlalchemy.exc import IntegrityError

        canonical = _canonical_json(event)
        provenance = event.get("provenance") or {}
        if (not provenance.get("source_ref") or not provenance.get("method")
                or not re.fullmatch(r"[0-9a-f]{64}", provenance.get("payload_hash", ""))):
            raise TutorCoreContractError(
                "unverifiable_source", "Событию нужны точная ссылка на источник, метод и SHA-256 исходного payload.",
            )
        request_key = hashlib.sha256(
            f"{subject_id}:{event['event_id']}".encode("utf-8")
        ).hexdigest()[:36]
        with _EVENT_WRITE_LOCK:
            existing = AiLabExperiment.query.filter_by(
                scenario_id=CLIENT_EVENT_SCENARIO, request_key=request_key,
            ).first()
            if existing:
                stored = (existing.result_json or {}).get("event") if isinstance(existing.result_json, dict) else None
                if not isinstance(stored, dict) or _canonical_json(stored) != canonical:
                    raise TutorCoreContractError(
                        "event_id_conflict", "Этот event_id уже сохранён с другим содержимым.", 409,
                    )
                return {
                    "contract_version": self.contract_version,
                    "event_id": event["event_id"], "stored": True, "duplicate": True,
                    "evidence_status": event["evidence_status"],
                }

            record = AiLabExperiment(
                actor_user_id=int(actor_user_id), request_key=request_key,
                scenario_id=CLIENT_EVENT_SCENARIO, status="succeeded", provider="local",
                prompt_snapshot="Источник передал проверяемое учебное событие в Tutor Core.",
                scenario_snapshot={"client_id": client_id, "subject_id": subject_id,
                                   "contract_version": self.contract_version},
                input_snapshot={"source_record_id": source_record_id.strip(), "event_id": event["event_id"]},
                expected_snapshot={}, result_json={"event": event}, validation_status="valid",
                quality_json={"module": "tutor_core_client_event", "synthetic_only": True},
            )
            db.session.add(record)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                existing = AiLabExperiment.query.filter_by(
                    scenario_id=CLIENT_EVENT_SCENARIO, request_key=request_key,
                ).first()
                stored = ((existing.result_json or {}).get("event")
                          if existing and isinstance(existing.result_json, dict) else None)
                if not isinstance(stored, dict):
                    raise
                if _canonical_json(stored) != canonical:
                    raise TutorCoreContractError(
                        "event_id_conflict", "Этот event_id уже сохранён с другим содержимым.", 409,
                    )
                return {
                    "contract_version": self.contract_version,
                    "event_id": event["event_id"], "stored": True, "duplicate": True,
                    "evidence_status": event["evidence_status"],
                }
        return {
            "contract_version": self.contract_version,
            "event_id": event["event_id"], "stored": True, "duplicate": False,
            "evidence_status": event["evidence_status"],
        }

    def learning_profile(self, actor_user_id: int, subject_id: str) -> dict[str, Any]:
        self._authorize_subject(actor_user_id, subject_id)
        from app.ai_lab.tutor_core31 import get_tutor_core31_evidence_bundle, _profile_card

        bundle = get_tutor_core31_evidence_bundle(int(actor_user_id), subject_id=subject_id)
        profile = _profile_card(subject_id, bundle["events"], 1, int(actor_user_id))
        return {
            "contract_version": self.contract_version,
            "subject_id": subject_id,
            "profile": profile,
            "evidence": {
                "event_count": bundle["event_count"],
                "duplicate_count": bundle["duplicate_count"],
                "events": bundle["events"],
            },
            "course_required": False,
        }

    def next_practice_step(
        self, client_id: str, actor_user_id: int, subject_id: str, goal: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = self._adapter(client_id)
        self._authorize_subject(actor_user_id, subject_id)
        skill_id, criterion_id, skill = _validated_goal(goal, adapter)
        bundle = self._events_for_subject(int(actor_user_id), subject_id)
        evidence_summary = _summarize_evidence(bundle, skill_id, criterion_id)
        evidence_refs = evidence_summary["used_event_ids"]
        if not adapter.list_candidates:
            return _unavailable_practice(skill_id, criterion_id,
                                         "Для клиента не подключён проверенный каталог упражнений.",
                                         evidence_summary)

        from app.ai_lab.practice import select_next_practice_exercise, validate_practice_exercise
        candidates, candidate_sources = _trusted_candidates(
            adapter, subject_id, skill_id, criterion_id,
        )
        if not candidates:
            return _unavailable_practice(
                skill_id, criterion_id,
                "В доступном банке нет задания с проверенным эталоном, checker и точной привязкой к критерию.",
                evidence_summary,
            )
        attempts = _practice_attempts(bundle, skill_id, criterion_id)
        selected = select_next_practice_exercise(candidates, skill_id=skill_id, attempts=attempts)
        exercise = selected.get("exercise")
        if exercise is None:
            return {
                "contract_version": self.contract_version, "status": selected["action"],
                "action": selected["action"], "skill_id": skill_id, "criterion_id": criterion_id,
                "reason": selected["reason"], "evidence_refs": evidence_refs,
                "evidence": evidence_summary,
                "candidate": None, "model_used": False,
                "next_material_requirements": _material_requirements(skill_id, criterion_id),
                "explanation": _decision_explanation(selected["action"], selected["reason"], evidence_summary),
            }
        source = candidate_sources.get(exercise["exercise_id"], {})
        return {
            "contract_version": self.contract_version, "status": "recommended",
            "action": selected["action"], "skill_id": skill_id, "criterion_id": criterion_id,
            "goal": str(goal.get("description") or "").strip(),
            "skill": {"skill_id": skill_id, "title": skill["title"],
                      "criterion_id": criterion_id,
                      "criterion_description": skill["criterion_description"]},
            "reason": selected["reason"],
            "evidence_refs": evidence_refs,
            "evidence": evidence_summary,
            "candidate": {
                "exercise_id": exercise["exercise_id"],
                "version": source["version"], "source_id": source["source_id"],
                "difficulty": exercise.get("difficulty"),
                "prompt": exercise["prompt"],
                "answer_type": exercise["answer_type"],
                "checker_id": source["checker_id"],
                "checker_version": source["checker_version"],
                "content_sha256": source["content_sha256"],
            },
            "next_material_requirements": _material_requirements(skill_id, criterion_id),
            "explanation": _decision_explanation(selected["action"], selected["reason"], evidence_summary),
            "limitations": [
                "Проверенный набор заданий не доказывает корректность для всех возможных случаев.",
                "Одна правильная попытка не подтверждает mastery; помощь вне платформы может быть неизвестна.",
            ],
            "model_used": False,
        }

    def explain_decision(
        self, client_id: str, actor_user_id: int, subject_id: str, goal: dict[str, Any],
    ) -> dict[str, Any]:
        decision = self.next_practice_step(client_id, actor_user_id, subject_id, goal)
        evidence = decision.get("evidence") or {}
        explanation = decision.get("explanation") or {}
        return {
            "contract_version": self.contract_version,
            "decision": decision,
            "used_evidence": evidence.get("used_event_ids", []),
            "excluded_evidence": evidence.get("excluded", []),
            "teacher_explanation": explanation.get("teacher"),
            "student_explanation": explanation.get("student"),
            "model_used": False,
        }

    def quiz_specification(
        self, client_id: str, actor_user_id: int, subject_id: str, *,
        skill_id: str, criterion_id: str, question_count: int = 3,
        difficulty_range: tuple[int, int] = (1, 5),
    ) -> dict[str, Any]:
        adapter = self._adapter(client_id)
        self._authorize_subject(actor_user_id, subject_id)
        skill = adapter.resolve_skill(skill_id, criterion_id)
        if not _skill_resolves(skill, skill_id, criterion_id):
            raise TutorCoreContractError("unknown_skill_criterion", "Навык или критерий не разрешился однозначно.", 404)
        if type(question_count) is not int or not 1 <= question_count <= 10:
            raise TutorCoreContractError("invalid_question_count", "Количество вопросов должно быть от 1 до 10.")
        if (not isinstance(difficulty_range, (tuple, list)) or len(difficulty_range) != 2
                or any(type(value) is not int or not 1 <= value <= 5 for value in difficulty_range)
                or difficulty_range[0] > difficulty_range[1]):
            raise TutorCoreContractError("invalid_difficulty_range", "Укажите корректный диапазон сложности 1–5.")

        bundle = self._events_for_subject(int(actor_user_id), subject_id)
        attempted = {item.get("exercise_id") for item in _practice_attempts(bundle, skill_id, criterion_id)}
        existing = []
        if adapter.list_candidates:
            candidates, sources = _trusted_candidates(adapter, subject_id, skill_id, criterion_id)
            for item in candidates:
                difficulty = _difficulty_rank(item.get("difficulty"))
                if item["exercise_id"] in attempted or not difficulty_range[0] <= difficulty <= difficulty_range[1]:
                    continue
                source = sources[item["exercise_id"]]
                existing.append({"exercise_id": item["exercise_id"], "source_id": source["source_id"],
                                 "version": source["version"], "checker_id": source["checker_id"],
                                 "checker_version": source["checker_version"],
                                 "content_sha256": source["content_sha256"],
                                 "difficulty": item.get("difficulty")})
        existing = sorted(existing, key=lambda item: (item["difficulty"], item["exercise_id"]))[:question_count]
        missing = max(0, question_count - len(existing))
        return {
            "contract_version": self.contract_version,
            "status": "ready_existing_material" if missing == 0 else "needs_author_or_generator",
            "skill": {"skill_id": skill_id, "title": str(skill["title"])},
            "criterion": {"criterion_id": criterion_id, "description": str(skill["criterion_description"])},
            "purpose": "Проверить конкретный микронавык короткой независимой работой.",
            "question_count": question_count,
            "difficulty_range": list(difficulty_range),
            "question_type": skill.get("question_type") or "задаёт автор в рамках поддерживаемого checker",
            "scoring": {"criterion_id": criterion_id, "rule": "Оценивать только зарегистрированный критерий; отсутствие данных не равно нулю."},
            "answer_requirements": skill.get("answer_requirements") or "Условие и ожидаемый ответ должны иметь проверяемую спецификацию.",
            "existing_candidates": existing,
            "authoring_requirements": ({
                "additional_questions_needed": missing,
                "must_define": ["condition", "stable_skill_id", "criterion_id", "checker", "answer contract", "provenance"],
                "generated_question_is_not_verified": True,
            } if missing else None),
            "after_result": {
                "verified_success": "Предложить другое независимое упражнение; не объявлять освоение по одному ответу.",
                "verified_error": "Предложить закрепление или диагностику; не объявлять устойчивый пробел по одной ошибке.",
                "insufficient_data": "Сохранить неопределённость и запросить подходящие данные.",
            },
            "evidence_refs": _matching_event_refs(bundle, skill_id, criterion_id),
            "model_used": False,
        }

    def course_recommendation(
        self, actor_user_id: int, subject_id: str, expected_course_id: int | None = None,
    ) -> dict[str, Any]:
        self._authorize_subject(actor_user_id, subject_id)
        if expected_course_id is not None and (type(expected_course_id) is not int or expected_course_id < 1):
            raise TutorCoreContractError("invalid_course_context", "Ожидаемый ID курса должен быть положительным целым числом.")
        from app.ai_lab.tutor_core import _platform_profile_cases

        case = next((item for item in _platform_profile_cases(int(actor_user_id))
                     if item.get("profile_id") == subject_id), None)
        if not case:
            return {"contract_version": self.contract_version, "status": "unavailable",
                    "reason": "Для профиля нет доступной синтетической курсовой проекции.",
                    "model_used": False, "course_mutated": False}
        resolution = case.get("curriculum_resolution") or {}
        active_course_id = resolution.get("course_copy_id")
        if expected_course_id is not None and active_course_id != expected_course_id:
            return {"contract_version": self.contract_version, "status": "course_context_mismatch",
                    "active_course_id": active_course_id,
                    "reason": "Переданный курс не совпадает с назначенной Tutor Core индивидуальной копией.",
                    "model_used": False, "course_mutated": False}
        return {
            "contract_version": self.contract_version,
            "status": resolution.get("status") or "unavailable",
            "subject_id": subject_id, "course_id": active_course_id,
            "decision": case.get("proposal"),
            "preview": case.get("adaptation_preview"),
            "evidence_refs": ((case.get("proposal") or {}).get("evidence_refs") or []),
            "model_used": False,
            "course_mutated": False,
        }

    def _events_for_subject(self, actor_user_id: int, subject_id: str) -> list[dict[str, Any]]:
        from app.ai_lab.tutor_core31 import get_tutor_core31_evidence_bundle

        return get_tutor_core31_evidence_bundle(actor_user_id, subject_id=subject_id)["events"]


class TutorCoreClientV1:
    """Thin client handle; all client types call the same TutorCoreV1 instance."""

    def __init__(self, core: TutorCoreV1, client_id: str):
        self._core = core
        self.client_id = client_id

    def profile(self, actor_user_id: int, subject_id: str) -> dict[str, Any]:
        return self._core.learning_profile(actor_user_id, subject_id)

    def record_result(self, actor_user_id: int, subject_id: str, source_record_id: str) -> dict[str, Any]:
        return self._core.record_learning_event(self.client_id, actor_user_id, subject_id, source_record_id)

    def next_practice(self, actor_user_id: int, subject_id: str, goal: dict[str, Any]) -> dict[str, Any]:
        return self._core.next_practice_step(self.client_id, actor_user_id, subject_id, goal)

    def quiz_specification(self, actor_user_id: int, subject_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._core.quiz_specification(self.client_id, actor_user_id, subject_id, **kwargs)

    def explain_decision(self, actor_user_id: int, subject_id: str, goal: dict[str, Any]) -> dict[str, Any]:
        return self._core.explain_decision(self.client_id, actor_user_id, subject_id, goal)

    def course_recommendation(self, actor_user_id: int, subject_id: str,
                              expected_course_id: int | None = None) -> dict[str, Any]:
        return self._core.course_recommendation(actor_user_id, subject_id, expected_course_id)


def stored_tutor_core_client_events(*, actor_user_id: int) -> list[dict[str, Any]]:
    """Read validated client events only for synthetic subjects the actor may access."""
    if type(actor_user_id) is not int or actor_user_id < 1:
        raise TutorCoreContractError("invalid_actor", "Для чтения учебной памяти нужен действующий ID пользователя.")
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.provider import is_local_ai_lab_enabled
    if not is_local_ai_lab_enabled() or not has_verified_safe_ai_lab_db():
        return []
    from core.db_models import AiLabExperiment
    rows = (AiLabExperiment.query.filter_by(scenario_id=CLIENT_EVENT_SCENARIO, status="succeeded")
            .order_by(AiLabExperiment.id.asc()).yield_per(500))
    output = []
    authorized_subjects: set[str] = set()
    denied_subjects: set[str] = set()
    for row in rows:
        raw = (row.result_json or {}).get("event") if isinstance(row.result_json, dict) else None
        if not isinstance(raw, dict):
            continue
        try:
            event = validate_evidence_event(raw)
        except EvidenceContractError:
            continue
        if event["subject_id"] not in authorized_subjects:
            if event["subject_id"] in denied_subjects:
                continue
            try:
                _authorize_synthetic_subject(int(actor_user_id), event["subject_id"])
            except TutorCoreContractError:
                denied_subjects.add(event["subject_id"])
                continue
            authorized_subjects.add(event["subject_id"])
        output.append(event)
    return output


def _authorize_synthetic_subject(actor_user_id: int, subject_id: str) -> None:
    # Reuse the same owner/teacher boundary used by the public service.
    gate = TutorCoreV1()
    gate._authorize_subject(actor_user_id, subject_id)


def _validated_goal(goal: Any, adapter: ClientAdapter) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(goal, dict):
        raise TutorCoreContractError("invalid_goal", "Цель должна содержать точные skill_id и criterion_id.")
    description = goal.get("description")
    skill_id = goal.get("skill_id")
    criterion_id = goal.get("criterion_id")
    if (not isinstance(description, str) or not description.strip() or len(description) > 500
            or not isinstance(skill_id, str) or not skill_id.strip()
            or not isinstance(criterion_id, str) or not criterion_id.strip()):
        raise TutorCoreContractError("invalid_goal", "Укажите цель, точный skill_id и criterion_id.")
    skill = adapter.resolve_skill(skill_id.strip(), criterion_id.strip())
    if not _skill_resolves(skill, skill_id.strip(), criterion_id.strip()):
        raise TutorCoreContractError("unknown_skill_criterion", "Навык или критерий отсутствует либо неоднозначен.", 404)
    return skill_id.strip(), criterion_id.strip(), skill


def _skill_resolves(skill: Any, skill_id: str, criterion_id: str) -> bool:
    return (isinstance(skill, dict) and skill.get("skill_id") == skill_id
            and skill.get("criterion_id") == criterion_id
            and isinstance(skill.get("title"), str) and bool(skill["title"].strip())
            and isinstance(skill.get("criterion_description"), str)
            and bool(skill["criterion_description"].strip()))


def _trusted_candidates(adapter: ClientAdapter, subject_id: str, skill_id: str,
                        criterion_id: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    from app.ai_lab.practice import validate_practice_exercise

    if not adapter.list_candidates:
        return [], {}
    candidates = []
    sources = {}
    seen = set()
    for raw in adapter.list_candidates(subject_id, skill_id, criterion_id) or ():
        if not isinstance(raw, dict):
            continue
        source = raw.get("source")
        if (not isinstance(source, dict) or source.get("status") != "verified"
                or source.get("kind") != "task_bank"
                or not isinstance(source.get("source_id"), str) or not source["source_id"].strip()
                or type(source.get("version")) is not int or source["version"] < 1
                or not isinstance(source.get("checker_id"), str) or not source["checker_id"].strip()
                or not isinstance(source.get("checker_version"), str) or not source["checker_version"].strip()
                or not isinstance(source.get("content_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["content_sha256"])
                or criterion_id not in raw.get("criterion_ids", [])):
            continue
        try:
            exercise = validate_practice_exercise(raw.get("exercise"))
        except (TypeError, ValueError):
            continue
        exercise_id = exercise["exercise_id"]
        if (exercise_id in seen or exercise_id != source["source_id"].strip()
                or skill_id not in exercise["skill_ids"]
                or _difficulty_rank(exercise.get("difficulty")) not in range(1, 6)):
            continue
        seen.add(exercise_id)
        candidates.append(exercise)
        sources[exercise_id] = {
            "source_id": source["source_id"].strip(), "version": source["version"],
            "checker_id": source["checker_id"].strip(),
            "checker_version": source["checker_version"].strip(),
            "content_sha256": source["content_sha256"],
        }
    return candidates, sources


def _practice_attempts(events: list[dict[str, Any]], skill_id: str,
                       criterion_id: str) -> list[dict[str, Any]]:
    attempts = []
    for event in events:
        criteria = event.get("criteria", [])
        criterion = next((item for item in criteria
                          if item.get("criterion_id") == criterion_id and item.get("skill_id") == skill_id), None)
        has_skill = (skill_id in event.get("skill_ids", [])
                     or any(item.get("skill_id") == skill_id for item in criteria))
        if not has_skill:
            continue
        assignment = event.get("assignment")
        attempt_context = event.get("attempt_context") or {}
        exercise_id = attempt_context.get("material_id")
        if not exercise_id:
            exercise_id = assignment.get("id") if isinstance(assignment, dict) else None
        if not isinstance(exercise_id, str) or not exercise_id.strip():
            continue
        verified = bool(
            criterion
            and event.get("evidence_status") in _CONFIRMED
            and criterion.get("evidence_status") in _CONFIRMED
            and criterion.get("status") in {"met", "not_met"}
        )
        assistance = event.get("assistance")
        attempts.append({
            "event_id": event["event_id"], "exercise_id": exercise_id,
            "skill_id": skill_id,
            "criterion_id": criterion_id,
            "verification_status": "verified" if verified else "unverified",
            "is_correct": ((criterion["status"] == "met"
                            and criterion.get("earned") == criterion.get("maximum"))
                           if verified else None),
            "assistance_level": assistance.get("level") if isinstance(assistance, dict) else None,
            "difficulty": attempt_context.get("difficulty"),
            "exposure_count": attempt_context.get("exposure_count"),
        })
    return attempts


def _matching_event_refs(events: list[dict[str, Any]], skill_id: str,
                         criterion_id: str) -> list[str]:
    return _summarize_evidence(events, skill_id, criterion_id)["used_event_ids"]


def _summarize_evidence(events: list[dict[str, Any]], skill_id: str,
                        criterion_id: str) -> dict[str, Any]:
    used: list[str] = []
    excluded: list[dict[str, str]] = []
    unrelated_count = 0
    for event in events:
        criteria = event.get("criteria", [])
        related = (skill_id in event.get("skill_ids", [])
                   or any(item.get("skill_id") == skill_id or item.get("criterion_id") == criterion_id
                          for item in criteria))
        if not related:
            unrelated_count += 1
            continue
        exact = next((item for item in criteria
                      if item.get("skill_id") == skill_id and item.get("criterion_id") == criterion_id), None)
        if (exact and event.get("evidence_status") in _CONFIRMED
                and exact.get("evidence_status") in _CONFIRMED
                and exact.get("status") in {"met", "not_met"}):
            used.append(event["event_id"])
            continue
        if exact:
            reason = ("event_not_confirmed" if event.get("evidence_status") not in _CONFIRMED
                      else "criterion_not_confirmed_or_insufficient_data")
        else:
            reason = "exact_skill_criterion_pair_missing"
        excluded.append({"event_id": event["event_id"], "reason": reason})
    return {"used_event_ids": used, "excluded": excluded, "unrelated_event_count": unrelated_count}


def _material_requirements(skill_id: str, criterion_id: str) -> dict[str, Any]:
    return {
        "skill_id": skill_id,
        "criterion_id": criterion_id,
        "must_be_new_to_learner": True,
        "requires_exact_skill_and_criterion_mapping": True,
        "requires_verified_answer_and_checker": True,
        "requires_stable_version_and_content_hash": True,
    }


def _decision_explanation(action: str, reason: str, evidence: dict[str, Any]) -> dict[str, str]:
    used = len(evidence.get("used_event_ids", []))
    excluded = len(evidence.get("excluded", []))
    teacher = reason
    if used:
        teacher += f" Использованы подтверждённые события: {', '.join(evidence['used_event_ids'])}."
    if excluded:
        teacher += f" Исключены по статусу или точности связи: {excluded}; подробности приведены в evidence.excluded."
    if evidence.get("unrelated_event_count"):
        teacher += f" События по другим целям не учитывались: {evidence['unrelated_event_count']}."
    teacher += " Это следующий ограниченный шаг проверки; он не подтверждает mastery."
    student_text = {
        "diagnostic_start": "Начни с короткого задания по выбранной цели. Один ответ не определяет весь уровень знаний.",
        "reinforce": "Попробуй ещё одно задание по этому приёму и проверь ход решения.",
        "practice_same_level": "Попробуй ещё одно задание того же типа.",
        "transfer_check": "Проверь тот же приём на другом задании.",
        "increase_difficulty": "Проверь знакомый приём на немного более сложном задании.",
        "pause": "Подходящие варианты уже встречались. Нужен новый материал, чтобы продолжить проверку.",
        "request_material": "Подходящего проверенного задания пока нет. Преподаватель может выбрать или подготовить материал.",
        "unavailable": "Подходящего проверенного задания пока нет. Обратись к преподавателю за следующим материалом.",
    }.get(action, "Выполни предложенное задание; результат относится только к указанному критерию.")
    return {"teacher": teacher, "student": student_text}


def _unavailable_practice(skill_id: str, criterion_id: str, reason: str,
                          evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence = evidence or {"used_event_ids": [], "excluded": [], "unrelated_event_count": 0}
    return {"contract_version": TUTOR_CORE_CLIENT_CONTRACT, "status": "unavailable",
            "action": "request_material", "skill_id": skill_id, "criterion_id": criterion_id,
            "reason": reason, "candidate": None, "evidence_refs": evidence["used_event_ids"],
            "evidence": evidence, "next_material_requirements": _material_requirements(skill_id, criterion_id),
            "explanation": _decision_explanation("unavailable", reason, evidence), "model_used": False}


def _difficulty_rank(value: Any) -> int:
    if type(value) is int and 1 <= value <= 5:
        return value
    from app.ai_lab.practice import DIFFICULTY_LEVELS
    return DIFFICULTY_LEVELS.get(str(value or "").strip().lower(), 3)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
