from copy import deepcopy

import pytest

from app.ai_lab.analytics import _demo_event
from app.ai_lab.learning_evidence import (
    EVIDENCE_CONTRACT_VERSION,
    LEGACY_EVIDENCE_CONTRACT_VERSION,
    EvidenceContractError,
    merge_evidence_events,
    validate_evidence_event,
)
from app.ai_lab import tutor_core31
from app.ai_lab.tutor_core31 import compare_learning_history, evaluate_learning_history


SUBJECT = "platform-student:9101"


def event(skill_id="logic.constraint-model", *, event_id="event-1", task_id=1,
          result="met", assistance="independent", minute=0):
    score = 1 if result == "met" else 0
    row = _demo_event(
        SUBJECT,
        event_id,
        "Synthetic subject area",
        skill_id,
        score,
        1,
        f"assignment-{task_id}",
        None if result == "met" else "synthetic.error",
        "Synthetic criterion evidence",
    )
    row["occurred_at"] = f"2026-10-20T12:{minute:02d}:00+07:00"
    row["platform_refs"] = {
        "submission_id": minute + 1,
        "attempt_id": 1,
        "assignment_id": task_id + 100,
        "assignment_task_id": task_id + 200,
        "task_id": task_id,
        "student_id": 9101,
        "review_id": minute + 300,
        "code_judge_test_set_id": 13,
        "code_judge_test_set_version": 1,
        "rubric_version": 1,
    }
    if assistance:
        row["assistance"] = {"level": assistance, "source_refs": [f"help-log:{event_id}"]}
    else:
        row["assistance"] = None
    return row


def test_legacy_events_remain_readable_and_do_not_become_independent():
    row = event()
    row["contract_version"] = LEGACY_EVIDENCE_CONTRACT_VERSION
    row.pop("assistance")

    normalized = validate_evidence_event(row)
    state = evaluate_learning_history([normalized], SUBJECT)

    assert normalized["contract_version"] == EVIDENCE_CONTRACT_VERSION
    assert normalized["assistance"] is None
    assert state["skills"][0]["state"] == "success_help_unrecorded"


def test_event_summary_exposes_historical_fixture_course_binding():
    from app.ai_lab.tutor_core31 import _event_summary

    row = event()
    row["source_module"] = "ai_homework"
    row["provenance"]["synthetic_fixture_binding"] = {
        "fixture_key": "historical-course-case",
        "course_id": 9311003,
        "course_version": 1,
    }

    summary = _event_summary(row)

    assert summary["fixture_key"] == "historical-course-case"
    assert summary["fixture_course_id"] == 9311003
    assert summary["fixture_course_version"] == 1


def test_event_summary_keeps_excluded_attempt_restorable_in_profile_ui():
    from app.ai_lab.tutor_core31 import _event_summary

    row = event(event_id="platform-submission:1:attempt:1:task:3")
    row["source_module"] = "ai_homework"
    review = {
        "status": "excluded",
        "reason": "synthetic_acceptance_only",
        "actor_user_id": 1,
        "reviewed_at": "2026-10-25T10:00:00+03:00",
        "label": "Исключено из педагогических выводов.",
    }
    summary = _event_summary(row, {
        "attempt_admissibility": review,
        "attempt_review_supported": True,
    })

    assert summary["attempt_review_supported"] is True
    assert summary["attempt_admissibility"] == review
    assert summary["score"] == 1
    assert summary["maximum"] == 1


def test_profile_event_effects_keep_full_context_but_only_recompute_visible_tail():
    rows = [
        validate_evidence_event(event(
            skill_id="logic.constraint-model",
            event_id=f"history-{index}",
            task_id=index + 1,
            minute=index,
            result="met" if index % 2 == 0 else "not_met",
        ))
        for index in range(12)
    ]

    full_effects = tutor_core31._event_effects(rows, SUBJECT)
    visible_tail = tutor_core31._event_effects(rows[-8:], SUBJECT, preceding_events=rows[:-8])

    assert visible_tail == full_effects[-8:]


def test_assistance_level_is_validated():
    row = event()
    row["assistance"] = {"level": "probably_independent", "source_refs": []}
    with pytest.raises(EvidenceContractError, match="характер помощи"):
        validate_evidence_event(row)


def test_evaluation_provenance_preserves_current_revision_and_rejects_superseded_claims():
    row = event()
    row["provenance"]["evaluation_revision"] = {
        "id": 91, "revision_no": 2, "method": "teacher_manual",
        "actor_user_id": 4, "state": "current",
    }

    normalized = validate_evidence_event(row)
    assert normalized["provenance"]["evaluation_revision"]["revision_no"] == 2
    assert normalized["provenance"]["evaluation_revision"]["actor_user_id"] == 4

    row["provenance"]["evaluation_revision"]["state"] = "superseded"
    with pytest.raises(EvidenceContractError, match="Происхождение оценки"):
        validate_evidence_event(row)


def test_duplicate_evidence_is_collapsed_and_conflicting_reuse_fails_closed():
    row = event()
    assert merge_evidence_events([[row, deepcopy(row)]], allowed_subject_ids={SUBJECT})["duplicate_count"] == 1
    conflicting = deepcopy(row)
    conflicting["criteria"][0]["reason"] = "different source claim"
    with pytest.raises(EvidenceContractError, match="противоречащими данными"):
        merge_evidence_events([[row, conflicting]], allowed_subject_ids={SUBJECT})


def test_success_after_help_is_not_relabelled_as_independent():
    state = evaluate_learning_history([event(assistance="substantive_hint")], SUBJECT)["skills"][0]

    assert state["state"] == "success_after_help"
    assert state["independent_success_count"] == 0
    assert compare_learning_history([event(assistance="substantive_hint")], SUBJECT)["decision"]["action"] == "independent_transfer_check"


def test_missing_help_metadata_stays_unknown():
    state = evaluate_learning_history([event(assistance=None)], SUBJECT)["skills"][0]

    assert state["state"] == "success_help_unrecorded"
    assert state["distinct_independent_tasks"] == 0


def test_two_distinct_independent_successes_keep_plan_and_preserve_history():
    rows = [
        event(event_id="first-error", task_id=1, result="not_met", assistance=None, minute=1),
        event(event_id="success-2", task_id=2, assistance="independent", minute=2),
        event(event_id="success-3", task_id=3, assistance="independent", minute=3),
    ]
    result = compare_learning_history(rows, SUBJECT)
    state = result["after"]["skills"][0]

    assert state["state"] == "repeated_independent_success"
    assert state["error_count"] == 1
    assert state["distinct_independent_tasks"] == 2
    assert result["decision"]["action"] == "keep_plan"
    assert result["changes"][0]["changed"] is True


def test_one_new_error_does_not_erase_a_prior_success():
    rows = [
        event(event_id="success", task_id=1, assistance="independent", minute=1),
        event(event_id="later-error", task_id=2, result="not_met", assistance=None, minute=2),
    ]
    result = compare_learning_history(rows, SUBJECT)

    assert result["after"]["skills"][0]["state"] == "contradictory_recent_error"
    assert result["after"]["skills"][0]["success_count"] == 1
    assert result["decision"]["action"] == "teacher_review_and_diagnostic"
    assert "success" in result["decision"]["evidence_refs"]


def test_insufficient_event_does_not_force_a_topic_review():
    row = event(assistance=None)
    row["evidence_status"] = "insufficient_data"
    row["outcome"] = {"score": None, "maximum": 1, "status": "insufficient_data"}
    row["criteria"][0].update({"earned": None, "status": "insufficient_data", "evidence_status": "insufficient_data"})
    result = compare_learning_history([row], SUBJECT)

    assert result["after"]["skills"] == []
    assert result["decision"]["action"] == "keep_plan_insufficient_evidence"


@pytest.mark.parametrize("skill_id", [
    "logic.constraint-model",
    "information.encoding",
    "number-systems.convert",
    "spreadsheet.aggregate-range",
    "relational-data.grouping-key",
    "algorithm.sequence-trace",
    "programming.function-contract",
    "graph.directed-paths",
])
def test_reasoning_rules_do_not_depend_on_a_subject_or_exam_number(skill_id):
    result = evaluate_learning_history([event(skill_id=skill_id)], SUBJECT)

    assert result["skills"][0]["skill_id"] == skill_id
    assert result["skills"][0]["state"] == "single_independent_success"


def _synthetic_fixture_event():
    skill_key = "skill.inf.relational-query"
    row = event(skill_id=skill_key, event_id="fixture-event", task_id=7)
    row["event_id"] = "platform-submission:101:attempt:1:task:7"
    row["skill_ids"] = [skill_key]
    row["course_context"] = {"course_id": "synthetic-tc31-test", "course_version": 1}
    row["provenance"]["synthetic_fixture_binding"] = {
        "fixture_run_key": "tc31_test",
        "fixture_key": "sql-relational-query",
        "knowledge_stable_key": "ege.inf.sql-relational-query.v1",
        "knowledge_version": 2,
        "knowledge_title": "SQL relational query",
        "knowledge_status": "source_checked",
        "knowledge_source_titles": ["Official synthetic fixture source"],
        "knowledge_content_sha256": "a" * 64,
        "task_id": 7,
        "task_content_sha256": "b" * 64,
        "source_key": "boostudy.synthetic.tutorcore31.v1/tc31_test/sql-relational-query",
        "course_id": 9331,
        "course_version": 1,
        "lesson_id": 9332,
        "skill_key": skill_key,
    }
    row["platform_refs"] = {
        "submission_id": 101,
        "attempt_id": 102,
        "assignment_id": 103,
        "assignment_task_id": 104,
        "task_id": 7,
        "student_id": 105,
        "review_id": None,
        "code_judge_test_set_id": None,
        "code_judge_test_set_version": None,
        "rubric_version": None,
        "course_id": 9331,
        "lesson_id": 9332,
    }
    return row


def test_historical_fixture_selection_returns_ambiguity_instead_of_last_event():
    from app.ai_lab.tutor_core31 import _select_historical_fixture_context

    first = _synthetic_fixture_event()
    second = _synthetic_fixture_event()
    second["event_id"] = "platform-submission:103:attempt:1:task:7"
    second_binding = second["provenance"]["synthetic_fixture_binding"]
    second_binding["fixture_run_key"] = "tc31_test_second"
    second_binding["source_key"] = "boostudy.synthetic.tutorcore31.v1/tc31_test_second/sql-relational-query"
    second_binding["course_id"] += 1
    second_binding["lesson_id"] += 1

    result = _select_historical_fixture_context([first, second])

    assert result["status"] == "ambiguous"
    assert result["fixture"] is None
    assert len(result["candidate_contexts"]) == 2


def test_historical_fixture_selection_deduplicates_events_from_same_lesson():
    from app.ai_lab.tutor_core31 import _select_historical_fixture_context

    first = _synthetic_fixture_event()
    second = _synthetic_fixture_event()
    second["event_id"] = "platform-submission:103:attempt:1:task:8"
    second_binding = second["provenance"]["synthetic_fixture_binding"]
    second_binding["task_id"] = 8
    second["event_id"] = second["event_id"].rsplit(":", 1)[0] + ":8"

    result = _select_historical_fixture_context([first, second])

    assert result["status"] == "resolved"
    assert result["fixture"]["fixture_run_key"] == "tc31_test"


def test_synthetic_fixture_binding_is_versioned_and_platform_refs_need_no_code_judge():
    normalized = validate_evidence_event(_synthetic_fixture_event())

    assert normalized["provenance"]["synthetic_fixture_binding"]["knowledge_version"] == 2
    assert normalized["platform_refs"]["review_id"] is None
    assert normalized["platform_refs"]["code_judge_test_set_id"] is None
    assert normalized["platform_refs"]["lesson_id"] == 9332


def test_synthetic_assistance_is_labelled_as_fixture_not_platform_help():
    from app.ai_lab.tutor_core31 import _event_summary

    normalized = validate_evidence_event(_synthetic_fixture_event())
    summary = _event_summary(normalized)
    state = evaluate_learning_history([normalized], SUBJECT)["skills"][0]

    assert summary["assistance_source_kind"] == "synthetic_fixture_label"
    assert "не проверялась" in summary["assistance_source_label"]
    assert "по метке сценария" in state["state_label"]


def test_synthetic_fixture_binding_rejects_a_mismatched_run_namespace():
    row = _synthetic_fixture_event()
    row["provenance"]["synthetic_fixture_binding"]["source_key"] = (
        "boostudy.synthetic.tutorcore31.v1/other-run/sql-relational-query"
    )

    with pytest.raises(EvidenceContractError, match="недопустимые значения"):
        validate_evidence_event(row)


def test_course_task_binding_preserves_semantic_compatibility_and_checker_provenance():
    row = event(skill_id="exam-skill:1")
    row["skill_ids"] = []
    row["criteria"][0]["criterion_id"] = "graph_optimal_paths"
    row["criteria"][0].update({
        "skill_id": None, "earned": None, "status": "insufficient_data",
        "evidence_status": "insufficient_data",
    })
    row["provenance"]["synthetic_course_task_binding"] = {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "course_id": 3,
        "course_version": 9,
        "lesson_id": 7,
        "task_id": 1,
        "skill_id": "exam-skill:1",
        "topic_code": "ege.inf.graph.optimal-paths",
        "criterion_id": "graph_optimal_paths",
        "semantic_compatibility": {
            "status": "unverified",
            "matches": [],
            "mismatches": ["teacher_selected_shared_review"],
            "reason": "Преподаватель выбрал материал для повторного разбора без подтверждения его независимости.",
        },
        "assessment_method": "exact_answer",
        "task_fingerprint": "a" * 64,
        "task_content_sha256": "b" * 64,
        "checker_fingerprint": "c" * 64,
        "pedagogical_status": "not_pedagogically_approved",
        "source_course_id": 2,
        "source_course_version": 4,
        "source_lesson_id": 22,
        "student_id": 9101,
        "purpose": "shared_review",
        "selected_at": "2026-10-20T12:00:00+00:00",
    }
    row["platform_refs"].update({"course_id": 3, "lesson_id": 7})

    normalized = validate_evidence_event(row)

    assert normalized["provenance"]["synthetic_course_task_binding"] == row["provenance"]["synthetic_course_task_binding"]

    invalid = dict(row)
    invalid["skill_ids"] = ["exam-skill:1"]
    invalid["criteria"] = [{
        **row["criteria"][0], "skill_id": "exam-skill:1", "earned": 1,
        "status": "met", "evidence_status": "technical_confirmed",
    }]
    with pytest.raises(EvidenceContractError, match="не должен подтверждать учебный критерий"):
        validate_evidence_event(invalid)

    mismatched_student = deepcopy(row)
    mismatched_student["platform_refs"]["student_id"] = 9102
    with pytest.raises(EvidenceContractError, match="не совпадает с атрибуцией ученика"):
        validate_evidence_event(mismatched_student)

    missing_platform_refs = deepcopy(row)
    missing_platform_refs.pop("platform_refs")
    with pytest.raises(EvidenceContractError, match="обязательны ссылки на отправленную работу"):
        validate_evidence_event(missing_platform_refs)


def test_course_task_binding_rejects_malformed_semantic_compatibility():
    row = event(skill_id="exam-skill:1")
    row["provenance"]["synthetic_course_task_binding"] = {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "course_id": 9313004,
        "course_version": 3,
        "lesson_id": 9313006,
        "task_id": 9313010,
        "skill_id": "exam-skill:1",
        "topic_code": "ege.inf.graph.optimal-paths",
        "criterion_id": "graph_optimal_paths",
        "semantic_compatibility": {
            "status": "verified",
            "matches": [],
            "mismatches": [],
            "reason": "Invalid unrecognized state.",
        },
        "assessment_method": "exact_answer",
        "task_fingerprint": "a" * 64,
        "task_content_sha256": "b" * 64,
        "checker_fingerprint": "c" * 64,
        "pedagogical_status": "not_pedagogically_approved",
    }

    with pytest.raises(EvidenceContractError, match="недопустимые значения"):
        validate_evidence_event(row)


def test_unverified_manual_event_does_not_change_confirmed_state_or_decision():
    sql = event(skill_id="skill.inf.relational-query", event_id="sql-correct", task_id=1, minute=0)
    error = event(skill_id="skill.inf.game-winning-strategy", event_id="game-error", task_id=2,
                  result="not_met", assistance="independent", minute=1)
    manual = event(skill_id="skill.inf.data-quality-pipeline", event_id="manual-ungraded", task_id=3,
                   result="met", assistance=None, minute=2)
    manual["evidence_status"] = "insufficient_data"
    manual["outcome"] = {"score": None, "maximum": 1, "status": "insufficient_data"}
    manual["criteria"][0].update({
        "earned": None, "status": "insufficient_data", "evidence_status": "insufficient_data",
    })

    before = compare_learning_history([sql, error], SUBJECT)
    after = compare_learning_history([sql, error, manual], SUBJECT)

    assert after["after"]["skills"] == before["after"]["skills"]
    assert after["decision"]["action"] == before["decision"]["action"]
    assert after["decision"]["action"] == "keep_plan_collect_more_evidence"
    assert all(not change["changed"] for change in after["changes"])


def test_platform_curriculum_preview_preserves_60_minute_total_without_applying(monkeypatch):
    case = {
        "profile_id": SUBJECT,
        "course_copy_id": 77,
        "course_title": "Синтетическая копия IPv4",
        "course_version": 2,
        "student_id": 88,
        "next_lesson": {
            "lesson_id": 99,
            "title": "IPv4: маска и границы сети",
            "duration_minutes": 60,
            "module_id": 5,
            "module_title": "Сети",
        },
        "proposal": {
            "action": "targeted_diagnostic_and_review",
            "text": "Добавить короткую проверку граничного условия.",
            "time_allocation": {"planned_lesson_minutes": 50, "adaptation_minutes": 10},
            "selected_exercise": {"exercise_id": "practice:ipv4:1", "title": "Сеть и границы"},
            "proposed_structure": [
                {"id": "check", "title": "Проверка", "minutes": 10},
                {"id": "preserved", "title": "Исходное содержание", "minutes": 50},
            ],
            "original_structure": [
                {"id": "intro", "title": "Вводная часть", "minutes": 10},
                {"id": "theory", "title": "Основное содержание", "minutes": 30},
                {"id": "practice", "title": "Практика", "minutes": 20},
            ],
            "time_plan": {"status": "redistributed"},
        },
        "curriculum_resolution": {"status": "resolved", "selection_basis": "User → Student → active assigned copy"},
        "can_generate": True,
        "source_refs": ["practice-attempt:1"],
        "skill_summary": {"status_label": "Нужна поддержка"},
    }
    monkeypatch.setattr("app.ai_lab.tutor_core._platform_profile_cases", lambda _actor_id: [case])

    preview = tutor_core31._platform_curriculum_context(SUBJECT, actor_user_id=4)

    assert preview["status"] == "linked"
    assert preview["lesson_id"] == 99
    assert [item["minutes"] for item in preview["plan_after"]] == [10, 50]
    assert preview["plan_after_total"] == preview["plan_before_total"] == 60
    assert preview["proposal_available"] is True

    case["proposal"] = {"action": "maintain_plan", "text": "План оставить без изменений."}
    maintained = tutor_core31._platform_curriculum_context(SUBJECT, actor_user_id=4)

    assert maintained["preview_available"] is True
    assert maintained["proposal_available"] is False
    assert maintained["plan_after"] is None


def test_platform_curriculum_without_allowlisted_copy_stays_unlinked(monkeypatch):
    case = {"profile_id": SUBJECT, "course_copy_id": None,
            "proposal": {"text": "Копия курса не разрешена."}}
    monkeypatch.setattr("app.ai_lab.tutor_core._platform_profile_cases", lambda _actor_id: [case])

    preview = tutor_core31._platform_curriculum_context(SUBJECT, actor_user_id=4)

    assert preview["status"] == "not_linked"
    assert preview["proposal_status"] == "not_available"
    assert "Копия курса не разрешена" in preview["proposal_reason"]


def test_platform_curriculum_exposes_ambiguous_assigned_copies(monkeypatch):
    case = {
        "profile_id": SUBJECT,
        "course_copy_id": None,
        "curriculum_resolution": {"status": "ambiguous_active_copies", "candidate_ids": [77, 78]},
        "proposal": {"text": "Для адаптации требуется явный выбор курса."},
    }
    monkeypatch.setattr("app.ai_lab.tutor_core._platform_profile_cases", lambda _actor_id: [case])

    preview = tutor_core31._platform_curriculum_context(SUBJECT, actor_user_id=4)

    assert preview["status"] == "ambiguous_curriculum"
    assert preview["candidate_course_ids"] == [77, 78]
    assert "явный выбор" in preview["proposal_reason"]
