from __future__ import annotations

import json
import copy
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def isolated_db():
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


def _file_app(database_path: Path):
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
    })
    with app.app_context():
        db.create_all()
    return app


class BlockingCourseProvider:
    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete_structured(self, *_args):
        self.calls += 1
        self.entered.set()
        assert self.release.wait(10), "test did not release the synthetic provider"
        return SimpleNamespace(
            content=json.dumps({"summary": "Синтетический материал проверен.", "material_proposals": []}, ensure_ascii=False),
            model="SyntheticSprint6",
            input_tokens=9,
            output_tokens=5,
            prompt_tokens=9,
            precached_prompt_tokens=0,
            total_tokens=14,
            generation_parameters={"temperature": 0.1, "max_tokens": 50},
            payload_id=f"course-{self.calls}",
            payload_sha256="b" * 64,
        )


class FailSecondLessonChunkProvider:
    def __init__(self, fail_on_call=None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def complete_structured(self, model, system_prompt, user_payload, schema):
        self.calls += 1
        if self.calls == self.fail_on_call:
            from app.ai_lab.provider import ProviderError
            raise ProviderError("connection_failed", "Synthetic interruption after a saved lesson chunk.")
        if "source_index" in user_payload:
            ref = user_payload["source_index"][0]["segment_id"]
            minutes = user_payload["session_minutes"]
            return SimpleNamespace(
                content=json.dumps({"decision": "insufficient_evidence", "reason": "Синтетический проект требует диагностики.",
                                    "stages": [{"title": "Проверка изучавшейся темы", "minutes": minutes,
                                                "reason": "Использовать только материал этой стенограммы.",
                                                "expected_check": "Самостоятельное объяснение решения.", "source_refs": [ref]}],
                                    "limitations": []}, ensure_ascii=False),
                model="SyntheticSprint6Lesson", input_tokens=11, output_tokens=6,
                prompt_tokens=9, precached_prompt_tokens=2, total_tokens=17,
                generation_parameters={"temperature": 0.1, "max_tokens": 50},
                payload_id=f"lesson-synthesis-{self.calls}", payload_sha256=f"{self.calls:064x}",
            )
        ref = user_payload["target_segment_ids"][0]
        return SimpleNamespace(
            content=json.dumps({"summary": "Синтетический фрагмент обработан.", "topics": [],
                                "content_segments": [], "observed_difficulties": [], "limitations": []}, ensure_ascii=False),
            model="SyntheticSprint6Lesson", input_tokens=11, output_tokens=6,
            prompt_tokens=9, precached_prompt_tokens=2, total_tokens=17,
            generation_parameters={"temperature": 0.1, "max_tokens": 50},
            payload_id=f"lesson-{self.calls}", payload_sha256=f"{self.calls:064x}",
        )


class LessonDifficultyProvider:
    def complete_structured(self, model, system_prompt, user_payload, schema):
        if "source_index" in user_payload:
            ref = user_payload["source_index"][0]["segment_id"]
            minutes = user_payload["session_minutes"]
            return SimpleNamespace(
                content=json.dumps({"decision": "propose_change", "reason": "Повторить только явно затруднившую ученика тему.",
                                    "stages": [{"title": "Практика уже изучавшейся границы", "minutes": minutes,
                                                "reason": "Ученик прямо сообщил о затруднении.",
                                                "expected_check": "Самостоятельно разобрать граничный пример.", "source_refs": [ref]}],
                                    "limitations": []}, ensure_ascii=False),
                model="SyntheticLesson", input_tokens=17, output_tokens=12,
                prompt_tokens=15, precached_prompt_tokens=2, total_tokens=29,
                generation_parameters={"temperature": 0.1, "max_tokens": 100},
                payload_id="lesson-synthesis", payload_sha256="d" * 64,
            )
        target = user_payload["target_segment_ids"][0]
        content = json.dumps({
            "summary": "Урок проверяет включение границы и роль условия.",
            "topics": [{"topic_id": "python.boundary_cases", "title": "Граничные случаи", "source_refs": [target]}],
            "content_segments": [],
            "observed_difficulties": [{
                "skill_id": "python.boundary_cases",
                "description": "Ученик прямо сообщил, что не понимает включение правой границы.",
                "source_refs": [target],
            }],
            "limitations": [],
        }, ensure_ascii=False)
        return SimpleNamespace(content=content, model="SyntheticLesson", input_tokens=17, output_tokens=12,
                               prompt_tokens=15, precached_prompt_tokens=2, total_tokens=29,
                               generation_parameters={"temperature": 0.1, "max_tokens": 100},
                               payload_id="lesson-payload", payload_sha256="d" * 64)


def test_structured_transcripts_keep_only_supplied_ids_timestamps_and_speakers():
    from app.ai_lab.lesson_intelligence import parse_transcript

    segments = parse_transcript([
        {"segment_id": "utterance-a", "timestamp": "00:01:12", "speaker_role": "student", "text": "Не понимаю этот пример."},
        {"text": "Рассмотрим его по шагам."},
    ])
    assert segments[0]["segment_id"] == "utterance-a"
    assert segments[0]["timestamp"] == "00:01:12"
    assert segments[0]["speaker"] == "student"
    assert segments[1]["timestamp"] is None and segments[1]["speaker"] is None
    assert segments[1]["segment_id"] == "segment-002"


def test_lesson_request_keeps_versioned_course_link_on_synthetic_transcript():
    from app.ai_lab.lesson_intelligence import LessonAnalysisError, validate_lesson_request

    raw = {"lesson_id": "synthetic-sprint6-linked-lesson", "lesson_version": 3,
           "synthetic_confirmed": True, "course_id": "synthetic-sprint6-course",
           "course_version": 4, "transcript": "Teacher: Synthetic lesson text."}
    normalized, _ = validate_lesson_request(raw)
    assert normalized["course_context"] == {"course_id": "synthetic-sprint6-course", "course_version": 4}
    with pytest.raises(LessonAnalysisError, match="course_version"):
        validate_lesson_request({**raw, "course_version": True})


def test_one_completion_attempt_leaves_inconsistent_homework_for_manual_review(isolated_db, monkeypatch):
    from app.ai_lab import service
    from app.ai_lab.service import ensure_initial_prompt, run_experiment
    from core.db_models import AiLabExperiment

    class SyntheticHomeworkProvider:
        name = "synthetic"
        model = "Synthetic-Homework"
        complete_calls = 0

        def list_models(self):
            return [self.model]

        def complete(self, *_args, **_kwargs):
            self.complete_calls += 1
            content = json.dumps({
                "score_awarded": 2, "max_score": 2, "grading_status": "checked", "criterion_scores": [],
                "insufficient_data_reason": "", "summary": "Synthetic output.", "mistakes": [],
                "student_feedback": "Review the result.", "teacher_feedback": "Review the criterion.",
                "recommended_topics": [], "needs_human_review": True, "review_reason": "Preliminary result.",
                "confidence_level": "medium",
            })
            return SimpleNamespace(content=content, model=self.model, input_tokens=12, output_tokens=20,
                                   prompt_tokens=10, precached_prompt_tokens=2, total_tokens=32,
                                   generation_parameters={"temperature": 0.1, "max_tokens": 32, "top_p": None},
                                   payload_id="sprint6-homework-payload", payload_sha256="c" * 64,
                                   request_payload={"synthetic": True})

    provider = SyntheticHomeworkProvider()
    monkeypatch.setattr(service, "is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr(service, "provider_settings", lambda: {"configured": True, "default_model": provider.model})
    with isolated_db.app_context():
        prompt = ensure_initial_prompt()
        row = run_experiment(actor_user_id=9879, provider=provider, max_completion_attempts=1, payload={
            "request_key": "61ee1166-5529-4d99-a3f4-333333333333",
            "scenario_id": "py-arithmetic-02", "model": provider.model,
            "prompt_version_id": prompt.id, "input": {},
        })
        assert row.status == "succeeded"
        assert row.result_json["grading_status"] == "manual_review"
        assert "после одной попытки" in row.result_json["summary"]
        assert row.quality_json["technical"]["semantic_validation"]["status"] == "manual_review_required"
        assert row.quality_json["technical"]["semantic_validation"]["retry_used"] is False
        assert len(row.quality_json["technical"]["attempts"]) == 1
        assert provider.complete_calls == 1
        assert AiLabExperiment.query.filter_by(actor_user_id=9879).count() == 1


def test_cross_chunk_verbal_claim_without_skill_matched_demonstration_does_not_resolve_difficulty():
    from app.ai_lab.lesson_intelligence import _merge_lesson_chunk_results, parse_transcript

    transcript = "\n".join([
        "Ученик: Я не понимаю, почему 10 не входит в range.",
        *[f"Преподаватель: Синтетический переход {index}." for index in range(90)],
        "Ученик: Понял: чтобы включить 10, нужно передать 11.",
    ])
    segments = parse_transcript(transcript)
    request = {"lesson_id": "synthetic-sprint6-cross-chunk", "lesson_version": 1,
               "source_ref": "synthetic-transcript:fixed", "segments": segments}
    early = segments[0]["segment_id"]
    late = segments[-1]["segment_id"]
    merged = _merge_lesson_chunk_results(request, [
        {"chunk_id": "early", "index": 1, "result": {
            "summary": "Задали вопрос о правой границе.", "topics": [], "content_segments": [],
            "observed_difficulties": [{"skill_id": "python.boundary_cases",
                                        "description": "Ученик прямо сообщил, что не понимает правую границу.",
                                        "source_refs": [early]}], "limitations": [],
        }},
        {"chunk_id": "late", "index": 2, "result": {
            "summary": "Ученик сформулировал способ включить границу.", "topics": [], "content_segments": [],
            "observed_difficulties": [], "limitations": [],
        }},
    ])
    difficulty = merged["observed_difficulties"][0]
    assert difficulty["evidence_status"] == "ai_inference"
    assert difficulty["review_status"] == "pending"
    assert difficulty["resolution_status"] == "unresolved_or_unknown"
    assert difficulty["resolution_source_refs"] == []


def test_concurrent_identical_course_requests_share_the_running_operation(tmp_path):
    from app import db
    from app.ai_lab.course import analyze_course, synthetic_course_samples
    from core.db_models import AiLabExperiment

    app = _file_app(tmp_path / "sprint6-concurrent.sqlite")
    provider = BlockingCourseProvider()
    sample = synthetic_course_samples()[0]
    first_result = []
    first_errors = []

    def first_request():
        try:
            with app.app_context():
                first_result.append(analyze_course(sample, actor_user_id=9876, provider=provider))
                db.session.remove()
        except Exception as exc:
            first_errors.append(exc)

    worker = threading.Thread(target=first_request, daemon=True)
    worker.start()
    assert provider.entered.wait(10), "the first request did not reach the synthetic provider"

    with app.app_context():
        duplicate = analyze_course(sample, actor_user_id=9876, provider=provider)
        assert duplicate.status == "running"
        db.session.remove()

    provider.release.set()
    worker.join(10)
    assert not worker.is_alive()
    assert not first_errors
    assert provider.calls == 1

    with app.app_context():
        rows = AiLabExperiment.query.filter_by(actor_user_id=9876, scenario_id="ai-course-analysis").all()
        assert len(rows) == 1
        assert rows[0].status == "succeeded"
        assert rows[0].quality_json["chunk_progress"]["completed"] == rows[0].quality_json["chunk_progress"]["total"]


def test_lesson_partial_progress_and_transport_error_resume_after_app_restart(tmp_path):
    from app import db
    from app.ai_lab.lesson_intelligence import analyze_lesson, lesson_analysis_chunks, parse_transcript
    from core.db_models import AiLabExperiment

    database_path = tmp_path / "sprint6-restart-resume.sqlite"
    first_app = _file_app(database_path)
    request = {
        "lesson_id": "synthetic-sprint6-resume-lesson",
        "lesson_version": 1,
        "synthetic_confirmed": True,
        "transcript": "\n".join(
            f"Преподаватель: Синтетический фрагмент {index}: обсудим проверку условия и границы списка. " + "пример " * 10
            for index in range(220)
        ),
    }
    planned_chunks = lesson_analysis_chunks(parse_transcript(request["transcript"]), request["lesson_id"], 1)
    assert len(planned_chunks) > 2

    with first_app.app_context():
        interrupted = analyze_lesson(request, actor_user_id=9878, provider=FailSecondLessonChunkProvider(fail_on_call=2))
        assert interrupted.status == "failed"
        saved_ids = [item["chunk_id"] for item in interrupted.quality_json["chunk_results"]]
        assert len(saved_ids) == 1
        attempts = interrupted.quality_json["generation_attempts"]
        assert attempts[-1]["transport_status"] == "error"
        assert attempts[-1]["request_payload_sha256"]
        assert attempts[-1]["usage"]["total_tokens"] is None
        db.session.remove()

    second_app = _file_app(database_path)
    with second_app.app_context():
        resumed_provider = FailSecondLessonChunkProvider()
        resumed = analyze_lesson(request, actor_user_id=9878, provider=resumed_provider)
        assert resumed.status == "succeeded"
        assert resumed_provider.calls == len(planned_chunks) - 1
        assert resumed.quality_json["chunk_results"][0]["chunk_id"] == saved_ids[0]
        assert len(resumed.quality_json["chunk_results"]) == len(planned_chunks)
        assert resumed.input_tokens == 11 * len(planned_chunks)
        assert resumed.output_tokens == 6 * len(planned_chunks)
        assert resumed.quality_json["generation_attempts"][0]["usage"] == {
            "prompt_tokens": 9, "precached_prompt_tokens": 2, "completion_tokens": 6,
            "total_tokens": 17, "full_input_tokens": 11,
        }
        assert AiLabExperiment.query.filter_by(actor_user_id=9878, request_key=interrupted.request_key).count() == 1


@pytest.mark.parametrize("trajectory_suffix", ["alpha", "beta"])
def test_all_five_modules_flow_through_persistent_synthetic_sqlite(tmp_path, monkeypatch, trajectory_suffix):
    from app import db
    from app.ai_lab import service
    from app.ai_lab.analytics import all_analytics_evidence, build_analytics_snapshot, synthetic_demo_events
    from app.ai_lab.course import analyze_course
    from app.ai_lab.lesson_intelligence import analyze_lesson, review_lesson_observation, stored_lesson_evidence
    from app.ai_lab.practice import recommend_practice
    from app.ai_lab.scenarios import list_python_assignments
    from app.ai_lab.service import ensure_initial_prompt, run_experiment
    from core.db_models import AiLabExperiment

    database_path = tmp_path / f"sprint10-five-module-flow-{trajectory_suffix}.sqlite"
    app = _file_app(database_path)
    course_input = {
        "course_id": f"synthetic-sprint10-flow-course-{trajectory_suffix}", "course_version": 1, "title": "Условия и границы",
        "topics": [
            {"topic_id": "python.conditions", "title": "Условия", "order": 1, "prerequisite_ids": [], "skill_id": "python.conditions"},
            {"topic_id": "python.boundary_cases", "title": "Граничные случаи", "order": 2,
             "prerequisite_ids": [], "skill_id": "python.boundary_cases"},
        ],
        "learning_goals": [],
        "materials": [
            {"material_id": "synthetic-s6-conditions", "title": "Условия", "topic_id": "python.conditions", "content": "Условие выбирает ветвь."},
            {"material_id": "synthetic-s6-boundaries", "title": "Границы", "topic_id": "python.boundary_cases", "content": "Проверяйте значения на границе интервала."},
        ],
        "assignments": [{"assignment_id": "ai-lab.python.classify", "title": "Классификация", "topic_id": "python.boundary_cases", "skill_id": "python.boundary_cases"}],
    }
    course_provider = BlockingCourseProvider()
    course_provider.release.set()

    with app.app_context():
        course_record = analyze_course(course_input, actor_user_id=9880, provider=course_provider)
        assert course_record.status == "succeeded"
        assert course_record.quality_json["input_hash"]
        assert course_record.quality_json["generation_attempts"][0]["usage"]["full_input_tokens"] == 9

        lesson_payload = {
            "lesson_id": f"synthetic-sprint10-flow-lesson-{trajectory_suffix}", "lesson_version": 2,
            "subject_id": f"synthetic-sprint10-flow-subject-{trajectory_suffix}", "synthetic_confirmed": True,
            "course_id": course_input["course_id"], "course_version": course_input["course_version"],
            "transcript": [{"segment_id": f"flow-student-{trajectory_suffix}", "timestamp": "00:00:12",
                            "speaker_role": "student", "text": "Я не понимаю, почему правая граница не включается."},
                           {"segment_id": f"flow-teacher-{trajectory_suffix}", "speaker_role": "teacher",
                            "text": "В range правая граница не включается."}],
        }
        lesson_record = analyze_lesson(lesson_payload, actor_user_id=9880, provider=LessonDifficultyProvider())
        assert lesson_record.status == "succeeded"
        assert lesson_record.scenario_snapshot["course_context"] == {
            "course_id": course_input["course_id"], "course_version": 1,
        }
        observation = lesson_record.result_json["observed_difficulties"][0]
        review_lesson_observation(lesson_record, observation["observation_id"], "confirmed", 9880,
                                  "Synthetic expert confirmation for integration test.")
        lesson_events = [event for event in stored_lesson_evidence()
                         if event["source_module"] == "ai_lesson_intelligence"
                         and event["source_record_id"] == str(lesson_record.id)]
        assert len(lesson_events) == 1
        assert lesson_events[0]["course_context"] == {"course_id": course_input["course_id"], "course_version": 1}

        # Feed confirmed synthetic evidence through Analytics, retaining only the source-bound lesson event.
        demo = synthetic_demo_events()
        flow_evidence = [copy.deepcopy(event) for event in demo if event["subject_id"] == "edge-case-learner"]
        for index, event in enumerate(flow_evidence):
            event["subject_id"] = f"synthetic-sprint10-flow-subject-{trajectory_suffix}"
            event["event_id"] = f"sprint10-flow-{trajectory_suffix}:{index}"
            event["source_record_id"] = f"synthetic-code-judge:{index}"
        flow_evidence.append(lesson_events[0])
        snapshot = build_analytics_snapshot(flow_evidence, f"synthetic-sprint10-flow-subject-{trajectory_suffix}")
        assert snapshot["subject_id"] == f"synthetic-sprint10-flow-subject-{trajectory_suffix}"
        assert snapshot["events"] == len(flow_evidence)

        course_outline = {"course_id": course_input["course_id"], "course_version": course_input["course_version"],
                          "topics": [{"topic_id": topic["topic_id"], "skill_id": topic["skill_id"],
                                      "assignment_ids": ["ai-lab.python.classify"] if topic["skill_id"] == "python.boundary_cases" else [],
                                      "prerequisite_ids": topic["prerequisite_ids"]}
                                     for topic in course_input["topics"]]}
        practice = recommend_practice(snapshot, list_python_assignments(), course_outline=course_outline)
        assert practice["prerequisites"]["course_id"] == course_input["course_id"]
        assert practice["recommendations"]
        assert practice["recommendations"][0]["course_context"]["course_version"] == 1

        class SyntheticHomeworkProvider:
            name = "synthetic"
            model = "Synthetic-Homework"
            complete_calls = 0

            def list_models(self):
                return [self.model]

            def complete(self, *_args, **_kwargs):
                self.complete_calls += 1
                content = json.dumps({
                    "score_awarded": 2, "max_score": 2, "grading_status": "checked", "criterion_scores": [],
                    "insufficient_data_reason": "", "summary": "Synthetic output.", "mistakes": [],
                    "student_feedback": "Review the result.", "teacher_feedback": "Review the criterion.",
                    "recommended_topics": [], "needs_human_review": True, "review_reason": "Preliminary result.",
                    "confidence_level": "medium",
                })
                return SimpleNamespace(content=content, model=self.model, input_tokens=12, output_tokens=20,
                                       prompt_tokens=10, precached_prompt_tokens=2, total_tokens=32,
                                       generation_parameters={"temperature": 0.1, "max_tokens": 32},
                                       payload_id="homework-flow-payload", payload_sha256="e" * 64,
                                       request_payload={"synthetic": True})

        homework_provider = SyntheticHomeworkProvider()
        monkeypatch.setattr(service, "is_local_ai_lab_enabled", lambda: True)
        monkeypatch.setattr(service, "provider_settings", lambda: {"configured": True, "default_model": homework_provider.model})
        prompt = ensure_initial_prompt()
        homework = run_experiment(actor_user_id=9880, provider=homework_provider, max_completion_attempts=1, payload={
            "request_key": f"6718e55c-2736-4a74-90c9-f3333333333{1 if trajectory_suffix == 'alpha' else 2}", "scenario_id": "py-arithmetic-02",
            "model": homework_provider.model, "prompt_version_id": prompt.id, "input": {},
        })
        assert homework.status == "succeeded"
        assert homework_provider.complete_calls == 1
        assert homework.quality_json["learning_evidence"]["evidence_status"] == "ai_inference"
        updated_events = all_analytics_evidence()
        assert any(event["source_module"] == "ai_homework"
                   and event["source_record_id"] == f"ai-lab-experiment:{homework.id}"
                   for event in updated_events)
        assert len([event for event in updated_events if event["source_module"] == "ai_lesson_intelligence"
                    and event["source_record_id"] == str(lesson_record.id)]) == 1
        db.session.remove()

    restarted = _file_app(database_path)
    with restarted.app_context():
        saved_course = AiLabExperiment.query.filter_by(scenario_id="ai-course-analysis", actor_user_id=9880).first()
        saved_lesson = AiLabExperiment.query.filter_by(scenario_id="ai-lesson-intelligence", actor_user_id=9880).first()
        saved_homework = AiLabExperiment.query.filter_by(actor_user_id=9880, scenario_id="py-arithmetic-02").first()
        assert saved_course and saved_course.quality_json["input_hash"]
        assert saved_lesson and saved_lesson.quality_json["course_context"]["course_version"] == 1
        assert saved_homework and saved_homework.quality_json["learning_evidence"]["evidence_status"] == "ai_inference"


def test_stale_running_operation_can_be_claimed_once_after_lease_expiry(isolated_db):
    from app import db
    from app.ai_lab.operation_state import claim_retry
    from core.db_models import AiLabExperiment

    with isolated_db.app_context():
        stale = datetime.now(timezone.utc) - timedelta(hours=1)
        row = AiLabExperiment(
            actor_user_id=9877,
            request_key="sprint6-stale-operation",
            scenario_id="ai-course-analysis",
            status="running",
            provider="gigachat",
            model="synthetic",
            prompt_version_no=4,
            prompt_snapshot="frozen",
            scenario_snapshot={"course_id": "s6-stale", "course_version": 1},
            input_snapshot={"course_id": "s6-stale", "course_version": 1},
            expected_snapshot={},
            updated_at=stale,
            quality_json={"operation": {"attempt_count": 1, "max_attempts": 2,
                                         "last_started_at": stale.isoformat(), "retryable": False},
                          "chunk_results": [{"chunk_id": "done-once"}]},
        )
        db.session.add(row)
        db.session.commit()

        assert claim_retry(row) is True
        assert row.status == "running"
        assert row.quality_json["operation"]["attempt_count"] == 2
        assert row.quality_json["chunk_results"] == [{"chunk_id": "done-once"}]
        assert claim_retry(row) is False
