"""Opt-in Code Judge + GigaChat review for explicitly allow-listed local pilot accounts."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from typing import Any

from flask import current_app

from app.ai_lab.code_judge import (
    CodeJudgeError,
    _normalize_result,
    _score_rubric,
    _serialize_test_set,
    validate_test_set,
)
from app.ai_lab.code_judge_runner_client import RunnerUnavailable, run_isolated, runner_diagnostics
from app.ai_lab.config import code_judge_limits, setting
from app.ai_lab.feedback_validation import (
    apply_feedback_evidence_gate,
    audit_feedback_claims,
    build_feedback_evidence_gate,
    extract_code_candidates,
    suppress_conflicting_comment,
)
from app.ai_lab.provider import GigaChatProvider, ProviderError, gigachat_request_queue, is_local_ai_lab_enabled, provider_settings
from app.models import db
from core.db_models import Answer, AiLabCodeJudgeTestSet, Submission, SubmissionAiReview, Tasks, utc_now


PLATFORM_HOMEWORK_PROMPT = """Ты составляешь педагогический комментарий по уже выполненным проверкам Python.
Code Judge — единственный источник оценки и фактов исполнения. Не меняй баллы, не выводи диагнозы навыков и не утверждай поведение вне переданного набора тестов.
Разделяй наблюдаемые результаты и объяснение. Если оснований недостаточно, назови ограничение.
Пиши доброжелательно и конкретно. Не предлагай полный исправленный код без необходимости; если всё же предлагаешь вариант в correction_recommendation, он будет повторно исполнен на том же наборе тестов.
Верни только JSON по схеме."""

PLATFORM_FEEDBACK_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "student_feedback", "teacher_feedback", "mistakes", "limitations"],
    "properties": {
        "summary": {"type": "string"},
        "student_feedback": {"type": "string"},
        "teacher_feedback": {"type": "string"},
        "mistakes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["criterion_id", "description", "why_it_is_error", "correction_recommendation", "evidence_refs"],
            "properties": {
                "criterion_id": {"type": "string"},
                "description": {"type": "string"},
                "why_it_is_error": {"type": "string"},
                "correction_recommendation": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
        }},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


def _value(name: str, default: str = "") -> str:
    configured = current_app.config.get(name)
    if configured is None:
        configured = os.environ.get(name)
    if configured is None:
        configured = setting(name, default)
    return str(configured if configured is not None else default).strip()


def _truthy(value: str) -> bool:
    return value.casefold() in {"1", "true", "yes", "on"}


def _allowlisted_user_ids() -> set[int]:
    """Synthetic learner user IDs that may contribute platform evidence."""
    allowed: set[int] = set()
    for raw in re.split(r"[,;\s]+", _value("AI_LAB_PLATFORM_TEST_USER_IDS")):
        if raw.isdigit():
            allowed.add(int(raw))
    return allowed


def _allowlisted_actor_ids() -> set[int]:
    """Synthetic teacher/admin IDs allowed to configure the local bridge."""
    allowed: set[int] = set()
    for raw in re.split(r"[,;\s]+", _value("AI_LAB_PLATFORM_TEST_ACTOR_IDS")):
        if raw.isdigit():
            allowed.add(int(raw))
    return allowed


def _allowlisted_task_author_ids() -> set[int]:
    """Limit selectable task authors separately from learners and actors."""
    configured = _value("AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS")
    if not configured:
        return _allowlisted_actor_ids()
    allowed: set[int] = set()
    for raw in re.split(r"[,;\s]+", configured):
        if raw.isdigit():
            allowed.add(int(raw))
    return allowed


def platform_homework_enabled(user_id: int | None = None) -> bool:
    """Fail closed unless the local lab and a synthetic actor allow-list are configured."""
    if not is_local_ai_lab_enabled() or not _truthy(_value("AI_LAB_PLATFORM_HOMEWORK_ENABLED", "false")):
        return False
    return user_id is not None and int(user_id) in _allowlisted_actor_ids()


def _task_fingerprint(task: Tasks) -> str:
    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    normalized = {
        "content_html": task.content_html or "",
        "starter_code": task.starter_code or "",
        "max_score": task.max_score,
        "answer_type": spec.get("type"),
        "grading_mode": spec.get("grading_mode"),
    }
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _binding(task: Tasks) -> dict[str, Any] | None:
    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    binding = spec.get("code_judge_binding")
    return binding if isinstance(binding, dict) else None


def list_linkable_tasks(actor_user_id: int) -> list[dict[str, Any]]:
    if not platform_homework_enabled(actor_user_id):
        return []
    allowed_authors = _allowlisted_task_author_ids()
    if not allowed_authors:
        return []
    # Apply the local synthetic-author scope before the result cap. Filtering
    # after a global 500-row window silently hid older allow-listed Python tasks.
    tasks = (Tasks.query.filter(Tasks.answer_spec.isnot(None),
                                Tasks.created_by_id.in_(allowed_authors))
             .order_by(Tasks.task_id.desc()).limit(500).all())
    rows = []
    for task in tasks:
        if task.created_by_id not in allowed_authors:
            continue
        spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
        if spec.get("type") != "code" or spec.get("grading_mode") != "auto":
            continue
        plain_title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", task.content_html or ""))).strip()
        rows.append({
            "task_id": task.task_id,
            "title": (plain_title or f"Задание #{task.task_id}")[:180],
            "max_score": int(task.max_score or 1),
            "is_linked": bool(_binding(task)),
            "course_id": task.course_id,
        })
    return rows


def link_test_set_to_task(actor_user_id: int, task_id: int, test_set_id: int) -> dict[str, Any]:
    if not platform_homework_enabled(actor_user_id):
        raise CodeJudgeError("Связь с реальным заданием разрешена только локальным пилотным аккаунтам.", code="pilot_disabled", status=403)
    task = db.session.get(Tasks, task_id)
    if not task:
        raise CodeJudgeError("Задание BooStudy не найдено.", code="platform_task_not_found", status=404)
    if task.created_by_id not in _allowlisted_task_author_ids():
        raise CodeJudgeError("Для локального пилота можно связать только задание разрешённого автора.", code="platform_task_forbidden", status=403)
    spec = task.answer_spec if isinstance(task.answer_spec, dict) else {}
    if spec.get("type") != "code" or spec.get("grading_mode") != "auto":
        raise CodeJudgeError("Связать можно только Python-задание с включённой штатной автопроверкой.", code="platform_task_not_eligible")
    test_set = db.session.get(AiLabCodeJudgeTestSet, test_set_id)
    if not test_set:
        raise CodeJudgeError("Сохранённый набор Code Judge не найден.", code="test_set_not_found", status=404)
    if not test_set.is_seeded and test_set.created_by_user_id != actor_user_id:
        raise CodeJudgeError("Привязать можно только собственный набор тестов или системный набор.", code="test_set_forbidden", status=403)
    normalized = validate_test_set(_serialize_test_set(test_set))
    rubric = normalized["rubric_json"]
    if not rubric or any(item["policy"] != "all_or_nothing" for item in rubric):
        raise CodeJudgeError("Для платформенной оценки нужны критерии с правилом «всё или ничего».", code="unsupported_rubric")
    rubric_total = sum(float(item["max_score"]) for item in rubric)
    task_max = int(task.max_score or 1)
    if abs(rubric_total - task_max) > 0.001 or any(float(item["max_score"]).is_integer() is False for item in rubric):
        raise CodeJudgeError("Сумма целочисленных критериев Code Judge должна совпадать с максимумом Python-задания.", code="rubric_score_mismatch")
    task.answer_spec = {
        **spec,
        "code_judge_binding": {
            "test_set_id": int(test_set.id),
            "test_set_version": int(test_set.test_set_version),
            "rubric_version": int(test_set.rubric_version),
            "task_fingerprint": _task_fingerprint(task),
            "linked_by_user_id": int(actor_user_id),
            "linked_at": utc_now().isoformat(),
        },
    }
    db.session.commit()
    return {"task_id": int(task.task_id), "test_set_id": int(test_set.id),
            "test_set_version": int(test_set.test_set_version), "rubric_version": int(test_set.rubric_version)}


def _run_code(code: str, test_set: AiLabCodeJudgeTestSet) -> dict[str, Any]:
    if not isinstance(code, str) or not code.strip():
        raise CodeJudgeError("В ответе нет Python-кода.", code="empty_code")
    if len(code.encode("utf-8")) > int(code_judge_limits()["max_source_bytes"]):
        raise CodeJudgeError("Исходный код превышает настроенный лимит Code Judge.", code="source_too_large")
    normalized = validate_test_set(_serialize_test_set(test_set))
    diagnostics = runner_diagnostics()
    if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
        raise RunnerUnavailable(diagnostics.get("message") or "Изолированный Runner не подтвердил безопасный профиль.")
    started_cases = normalized["test_cases"]
    raw = run_isolated({
        "code": code,
        "mode": normalized["mode"],
        "function_name": normalized["function_name"],
        "comparator": normalized["comparator"],
        "tolerance": normalized["tolerance"],
        "test_cases": started_cases,
        "limits": code_judge_limits(),
    })
    result = _normalize_result(raw, len(started_cases))
    result["rubric"] = _score_rubric(normalized["rubric_json"], started_cases, result["tests"])
    result["test_set_snapshot"] = {
        "id": int(test_set.id), "test_set_version": int(test_set.test_set_version),
        "rubric_version": int(test_set.rubric_version), "mode": normalized["mode"],
    }
    return result


def _visible_evidence(result: dict[str, Any], test_set: AiLabCodeJudgeTestSet, task: Tasks, assignment_task_id: int) -> dict[str, Any]:
    tests_by_id = {str(item.get("id")): item for item in result.get("tests") or [] if isinstance(item, dict)}
    normalized = validate_test_set(_serialize_test_set(test_set))
    test_by_id = {str(item["id"]): item for item in normalized["test_cases"]}
    visible_tests = []
    for index, case in enumerate(normalized["test_cases"], 1):
        test = tests_by_id.get(str(case["id"]), {})
        public = case.get("visibility") != "hidden"
        visible_tests.append({
            "id": str(case["id"]) if public else f"hidden-{index}",
            "name": str(case.get("name") or f"Проверка {index}") if public else f"Скрытая проверка {index}",
            "visibility": "public" if public else "hidden",
            "status": str(test.get("status") or "unconfirmed"),
            **({"actual": test.get("actual")} if public and "actual" in test else {}),
        })
    rubric = result.get("rubric") or {}
    case_visibility = {str(case["id"]): case.get("visibility") for case in normalized["test_cases"]}
    public_rubric = []
    for criterion in rubric.get("criteria") or []:
        item = {key: value for key, value in criterion.items() if key != "evidence"}
        item["evidence"] = []
        for evidence in criterion.get("evidence") or []:
            public = case_visibility.get(str(evidence.get("case_id"))) != "hidden"
            entry = {key: value for key, value in evidence.items() if key not in {"expected", "actual", "case_id"}}
            entry["test_ref"] = str(evidence.get("case_id")) if public else "hidden"
            item["evidence"].append(entry)
        public_rubric.append(item)
    total = int(task.max_score or 1)
    score = rubric.get("confirmed_score") if all(item.get("status") != "insufficient_data" for item in public_rubric) else None
    return {
        "report_type": "platform_code_judge_evidence_v1",
        "submission_id": None,
        "assignment_task_id": int(assignment_task_id),
        "task_id": int(task.task_id),
        "test_set_id": int(test_set.id),
        "test_set_version": int(test_set.test_set_version),
        "rubric_version": int(test_set.rubric_version),
        "limited_test_set": True,
        "run_status": "complete" if result.get("complete") else "incomplete",
        "passed": int(result.get("passed") or 0),
        "failed": int(result.get("failed") or 0),
        "total": int(result.get("total") or 0),
        "tests": visible_tests,
        "rubric": {"criteria": public_rubric, "confirmed_score": score, "confirmed_max_score": rubric.get("confirmed_max_score"),
                   "unconfirmed_max_score": rubric.get("unconfirmed_max_score"), "max_score": total},
    }


def grade_bound_answer(answer: Any, assignment_task: Any, actor_user_id: int) -> tuple[bool | None, int | None]:
    """Grade a submitted bound Python task; preserve uncertainty for human review."""
    task = assignment_task.task
    binding = _binding(task)
    if not binding or not platform_homework_enabled(actor_user_id):
        return None, None
    report: dict[str, Any] = {"status": "unavailable"}
    try:
        if _task_fingerprint(task) != binding.get("task_fingerprint"):
            raise CodeJudgeError("Условие или стартовый код изменились после привязки набора. Нужна повторная настройка.", code="stale_task_binding")
        test_set = db.session.get(AiLabCodeJudgeTestSet, int(binding.get("test_set_id") or 0))
        if (not test_set or test_set.test_set_version != int(binding.get("test_set_version") or 0)
                or test_set.rubric_version != int(binding.get("rubric_version") or 0)):
            raise CodeJudgeError("Связанная версия тестов Code Judge больше не доступна.", code="stale_test_set")
        normalized = validate_test_set(_serialize_test_set(test_set))
        if abs(sum(float(item["max_score"]) for item in normalized["rubric_json"]) - float(assignment_task.max_score or 1)) > 0.001:
            raise CodeJudgeError("Максимум баллов назначения не совпадает с версией рубрики Code Judge.", code="rubric_score_mismatch")
        raw = _run_code((getattr(answer, "student_code", None) or answer.value or "").strip(), test_set)
        report = _visible_evidence(raw, test_set, task, assignment_task.assignment_task_id)
        report["runner_version"] = str(raw.get("runner_version") or "unknown")
        report["duration_ms"] = int(raw.get("duration_ms") or 0)
        if not raw.get("complete") or report["rubric"].get("unconfirmed_max_score"):
            report["status"] = "insufficient_data"
            answer._platform_code_judge_report = report
            return None, None
        score = int(round(float(report["rubric"].get("confirmed_score") or 0)))
        maximum = int(round(float(assignment_task.max_score or 1)))
        report["status"] = "completed"
        report["score_awarded"] = score
        answer._platform_code_judge_report = report
        return score == maximum, score
    except Exception as exc:
        report.update({
            "status": "sandbox_unavailable" if isinstance(exc, RunnerUnavailable) else "configuration_error",
            "error_code": getattr(exc, "code", "runner_unavailable" if isinstance(exc, RunnerUnavailable) else "code_judge_error"),
            "error_message": str(exc)[:1000],
            "task_id": int(task.task_id),
            "assignment_task_id": int(assignment_task.assignment_task_id),
        })
        answer._platform_code_judge_report = report
        return None, None


def _student_safe_report(report: dict[str, Any]) -> dict[str, Any]:
    allowed = {"task_id", "assignment_task_id", "test_set_version", "rubric_version", "limited_test_set",
               "run_status", "passed", "failed", "total", "rubric", "status", "score_awarded", "error_code", "error_message"}
    safe = {key: value for key, value in report.items() if key in allowed}
    criteria = []
    for item in (safe.get("rubric") or {}).get("criteria", []):
        criteria.append({key: item.get(key) for key in ("id", "title", "description", "max_score", "status", "score_awarded", "rationale")})
    if safe.get("rubric"):
        safe["rubric"] = {**safe["rubric"], "criteria": criteria}
    return safe


def student_review_payload(review: SubmissionAiReview | None) -> dict[str, Any] | None:
    if not review:
        return None
    tasks = []
    for item in review.task_reviews or []:
        if not isinstance(item, dict):
            continue
        tasks.append({
            "task_id": item.get("task_id"),
            "assignment_task_id": item.get("assignment_task_id"),
            "student_feedback": item.get("student_feedback") or "",
            "technical": _student_safe_report(item.get("technical") or {}),
        })
    return {"status": review.status,
            "summary": "Оценка определена проверками Code Judge. Комментарий GigaChat — предварительный и не меняет баллы.",
            "tasks": tasks, "error_message": review.error_message or "",
            "teacher_review_required": bool(review.teacher_review_required)}


def _feedback_for_submission(reports: list[dict[str, Any]], codes: dict[int, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = provider_settings()
    model = str(settings.get("default_model") or "").strip()
    provider = GigaChatProvider(settings)
    input_payload = {
        "tasks": [{
            "task_id": item["task_id"], "condition": item.get("condition", ""),
            "student_code": codes.get(int(item["assignment_task_id"]), ""),
            "evidence": item["technical"],
        } for item in reports],
        "constraints": ["Баллы и статусы критериев неизменяемы.", "Не раскрывай тестовые входы и ожидаемые значения скрытых проверок.",
                        "Проверенный набор ограничен и не доказывает корректность для всех входов.",
                        "Свободные педагогические суждения не объявляй технически подтверждёнными."],
    }
    if not model:
        raise ProviderError("not_configured", "Модель GigaChat не настроена для локальной AI Lab.")
    with gigachat_request_queue.request("Предварительный комментарий по реальной синтетической работе"):
        completion = provider.complete_structured(model, PLATFORM_HOMEWORK_PROMPT, input_payload, PLATFORM_FEEDBACK_SCHEMA)
    try:
        result = json.loads(completion.content)
    except (TypeError, ValueError) as exc:
        raise ProviderError("invalid_provider_response", "GigaChat вернул некорректный структурированный комментарий.") from exc
    if not isinstance(result, dict) or any(not isinstance(result.get(key), str) for key in ("summary", "student_feedback", "teacher_feedback")):
        raise ProviderError("invalid_provider_response", "Структура педагогического комментария не прошла проверку.")
    gate_claims = []
    audits = []
    candidate_check = {"status": "no_complete_code_candidate", "candidate_count": 0}
    candidates = extract_code_candidates(result)
    if candidates:
        if len(candidates) != 1:
            candidate_check = {"status": "manual_check_multiple_candidates", "candidate_count": len(candidates)}
        else:
            candidate_report = reports[0]["technical"]
            candidate_set = db.session.get(AiLabCodeJudgeTestSet, int(candidate_report.get("test_set_id") or 0))
            if candidate_set:
                try:
                    candidate_result = _run_code(candidates[0], candidate_set)
                    if not candidate_result.get("complete"):
                        candidate_check = {"status": "incomplete", "candidate_count": 1}
                    elif candidate_result.get("failed"):
                        candidate_check = {"status": "fails_saved_tests", "candidate_count": 1}
                    else:
                        candidate_check = {"status": "passes_saved_tests", "candidate_count": 1}
                except RunnerUnavailable:
                    candidate_check = {"status": "runner_unavailable", "candidate_count": 1}
                except Exception:
                    current_app.logger.exception("Code recommendation verification failed")
                    candidate_check = {"status": "incomplete", "candidate_count": 1}
    normalized_reports = [item["technical"] for item in reports]
    for report in normalized_reports:
        synthetic_report = {
            **report,
            "rubric": report.get("rubric") or {},
            "tests": report.get("tests") or [],
        }
        audit = audit_feedback_claims(result, synthetic_report)
        audits.append(audit)
        gate_claims.extend((audit.get("claims") or []))
    aggregate_audit = {
        "status": "conflict_detected" if any(item.get("status") == "conflict_detected" for item in audits) else "audited",
        "issues": [issue for item in audits for issue in (item.get("issues") or [])],
        "unverified_claims": [claim for item in audits for claim in (item.get("unverified_claims") or [])],
        "claims": gate_claims,
    }
    for report in normalized_reports:
        if report.get("tests") and report.get("rubric"):
            gate = build_feedback_evidence_gate(result, report, candidate_check, aggregate_audit)
            result = apply_feedback_evidence_gate(result, gate, candidate_check)
    if aggregate_audit["status"] == "conflict_detected":
        result = suppress_conflicting_comment(result, aggregate_audit)
    usage = {
        "model": completion.model or model,
        "payload_id": completion.payload_id,
        "payload_sha256": completion.payload_sha256,
        "generation_parameters": completion.generation_parameters,
        "usage": {"prompt_tokens": completion.prompt_tokens, "precached_prompt_tokens": completion.precached_prompt_tokens,
                  "completion_tokens": completion.output_tokens, "total_tokens": completion.total_tokens,
                  "full_input_tokens": completion.input_tokens},
        "pedagogical_validation": aggregate_audit,
        "code_candidate_status": candidate_check["status"],
    }
    return result, usage


def save_platform_submission_review(
    submission_id: int,
    reports: list[tuple[Any, dict[str, Any]]],
    *,
    generate_gigachat_feedback: bool = True,
) -> SubmissionAiReview | None:
    """Persist Code Judge evidence; optionally request a separate GigaChat draft."""
    submission = db.session.get(Submission, submission_id)
    if not submission or not reports:
        return None
    from app.assignments.ai_review_service import compute_submission_hash

    sub_hash = compute_submission_hash(submission)
    existing = SubmissionAiReview.query.filter_by(submission_id=submission_id, submission_hash=sub_hash).order_by(SubmissionAiReview.revision_no.desc()).first()
    if existing and existing.status in {"completed", "unavailable", "accepted"}:
        return existing
    latest = SubmissionAiReview.query.filter_by(submission_id=submission_id).order_by(SubmissionAiReview.revision_no.desc()).first()
    attempt_no = max(1, len(submission.attempts or []))
    task_rows = []
    code_by_task: dict[int, str] = {}
    for answer, report in reports:
        answer_id = int(answer.answer_id)
        persisted_answer = db.session.get(Answer, answer_id)
        if not persisted_answer:
            raise CodeJudgeError("Ответ ученика исчез из локальной синтетической базы до сохранения AI Review.", code="answer_not_found")
        assignment_task = persisted_answer.assignment_task
        task_rows.append({
            "task_id": int(assignment_task.task.task_id),
            "assignment_task_id": int(assignment_task.assignment_task_id),
            "condition": str(assignment_task.task.content_html or "")[:6000],
            "technical": report,
            "student_feedback": "",
        })
        code_by_task[int(assignment_task.assignment_task_id)] = (persisted_answer.student_code or persisted_answer.value or "")[:24_000]
    review = existing or SubmissionAiReview(
        submission_id=submission_id,
        attempt_no=attempt_no,
        revision_no=(latest.revision_no + 1) if latest else 1,
        submission_hash=sub_hash,
        status="processing",
        provider="gigachat",
        teacher_review_required=True,
        suggested_total_points=float(sum(int((item[1] or {}).get("score_awarded") or 0) for item in reports)),
        task_reviews=task_rows,
    )
    if not existing:
        db.session.add(review)
    db.session.commit()
    if any(item[1].get("status") != "completed" for item in reports):
        review.status = "unavailable"
        review.provider = "code_judge"
        review.model = None
        review.error_code = "CODE_JUDGE_INCOMPLETE"
        review.error_message = "Code Judge не завершил все связанные проверки. Итог требует ручной проверки преподавателем."
        review.summary_for_teacher = review.error_message
        db.session.commit()
        return review
    if not generate_gigachat_feedback:
        review.status = "completed"
        review.provider = "code_judge"
        review.model = None
        review.summary_for_teacher = "Результат подтверждён Code Judge; комментарий GigaChat не запрашивался."
        review.skill_signals = []
        review.task_reviews = task_rows
        review.raw_response = None
        review.error_code = None
        review.error_message = None
        db.session.commit()
        return review
    try:
        feedback, usage = _feedback_for_submission(task_rows, code_by_task)
        for item in task_rows:
            item["student_feedback"] = feedback.get("student_feedback", "")
            item["teacher_feedback"] = feedback.get("teacher_feedback", "")
            item["mistakes"] = feedback.get("mistakes") or []
            item["limitations"] = feedback.get("limitations") or []
        review.status = "completed"
        review.provider = "gigachat"
        review.model = usage["model"]
        review.summary_for_teacher = feedback.get("teacher_feedback") or feedback.get("summary")
        review.skill_signals = []
        review.task_reviews = task_rows
        review.raw_response = None
        review.error_code = None
        review.error_message = None
        review.confidence = None
        review.teacher_review_required = True
        review.task_reviews = [{**item, "technical": _student_safe_report(item["technical"])} for item in task_rows]
        review.task_reviews = [{**item, "technical": report} for item, (_, report) in zip(review.task_reviews, reports)]
        review.task_reviews = [{**item, "usage": usage, "technical": _student_safe_report(item["technical"])} for item in review.task_reviews]
    except ProviderError as exc:
        review.status = "unavailable"
        review.error_code = exc.code
        review.error_message = str(exc)[:1000]
        review.summary_for_teacher = "Техническая оценка Code Judge сохранена; комментарий GigaChat недоступен."
        review.task_reviews = task_rows
    except Exception:
        current_app.logger.exception("Platform AI Homework feedback failed for submission %s", submission_id)
        review.status = "unavailable"
        review.error_code = "FEEDBACK_FAILED"
        review.error_message = "Не удалось сохранить педагогический комментарий. Технический результат Code Judge сохранён."
        review.summary_for_teacher = review.error_message
        review.task_reviews = task_rows
    db.session.commit()
    return review


def serialize_teacher_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep hidden test values private even in teacher-facing AI review JSON."""
    safe = dict(report)
    safe.pop("tests", None)
    return safe

