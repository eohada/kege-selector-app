from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai_lab.analytics import build_analytics_snapshot
from app.ai_lab.course import (
    CourseAnalysisError,
    analyze_course,
    course_analysis_chunks,
    course_response_schema,
    inspect_course_structure,
    rollback_course_proposal,
    review_course_proposal,
    synthetic_course_samples,
    validate_course_input,
)
from app.ai_lab.lesson_intelligence import (
    LessonAnalysisError,
    analyze_lesson,
    lesson_response_schema,
    parse_transcript,
    review_lesson_observation,
    stored_lesson_evidence,
    synthetic_transcript_samples,
)
from app.ai_lab.practice import recommend_practice
from app.ai_lab.scenarios import list_python_assignments


@pytest.fixture()
def isolated_app():
    from app import create_app, db

    test_app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with test_app.app_context():
        db.create_all()
    try:
        yield test_app
    finally:
        with test_app.app_context():
            db.session.remove()
            db.drop_all()


class FakeStructuredProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def complete_structured(self, model, system_prompt, user_payload, schema):
        self.calls += 1
        if "source_index" in user_payload:
            ref = user_payload["source_index"][0]["segment_id"]
            minutes = user_payload["session_minutes"]
            return SimpleNamespace(
                content=json.dumps({"decision": "insufficient_evidence", "reason": "Синтетический проект требует ручной проверки.",
                                    "stages": [{"title": "Диагностическая проверка изучавшейся темы", "minutes": minutes,
                                                "reason": "Проверить только материал, встречавшийся в стенограмме.",
                                                "expected_check": "Ученик самостоятельно объясняет решение.", "source_refs": [ref]}],
                                    "limitations": []}, ensure_ascii=False),
                model="GigaChat-3-Pro-test-double", input_tokens=42, output_tokens=21,
                generation_parameters={"temperature": 0.1, "max_tokens": 3200},
                payload_id=f"payload-{self.calls}", payload_sha256="a" * 64,
            )
        output = self.outputs.pop(0) if self.outputs else getattr(self, "last_output", {})
        self.last_output = output
        return SimpleNamespace(
            content=json.dumps(output, ensure_ascii=False),
            model="GigaChat-3-Pro-test-double",
            input_tokens=42,
            output_tokens=21,
            generation_parameters={"temperature": 0.1, "max_tokens": 3200},
            payload_id=f"payload-{self.calls}",
            payload_sha256="a" * 64,
        )


class FailOnceStructuredProvider(FakeStructuredProvider):
    def __init__(self, outputs):
        super().__init__(outputs)
        self.failed_once = False

    def complete_structured(self, model, system_prompt, user_payload, schema):
        if not self.failed_once:
            self.failed_once = True
            self.calls += 1
            from app.ai_lab.provider import ProviderError
            raise ProviderError("connection_failed", "Синтетическая временная ошибка сети.")
        return super().complete_structured(model, system_prompt, user_payload, schema)


class CourseFragmentProvider:
    def __init__(self, fail_on_call=None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def complete_structured(self, model, system_prompt, user_payload, schema):
        self.calls += 1
        if self.calls == self.fail_on_call:
            from app.ai_lab.provider import ProviderError
            raise ProviderError("connection_failed", "Synthetic temporary network failure.")
        course = user_payload["course"]
        material = course["materials"][0] if course["materials"] else None
        fragment = material["source_fragments"][0] if material and material.get("source_fragments") else None
        proposals = ([{
            "proposal_id": f"proposal-{fragment['ordinal']}",
            "material_id": material["material_id"],
            "observation": f"Проверьте фрагмент {fragment['ordinal']}.",
            "proposed_text": "Уточнить синтетическое объяснение.",
            "source_refs": [fragment["source_ref"]],
        }] if fragment else [])
        return SimpleNamespace(
            content=json.dumps({"summary": f"Часть {self.calls} проверена.", "material_proposals": proposals}, ensure_ascii=False),
            model="LocalChunkTest", input_tokens=10, output_tokens=5,
            generation_parameters={"temperature": 0.1, "max_tokens": 3200},
            payload_id=f"fragment-payload-{self.calls}", payload_sha256=f"{self.calls:064x}",
        )


class LessonChunkProvider:
    def __init__(self, fail_on_call=None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def complete_structured(self, model, system_prompt, user_payload, schema):
        self.calls += 1
        if self.calls == self.fail_on_call:
            from app.ai_lab.provider import ProviderError
            raise ProviderError("connection_failed", "Synthetic temporary network failure.")
        if "source_index" in user_payload:
            ref = user_payload["source_index"][0]["segment_id"]
            minutes = user_payload["session_minutes"]
            return SimpleNamespace(
                content=json.dumps({"decision": "insufficient_evidence", "reason": "Синтетическая рекомендация.",
                                    "stages": [{"title": "Проверка изучавшейся темы", "minutes": minutes,
                                                "reason": "Повторить доступный материал.", "expected_check": "Самостоятельное объяснение.",
                                                "source_refs": [ref]}], "limitations": []}, ensure_ascii=False),
                model="LocalLessonChunkTest", input_tokens=10, output_tokens=5,
                generation_parameters={"temperature": 0.1, "max_tokens": 3200},
                payload_id=f"lesson-synthesis-{self.calls}", payload_sha256=f"{self.calls:064x}",
            )
        ref = user_payload["target_segment_ids"][0]
        return SimpleNamespace(
            content=json.dumps({"summary": f"Обработана часть {self.calls}.",
                                "topics": [{"topic_id": "python.iteration", "title": "Цикл", "source_refs": [ref]}],
                                "content_segments": [], "observed_difficulties": [], "limitations": []}, ensure_ascii=False),
            model="LocalLessonChunkTest", input_tokens=10, output_tokens=5,
            generation_parameters={"temperature": 0.1, "max_tokens": 3200},
            payload_id=f"lesson-chunk-payload-{self.calls}", payload_sha256=f"{self.calls:064x}",
        )


def _course_proposal(material_id="material.conditions", ref=None):
    return {
        "summary": "В условии полезно явно разобрать правую границу.",
        "material_proposals": [{
            "proposal_id": "proposal-boundary-note",
            "material_id": material_id,
            "observation": "В материале нет примера проверки правой границы.",
            "proposed_text": "Добавить отдельный пример для включённой правой границы.",
            "source_refs": [ref or material_id],
        }],
    }


def _lesson_output(with_difficulty=True, source_ref="segment-002"):
    return {
        "summary": "Обсуждалась обработка граничного значения в условии.",
        "topics": [{"topic_id": "python.conditions", "title": "Условия", "source_refs": ["segment-001", "segment-002"]}],
        "content_segments": [{"segment_id": "summary-1", "summary": "Проверка ветви else", "source_refs": [source_ref]}],
        "observed_difficulties": ([{
            "skill_id": "python.boundary_cases",
            "description": "Ученик прямо сообщил, что не понимает, какую ветвь выбрать при ложном условии.",
            "source_refs": [source_ref],
        }] if with_difficulty else []),
        "limitations": [],
    }


def test_course_structure_only_flags_explicit_relations_and_missing_material():
    samples = synthetic_course_samples()
    findings = inspect_course_structure(samples[1])
    assert {item["code"] for item in findings} >= {
        "prerequisite_after_topic", "topic_without_material", "assignment_skill_mismatch",
    }
    alternative_findings = inspect_course_structure(samples[2])
    assert not any(item["code"] == "prerequisite_after_topic" for item in alternative_findings)


def test_sprint5_frozen_synthetic_evaluation_cases_have_expert_oracles():
    from app.ai_lab.course import validate_course_input

    fixture_path = Path(__file__).parents[1] / "fixtures" / "ai_lab_sprint5_evaluation_cases.json"
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert dataset["dataset_id"] == "boostudy-ai-lab-sprint5-synthetic-v1"
    assert dataset["synthetic_only"] is True and dataset["real_student_data"] is False
    assert dataset["frozen_before_live_model_runs"] is True
    development = dataset["development"]
    holdout = dataset["holdout"]
    assert len(development) >= 6 and len(holdout) >= 4
    ids = [item["case_id"] for item in development + holdout]
    assert len(ids) == len(set(ids))

    for case in development + holdout:
        if case["module"] == "ai_course":
            course = validate_course_input(case["input"])
            actual = {item["code"] for item in inspect_course_structure(course)}
            expected = set(case["expert_expectation"].get("deterministic_findings", []))
            assert actual == expected, case["case_id"]
        else:
            segments = parse_transcript(case["input"]["transcript"])
            assert segments, case["case_id"]
            assert case["input"]["lesson_id"].startswith("synthetic-")


def test_course_source_fragment_ids_are_stable_versioned_and_bound_to_material():
    from app.ai_lab.course import _validate_model_output, validate_course_input

    sample = copy.deepcopy(synthetic_course_samples()[0])
    prepared = validate_course_input(sample)
    material = prepared["materials"][0]
    fragment = material["source_fragments"][0]
    same = validate_course_input(copy.deepcopy(sample))["materials"][0]["source_fragments"][0]
    changed_version = copy.deepcopy(sample)
    changed_version["course_version"] += 1
    next_fragment = validate_course_input(changed_version)["materials"][0]["source_fragments"][0]
    assert same["source_ref"] == fragment["source_ref"]
    assert next_fragment["source_ref"] != fragment["source_ref"]

    valid = _course_proposal(material_id=material["material_id"], ref=fragment["source_ref"])
    normalized = _validate_model_output(valid, prepared)
    assert normalized["material_proposals"][0]["source_locations"] == [fragment]

    wrong_material = copy.deepcopy(valid)
    wrong_material["material_proposals"][0]["material_id"] = prepared["materials"][1]["material_id"]
    with pytest.raises(CourseAnalysisError, match="другого материала"):
        _validate_model_output(wrong_material, prepared)


def test_long_course_chunks_resume_after_partial_failure_without_repeating_completed_chunk(isolated_app):
    with isolated_app.app_context():
        course = copy.deepcopy(synthetic_course_samples()[0])
        course["course_id"] = "synthetic-long-course"
        course["materials"] = [{"material_id": "material.long", "title": "Длинный синтетический материал",
                                "topic_id": course["topics"][0]["topic_id"],
                                "content": ("Абзац о проверяемом синтетическом понятии.\n\n" * 1_100)}]
        course["learning_goals"] = []
        course["assignments"] = []
        provider = CourseFragmentProvider(fail_on_call=2)

        partial = analyze_course(course, None, provider)
        assert partial.status == "failed"
        completed_before_retry = list(partial.quality_json["chunk_results"])
        assert len(completed_before_retry) == 1
        completed_chunk_id = completed_before_retry[0]["chunk_id"]

        recovered = analyze_course(course, None, provider)
        assert recovered.id == partial.id
        assert recovered.status == "succeeded"
        assert provider.calls == len(recovered.quality_json["chunk_plan"]) + 1
        assert len(recovered.quality_json["chunk_results"]) == len(recovered.quality_json["chunk_plan"])
        assert recovered.quality_json["chunk_results"][0]["chunk_id"] == completed_chunk_id
        assert recovered.input_tokens == 10 * len(recovered.quality_json["chunk_plan"])
        assert recovered.output_tokens == 5 * len(recovered.quality_json["chunk_plan"])


def test_course_analysis_is_idempotent_versioned_and_review_does_not_apply_changes(isolated_app):
    from core.db_models import AiLabExperiment, db

    with isolated_app.app_context():
        admin_id = None
        course = copy.deepcopy(synthetic_course_samples()[0])
        provider = FakeStructuredProvider([_course_proposal()])
        record = analyze_course(course, admin_id, provider)
        assert record.status == "succeeded"
        assert record.result_json["material_proposals"][0]["status"] == "draft"
        assert provider.calls == 1

        reused = analyze_course(copy.deepcopy(course), admin_id, provider)
        assert reused.id == record.id
        assert provider.calls == 1

        review_course_proposal(record, "proposal-boundary-note", "accepted", admin_id, "Оставить черновик")
        db.session.expire_all()
        stored = db.session.get(AiLabExperiment, record.id)
        assert [item["content"] for item in stored.input_snapshot["materials"]] == [item["content"] for item in course["materials"]]
        assert stored.quality_json["proposal_reviews"][-1]["decision"] == "accepted"
        assert stored.result_json["material_proposals"][0]["proposed_text"].startswith("Добавить")

        changed = copy.deepcopy(course)
        changed["materials"][1]["content"] += " Дополнительный синтетический текст."
        with pytest.raises(CourseAnalysisError, match="course_version") as error:
            analyze_course(changed, admin_id, provider)
        assert error.value.status_code == 409


def test_course_rejects_unknown_model_source_refs_without_marking_success(isolated_app):
    with isolated_app.app_context():
        provider = FakeStructuredProvider([_course_proposal(ref="real-student-material")])
        record = analyze_course(synthetic_course_samples()[0], None, provider)
        assert record.status == "invalid_response", record.error_message
        assert "ссылаться на фактические источники" in record.error_message
        assert record.input_tokens == 42
        assert record.output_tokens == 21
        assert json.loads(record.raw_response)["material_proposals"][0]["source_refs"] == ["real-student-material"]
        attempt = record.quality_json["generation_attempts"][0]
        assert attempt["validation_status"] == "invalid"
        assert attempt["validation_error"] == record.error_message


def test_course_response_schema_limits_material_and_source_ids_to_chunk():
    course = validate_course_input(synthetic_course_samples()[1])
    chunk = course_analysis_chunks(course)[0]
    schema = course_response_schema(chunk)
    proposal = schema["properties"]["material_proposals"]["items"]["properties"]
    expected_materials = sorted(material["material_id"] for material in chunk["materials"])
    expected_refs = sorted({fragment["source_ref"] for material in chunk["materials"]
                            for fragment in material["source_fragments"]})
    assert proposal["material_id"]["enum"] == expected_materials
    assert proposal["source_refs"]["minItems"] == 1
    assert proposal["source_refs"]["items"]["enum"] == expected_refs


def test_lesson_preserves_source_metadata_and_requires_synthetic_attestation():
    segments = parse_transcript("[00:01:02] Преподаватель: Проверим условие.\nУченик: Я не понимаю ветку else.")
    assert segments[0]["timestamp"] == "00:01:02"
    assert segments[0]["speaker"] == "Преподаватель"
    assert segments[1]["timestamp"] is None
    assert segments[1]["speaker"] == "Ученик"
    with pytest.raises(LessonAnalysisError, match="Подтвердите, что текст синтетический"):
        analyze_lesson({"transcript": "synthetic text"}, None, FakeStructuredProvider([]))


def test_lesson_analysis_requires_source_refs_and_never_auto_confirms(isolated_app):
    from core.db_models import db

    with isolated_app.app_context():
        payload = {"lesson_id": "synthetic-test-lesson", "lesson_version": 1,
                   "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                   "transcript": "Преподаватель: Проверим условие.\nУченик: Я не понимаю ветку else."}
        provider = FakeStructuredProvider([_lesson_output()])
        record = analyze_lesson(payload, None, provider)
        assert record.status == "succeeded"
        observation = record.result_json["observed_difficulties"][0]
        assert observation["evidence_status"] == "ai_inference"
        assert observation["review_status"] == "pending"
        assert stored_lesson_evidence() == []
        assert analyze_lesson(payload, None, provider).id == record.id
        assert provider.calls == 1

        review_lesson_observation(record, "difficulty-1", "confirmed", None)
        db.session.expire_all()
        event = stored_lesson_evidence()[0]
        assert event["source_module"] == "ai_lesson_intelligence"
        assert event["evidence_status"] == "expert_confirmed"
        assert event["outcome"] == {"score": None, "maximum": None, "status": "qualitative_observation"}
        assert event["criteria"][0]["earned"] is None
        analytics = build_analytics_snapshot([event], "synthetic-lesson-learner")
        assert analytics["confirmed_lesson_observations"] == 1
        assert analytics["skills"][0]["status"] == "insufficient_data"
        assert analytics["skills"][0]["qualitative_observations"] == 1


def test_lesson_analysis_links_allowlisted_demo_lesson_to_platform_student_analytics(isolated_app):
    from app.ai_lab.lesson_adapter import list_synthetic_lesson_sources
    from app.ai_lab.lesson_intelligence import validate_lesson_request
    from core.db_models import Lesson, Student, User, db

    with isolated_app.app_context():
        isolated_app.config.update({
            "AI_LAB_SYNTHETIC_LESSON_IDS": "1",
            "AI_LAB_SYNTHETIC_LESSON_STUDENT_IDS": "1",
        })
        user = User(username="demo_student_linked", role="student", is_active=True)
        db.session.add(user)
        db.session.flush()
        student = Student(user_id=user.id, name="demo_student_linked")
        db.session.add(student)
        db.session.flush()
        lesson = Lesson(student_id=student.student_id, topic="Synthetic lesson linking test", status="completed")
        db.session.add(lesson)
        db.session.flush()

        options = list_synthetic_lesson_sources()
        assert [item["lesson_id"] for item in options] == [lesson.lesson_id]
        payload = {
            "platform_lesson_id": str(lesson.lesson_id),
            "lesson_version": 1,
            "transcript": "Преподаватель: Проверим условие.\nУченик: Я не понимаю ветку else.",
            "synthetic_confirmed": True,
        }
        normalized, _ = validate_lesson_request(payload)
        assert normalized["lesson_id"] == f"boostudy-lesson:{lesson.lesson_id}"
        assert normalized["subject_id"] == f"platform-student:{user.id}"
        assert normalized["source_identity"]["source_table"] == "Lessons"

        record = analyze_lesson(payload, user.id, FakeStructuredProvider([_lesson_output()]))
        assert record.status == "succeeded"
        assert record.scenario_snapshot["source_identity"]["source_record_id"] == str(lesson.lesson_id)
        assert stored_lesson_evidence(actor_user_id=user.id) == []
        review_lesson_observation(record, "difficulty-1", "confirmed", user.id)
        event = stored_lesson_evidence(actor_user_id=user.id)[0]
        assert event["subject_id"] == f"platform-student:{user.id}"
        assert event["assignment"]["id"] == f"boostudy-lesson:{lesson.lesson_id}"
        assert build_analytics_snapshot([event], event["subject_id"])["confirmed_lesson_observations"] == 1

        with pytest.raises(LessonAnalysisError, match="разрешённых синтетических связок"):
            validate_lesson_request({**payload, "platform_lesson_id": "999"})


def test_lesson_analysis_rejects_unknown_segment_refs(isolated_app):
    with isolated_app.app_context():
        payload = {"lesson_id": "synthetic-ref-check", "lesson_version": 1,
                   "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                   "transcript": "Ученик: Я понял пример."}
        invalid = _lesson_output(with_difficulty=False)
        invalid["topics"][0]["source_refs"] = ["segment-999"]
        record = analyze_lesson(payload, None, FakeStructuredProvider([invalid]))
        assert record.status == "invalid_response"
        assert "отсутствующий фрагмент" in record.error_message
        assert record.input_tokens == 84
        assert record.output_tokens == 42
        attempts = record.quality_json["generation_attempts"]
        assert len(attempts) == 2
        assert attempts[0]["validation_status"] == "invalid"
        assert attempts[0]["validation_error"]
        assert attempts[1]["validation_status"] == "invalid"


def test_lesson_response_schema_limits_evidence_to_chunk_segments():
    segments = parse_transcript("Ученик: Я не понимаю условие.")
    chunk = {"segments": segments}
    refs = lesson_response_schema(chunk)["properties"]["topics"]["items"]["properties"]["source_refs"]
    assert refs["items"]["enum"] == [segments[0]["segment_id"]]
    assert refs["minItems"] == 1


def test_long_lesson_chunks_resume_after_partial_failure_without_repeating_completed_chunk(isolated_app, monkeypatch):
    from app.ai_lab.lesson_intelligence import lesson_analysis_chunks

    monkeypatch.setenv("AI_LAB_LESSON_CHUNK_BYTES", "32000")
    monkeypatch.setenv("AI_LAB_LESSON_MAX_CHUNKS", "16")
    with isolated_app.app_context():
        transcript = "\n".join(
            f"Преподаватель: Разберём пункт {index}. " + ("Повторяем синтетическое объяснение границ и циклов. " * 12)
            for index in range(36)
        )
        payload = {"lesson_id": "synthetic-long-lesson", "lesson_version": 1,
                   "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                   "transcript": transcript}
        planned = lesson_analysis_chunks(parse_transcript(transcript), payload["lesson_id"], payload["lesson_version"])
        assert 1 < len(planned) <= 16
        provider = LessonChunkProvider(fail_on_call=2)
        failed = analyze_lesson(payload, None, provider)
        assert failed.status == "failed"
        assert failed.quality_json["chunk_progress"] == {"completed": 1, "total": len(planned)}
        assert failed.input_tokens == 10

        retried = analyze_lesson(payload, None, provider)
        assert retried.id == failed.id
        assert retried.status == "succeeded"
        assert provider.calls == len(planned) + 1
        assert retried.input_tokens == len(planned) * 10
        assert retried.output_tokens == len(planned) * 5
        assert retried.result_json["completed_chunks"] == len(planned)
        assert retried.result_json["total_chunks"] == len(planned)
        assert len(retried.quality_json["generation_parameters_by_chunk"]) == len(planned)


def test_resolved_lesson_observation_is_qualitative_and_never_a_current_difficulty(isolated_app):
    from app.ai_lab.lesson_intelligence import review_lesson_observations

    with isolated_app.app_context():
        payload = {"lesson_id": "synthetic-resolved-lesson", "lesson_version": 1,
                   "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                   "transcript": "Преподаватель: Проверим правую границу.\n"
                                 "Ученик: Я не понимаю, почему нужен n плюс один.\n"
                                 "Преподаватель: Правая граница range не включается.\n"
                                 "Ученик: Теперь понятно, проверка проходит."}
        output = _lesson_output(source_ref="segment-002")
        output["observed_difficulties"][0]["source_refs"] = ["segment-002", "segment-004"]
        output["observed_difficulties"][0]["skill_facet_id"] = "python.range.stop_boundary"
        output["learner_events"] = [{"kind": "resolved_difficulty",
                                     "skill_id": output["observed_difficulties"][0]["skill_id"],
                                     "skill_facet_id": "python.range.stop_boundary",
                                     "skill": "правая граница диапазона",
                                     "summary": "Ученик сообщил, что понял объяснение.",
                                     "source_refs": ["segment-004"]}]
        record = analyze_lesson(payload, None, FakeStructuredProvider([output]))
        assert record.status == "succeeded"
        observation = record.result_json["observed_difficulties"][0]
        assert observation["review_status"] == "pending"
        assert observation["resolution_status"] == "verbal_claim_only"
        assert observation["resolution_source_refs"] == ["segment-004"]
        review_lesson_observations(record, [observation["observation_id"]], "resolved", None)
        event = stored_lesson_evidence()[0]
        assert event["outcome"] == {"score": None, "maximum": None, "status": "qualitative_resolution"}
        assert event["criteria"][0]["status"] == "insufficient_data"
        assert event["criteria"][0]["source_refs"] == ["segment-002", "segment-004"]


def test_confirmed_lesson_evidence_uses_bounded_pages_and_keeps_history_beyond_ui_limit(isolated_app):
    from app.ai_lab.lesson_intelligence import _LESSON_SCENARIO
    from core.db_models import AiLabExperiment, db

    with isolated_app.app_context():
        records = []
        for index in range(1_005):
            records.append(AiLabExperiment(
                actor_user_id=None,
                request_key=f"lesson-evidence-scale-{index:04d}",
                scenario_id=_LESSON_SCENARIO,
                status="succeeded",
                provider="test",
                prompt_snapshot="synthetic test",
                scenario_snapshot={"lesson_id": f"synthetic-lesson-{index}", "lesson_version": 1,
                                   "subject_id": "synthetic-lesson-learner"},
                input_snapshot={"segments": []},
                expected_snapshot={},
                result_json={"topics": [], "observed_difficulties": [{
                    "observation_id": "difficulty-1", "skill_id": "python.iteration",
                    "description": "Подтверждённый синтетический факт.", "source_ref": "segment-1",
                }]},
                validation_status="valid",
                quality_json={"observation_reviews": [{"observation_id": "difficulty-1", "decision": "confirmed",
                                                       "reviewed_at": "2026-10-20T00:00:00+00:00"}]},
            ))
        db.session.add_all(records)
        db.session.commit()

        evidence = stored_lesson_evidence(batch_size=37)

    assert len(evidence) == 1_005
    assert len({event["event_id"] for event in evidence}) == 1_005
    assert evidence[0]["source_module"] == "ai_lesson_intelligence"
    assert evidence[-1]["source_module"] == "ai_lesson_intelligence"


def test_failed_course_and_lesson_operations_allow_one_explicit_retry(isolated_app):
    with isolated_app.app_context():
        course = copy.deepcopy(synthetic_course_samples()[0])
        course_provider = FailOnceStructuredProvider([_course_proposal()])
        failed_course = analyze_course(course, None, course_provider)
        assert failed_course.status == "failed"
        assert failed_course.quality_json["operation"]["retryable"] is True

        retried_course = analyze_course(course, None, course_provider)
        assert retried_course.id == failed_course.id
        assert retried_course.status == "succeeded"
        assert course_provider.calls == 2
        assert analyze_course(course, None, course_provider).id == failed_course.id
        assert course_provider.calls == 2

        lesson = {"lesson_id": "synthetic-explicit-retry", "lesson_version": 1,
                  "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                  "transcript": "Преподаватель: Проверьте ветку else.\nУченик: Я не понимаю эту ветку."}
        lesson_provider = FailOnceStructuredProvider([_lesson_output()])
        failed_lesson = analyze_lesson(lesson, None, lesson_provider)
        assert failed_lesson.status == "failed"
        assert failed_lesson.quality_json["operation"]["retryable"] is True

        retried_lesson = analyze_lesson(lesson, None, lesson_provider)
        assert retried_lesson.id == failed_lesson.id
        assert retried_lesson.status == "succeeded"
        assert lesson_provider.calls == 2
        assert analyze_lesson(lesson, None, lesson_provider).id == failed_lesson.id
        assert lesson_provider.calls == 2


def test_course_adapter_reads_only_explicitly_allowlisted_master_course_structure(isolated_app):
    from app.ai_lab.course_adapter import export_synthetic_learning_trajectory, list_synthetic_learning_trajectories
    from core.db_models import LearningItem, LearningTrajectory, Lesson, TrajectoryModule, db

    with isolated_app.app_context():
        course = LearningTrajectory(title="Synthetic adapter course", student_id=None, is_template=True,
                                    current_version=3, learning_goal="Проверить работу с границами.")
        db.session.add(course)
        db.session.flush()
        module = TrajectoryModule(course_id=course.course_id, title="Условия", order_index=2,
                                  learning_result="Различать включённую и исключённую границу.")
        db.session.add(module)
        db.session.flush()
        lesson = Lesson(learning_trajectory_id=course.course_id, course_module_id=module.module_id,
                        student_id=None, topic="Правая граница", content="Включённая граница учитывается.\n\nПроверьте n = 1.",
                        content_blocks=[{"type": "paragraph", "text": "Дополнительный проверочный пример."}],
                        student_notes="PRIVATE_STUDENT_NOTE_MUST_NOT_BE_EXPORTED")
        db.session.add(lesson)
        db.session.flush()
        db.session.add(LearningItem(course_id=course.course_id, module_id=module.module_id,
                                    item_type="practice", title="Задача на границы", why_now="Закрепить тему."))
        db.session.commit()

        isolated_app.config["AI_LAB_COURSE_ADAPTER_ENABLED"] = True
        isolated_app.config["AI_LAB_SYNTHETIC_COURSE_IDS"] = [course.course_id]
        assert list_synthetic_learning_trajectories() == [{"course_id": course.course_id,
                                                           "title": "Synthetic adapter course", "version": 3}]
        adapted = export_synthetic_learning_trajectory(course.course_id)
        assert adapted["course_id"] == f"synthetic-boostudy-course-{course.course_id}"
        assert adapted["course_version"] == 3
        assert adapted["topics"][0]["topic_id"] == f"boostudy-module:{module.module_id}"
        assert adapted["learning_goals"][0]["text"] == "Различать включённую и исключённую границу."
        assert adapted["assignments"][0]["title"] == "Задача на границы"
        assert "PRIVATE_STUDENT_NOTE_MUST_NOT_BE_EXPORTED" not in json.dumps(adapted, ensure_ascii=False)
        assert adapted["materials"][0]["content"].endswith("Дополнительный проверочный пример.")

        isolated_app.config["AI_LAB_SYNTHETIC_COURSE_IDS"] = []
        assert export_synthetic_learning_trajectory(course.course_id) is None


def test_file_backed_ai_lab_state_survives_app_restart_and_keeps_course_and_lesson_links(tmp_path):
    from app import create_app, db
    from app.ai_lab.course_adapter import export_synthetic_learning_trajectory
    from app.ai_lab.analytics import all_analytics_evidence
    from core.db_models import AiLabExperiment, LearningTrajectory, TrajectoryModule, Lesson, LearningItem

    database_path = tmp_path / "sprint5-isolated.sqlite"
    database_uri = f"sqlite:///{database_path.as_posix()}"
    config = {"TESTING": True, "WTF_CSRF_ENABLED": False, "SQLALCHEMY_DATABASE_URI": database_uri,
              "RUN_ENV": "local", "AI_LAB_ENABLED": True, "AI_LAB_COURSE_ADAPTER_ENABLED": True,
              "AI_LAB_SYNTHETIC_COURSE_IDS": [1]}
    app_before_restart = create_app(config)
    with app_before_restart.app_context():
        db.create_all()
        source = LearningTrajectory(title="Synthetic restart course", student_id=None, is_template=True,
                                    current_version=4, learning_goal="Проверить обработку границ.")
        db.session.add(source)
        db.session.flush()
        module = TrajectoryModule(course_id=source.course_id, title="Условия", order_index=1,
                                  learning_result="Различать ветви условия.")
        db.session.add(module)
        db.session.flush()
        lesson_source = Lesson(learning_trajectory_id=source.course_id, course_module_id=module.module_id,
                               student_id=None, topic="Граничный случай", content="При x = 0 выполняется ветка else.")
        db.session.add(lesson_source)
        db.session.flush()
        db.session.add(LearningItem(course_id=source.course_id, module_id=module.module_id,
                                    item_type="practice", title="Проверка x = 0"))
        db.session.commit()
        source_id = source.course_id
        app_before_restart.config["AI_LAB_SYNTHETIC_COURSE_IDS"] = [source_id]
        course_input = export_synthetic_learning_trajectory(source_id)
        course_provider = CourseFragmentProvider()
        course_record = analyze_course(course_input, None, course_provider)
        assert course_record.status == "succeeded"
        proposal_id = course_record.result_json["material_proposals"][0]["proposal_id"]
        old_content = lesson_source.content
        approved_text = "Подтвердите ветвь при x = 0 и запишите результат."
        review_course_proposal(course_record, proposal_id, "accepted", None, "Проверено преподавателем", approved_text)
        assert lesson_source.content == approved_text
        assert source.current_version == 5
        assert course_record.quality_json["proposal_reviews"][-1]["application_status"] == "applied"
        rollback_course_proposal(course_record, proposal_id, None)
        assert lesson_source.content == old_content
        assert source.current_version == 6

        transcript = {"lesson_id": "synthetic-restart-lesson", "lesson_version": 2,
                      "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                      "transcript": "Преподаватель: Проверим x = 0.\nУченик: Я не понимаю, какую ветвь выбрать."}
        lesson_record = analyze_lesson(transcript, None, FakeStructuredProvider([_lesson_output()]))
        review_lesson_observation(lesson_record, "difficulty-1", "confirmed", None)
        course_record_id, lesson_record_id = course_record.id, lesson_record.id
        course_hash = course_record.quality_json["input_hash"]
        lesson_event_id = f"ai-lab-lesson:{lesson_record.id}:difficulty-1"
        db.session.remove()
        db.engine.dispose()

    app_after_restart = create_app(config)
    with app_after_restart.app_context():
        course_record = db.session.get(AiLabExperiment, course_record_id)
        lesson_record = db.session.get(AiLabExperiment, lesson_record_id)
        assert course_record.quality_json["input_hash"] == course_hash
        assert course_record.quality_json["proposal_reviews"][-1]["decision"] == "accepted"
        assert course_record.quality_json["proposal_reviews"][-1]["application_status"] == "rolled_back"
        assert lesson_record.quality_json["observation_reviews"][-1]["decision"] == "confirmed"
        assert lesson_event_id in {event["event_id"] for event in all_analytics_evidence()}
        no_repeat_provider = CourseFragmentProvider()
        reused = analyze_course(course_record.input_snapshot, None, no_repeat_provider)
        assert reused.id == course_record_id
        assert no_repeat_provider.calls == 0
        changed = copy.deepcopy(course_record.input_snapshot)
        changed["materials"][0]["content"] += " Изменение источника."
        changed["course_version"] += 1
        assert analyze_course(changed, None, CourseFragmentProvider()).status == "succeeded"
        db.session.remove()
        db.engine.dispose()


def test_practice_uses_explicit_course_prerequisites_and_keeps_lesson_evidence_qualitative():
    from app.ai_lab.analytics import synthetic_demo_events

    snapshot = build_analytics_snapshot(synthetic_demo_events(), "edge-case-learner")
    catalog = [{"assignment_id": "synthetic.boundary-next", "assignment_version": 1,
                "title": "Граничные значения", "topic": "Условия и границы", "type": "python"}]
    course = {"course_id": "synthetic-course", "course_version": 1, "topics": [
        {"topic_id": "python.basics", "skill_id": "python.functions", "prerequisite_ids": [], "assignment_ids": []},
        {"topic_id": "python.conditions", "skill_id": "python.boundary_cases", "prerequisite_ids": ["python.basics"], "assignment_ids": ["synthetic.boundary-next"]},
    ]}
    blocked = recommend_practice(snapshot, catalog, course_outline=course)
    assert blocked["recommendations"] == []
    assert any("предпосылки курса" in item["reason"] for item in blocked["suppressed"])

    snapshot["skills"].append({"skill_id": "python.functions", "status": "demonstrated"})
    allowed = recommend_practice(snapshot, catalog, course_outline=course)
    assert allowed["recommendations"][0]["assignment_id"] == "synthetic.boundary-next"
    assert allowed["recommendations"][0]["course_context"]["course_version"] == 1


def test_practice_uses_the_real_synthetic_ai_lab_catalog():
    from app.ai_lab.analytics import synthetic_demo_events

    catalog = list_python_assignments()
    assert catalog and all(item.get("type") == "python" and item.get("topic") for item in catalog)
    snapshot = build_analytics_snapshot(synthetic_demo_events(), "edge-case-learner")
    result = recommend_practice(snapshot, catalog)
    assert result["recommendations"]
    assert result["recommendations"][0]["assignment_id"] == "ai-lab.python.classify"


def test_sprint4_pages_and_routes_are_admin_only(isolated_app, monkeypatch):
    from app.ai_lab import routes
    from app.models import User, db

    with isolated_app.app_context():
        admin = User(username="sprint4_admin", email="sprint4-admin@example.test", role="admin")
        admin.set_password("local-test-password")
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
    client = isolated_app.test_client()
    assert client.get("/admin/ai-lab/course").status_code == 302
    assert client.post("/admin/ai-lab/api/course/analyze", json={}).status_code == 302
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True

    course_provider = FakeStructuredProvider([_course_proposal()])
    lesson_provider = FakeStructuredProvider([_lesson_output(), _lesson_output()])
    monkeypatch.setattr(routes, "analyze_course", lambda payload, actor: analyze_course(payload, actor, course_provider))
    monkeypatch.setattr(routes, "analyze_lesson", lambda payload, actor: analyze_lesson(payload, actor, lesson_provider))

    assert client.get("/admin/ai-lab/course").status_code == 200
    assert client.get("/admin/ai-lab/lesson-intelligence").status_code == 200
    course_response = client.post("/admin/ai-lab/api/course/analyze", json={"course": synthetic_course_samples()[0]})
    assert course_response.status_code == 200
    course_record = course_response.json["record"]
    review_response = client.post(
        f"/admin/ai-lab/api/course/analyses/{course_record['id']}/proposals/proposal-boundary-note/review",
        json={"decision": "accepted"},
    )
    assert review_response.status_code == 200
    assert client.get(f"/admin/ai-lab/api/course/analyses/{course_record['id']}").json["record"]["quality"]["proposal_reviews"]

    lesson_payload = {"lesson_id": "synthetic-route-lesson", "lesson_version": 1,
                      "subject_id": "synthetic-lesson-learner", "synthetic_confirmed": True,
                      "transcript": "Преподаватель: Проверим условие.\nУченик: Я не понимаю ветку else."}
    lesson_response = client.post("/admin/ai-lab/api/lesson-intelligence/analyze", json=lesson_payload)
    assert lesson_response.status_code == 200
    lesson_record = lesson_response.json["record"]
    review = client.post(
        f"/admin/ai-lab/api/lesson-intelligence/analyses/{lesson_record['id']}/observations/difficulty-1/review",
        json={"decision": "confirmed"},
    )
    assert review.status_code == 200
    analytics = client.get("/admin/ai-lab/api/analytics?subject_id=synthetic-lesson-learner")
    assert analytics.status_code == 200
    assert analytics.json["snapshot"]["confirmed_lesson_observations"] == 1

    batch_payload = {**lesson_payload, "lesson_id": "synthetic-route-batch-lesson"}
    batch_analysis = client.post("/admin/ai-lab/api/lesson-intelligence/analyze", json=batch_payload)
    assert batch_analysis.status_code == 200
    batch_record = batch_analysis.json["record"]
    batch_review = client.post(
        f"/admin/ai-lab/api/lesson-intelligence/analyses/{batch_record['id']}/observations/batch-review",
        json={"observation_ids": ["difficulty-1"], "decision": "confirmed"},
    )
    assert batch_review.status_code == 200
    assert batch_review.json["record"]["quality"]["observation_reviews"][-1]["decision"] == "confirmed"

    monkeypatch.setattr(routes, "list_python_assignments", lambda: [{
        "assignment_id": "synthetic-next-boundary", "assignment_version": 1,
        "title": "Проверка границ", "topic": "Условия и границы", "type": "python",
    }])
    recommendations = client.get("/admin/ai-lab/api/practice/recommendations?subject_id=edge-case-learner")
    assert recommendations.status_code == 200
    assert recommendations.json["recommendations"][0]["assignment_id"] == "synthetic-next-boundary"
    feedback_payload = {"assignment_id": "synthetic-next-boundary", "vote": "helpful", "subject_id": "edge-case-learner"}
    feedback_one = client.post("/admin/ai-lab/api/practice/feedback", json=feedback_payload)
    feedback_two = client.post("/admin/ai-lab/api/practice/feedback", json=feedback_payload)
    assert feedback_one.status_code == feedback_two.status_code == 200
    assert feedback_one.json["feedback_id"] == feedback_two.json["feedback_id"]

