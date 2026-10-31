from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def isolated_lesson_app():
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with app.app_context():
        db.create_all()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def test_markdown_transcript_keeps_multiline_roles_time_and_source_offsets():
    from app.ai_lab.lesson_intelligence import parse_transcript

    source = (
        "# Синтетический урок\n"
        "**[00:18:12] Ученик:** Для /27 я получил четыре адреса.\n"
        "Продолжение ответа без повторной метки.\n"
        "**[00:18:20] Преподаватель:** Назови адрес сети и broadcast.\n"
        "Наблюдатель: Проверка записи.\n"
    )
    segments = parse_transcript(source)

    assert segments[0]["segment_kind"] == "metadata"
    student = segments[1]
    assert student["speaker"] == "Ученик"
    assert student["speaker_role"] == "student"
    assert student["timestamp"] == "00:18:12"
    assert student["text"] == "Для /27 я получил четыре адреса.\nПродолжение ответа без повторной метки."
    assert source[student["source_start_char"]:student["source_end_char"]].startswith("**[00:18:12]")
    assert student["source_line"] == 2 and student["source_line_end"] == 3
    assert segments[2]["speaker_role"] == "teacher"
    assert segments[3]["speaker_role"] == "unknown"


def test_retrieved_knowledge_skill_is_allowed_by_schema_and_validator():
    from app.ai_lab.lesson_intelligence import (
        _validate_ai_result,
        lesson_analysis_chunks,
        lesson_response_schema,
        parse_transcript,
    )

    knowledge = {"items": [{"stable_key": "ege.inf.ip-prefix-mask.v1", "title": "IPv4: маски и подсети",
                             "content": {"learning_goal": "Префикс, маска и адрес сети."}}]}
    segments = parse_transcript("Преподаватель: Назови смысл маски IPv4 и префикса.\nУченик: Я не понимаю, что означает /27.")
    chunk = lesson_analysis_chunks(segments, knowledge_context=knowledge)[0]
    allowed_skill_ids = chunk["allowed_skill_ids"]
    assert "ege.inf.ip-prefix-mask.v1" in allowed_skill_ids
    assert allowed_skill_ids == ["ege.inf.ip-prefix-mask.v1"]
    schema = lesson_response_schema(chunk)
    assert "ege.inf.ip-prefix-mask.v1" in schema["properties"]["observed_difficulties"]["items"]["properties"]["skill_id"]["enum"]
    assert "python.iteration" not in schema["properties"]["observed_difficulties"]["items"]["properties"]["skill_id"]["enum"]

    validated = _validate_ai_result(
        {"summary": "Ученик затрудняется с префиксом.", "topics": [], "content_segments": [],
         "observed_difficulties": [{"skill_id": "ege.inf.ip-prefix-mask.v1",
                                    "description": "Не понимает значение префикса.",
                                    "source_refs": ["segment-002"]}], "limitations": []},
        {"lesson_id": "synthetic-ipv4", "lesson_version": 1, "segments": segments,
         "knowledge_context": knowledge, "source_ref": "synthetic:test"},
    )
    assert validated["observed_difficulties"][0]["skill_id"] == "ege.inf.ip-prefix-mask.v1"


def test_retrieved_domain_skill_blocks_unrelated_generic_python_mapping():
    from app.ai_lab.lesson_intelligence import LessonAnalysisError, _validate_ai_result, parse_transcript

    segments = parse_transcript("Ученик: Я не уверен, где в адресе искать границу для /20.")
    request = {"lesson_id": "synthetic-domain-skill-guard", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": segments,
               "knowledge_context": {"items": [{"stable_key": "ege.inf.ip-prefix-mask.v1"}]}}
    raw = {"summary": "Затруднение относится к подсетям.", "topics": [], "content_segments": [],
           "observed_difficulties": [{"skill_id": "python.iteration", "skill_facet_id": "block.boundary",
                                      "description": "Не уверен в выборе октета.", "source_refs": ["segment-001"]}],
           "limitations": [], "learner_events": []}

    with pytest.raises(LessonAnalysisError, match="поддерживаемый skill_id"):
        _validate_ai_result(raw, request)


def test_priorities_count_repeated_explicit_difficulty_citations_without_model_events():
    from app.ai_lab.lesson_intelligence import _build_prioritized_lesson_plan, parse_transcript

    segments = parse_transcript(
        "Ученик: Я не понимаю, как выбрать октет для /20.\n"
        "Преподаватель: Сначала проверь, где в маске заканчиваются единицы.\n"
        "Ученик: Я всё ещё не уверен, какой октет использовать.\n"
        "Преподаватель: Попробуй найти размер блока в неполном октете.\n"
        "Ученик: Я снова запутался и не знаю, где считать блоки."
    )
    item = {"skill_id": "ege.inf.ip-prefix-mask.v1", "skill_facet_id": "ipv4.prefix.third_octet_boundary",
            "description": "Выбор октета для границы /20 остаётся затруднением.",
            "source_refs": ["segment-001", "segment-003", "segment-005"],
            "resolution_source_refs": [], "resolution_status": "unresolved_or_unknown", "progress_evidence": []}
    plan = _build_prioritized_lesson_plan({"segments": segments, "planned_session_minutes": 60},
                                         {"topics": [], "observed_difficulties": [item]})

    assert plan["priority_items"][0]["reasons"]["repeated_difficulty_count"] == 2
    assert plan["total_minutes"] == 60 == sum(stage["minutes"] for stage in plan["stages"])


def test_server_checks_event_roles_order_and_repeated_evidence():
    from app.ai_lab.lesson_intelligence import _validate_ai_result, parse_transcript

    segments = parse_transcript(
        "Преподаватель: Попробуй объяснить деление на подсети.\n"
        "Ученик: Я не понимаю, как найти адрес сети.\n"
        "Преподаватель: Сравни биты маски и адреса.\n"
        "Ученик: Теперь понял: адрес сети получается обнулением хостовой части."
    )
    raw = {"summary": "Обсудили маску.", "topics": [], "content_segments": [],
           "observed_difficulties": [], "limitations": [],
           "learner_events": [
               {"kind": "after_hint_demonstration", "skill": "адрес сети",
                "summary": "После подсказки ученик назвал способ нахождения адреса сети.",
                "source_refs": ["segment-003", "segment-004"]},
               {"kind": "independent_demonstration", "skill": "адрес сети",
                "summary": "Ученик самостоятельно владеет темой.", "source_refs": ["segment-001"]},
               {"kind": "repeated_difficulty", "skill": "адрес сети",
                "summary": "Затруднение повторилось.", "source_refs": ["segment-002"]},
           ]}

    result = _validate_ai_result(raw, {"lesson_id": "synthetic-evidence", "lesson_version": 1,
                                       "source_ref": "synthetic:test", "segments": segments})
    by_kind = {event["kind"]: event for event in result["learner_events"]}
    assert by_kind["after_hint_demonstration"]["validation_status"] == "supported_by_transcript"
    assert by_kind["after_hint_demonstration"]["citations"][0]["speaker_role"] == "teacher"
    assert by_kind["after_hint_demonstration"]["citations"][1]["timestamp"] is None
    assert by_kind["independent_demonstration"]["validation_status"] == "unverified"
    assert by_kind["repeated_difficulty"]["validation_status"] == "unverified"


def test_next_lesson_plan_rejects_wrong_total_and_unsupported_topic_change():
    from app.ai_lab.lesson_intelligence import _validate_lesson_synthesis, parse_transcript

    segments = parse_transcript("Преподаватель: Разберём IPv4-маску.\nУченик: Я не понимаю адрес сети.")
    request = {"segments": segments, "planned_session_minutes": 60}
    good_stage = {"title": "Диагностика маски", "minutes": 60, "reason": "Ученик назвал затруднение.",
                  "expected_check": "Ученик указывает адрес сети.", "source_refs": ["segment-002"]}
    result = _validate_lesson_synthesis({"decision": "propose_change", "reason": "Повторить найденное затруднение.",
                                         "stages": [good_stage], "limitations": []}, request,
                                        {"segment-001", "segment-002"})
    assert result["decision"] == "propose_change"
    assert result["total_minutes"] == 60
    assert result["baseline_plan_available"] is False
    assert result["stages"][0]["citations"][0]["quote"] == "Я не понимаю адрес сети."

    invalid = {"decision": "propose_change", "reason": "Ввести новую тему.",
               "stages": [{**good_stage, "minutes": 45, "source_refs": ["segment-001"]}], "limitations": []}
    with pytest.raises(ValueError, match="не равна длительности"):
        _validate_lesson_synthesis(invalid, request, {"segment-001", "segment-002"})


def test_skill_state_requires_same_skill_provenance_and_separates_help_from_independent_use():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю, почему верхняя граница range не включается.\n"
        "Преподаватель: Посчитай следующий пример с границей 8.\n"
        "Ученик: После подсказки передам 9, тогда 8 попадёт в диапазон."
    )
    request = {"lesson_id": "synthetic-state", "lesson_version": 1, "source_ref": "synthetic:test",
               "segments": transcript}
    result = _validate_ai_result({
        "summary": "Ученик исправил ответ после подсказки.", "topics": [], "content_segments": [],
        "observed_difficulties": [{"skill_id": "python.boundary_cases", "skill_facet_id": "python.range.stop_boundary",
                                   "description": "Не понимает включение правой границы.",
                                   "source_refs": ["segment-001"]}], "limitations": [],
        "learner_events": [{"kind": "after_hint_demonstration", "skill_id": "python.boundary_cases",
                            "skill_facet_id": "python.range.stop_boundary",
                            "skill": "правая граница range", "summary": "Ответ после подсказки.",
                            "source_refs": ["segment-002", "segment-003"]}],
    }, request)
    merged = _merge_lesson_chunk_results(request, [{"result": result}])
    difficulty = merged["observed_difficulties"][0]
    assert difficulty["resolution_status"] == "corrected_after_hint"
    assert difficulty["durability_status"] == "not_established"
    assert difficulty["resolution_source_refs"] == ["segment-002", "segment-003"]


def test_independent_application_is_only_a_review_candidate_and_verbal_claim_is_not_resolution():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю, как проверить край диапазона.\n"
        "Ученик: На новом примере 12 включается, если stop равен 13.\n"
        "Ученик: Я понял."
    )
    request = {"lesson_id": "synthetic-independent", "lesson_version": 1, "source_ref": "synthetic:test",
               "segments": transcript}
    raw = {"summary": "Проверено применение границ.", "topics": [], "content_segments": [],
           "observed_difficulties": [{"skill_id": "python.boundary_cases", "skill_facet_id": "python.range.stop_boundary",
                                      "description": "Не понимает правую границу.",
                                      "source_refs": ["segment-001"]}], "limitations": [],
           "learner_events": [
               {"kind": "independent_demonstration", "skill_id": "python.boundary_cases",
                "skill_facet_id": "python.range.stop_boundary", "skill": "правая граница",
                "summary": "Ученик применил правило на новом примере.", "source_refs": ["segment-002"]},
               {"kind": "resolved_difficulty", "skill_id": "python.boundary_cases",
                "skill_facet_id": "python.range.stop_boundary", "skill": "правая граница",
                "summary": "Ученик сказал, что понял.", "source_refs": ["segment-003"]},
           ]}
    validated = _validate_ai_result(raw, request)
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])
    difficulty = merged["observed_difficulties"][0]
    events = {event["kind"]: event for event in merged["learner_events"]}
    assert events["independent_demonstration"]["validation_status"] == "supported_by_transcript"
    assert events["resolved_difficulty"]["validation_status"] == "unverified"
    assert difficulty["resolution_status"] == "independent_application_candidate"
    assert difficulty["review_status"] == "resolution_candidate"
    assert difficulty["durability_status"] == "not_established"
    assert {item["kind"] for item in difficulty["progress_evidence"]} == {
        "independent_demonstration", "resolved_difficulty"
    }


def test_same_skill_must_match_exact_stable_id_and_later_difficulty_overrides_earlier_candidate():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю граничный случай.\n"
        "Ученик: На примере 5 правило сработало самостоятельно.\n"
        "Ученик: Но я не понимаю, что происходит на значении 0."
    )
    request = {"lesson_id": "synthetic-conflict", "lesson_version": 1, "source_ref": "synthetic:test",
               "segments": transcript}
    raw = {"summary": "Есть противоречивые свидетельства.", "topics": [], "content_segments": [],
           "observed_difficulties": [{"skill_id": "python.boundary_cases", "skill_facet_id": "python.boundary.edge",
                                      "description": "Затруднение с границей.",
                                      "source_refs": ["segment-001"]}], "limitations": [],
           "learner_events": [
               {"kind": "independent_demonstration", "skill_id": "python.boundary_cases",
                "skill_facet_id": "python.boundary.edge", "skill": "границы",
                "summary": "Самостоятельный ответ на примере.", "source_refs": ["segment-002"]},
               {"kind": "repeated_difficulty", "skill_id": "python.boundary_cases",
                "skill_facet_id": "python.boundary.edge", "skill": "границы",
                "summary": "Новое затруднение на нуле.", "source_refs": ["segment-001", "segment-003"]},
               {"kind": "independent_demonstration", "skill_id": "python.iteration",
                "skill_facet_id": "python.iteration.loop", "skill": "итерации",
                "summary": "Свидетельство другого навыка.", "source_refs": ["segment-002"]},
           ]}
    validated = _validate_ai_result(raw, request)
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])
    difficulty = merged["observed_difficulties"][0]
    assert difficulty["resolution_status"] == "unresolved_or_unknown"
    assert difficulty["resolution_source_refs"] == []
    assert any(item["kind"] == "independent_demonstration" and item["skill_id"] == "python.iteration"
               for item in merged["learner_events"])


def test_same_broad_skill_id_does_not_transfer_evidence_between_micro_skill_facets():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю, какой октет определить для маски /20.\n"
        "Ученик: Для /27 самостоятельно посчитал 32 адреса, из них 30 пригодны."
    )
    request = {"lesson_id": "synthetic-facet-isolation", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript,
               "knowledge_context": {"items": [{"stable_key": "ege.inf.ip-prefix-mask.v1"}]}}
    validated = _validate_ai_result({
        "summary": "Ученик справился с подсчётом адресов, но сомневается в выборе октета для /20.",
        "topics": [], "content_segments": [], "limitations": [],
        "observed_difficulties": [{
            "skill_id": "ege.inf.ip-prefix-mask.v1",
            "skill_facet_id": "ipv4.prefix.network_octet_for_slash20",
            "description": "Не уверен, какой октет относится к сети при /20.",
            "source_refs": ["segment-001"],
        }],
        "learner_events": [{
            "kind": "independent_demonstration",
            "skill_id": "ege.inf.ip-prefix-mask.v1",
            "skill_facet_id": "ipv4.prefix.usable_host_count",
            "skill": "подсчёт пригодных адресов",
            "summary": "Самостоятельно назвал число адресов для /27.",
            "source_refs": ["segment-002"],
        }],
    }, request)
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])

    assert len(merged["observed_difficulties"]) == 1
    difficulty = merged["observed_difficulties"][0]
    assert difficulty["resolution_status"] == "unresolved_or_unknown"
    assert difficulty["resolution_source_refs"] == []
    assert difficulty["skill_facet_id"] == "ipv4.prefix.network_octet_for_slash20"
    event = next(item for item in merged["learner_events"]
                 if item["kind"] == "independent_demonstration")
    assert event["skill_facet_id"] == "ipv4.prefix.usable_host_count"


def test_lesson_knowledge_context_filters_low_relevance_and_chunk_context_prefers_matching_topic(monkeypatch):
    from app.ai_lab import lesson_intelligence
    from app.ai_lab.lesson_intelligence import _lesson_knowledge_context, lesson_analysis_chunks, parse_transcript

    candidates = [
        {"stable_key": "ege.inf.ip-prefix-mask.v1", "title": "IPv4: маски и подсети", "retrieval_score": 44,
         "content_sha256": "a" * 64, "content": {"learning_goal": "CIDR и адрес сети", "explanation": "Маска IPv4"}},
        {"stable_key": "ege.inf.graphs.v1", "title": "Графы", "retrieval_score": 25,
         "content_sha256": "b" * 64, "content": {"learning_goal": "Обход графа", "explanation": "Рёбра и вершины"}},
        {"stable_key": "ege.inf.spreadsheets.v1", "title": "Таблицы", "retrieval_score": 22,
         "content_sha256": "c" * 64, "content": {"learning_goal": "Электронные таблицы", "explanation": "Формулы"}},
    ]
    monkeypatch.setattr(lesson_intelligence, "retrieve_knowledge", lambda query, limit: candidates[:limit])
    ipv4 = parse_transcript("Преподаватель: Разберём маску IPv4 и адрес сети.\nУченик: Я не понимаю CIDR.")
    context = _lesson_knowledge_context(ipv4)
    assert [item["stable_key"] for item in context["items"]] == ["ege.inf.ip-prefix-mask.v1"]
    assert {item["stable_key"] for item in context["excluded_candidates"]} == {
        "ege.inf.graphs.v1", "ege.inf.spreadsheets.v1"
    }

    chunks = lesson_analysis_chunks(ipv4, knowledge_context={"status": "retrieved", "items": [
        {"stable_key": "ege.inf.ip-prefix-mask.v1", "title": "IPv4 маски", "content": {"learning_goal": "маска CIDR", "explanation": "адрес сети"}},
        {"stable_key": "ege.inf.graphs.v1", "title": "Графы", "content": {"learning_goal": "обход графа", "explanation": "рёбра"}},
    ]})
    assert [item["stable_key"] for item in chunks[0]["knowledge_context"]["items"]] == ["ege.inf.ip-prefix-mask.v1"]


def test_retrieval_relative_threshold_keeps_multiple_equally_relevant_topics(monkeypatch):
    from app.ai_lab import lesson_intelligence
    from app.ai_lab.lesson_intelligence import _lesson_knowledge_context, parse_transcript

    candidates = [
        {"stable_key": "ege.inf.ipv4.v1", "title": "IPv4", "retrieval_score": 18, "content": {}},
        {"stable_key": "ege.inf.logic.v1", "title": "Логические выражения", "retrieval_score": 16,
         "content": {"learning_goal": "Проверка логических выражений и условий."}},
        {"stable_key": "ege.inf.graphs.v1", "title": "Графы", "retrieval_score": 6, "content": {}},
    ]
    monkeypatch.setattr(lesson_intelligence, "retrieve_knowledge", lambda query, limit: candidates[:limit])
    context = _lesson_knowledge_context(parse_transcript(
        "Преподаватель: Сравним IPv4 с логическими выражениями.\nУченик: Я не понимаю оба шага."
    ))
    assert [item["stable_key"] for item in context["items"]] == ["ege.inf.ipv4.v1", "ege.inf.logic.v1"]


def test_lesson_knowledge_relevance_rejects_high_score_noise_and_keeps_direct_topic_match(monkeypatch):
    from app.ai_lab import lesson_intelligence
    from app.ai_lab.lesson_intelligence import _lesson_knowledge_context, parse_transcript

    candidates = [
        {"stable_key": "ege.inf.graph-table-matching.v1", "title": "Графы и таблицы", "retrieval_score": 50,
         "content": {"learning_goal": "Сопоставлять строки и считать значения."}},
        {"stable_key": "ege.inf.python-integer-parity.v1", "title": "Python: чётность, отрицательные значения и деление",
         "retrieval_score": 7, "content": {"learning_goal": "Проверять чётность чисел с операциями % и //."}},
    ]
    monkeypatch.setattr(lesson_intelligence, "retrieve_knowledge", lambda query, limit: candidates[:limit])
    context = _lesson_knowledge_context(parse_transcript(
        "Преподаватель: Проверим чётное число и остаток от деления на 2.\n"
        "Ученик: Для 14 остаток ноль, значит число чётное."
    ))

    assert [item["stable_key"] for item in context["items"]] == ["ege.inf.python-integer-parity.v1"]
    assert context["retrieval_policy"]["method"] == "title_goal_with_lexical_rank.v2"
    assert context["excluded_candidates"][0]["stable_key"] == "ege.inf.graph-table-matching.v1"
    assert context["excluded_candidates"][0]["retrieval_score"] == 50
    assert context["retrieval_policy"]["selected_count"] == 1


def test_prioritized_next_lesson_plan_targets_help_dependent_skill_and_exact_session_time():
    from app.ai_lab.lesson_intelligence import _build_prioritized_lesson_plan, parse_transcript

    segments = parse_transcript(
        "Ученик: Для /27 я самостоятельно получил адрес сети.\n"
        "Ученик: Я не понимаю, какой октет менять для /20.\n"
        "Преподаватель: Сравни размер блока с третьим октетом.\n"
        "Ученик: После подсказки получил адрес сети, но всё ещё не уверен."
    )
    request = {"segments": segments, "planned_session_minutes": 60,
               "knowledge_context": {"items": [{"stable_key": "ege.inf.next-topic.v1",
                                                  "content": {"prerequisites": ["ege.inf.ip20.v1"]}}]}}
    merged = {"topics": [{"topic_id": "ege.inf.ipv4.v1", "title": "IPv4", "source_refs": ["segment-001"]}],
              "observed_difficulties": [
                  {"skill_id": "ege.inf.ip27.v1", "description": "Самостоятельное применение /27 нужно подтвердить переносом.",
                   "source_refs": ["segment-001"], "resolution_source_refs": ["segment-001"],
                   "resolution_status": "independent_application_candidate", "progress_evidence": []},
                  {"skill_id": "ege.inf.ip20.v1", "description": "Неуверенно выбирает октет для /20.",
                   "source_refs": ["segment-002"], "resolution_source_refs": ["segment-003", "segment-004"],
                   "resolution_status": "corrected_after_hint", "progress_evidence": [
                       {"kind": "after_hint_demonstration", "validation_status": "supported_by_transcript",
                        "source_refs": ["segment-003", "segment-004"]},
                       {"kind": "repeated_difficulty", "validation_status": "supported_by_transcript",
                        "source_refs": ["segment-004"]},
                   ]},
              ]}
    plan = _build_prioritized_lesson_plan(request, merged)
    assert plan["plan_method"] == "deterministic_evidence_priority.v3"
    assert plan["priority_items"][0]["skill_id"] == "ege.inf.ip20.v1"
    assert plan["priority_items"][0]["reasons"]["repeated_difficulty_count"] >= 1
    assert plan["priority_items"][0]["reasons"]["helped_demonstration_count"] == 1
    assert plan["decision"] == "propose_change"
    assert plan["total_minutes"] == 60 == sum(stage["minutes"] for stage in plan["stages"])
    assert plan["baseline_plan_available"] is False
    assert plan["assigned_practice_available"] is False
    assert "сравнение «до/после» невозможно" in plan["reason"]
    assert all(stage["source_refs"] and stage["citations"] for stage in plan["stages"])


def test_preregistered_tutor_control_scenarios_are_frozen_and_holdout_is_separate():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_core_pedagogical_v6_preregistered.json"
    digest_file = fixture.with_suffix(".sha256")
    raw = fixture.read_bytes()
    protocol = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest_file.read_text(encoding="utf-8").strip() == digest
    assert protocol["expectations_frozen_before_model_runs"] is True
    assert protocol["expected_results_sent_to_model"] is False
    assert len(protocol["scenarios"]) == 8
    case_ids = [item["case_id"] for item in protocol["scenarios"]]
    assert len(case_ids) == len(set(case_ids))
    assert set(protocol["holdout_case_ids"]) == {
        item["case_id"] for item in protocol["scenarios"] if item["split"] == "holdout"
    }
    assert len([item for item in protocol["scenarios"] if item["split"] == "development"]) == 6


class TruncatedThenValidLessonProvider:
    def __init__(self):
        self.calls = 0

    def complete_structured(self, model, system_prompt, user_payload, schema):
        self.calls += 1
        if "source_index" in user_payload:
            ref = user_payload["source_index"][0]["segment_id"]
            content = {"decision": "insufficient_evidence", "reason": "Сначала уточнить самостоятельность решения.",
                       "stages": [{"title": "Диагностическая проверка изученной темы", "minutes": user_payload["session_minutes"],
                                   "reason": "Проверить только тему из стенограммы.",
                                   "expected_check": "Ученик объясняет шаг без подсказки.", "source_refs": [ref]}],
                       "limitations": ["Исходный план не предоставлен."]}
            content = json.dumps(content, ensure_ascii=False)
            finish_reason = "stop"
        elif self.calls == 1:
            content = '{"summary":"Частичный ответ'
            finish_reason = "length"
        else:
            content = json.dumps({"summary": "Учитель дал подсказку, после которой ученик описал решение.",
                                  "topics": [{"topic_id": "ipv4.subnet-mask", "title": "Адрес сети", "source_refs": ["segment-002"]}],
                                  "content_segments": [], "observed_difficulties": [], "limitations": [],
                                  "learner_events": [{"kind": "after_hint_demonstration", "skill": "адрес сети",
                                                      "summary": "После подсказки ученик описал способ.",
                                                      "source_refs": ["segment-001", "segment-002"]}]}, ensure_ascii=False)
            finish_reason = "stop"
        return SimpleNamespace(content=content, finish_reason=finish_reason, model="Synthetic-Truncation-Test",
                               input_tokens=17, output_tokens=9, prompt_tokens=17, precached_prompt_tokens=0,
                               total_tokens=26, generation_parameters={"temperature": 0.1, "max_tokens": 100},
                               payload_id=f"payload-{self.calls}", payload_sha256=f"{self.calls:064x}")


def test_truncated_chunk_uses_one_compact_recovery_and_preserves_both_attempts(isolated_lesson_app, monkeypatch):
    from app.ai_lab.lesson_intelligence import analyze_lesson

    monkeypatch.setattr("app.ai_lab.lesson_intelligence._lesson_knowledge_context",
                        lambda segments: {"status": "retrieved", "used_as_transcript_evidence": False,
                                         "items": [{"key": "ipv4", "version": 2, "status": "source_checked",
                                                    "content_sha256": "a" * 64}]})
    payload = {"lesson_id": "synthetic-ipv4-reliability", "lesson_version": 2,
               "synthetic_confirmed": True,
               "transcript": "Преподаватель: Попробуй объяснить маску.\nУченик: После подсказки я нашёл адрес сети."}
    provider = TruncatedThenValidLessonProvider()
    with isolated_lesson_app.app_context():
        record = analyze_lesson(payload, actor_user_id=98765, provider=provider)
        assert record.status == "succeeded", record.error_message
        observed = {"status": record.status, "attempts": record.quality_json["generation_attempts"],
                    "raw_response": record.raw_response, "learner_events": record.quality_json["learner_events"],
                    "knowledge": record.quality_json["knowledge_retrieval"],
                    "lesson_synthesis": record.quality_json["lesson_synthesis"],
                    "input_tokens": record.input_tokens, "output_tokens": record.output_tokens}
    assert provider.calls == 2
    attempts = observed["attempts"]
    assert [attempt["finish_reason"] for attempt in attempts] == ["length", "stop"]
    assert attempts[0]["validation_status"] == "invalid"
    assert attempts[1]["validation_status"] == "valid"
    assert "raw_response" in attempts[0] and "Частичный" in attempts[0]["raw_response"]
    assert len(observed["raw_response"].splitlines()) == 2
    event = observed["learner_events"][0]
    assert event["validation_status"] == "supported_by_transcript"
    assert event["citations"][0]["speaker_role"] == "teacher"
    assert observed["knowledge"]["items"][0]["content_sha256"] == "a" * 64
    assert observed["lesson_synthesis"]["total_minutes"] == 60
    assert observed["lesson_synthesis"]["plan_method"] == "deterministic_evidence_priority.v3"
    assert observed["input_tokens"] == 34 and observed["output_tokens"] == 18


def test_resume_uses_saved_input_and_retrieval_without_rehashing_current_knowledge(isolated_lesson_app, monkeypatch):
    from app.ai_lab import lesson_intelligence as lesson_module
    from core.db_models import AiLabExperiment, db

    actor_user_id = 98765
    payload = {"lesson_id": "synthetic-ipv4-resume", "lesson_version": 2, "synthetic_confirmed": True,
               "transcript": "Преподаватель: Попробуй объяснить маску.\nУченик: После подсказки я нашёл адрес сети."}
    knowledge = {"status": "retrieved", "used_as_transcript_evidence": False,
                 "items": [{"stable_key": "ege.inf.ip-prefix-mask.v1", "version": 2,
                            "status": "source_checked", "content_sha256": "b" * 64}]}
    with isolated_lesson_app.app_context():
        request_data, _ = lesson_module.validate_lesson_request(payload)
        request_data["source_ref"] = "synthetic-transcript:" + hashlib.sha256(
            "\n".join(item["text"] for item in request_data["segments"]).encode("utf-8")).hexdigest()[:16]
        request_data["knowledge_context"] = knowledge
        chunks = lesson_module.lesson_analysis_chunks(request_data["segments"], request_data["lesson_id"],
                                                     request_data["lesson_version"], knowledge)
        digest, request_key = lesson_module._request_identity(actor_user_id, request_data)
        record = AiLabExperiment(
            actor_user_id=actor_user_id, request_key=request_key, scenario_id="ai-lesson-intelligence",
            status="invalid_response", provider="gigachat", prompt_snapshot=lesson_module.LESSON_PROMPT,
            scenario_snapshot={"module": "ai_lesson_intelligence", "lesson_id": request_data["lesson_id"],
                               "lesson_version": request_data["lesson_version"]},
            input_snapshot=request_data, expected_snapshot={}, validation_status="pending",
            quality_json={"module": "ai_lesson_intelligence", "input_hash": digest,
                          "prompt_version": lesson_module.LESSON_PROMPT_VERSION,
                          "generation_attempts": [], "chunk_results": [],
                          "chunk_plan": [{"chunk_id": "previous-plan", "index": 1,
                                          "segment_count": len(chunks[0]["target_segment_ids"]),
                                          "input_bytes": chunks[0]["input_bytes"]}]},
        )
        db.session.add(record)
        db.session.commit()
        record_id = record.id

        monkeypatch.setattr(lesson_module, "_lesson_knowledge_context",
                            lambda _segments: (_ for _ in ()).throw(AssertionError("retrieval must not run on resume")))
        monkeypatch.setattr(lesson_module, "claim_retry", lambda _record: True)
        provider = TruncatedThenValidLessonProvider()
        observed_payloads = []
        original_complete = provider.complete_structured

        def capture_payload(model, system_prompt, user_payload, schema):
            observed_payloads.append(user_payload)
            return original_complete(model, system_prompt, user_payload, schema)

        provider.complete_structured = capture_payload
        resumed = lesson_module.analyze_lesson({}, actor_user_id, provider=provider, resume_record_id=record_id)

        assert resumed.id == record_id
        assert resumed.status == "succeeded", resumed.error_message
        assert provider.calls == 2
        assert all(item["knowledge_context"]["status"] == "no_relevant_material"
                   and item["knowledge_context"]["items"] == [] for item in observed_payloads)
        assert resumed.quality_json["superseded_chunk_plans"][0][0]["chunk_id"] == "previous-plan"


@pytest.mark.skipif(not os.getenv("AI_LAB_LESSON_REGRESSION_DB"),
                    reason="Нужен путь к согласованной read-only копии изолированной AI Lab DB")
def test_historical_analysis_36_snapshot_reproduces_markdown_timestamp_regression():
    from app.ai_lab.lesson_intelligence import parse_transcript

    database_path = Path(os.environ["AI_LAB_LESSON_REGRESSION_DB"])
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        snapshot = None
        for table in tables:
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if {"id", "scenario_id", "input_snapshot"}.issubset(columns):
                row = connection.execute(
                    f'SELECT input_snapshot FROM "{table}" WHERE id = ? AND scenario_id = ?',
                    (36, "ai-lesson-intelligence")).fetchone()
                if row:
                    snapshot = json.loads(row[0])
                    break
    finally:
        connection.close()

    assert snapshot and snapshot["lesson_id"] == "synthetic-ipv4-masks-01"
    rows = OrderedDict()
    for segment in snapshot["segments"]:
        line = segment.get("source_line")
        entry = rows.setdefault(line, {"speaker": segment.get("speaker"), "text": []})
        entry["text"].append(segment.get("text", ""))
    reconstructed = "\n".join(f"{item['speaker']}:{''.join(item['text'])}" for item in rows.values())
    normalized = parse_transcript(reconstructed)
    assert any(item["speaker_role"] == "student" and item["timestamp"] for item in normalized)
    assert all(item["speaker_role"] != "unknown" for item in normalized if item["timestamp"])


def test_duplicate_topic_ids_are_preserved_as_a_title_conflict_not_a_failed_chunk():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript
    from app.ai_lab.learning_evidence import validate_lesson_intelligence_output

    segments = parse_transcript("Ученик: Я не понимаю, как определить границу.")
    request = {"lesson_id": "synthetic-topic-conflict", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": segments}
    validated = _validate_ai_result({
        "summary": "Два названия для одного ID.",
        "topics": [
            {"topic_id": "python.boundary_cases", "title": "Границы диапазона", "source_refs": ["segment-001"]},
            {"topic_id": "python.boundary_cases", "title": "Проверка конца диапазона", "source_refs": ["segment-001"]},
        ],
        "content_segments": [{"segment_id": "python.boundary_cases", "summary": "Фрагмент", "source_refs": ["segment-001"]}],
        "observed_difficulties": [], "limitations": [], "learner_events": [],
    }, request)
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])
    normalized = validate_lesson_intelligence_output(merged)

    assert normalized["topics"][0]["topic_id"] == "python.boundary_cases"
    assert normalized["topics"][0]["title_conflict"] is True
    assert normalized["topics"][0]["title_variants"] == ["Границы диапазона", "Проверка конца диапазона"]


def test_same_evidence_with_similar_different_skill_labels_is_flagged_without_merging():
    from app.ai_lab.lesson_intelligence import _possible_skill_identity_conflicts

    candidates = [
        {"skill_id": "python.functions", "skill_facet_id": "python.parameters",
         "description": "Путает параметр функции с аргументом вызова", "source_refs": ["segment-010"]},
        {"skill_id": "python.calls", "skill_facet_id": "python.arguments",
         "description": "Путает аргумент вызова с параметром функции", "source_refs": ["segment-010"]},
    ]

    conflicts = _possible_skill_identity_conflicts(candidates)

    assert len(conflicts) == 1
    assert conflicts[0]["status"] == "possible_identity_conflict_manual_review_required"
    assert conflicts[0]["left"]["skill_facet_id"] != conflicts[0]["right"]["skill_facet_id"]


def test_hourly_token_normalization_requires_long_timestamped_transcript():
    from app.ai_lab.lesson_intelligence import _transcript_timed_span_seconds

    short = [{"timestamp": "00:00:00"}, {"timestamp": "00:12:00"}]
    full = [{"timestamp": "00:03:10"}, {"timestamp": "00:58:20"}]

    assert _transcript_timed_span_seconds(short) is None
    assert _transcript_timed_span_seconds(full) == 3310


def test_v7_preregistration_reuses_only_frozen_development_scenarios():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_core_pedagogical_v7_development_preregistered.json"
    raw = fixture.read_bytes()
    protocol = json.loads(raw)
    assert fixture.with_suffix(".sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(raw).hexdigest()
    source = fixture.with_name(protocol["source_fixture"]["path"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == protocol["source_fixture"]["sha256"]
    assert protocol["implementation_target"]["lesson_prompt_version"] == "lesson-intelligence.v7"
    assert len(protocol["development_case_ids"]) == 6
    assert protocol["holdout_case_ids"] == ["case-07-similar-skill-labels", "case-08-contradictory-evidence"]
    assert protocol["holdout_evaluated"] is False


def test_missing_topic_id_is_replaced_with_reviewable_deterministic_identity():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript
    from app.ai_lab.learning_evidence import validate_lesson_intelligence_output

    segments = parse_transcript("Ученик: Для /20 я не понимаю, какой октет меняется.")
    request = {"lesson_id": "synthetic-missing-topic-id", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": segments}
    validated = _validate_ai_result({
        "summary": "Тема названа, но ID пропущен.",
        "topics": [{"topic_id": "", "title": "Выбор октета для /20", "source_refs": ["segment-001"]}],
        "content_segments": [], "observed_difficulties": [], "limitations": [], "learner_events": [],
    }, request)
    output = validate_lesson_intelligence_output(
        _merge_lesson_chunk_results(request, [{"result": validated}]))

    topic = output["topics"][0]
    assert topic["topic_id"].startswith("generated.")
    assert topic["id_resolution_status"] == "generated_from_title_and_evidence_requires_manual_review"
    assert topic["source_refs"] == ["segment-001"]


def test_nearby_teacher_turn_is_added_as_context_for_student_progress_after_hint():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю, почему сумма не меняется в цикле.\n"
        "Преподаватель: Проверь, где находится присваивание total = total + value.\n"
        "Ученик: После подсказки перенёс присваивание внутрь цикла, теперь сумма растёт."
    )
    request = {"lesson_id": "synthetic-contextual-hint", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript}
    validated = _validate_ai_result({
        "summary": "Есть результат после подсказки.", "topics": [], "content_segments": [],
        "observed_difficulties": [{"skill_id": "python.iteration", "skill_facet_id": "iteration.accumulator.scope",
                                    "description": "Затруднение с местом обновления суммы.", "source_refs": ["segment-001"]}],
        "limitations": [], "learner_events": [{"kind": "partial_progress", "skill_id": "python.iteration",
            "skill_facet_id": "iteration.accumulator.scope", "skill": "обновление суммы в цикле",
            "summary": "Ученик перенёс обновление внутрь цикла после подсказки.", "source_refs": ["segment-003"]}],
    }, request)
    event = validated["learner_events"][0]
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])

    assert event["validation_status"] == "supported_by_transcript"
    assert event["source_refs"] == ["segment-002", "segment-003"]
    difficulty = merged["observed_difficulties"][0]
    assert difficulty["resolution_status"] == "partial_progress"
    assert difficulty["durability_status"] == "not_established"


def test_self_correction_is_a_distinct_supported_event_and_not_mastery():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, _validate_ai_result, parse_transcript

    transcript = parse_transcript("Ученик: Для чётного n % 2 == 1… нет, оговорился: нужно n % 2 == 0.")
    request = {"lesson_id": "synthetic-self-correction", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript}
    validated = _validate_ai_result({"summary": "Ученик сам поправился.", "topics": [], "content_segments": [],
        "observed_difficulties": [], "limitations": [], "learner_events": [{
            "kind": "self_correction", "skill_id": "python.boundary_cases", "skill_facet_id": "integer.parity.modulo",
            "skill": "проверка чётности", "summary": "Ученик сам исправил оговорку.", "source_refs": ["segment-001"]}]}, request)
    merged = _merge_lesson_chunk_results(request, [{"result": validated}])

    assert validated["learner_events"][0]["validation_status"] == "supported_by_transcript"
    assert merged["learner_events"][0]["kind"] == "self_correction"
    assert merged["observed_difficulties"] == []


def test_literal_self_correction_is_recovered_when_model_omits_the_event():
    from app.ai_lab.lesson_intelligence import _validate_ai_result, parse_transcript

    transcript = parse_transcript("Ученик: От 32 до 63. Подожди... Нет, 77 больше 63, значит от 64 до 95.")
    request = {"lesson_id": "synthetic-recovered-self-correction", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript}
    validated = _validate_ai_result({"summary": "Реплика содержит самоисправление.", "topics": [],
        "content_segments": [], "observed_difficulties": [], "limitations": [], "learner_events": []}, request)

    event = validated["learner_events"][0]
    assert event["kind"] == "self_correction"
    assert event["validation_status"] == "supported_by_transcript"
    assert event["skill_id"] is None
    assert event["event_origin"] == "deterministic_text_rule.v1"
    assert event["semantic_support_status"] == "manual_review_required"


def test_explicit_after_hint_text_cannot_remain_self_correction_or_mastery():
    from app.ai_lab.lesson_intelligence import _validate_ai_result, parse_transcript

    transcript = parse_transcript(
        "Ученик: Я не понимаю, где менять размер блока.\n"
        "Преподаватель: Сначала найди октет, в котором маска содержит неполный набор единиц.\n"
        "Ученик: После подсказки применил блок 16 к третьему октету."
    )
    request = {"lesson_id": "synthetic-after-hint-relabel", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript,
               "allowed_skill_ids": ["ege.inf.ip-prefix-mask.v1"]}
    validated = _validate_ai_result({"summary": "Ответ следует после подсказки.", "topics": [],
        "content_segments": [], "observed_difficulties": [{"skill_id": "ege.inf.ip-prefix-mask.v1",
        "skill_facet_id": "ipv4.prefix.third_octet_boundary", "description": "Затруднение с выбором октета.",
        "source_refs": ["segment-001"]}], "limitations": [], "learner_events": [{
        "kind": "self_correction", "skill_id": "ege.inf.ip-prefix-mask.v1",
        "skill_facet_id": "ipv4.prefix.third_octet_boundary", "skill": "выбор октета",
        "summary": "Ученик исправил ответ.", "source_refs": ["segment-003"]}]}, request)

    event = validated["learner_events"][0]
    assert event["kind"] == "partial_progress"
    assert event["validation_status"] == "supported_by_transcript"
    assert event["source_refs"] == ["segment-002", "segment-003"]
    assert "правильность ответа" in event["summary"]


def test_unmarked_self_correction_claim_is_demoted_to_unverified_other_event():
    from app.ai_lab.lesson_intelligence import _validate_ai_result, parse_transcript

    transcript = parse_transcript("Ученик: Кажется, я понял, как работают маски.")
    request = {"lesson_id": "synthetic-verbal-claim", "lesson_version": 1,
               "source_ref": "synthetic:test", "segments": transcript,
               "allowed_skill_ids": ["ege.inf.ip-prefix-mask.v1"]}
    validated = _validate_ai_result({"summary": "Есть заявление о понимании.", "topics": [],
        "content_segments": [], "observed_difficulties": [], "limitations": [], "learner_events": [{
        "kind": "self_correction", "skill_id": "ege.inf.ip-prefix-mask.v1",
        "skill_facet_id": "ipv4.mask.basics", "skill": "маска подсети",
        "summary": "Ученик исправил понимание.", "source_refs": ["segment-001"]}]}, request)

    event = validated["learner_events"][0]
    assert event["kind"] == "other"
    assert event["validation_status"] == "unverified"
    assert "маркер" in event["summary"]


def test_v8_preregistration_freezes_the_v6_development_cases_and_keeps_holdout_closed():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_core_pedagogical_v8_development_preregistered.json"
    raw = fixture.read_bytes()
    protocol = json.loads(raw)
    assert fixture.with_suffix(".sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(raw).hexdigest()
    source = fixture.with_name(protocol["source_fixture"]["path"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == protocol["source_fixture"]["sha256"]
    assert protocol["implementation_target"]["lesson_prompt_version"] == "lesson-intelligence.v8"
    assert len(protocol["development_case_ids"]) == 6
    assert protocol["holdout_case_ids"] == ["case-07-similar-skill-labels", "case-08-contradictory-evidence"]
    assert protocol["holdout_evaluated"] is False


def test_v9_preregistration_freezes_validator_refinement_without_opening_holdout():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tutor_core_pedagogical_v9_development_preregistered.json"
    raw = fixture.read_bytes()
    protocol = json.loads(raw)
    assert fixture.with_suffix(".sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(raw).hexdigest()
    source = fixture.with_name(protocol["source_fixture"]["path"])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == protocol["source_fixture"]["sha256"]
    assert protocol["implementation_target"]["lesson_prompt_version"] == "lesson-intelligence.v9"
    assert protocol["implementation_target"]["event_validation"] == "lesson-event-validation.v3"
    assert protocol["implementation_target"]["plan_method"] == "deterministic_evidence_priority.v2"
    assert len(protocol["development_case_ids"]) == 6
    assert protocol["holdout_evaluated"] is False
    assert protocol["model_run_completed"] is False
