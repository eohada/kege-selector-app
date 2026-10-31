from types import SimpleNamespace
from copy import deepcopy

import pytest

from app.ai_lab.tutor_core import (
    _attach_knowledge_context,
    _alternative_algorithm_verified,
    _case_proposal,
    _fixture_events,
    _reference_legend,
    _supported_detail_context,
    _unverified_detail_reason,
    _validate_narrative,
)
from app.ai_lab import tutor_core
from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION, validate_evidence_event


def _pilot_fixture():
    specs = [
        (75, 10, 1, "Урок 9. Графы и таблицы"),
        (76, 20, 4, "Урок 10. Условие Фано"),
        (77, 30, 1, "Урок 11. Практика графов"),
        (78, 40, 14, "Урок 12. Системы счисления"),
        (79, 50, 8, "Урок 13. Комбинаторика"),
        (80, 60, 8, "Урок 14. Перебор комбинаций"),
    ]
    lessons = []
    materials = []
    for lesson_id, order, task_number, title in specs:
        skill = SimpleNamespace(
            skill_id=task_number, task_number=task_number,
            title=f"Навык ЕГЭ №{task_number}",
        )
        lesson = SimpleNamespace(
            lesson_id=lesson_id, course_order_index=order, course_module_id=1 if lesson_id < 78 else 2,
            topic=title, content="Материал синтетического пилота.", skills=[skill],
        )
        lessons.append(lesson)
        materials.append({
            "source_lesson_id": lesson_id,
            "title": title,
            "content": "Материал синтетического пилота.",
            "topic_id": f"boostudy-module:{lesson.course_module_id}",
        })
    course = {"course_version": 1, "title": "Пилотный курс", "materials": materials}
    return course, lessons


def test_three_profiles_use_distinct_evidence_and_preserve_plan_constraints():
    course, lessons = _pilot_fixture()
    event_sets = _fixture_events(lessons, course_version=1)
    proposals = {
        profile_id: _case_proposal(profile_id, events, course, lessons)
        for profile_id, events in event_sets.items()
    }

    support = proposals["synthetic-tutor-support"]
    steady = proposals["synthetic-tutor-steady"]
    uncertain = proposals["synthetic-tutor-uncertain"]

    assert support["skill_summary"]["status"] == "developing"
    assert support["next_lesson"]["lesson_id"] == 79
    assert support["proposal"]["action"] == "maintain_plan"
    assert "не совпадает" in support["proposal"]["text"]
    assert [event["score"] for event in support["evidence"]] == [0, 0, 1, 1]
    assert all(item["source_module"] == "ai_tutor_core" for item in event_sets["synthetic-tutor-support"])

    assert steady["skill_summary"]["status"] == "demonstrated"
    assert steady["next_lesson"]["lesson_id"] == 80
    assert steady["proposal"]["action"] == "extension_with_alternative_method"
    assert len({item["assignment"]["id"] for item in event_sets["synthetic-tutor-steady"]}) == 3

    assert uncertain["skill_summary"]["status"] == "insufficient_data"
    assert uncertain["next_lesson"]["lesson_id"] == 76
    assert uncertain["proposal"]["action"] == "maintain_plan"
    assert "не совпадает" in uncertain["proposal"]["text"]
    assert any(item["evidence_status"] == "ai_inference" for item in event_sets["synthetic-tutor-uncertain"])

    for proposal in proposals.values():
        assert len(proposal["current_plan"]) == 6
        assert proposal["constraints"]["lessons_per_week"] == 2
        assert proposal["constraints"]["lesson_duration_minutes"] == 60
        assert proposal["constraints"]["course_structure_changed"] is False
        time = proposal["proposal"]["time_allocation"]
        assert time["total_minutes"] == time["planned_lesson_minutes"] + time["adaptation_minutes"]
        assert proposal["constraints"]["schedule_status"].startswith("экспериментальное")


def test_mixed_technical_results_do_not_establish_a_skill_gap_or_mastery():
    from app.ai_lab.analytics import build_analytics_snapshot

    course, lessons = _pilot_fixture()
    base_events = _fixture_events(lessons, course_version=1)["synthetic-tutor-support"]
    events = []
    for index in range(8):
        event = deepcopy(base_events[index % len(base_events)])
        event_id = f"synthetic-mixed-attempt:{index + 1}"
        is_correct = index < 5
        criterion = event["criteria"][0]
        event["event_id"] = event_id
        event["source_record_id"] = f"synthetic-mixed-lesson:{index + 1}"
        event["assignment"]["id"] = f"synthetic-mixed-assignment:{index + 1}"
        event["outcome"].update(score=2 if is_correct else 0, status="met" if is_correct else "not_met")
        event["provenance"]["source_ref"] = event_id
        event["error_codes"] = []
        criterion.update(
            status="met" if is_correct else "not_met",
            earned=2 if is_correct else 0,
            source_refs=[event_id],
        )
        events.append(event)

    skill = build_analytics_snapshot(events, "synthetic-tutor-support")["skills"][0]

    assert skill["status"] == "developing"
    assert skill["technical_correct_attempts"] == 5
    assert skill["technical_incorrect_attempts"] == 3
    assert skill["observed_difficulty"] is True
    assert skill["diagnostic_recommended"] is True
    assert skill["mastery_confirmed"] is False
    assert skill["error_cause_confirmed"] is False
    assert "причина затруднения не установлена" in skill["status_label"]

    repeated_code_events = deepcopy(events)
    varied_code_events = deepcopy(events)
    for index in range(5, 8):
        repeated_code_events[index]["error_codes"] = ["boundary_or_condition"]
        varied_code_events[index]["error_codes"] = [f"observed_error_{index}"]

    repeated = build_analytics_snapshot(repeated_code_events, "synthetic-tutor-support")["skills"][0]
    varied = build_analytics_snapshot(varied_code_events, "synthetic-tutor-support")["skills"][0]
    assert repeated["status"] == varied["status"] == "developing"
    assert repeated["diagnostic_hypothesis"] == "repeated_error_pattern"
    assert varied["diagnostic_hypothesis"] == "mixed_technical_outcomes"
    assert repeated["diagnostic_hypothesis_confirmed"] is False
    assert varied["diagnostic_hypothesis_confirmed"] is False
    assert repeated["error_cause_confirmed"] is varied["error_cause_confirmed"] is False

    all_correct_events = deepcopy(events)
    for event in all_correct_events:
        event["outcome"].update(score=2, status="met")
        event["criteria"][0].update(status="met", earned=2)
    all_correct = build_analytics_snapshot(all_correct_events, "synthetic-tutor-support")["skills"][0]
    assert all_correct["status"] == "demonstrated"
    assert all_correct["mastery_confirmed"] is False


def test_alternative_combinatorics_algorithm_matches_controlled_cases():
    assert _alternative_algorithm_verified() is True


def test_narrative_cannot_supply_or_change_deterministic_scores():
    event_ref = "tutor-fixture:synthetic-tutor-support:event:1"
    result = _validate_narrative({
        "student_feedback": "Повтори один пример.",
        "teacher_explanation": "Есть повторяющийся сигнал.",
        "uncertainty_note": "Вывод ограничен синтетическими случаями.",
        "evidence_refs": [event_ref],
        "score_awarded": 99,
    }, {event_ref})

    assert "score_awarded" not in result
    assert result["evidence_refs"] == [event_ref]


def test_narrative_cannot_reference_unknown_evidence():
    with pytest.raises(ValueError, match="неизвестное доказательство"):
        _validate_narrative({
            "student_feedback": "Повтори пример.",
            "teacher_explanation": "Смотри на данные.",
            "uncertainty_note": "Данных мало.",
            "evidence_refs": ["not-an-event"],
        }, {"known-event"})


def test_knowledge_context_requires_exact_versioned_reference():
    knowledge_ref = "knowledge:ege.inf.positional-number-systems.v1:v2"
    narrative = {
        "student_feedback": "Проверь позиционную запись числа.",
        "teacher_explanation": "Объяснение опирается на материал курса.",
        "uncertainty_note": "Проверены только имеющиеся синтетические события.",
        "evidence_refs": ["synthetic-event:1"],
        "knowledge_refs": [knowledge_ref],
    }

    result = _validate_narrative(
        narrative, {"synthetic-event:1"}, {knowledge_ref}, require_knowledge_refs=True,
    )

    assert result["knowledge_refs"] == [knowledge_ref]
    narrative["knowledge_refs"] = []
    with pytest.raises(ValueError, match="базы знаний"):
        _validate_narrative(
            narrative, {"synthetic-event:1"}, {knowledge_ref}, require_knowledge_refs=True,
        )


def test_reference_legend_separates_event_ids_from_knowledge_versions():
    event_id = "platform-submission:13:attempt:2:task:230"
    knowledge_ref = "knowledge:ege.inf.graph-table-matching.v1:v1"

    legend = _reference_legend({
        "evidence": [{"event_id": event_id, "source_ref": "submission:13:task:230"}],
        "knowledge_context": [{"knowledge_ref": knowledge_ref}],
    })

    assert legend == {"evidence_refs": [event_id], "knowledge_refs": [knowledge_ref]}


def test_narrative_rejects_graph_labels_and_rows_missing_from_evidence():
    narrative = {
        "student_feedback": "В задании №1 нужно сопоставить граф и таблицу.",
        "teacher_explanation": "Например, если A уже сопоставлена со строкой 3, то C и D нужно проверить по связям.",
        "uncertainty_note": "Проверь перенос на другом примере.",
    }
    context = _supported_detail_context({
        "evidence": [{
            "event_id": "platform-submission:13:attempt:2:task:230",
            "score": 1,
            "maximum": 1,
            "reason": "Ответ совпал с сохранённым ключом.",
        }],
        "skill_summary": {"skill_id": "exam-skill:1", "task_number": 1, "status_label": "Недостаточно данных"},
        "next_lesson": {"lesson_id": 3, "title": "Задание №1. Графы и таблицы"},
        "knowledge_context": [{
            "knowledge_ref": "knowledge:ege.inf.graph-table-matching.v3:v3",
            "content": {
                "summary": "При одинаковой степени проверяйте связи между сопоставленными вершинами.",
                "platform_task_links": [{"task_id": 3, "skill_id": "exam-skill:3"}],
            },
        }],
    })

    reason = _unverified_detail_reason(narrative, context)

    assert reason is not None
    assert "конкретные числа или обозначения" in reason


def test_narrative_allows_general_graph_guidance_without_invented_examples():
    narrative = {
        "student_feedback": "Задание №1 требует сопоставить граф и таблицу.",
        "teacher_explanation": "При одинаковой степени проверяй связи между уже сопоставленными вершинами; не выбирай вариант произвольно.",
        "uncertainty_note": "Недостаточно данных, чтобы сделать вывод об освоении темы.",
    }
    context = _supported_detail_context({
        "skill_summary": {"task_number": 1},
        "next_lesson": {"title": "Задание №1. Графы и таблицы"},
        "knowledge_context": [{"content": {"summary": "При одинаковой степени проверяйте связи между сопоставленными вершинами."}}],
    })

    assert _unverified_detail_reason(narrative, context) is None


def test_tutor_retrieval_keeps_only_sources_linked_to_confirmed_skill(monkeypatch):
    from app.ai_lab import knowledge_base

    candidates = [
        {"stable_key": "matched", "content": {"task_links": [{"skill_id": "exam-skill:14"}]}},
        {"stable_key": "unrelated", "content": {"task_links": [{"skill_id": "exam-skill:2"}]}},
        {"stable_key": "unmapped", "content": {"lesson_links": []}},
    ]
    monkeypatch.setattr(knowledge_base, "retrieve_knowledge", lambda query, limit: candidates)
    proposal = {
        "evidence": [{"reason": "синтетическая ошибка"}],
        "skill_summary": {"skill_id": "exam-skill:14", "task_number": 14},
        "next_lesson": {"title": "Позиционные системы"},
        "proposal": {"skill_titles": []},
    }

    _attach_knowledge_context(proposal)

    assert [item["stable_key"] for item in proposal["knowledge_context"]] == ["matched"]
    assert proposal["knowledge_context_status"] == "retrieved"


def test_specific_code_examples_without_evidence_are_marked_unverified():
    narrative = {
        "student_feedback": "Проверь значение '0' и пустую строку.",
        "teacher_explanation": "В цикле while добавь отдельную обработку.",
        "uncertainty_note": "Нужна дополнительная проверка.",
    }
    assert _unverified_detail_reason(narrative)


def test_general_evidence_based_feedback_is_not_blocked():
    narrative = {
        "student_feedback": "В синтетических контрольных вариантах заметен частичный прогресс.",
        "teacher_explanation": "Предложена короткая проверка граничного условия.",
        "uncertainty_note": "Вывод относится только к указанным синтетическим вариантам.",
    }
    assert _unverified_detail_reason(narrative) is None


def test_platform_profile_stays_unadapted_without_verified_skill_evidence():
    event = validate_evidence_event({
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": "platform-submission:501:attempt:1:task:505",
        "subject_id": "platform-student:12",
        "source_module": "ai_homework",
        "source_record_id": "submission:501",
        "occurred_at": "2026-10-21T10:00:00+00:00",
        "evidence_status": "insufficient_data",
        "assignment": {"id": "platform-assignment:503", "version": 1},
        "topic_ids": [], "skill_ids": [], "error_codes": [],
        "limitations": ["Источник проверки не подтверждён."],
        "outcome": {"score": 3, "maximum": 3, "status": "insufficient_data"},
        "criteria": [{
            "criterion_id": "assignment-task:504", "skill_id": None,
            "earned": None, "maximum": 3, "status": "insufficient_data",
            "evidence_status": "insufficient_data",
            "reason": "Сохранённый балл не связан с проверенным навыком.",
            "source_refs": ["submission:501:answer:502"],
        }],
        "provenance": {"source_ref": "platform-submission:501:attempt:1:task:505",
                       "method": "Сохранённая оценка без подтверждённого источника проверки"},
    })

    case = tutor_core._platform_profile_case("platform-student:12", [event], student_id=4, copy=None)

    assert case["label"] == "Синтетический ученик · ID 12"
    assert case["profile_label"] == case["label"]
    assert case["event_count"] == 1
    assert case["course_copy_id"] is None
    assert case["can_generate"] is False
    assert case["adaptation_preview"] == {
        "status": "no_individual_copy", "course_id": None, "changes": [], "will_mutate": False,
    }


def test_platform_skill_bridge_uses_only_unique_curated_topic_codes():
    ipv4_skill = SimpleNamespace(skill_id=1, topic_code="ege.inf.ipv4.subnet-mask.v1")
    mapped, details = tutor_core._bridge_evidence_skill_ids(
        ["skill.inf.ipv4.subnet-mask", "skill.inf.unknown"], [ipv4_skill],
    )

    assert mapped == ["exam-skill:1"]
    assert details == [{
        "evidence_skill_id": "skill.inf.ipv4.subnet-mask",
        "course_skill_id": "exam-skill:1",
        "topic_code": "ege.inf.ipv4.subnet-mask.v1",
        "status": "resolved",
        "method": "curated_practice_topic_code",
    }]

    duplicate = SimpleNamespace(skill_id=7, topic_code="ege.inf.ipv4.subnet-mask.v1")
    assert tutor_core._bridge_evidence_skill_ids(
        ["skill.inf.ipv4.subnet-mask"], [ipv4_skill, duplicate],
    ) == ([], [])


def test_idempotency_key_is_scoped_to_tutor_version(monkeypatch):
    payload = {"evidence": [{"event_id": "synthetic-1"}]}
    first = tutor_core._proposal_key(1, "profile_a", payload, "GigaChat-3-Pro")
    monkeypatch.setattr(tutor_core, "TUTOR_VERSION", "boostudy.tutor-core.next")
    second = tutor_core._proposal_key(1, "profile_a", payload, "GigaChat-3-Pro")
    assert first != second
