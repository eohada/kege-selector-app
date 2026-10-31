"""Evidence checks for AI-generated Homework feedback and code suggestions.

This module never treats free-form model prose as verified. Concrete full-code
suggestions are checked only by the existing isolated Code Judge runner.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


_PYTHON_CANDIDATE = re.compile(r"```python\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)
_ERROR_LANGUAGE = re.compile(
    r"(?:ошиб\w*|неверн\w*|неправильн\w*|некорректн\w*|"
    r"исправ\w*|замен\w*|рекоменд\w*|должн\w* быть|не соответствует|"
    r"incorrect|wrong|bug|replace|fix)",
    re.IGNORECASE,
)
_UNSUPPORTED_FULL_COVERAGE = re.compile(
    r"(?:все\s+тесты\s+(?:пройд\w*|прош\w*)|ошибок\s+в\s+решении\s+нет|"
    r"корректн\w*\s+для\s+люб\w*\s+вход\w*|works\s+for\s+all\s+inputs)",
    re.IGNORECASE,
)
_RUNNER_REFERENCE = re.compile(r"\b(?:Code\s+Judge|Runner)\b", re.IGNORECASE)
_RUNNER_ASSERTION = re.compile(
    r"\b(?:подтвержд\w*|провер\w*|прош\w*|показ\w*|зафиксир\w*|"
    r"исполн\w*|запуст\w*|выполн\w*|confirm\w*|verif\w*|pass\w*|"
    r"check\w*|report\w*|show\w*|execut\w*|ran)\b",
    re.IGNORECASE,
)
_NEGATED_RUNNER_ASSERTION = re.compile(r"\b(?:не|нет|без|not|never|cannot|can't|didn't|wasn't)\b", re.IGNORECASE)
_EXECUTION_FAILURE_STATUSES = {
    "failed", "wrong_answer", "syntax_error", "runtime_error", "time_limit_exceeded",
    "memory_limit_exceeded", "output_limit_exceeded", "internal_error",
}


def _is_failed_test_status(status: Any) -> bool:
    return str(status or "") in _EXECUTION_FAILURE_STATUSES


def _claims_runner_confirmation(narrative: str) -> bool:
    for reference in _RUNNER_REFERENCE.finditer(narrative):
        sentence = re.split(r"[.!?\n]", narrative[reference.end():], maxsplit=1)[0]
        assertion = _RUNNER_ASSERTION.search(sentence[:160])
        if assertion and not _NEGATED_RUNNER_ASSERTION.search(sentence[:assertion.start()]):
            return True
    return False


def extract_code_candidates(result: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for mistake in result.get("mistakes") or []:
        if not isinstance(mistake, dict):
            continue
        for match in _PYTHON_CANDIDATE.finditer(str(mistake.get("correction_recommendation") or "")):
            code = match.group(1).strip()
            if code and code not in candidates:
                candidates.append(code)
    return candidates


def audit_feedback_claims(result: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    criteria = ((report.get("rubric") or {}).get("criteria") or [])
    by_id = {str(item.get("assignment_criterion_id") or item.get("id")): item
             for item in criteria if item.get("assignment_criterion_id") or item.get("id")}
    failed = [item for item in criteria if item.get("status") == "not_fulfilled"]
    all_confirmed = bool(criteria) and all(item.get("status") == "fulfilled" for item in criteria)
    issues: list[str] = []
    unverified: list[str] = []

    public_refs = {
        str(item.get("id")) for item in report.get("tests", [])
        if isinstance(item, dict) and item.get("visibility") == "public" and item.get("id")
    }
    public_statuses = {
        str(item.get("id")): item.get("status")
        for item in report.get("tests", [])
        if isinstance(item, dict) and item.get("visibility") == "public" and item.get("id")
    }

    for index, mistake in enumerate(result.get("mistakes") or [], 1):
        if not isinstance(mistake, dict):
            issues.append(f"Описание ошибки №{index} имеет неверную структуру.")
            continue
        criterion_id = mistake.get("criterion_id")
        refs = mistake.get("evidence_refs") or []
        if criterion_id:
            criterion = by_id.get(str(criterion_id))
            if criterion is None:
                issues.append(f"Ошибка №{index} ссылается на неизвестный критерий.")
            elif criterion.get("status") == "fulfilled":
                issues.append(
                    f"Ошибка №{index} противоречит статусу критерия «{criterion.get('title') or criterion_id}»."
                )
            elif criterion.get("status") == "insufficient_data":
                unverified.append(f"Ошибка №{index}: недостаточно данных по связанному критерию.")
            elif criterion.get("status") != "not_fulfilled":
                unverified.append(f"Ошибка №{index}: статус связанного критерия не подтверждает утверждение.")
            elif refs and any(str(ref) not in public_refs for ref in refs):
                issues.append(f"Ошибка №{index} содержит неподтверждённую или скрытую ссылку на тест.")
            elif refs and any(not _is_failed_test_status(public_statuses.get(str(ref))) for ref in refs):
                issues.append(f"Ошибка №{index} ссылается на проверку, которая не подтверждает ошибку.")
            elif not refs:
                unverified.append(f"Ошибка №{index}: не приведена ссылка на доступное подтверждение.")
        else:
            unverified.append(f"Ошибка №{index}: не связана со стабильным ID критерия.")

    narrative = " ".join(str(result.get(field) or "") for field in (
        "summary", "student_feedback", "teacher_feedback",
    ))
    code_judge_available = report.get("runner_status") != "not_run"
    if not code_judge_available and _claims_runner_confirmation(narrative):
        issues.append(
            "Комментарий приписывает подтверждение Code Judge/Runner, хотя отдельное исполнение не запускалось."
        )
    if all_confirmed and not failed and _ERROR_LANGUAGE.search(narrative):
        issues.append(
            "Комментарий утверждает ошибку или предлагает исправление, хотя Code Judge подтвердил все критерии."
        )
    if report.get("passed", 0) < report.get("total", 0) and _UNSUPPORTED_FULL_COVERAGE.search(narrative):
        issues.append("Комментарий объявляет полное прохождение тестов при наличии непройденных проверок.")
    if all_confirmed and not failed and result.get("mistakes"):
        issues.append("Список ошибок модели не согласуется с подтверждёнными статусами критериев.")

    return {
        "status": "conflict_detected" if issues else "unverified_claims" if unverified else "draft_unverified",
        "issues": list(dict.fromkeys(issues)),
        "unverified_claims": list(dict.fromkeys(unverified)),
        "failed_criterion_ids": [str(item.get("assignment_criterion_id") or item.get("id")) for item in failed],
        "code_judge_available": code_judge_available,
        "method": "Проверка ссылок и статусов критериев; свободный текст не считается доказательством.",
    }


def build_feedback_evidence_gate(
    result: dict[str, Any],
    report: dict[str, Any],
    recommendation_check: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Classify checkable feedback claims without treating prose as proof."""
    tests = {
        str(item.get("id")): item
        for item in report.get("tests", [])
        if isinstance(item, dict) and item.get("id")
    }
    public_tests = {key: item for key, item in tests.items() if item.get("visibility") == "public"}
    criteria = {
        str(item.get("assignment_criterion_id") or item.get("id")): item
        for item in (report.get("rubric") or {}).get("criteria", [])
        if isinstance(item, dict) and (item.get("assignment_criterion_id") or item.get("id"))
    }
    claims: list[dict[str, Any]] = []

    for index, mistake in enumerate(result.get("mistakes") or [], 1):
        if not isinstance(mistake, dict):
            continue
        criterion_id = str(mistake.get("criterion_id") or "")
        criterion = criteria.get(criterion_id)
        refs = [str(ref) for ref in (mistake.get("evidence_refs") or [])]
        if criterion is not None:
            evidence = criterion.get("evidence") or []
            failed = [item for item in evidence if isinstance(item, dict) and item.get("status") == "failed"]
            public_refs = [
                str(item.get("case_id")) for item in failed
                if item.get("case_id") and str(item.get("case_id")) in public_tests
            ]
            if criterion.get("status") == "not_fulfilled" and failed:
                status = "verified"
                claim = f"Критерий «{criterion.get('title') or criterion_id}» не выполнен на сохранённом наборе Code Judge."
                note = ("Подтверждено публичными проверками." if public_refs
                        else "Подтверждено набором Code Judge; детали скрытых проверок не раскрываются.")
            elif criterion.get("status") == "fulfilled":
                status = "contradicted"
                claim = f"Модель связала ошибку №{index} с критерием «{criterion.get('title') or criterion_id}», который Code Judge подтвердил."
                note = "Технический результат противоречит утверждению об ошибке по этому критерию."
            else:
                status = "unverified"
                claim = f"Основание ошибки №{index} не подтверждено связанными тестами."
                note = "Для критерия недостаточно достоверных результатов исполнения."
            claims.append({
                "claim_type": "criterion_result",
                "status": status,
                "claim": claim,
                "evidence_refs": public_refs,
                "note": note,
            })
        elif refs:
            referenced = [public_tests.get(ref) for ref in refs]
            if all(item is not None for item in referenced) and all(_is_failed_test_status(item.get("status")) for item in referenced):
                status = "verified"
                note = "Runner зафиксировал провал указанных публичных проверок; это не подтверждает все детали объяснения модели."
            elif any(item is not None and item.get("status") == "passed" for item in referenced):
                status = "contradicted"
                note = "Как минимум одна указанная проверка пройдена, поэтому ссылка не подтверждает заявленную ошибку."
            else:
                status = "unverified"
                note = "Нет доступного публичного результата для всех указанных ссылок."
            claims.append({
                "claim_type": "execution_result",
                "status": status,
                "claim": f"Результат публичных проверок, на которые ссылается ошибка №{index}.",
                "evidence_refs": refs if all(ref in public_tests for ref in refs) else [],
                "note": note,
            })
        else:
            claims.append({
                "claim_type": "criterion_result",
                "status": "unverified",
                "claim": f"Ошибка №{index} не привязана к проверяемому критерию или публичному тесту.",
                "evidence_refs": [],
                "note": "Свободное описание модели само по себе не является техническим доказательством.",
            })

        explanation = " ".join(str(mistake.get(field) or "") for field in ("description", "explanation"))
        if explanation.strip():
            claims.append({
                "claim_type": "pedagogical_explanation",
                "status": "unverified",
                "claim": f"Пояснение модели к ошибке №{index}.",
                "evidence_refs": [],
                "note": "Code Judge проверяет исполнение и критерии, но не доказывает точность свободной формулировки причины.",
            })

    recommendations = [
        (index, str(item.get("correction_recommendation") or ""))
        for index, item in enumerate(result.get("mistakes") or [], 1)
        if isinstance(item, dict) and str(item.get("correction_recommendation") or "").strip()
    ]
    if recommendations:
        check_status = recommendation_check.get("status")
        status = {
            "passes_saved_tests": "verified",
            "fails_saved_tests": "contradicted",
        }.get(str(check_status), "unverified")
        if status == "verified":
            note = (
                f"Полный вариант прошёл {recommendation_check.get('passed', 0)} из "
                f"{recommendation_check.get('total', 0)} тестов связанного набора. Это не доказывает корректность для всех входов."
            )
        elif status == "contradicted":
            note = "Полный вариант не прошёл сохранённые проверки; его нельзя показывать как корректное исправление."
        else:
            note = str(recommendation_check.get("message") or "Вариант не проверен и не считается подтверждённым исправлением.")
        claims.append({
            "claim_type": "code_recommendation",
            "status": status,
            "claim": "Предложенный моделью вариант исправления кода.",
            "evidence_refs": [
                str(item.get("id")) for item in recommendation_check.get("test_evidence", [])
                if isinstance(item, dict) and item.get("visibility") == "public" and item.get("id")
            ],
            "counterexample": recommendation_check.get("counterexample") if status == "contradicted" else None,
            "candidate_sha256": recommendation_check.get("candidate_sha256"),
            "note": note,
        })

    narrative = " ".join(str(result.get(field) or "") for field in (
        "summary", "student_feedback", "teacher_feedback",
    ))
    if audit.get("code_judge_available") is False and _claims_runner_confirmation(narrative):
        claims.append({
            "claim_type": "execution_result",
            "status": "contradicted",
            "claim": "Модель приписала Code Judge/Runner подтверждение без отдельного запуска.",
            "evidence_refs": [],
            "note": "Изолированное исполнение не запускалось; это утверждение скрыто до ручной проверки.",
        })

    if any(str(result.get(field) or "").strip() for field in ("summary", "student_feedback", "teacher_feedback")):
        claims.append({
            "claim_type": "pedagogical_narrative",
            "status": "unverified",
            "claim": "Свободное педагогическое объяснение модели.",
            "evidence_refs": [],
            "note": "Технические тесты не проверяют точность педагогической формулировки; она остаётся черновиком для преподавателя.",
        })

    if audit.get("status") == "conflict_detected":
        for issue in audit.get("issues") or []:
            claims.append({
                "claim_type": "evidence_conflict",
                "status": "contradicted",
                "claim": str(issue),
                "evidence_refs": [],
                "note": "Противоречие сохранено для ручного разбора.",
            })

    statuses = [item["status"] for item in claims]
    overall = "contradicted" if "contradicted" in statuses else "unverified" if "unverified" in statuses else "verified"
    return {
        "schema_version": 1,
        "status": overall,
        "claims": claims,
        "limitations": [
            "Прохождение конечного тестового набора не доказывает корректность для всех входов.",
            "Свободные педагогические объяснения не считаются подтверждёнными исполнением Python.",
        ],
    }


def apply_feedback_evidence_gate(
    result: dict[str, Any],
    gate: dict[str, Any],
    recommendation_check: dict[str, Any],
) -> dict[str, Any]:
    """Hide only a contradicted full-code fix and label every unchecked proposal."""
    safe_result = dict(result)
    check_status = str(recommendation_check.get("status") or "not_checked")
    messages = {
        "passes_saved_tests": "Вариант прошёл тесты связанного набора; это ограниченная проверка, не доказательство для всех входов.",
        "fails_saved_tests": "Предложенный вариант опровергнут тестами Code Judge и скрыт. Ручное решение требуется преподавателю.",
        "runner_unavailable": "Runner недоступен; вариант не проверен и не считается подтверждённым исправлением.",
        "incomplete": "Runner не завершил проверку; вариант остаётся непроверенным.",
    }
    updated_mistakes = []
    for raw in result.get("mistakes") or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        recommendation = str(item.get("correction_recommendation") or "")
        has_python_candidate = bool(_PYTHON_CANDIDATE.search(recommendation))
        if recommendation.strip():
            if has_python_candidate and check_status == "fails_saved_tests":
                item["correction_recommendation"] = ""
                item["evidence_gate"] = {"status": "contradicted", "message": messages[check_status]}
            elif has_python_candidate and check_status == "passes_saved_tests":
                item["evidence_gate"] = {"status": "verified", "message": messages[check_status]}
            else:
                item["evidence_gate"] = {
                    "status": "unverified",
                    "message": messages.get(check_status, "Текстовое предложение не проверено Runner и требует ручного подтверждения."),
                }
        updated_mistakes.append(item)
    safe_result["mistakes"] = updated_mistakes
    safe_result["feedback_evidence_gate"] = gate
    return safe_result


def suppress_conflicting_comment(result: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    """Keep the independent score while withholding an untrustworthy model comment."""
    if audit.get("status") != "conflict_detected":
        return result
    safe_result = dict(result)
    issue = "; ".join(audit.get("issues") or [])
    safe_result["summary"] = (
        "Технический балл подтверждён Code Judge; комментарий модели остановлен из-за противоречия."
        if audit.get("code_judge_available", True)
        else "Комментарий модели скрыт из-за неподтверждённого утверждения о запуске; требуется ручная проверка."
    )
    safe_result["student_feedback"] = "Комментарий модели требует проверки преподавателем и пока не показан как рекомендация ученику."
    safe_result["teacher_feedback"] = issue or "Обнаружено противоречие в педагогическом комментарии."
    safe_result["mistakes"] = []
    safe_result["recommended_topics"] = []
    safe_result["needs_human_review"] = True
    safe_result["review_reason"] = issue or "Педагогический комментарий требует решения преподавателя."
    return safe_result


def verify_code_candidate(
    result: dict[str, Any], *, actor_user_id: int, judge_report: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = extract_code_candidates(result)
    if not candidates:
        return {"status": "no_complete_code_candidate", "candidate_count": 0}
    if len(candidates) != 1:
        return {
            "status": "manual_check_multiple_candidates", "candidate_count": len(candidates),
            "message": "Можно автоматически проверить только один полный вариант кода за ответ.",
        }
    candidate = candidates[0]
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    try:
        report = judge_report or {}
        run_id = int(report.get("run_id"))
        from app import db
        from app.ai_lab.code_judge import _normalize_result, validate_test_set
        from app.ai_lab.code_judge_runner_client import run_isolated, runner_diagnostics
        from app.ai_lab.config import code_judge_limits
        from core.db_models import AiLabCodeJudgeRun

        original = db.session.get(AiLabCodeJudgeRun, run_id)
        if (original is None or original.actor_user_id != actor_user_id or original.run_type != "submit"
                or original.test_set_id != report.get("test_set_id")
                or original.test_set_version != report.get("test_set_version")
                or original.status not in {"accepted", "wrong_answer"}):
            return {"status": "unverified_source_run", "candidate_count": 1, "candidate_sha256": candidate_hash}
        snapshot = original.result_json.get("test_set_snapshot") if original.result_json else None
        if not isinstance(snapshot, dict) or not snapshot.get("test_cases"):
            return {"status": "unverified_test_snapshot", "candidate_count": 1, "candidate_sha256": candidate_hash}
        test_set = validate_test_set(snapshot)
        if (test_set.get("assignment_id") != report.get("assignment_id")
                or test_set.get("assignment_version") != report.get("assignment_version")):
            return {"status": "unverified_test_snapshot", "candidate_count": 1, "candidate_sha256": candidate_hash}
        diagnostics = runner_diagnostics()
        if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
            return {"status": "runner_unavailable", "candidate_count": 1,
                    "candidate_sha256": candidate_hash, "message": "Code Judge Runner не подтвердил профиль изоляции."}
        payload = {
            "code": candidate, "mode": test_set["mode"],
            "function_name": test_set["function_name"], "comparator": test_set["comparator"],
            "tolerance": test_set["tolerance"], "test_cases": test_set["test_cases"],
            "limits": code_judge_limits(),
        }
        raw = run_isolated(payload)
        normalized = _normalize_result(raw, len(test_set["test_cases"]))
        if normalized.get("status") != "completed" or not normalized.get("complete"):
            return {"status": "incomplete", "candidate_count": 1, "candidate_sha256": candidate_hash,
                    "message": "Runner не завершил весь сохранённый набор проверок."}
        failed = int(normalized.get("failed") or 0)
        cases_by_id = {str(case.get("id")): case for case in test_set["test_cases"]}
        public_evidence = []
        hidden_failure = False
        for test in normalized.get("tests") or []:
            case = cases_by_id.get(str(test.get("id")), {})
            if case.get("visibility") != "public":
                hidden_failure = hidden_failure or test.get("status") != "passed"
                continue
            evidence = {
                "id": str(test.get("id")),
                "visibility": "public",
                "status": test.get("status"),
            }
            for field in ("expected", "actual"):
                if field in test:
                    evidence[field] = test[field]
            public_evidence.append(evidence)
        counterexample = next((item for item in public_evidence if item["status"] != "passed"), None)
        if counterexample is None and hidden_failure:
            counterexample = {"visibility": "hidden", "details_withheld": True}
        return {
            "status": "passes_saved_tests" if failed == 0 else "fails_saved_tests",
            "candidate_count": 1, "candidate_sha256": candidate_hash,
            "passed": int(normalized.get("passed") or 0), "total": int(normalized.get("total") or 0),
            "test_evidence": public_evidence,
            "counterexample": counterexample,
            "message": ("Вариант прошёл все тесты сохранённого набора. Это не доказывает общую корректность."
                        if failed == 0 else "Вариант не прошёл часть тестов сохранённого набора."),
        }
    except Exception as exc:
        # Never return runner payloads, hidden cases, credentials, or raw exception text.
        from app.ai_lab.code_judge import CodeJudgeError, RunnerUnavailable

        if isinstance(exc, RunnerUnavailable):
            return {"status": "runner_unavailable", "candidate_count": 1,
                    "candidate_sha256": candidate_hash,
                    "message": "Изолированный Runner не подтвердил проверку; исправление не верифицировано."}
        if isinstance(exc, CodeJudgeError):
            return {"status": "not_verified", "candidate_count": 1,
                    "candidate_sha256": candidate_hash,
                    "message": "Сохранённый набор или результат исполнения не прошёл проверку; исправление не верифицировано."}
        return {"status": "not_verified", "candidate_count": 1,
                "candidate_sha256": candidate_hash,
                "message": "Вариант не проверен: Code Judge не смог завершить безопасный запуск."}
