from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION
from app.ai_lab.tutor_core_contract import (
    CLIENT_EVENT_SCENARIO,
    ClientAdapter,
    TutorCoreContractError,
    TutorCoreV1,
)
from app.models import db, Enrollment, Student
from core.db_models import AiLabExperiment, User


SKILL_ID = "skill.math.fractions"
CRITERION_ID = "add_common_denominator"
SUBJECT_ID = "platform-student:{}"


def _event(subject_id: str, source_record_id: str, event_id: str, exercise_id: str,
           *, is_correct: bool = True, exposure_count: int | None = 1,
           include_attempt_context: bool = True, course_version: int | None = None,
           skill_id: str = SKILL_ID, criterion_id: str = CRITERION_ID) -> dict:
    payload = f"{event_id}:{exercise_id}:{is_correct}".encode()
    return {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": event_id,
        "subject_id": subject_id,
        "source_module": "ai_tutor_core",
        "source_record_id": source_record_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "evidence_status": "technical_confirmed",
        "assignment": {"id": exercise_id, "version": 1},
        "attempt_context": ({
            "attempt_no": 1, "material_id": exercise_id,
            "exposure_count": exposure_count, "difficulty": 2,
        } if include_attempt_context else None),
        "response": {"format": "text", "value": "8/16", "submitted_at": datetime.now(timezone.utc).isoformat()},
        "course_context": ({"course_id": "synthetic-course-4", "course_version": course_version}
                           if course_version is not None else None),
        "topic_ids": [],
        "skill_ids": [skill_id],
        "outcome": {"score": 1 if is_correct else 0, "maximum": 1, "status": "graded"},
        "criteria": [{
            "criterion_id": criterion_id,
            "earned": 1 if is_correct else 0,
            "maximum": 1,
            "status": "met" if is_correct else "not_met",
            "evidence_status": "technical_confirmed",
            "skill_id": skill_id,
            "reason": "Synthetic deterministic checker result.",
            "source_refs": [f"checker:{event_id}"],
        }],
        "assistance": {"level": "no_platform_hint", "source_refs": []},
        "error_codes": [],
        "limitations": [],
        "provenance": {
            "source_ref": f"synthetic-client:{source_record_id}",
            "payload_hash": hashlib.sha256(payload).hexdigest(),
            "method": "synthetic-test-checker-v1",
        },
    }


def _candidate(exercise_id: str, difficulty: int) -> dict:
    prompt = f"Сократите дробь {difficulty + 1}/{2 * (difficulty + 1)}."
    return {
        "exercise": {
            "exercise_id": exercise_id,
            "prompt": prompt,
            "answer_type": "short_text",
            "answer_key": "1/2",
            "skill_ids": [SKILL_ID],
            "difficulty": difficulty,
        },
        "criterion_ids": [CRITERION_ID],
        "source": {
            "kind": "task_bank", "status": "verified", "source_id": exercise_id,
            "version": 1, "content_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "checker_id": "exact-fraction-v1", "checker_version": "1.0",
        },
    }


def _setup(monkeypatch, role_users):
    import app.ai_lab.database_safety as database_safety
    import app.ai_lab.platform_homework as platform_homework
    import app.ai_lab.provider as provider

    subject_user_id = role_users["student_user_id"]
    actor_user_id = role_users["tutor_id"]
    with db.session.begin_nested():
        user = db.session.get(User, subject_user_id)
        user.username = "synthetic_contract_student"
        db.session.flush()

    monkeypatch.setattr(database_safety, "has_verified_safe_ai_lab_db", lambda: True)
    monkeypatch.setattr(provider, "is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr(platform_homework, "_allowlisted_user_ids", lambda: {subject_user_id})
    monkeypatch.setattr(platform_homework, "_allowlisted_actor_ids", lambda: {actor_user_id})

    events = {}
    skills = {
        (SKILL_ID, CRITERION_ID): {
            "skill_id": SKILL_ID, "title": "Сокращение дробей",
            "criterion_id": CRITERION_ID,
            "criterion_description": "Сокращает дробь, сохраняя её значение.",
            "question_type": "short_text",
            "answer_requirements": "Несократимая дробь в формате a/b.",
        },
    }
    candidates = [_candidate("bank:fractions:one", 2), _candidate("bank:fractions:two", 2)]

    def resolve_event(actor_id, subject_id, source_record_id):
        return events.get(source_record_id)

    def resolve_skill(skill_id, criterion_id):
        return skills.get((skill_id, criterion_id))

    def list_candidates(subject_id, skill_id, criterion_id):
        return candidates if skill_id == SKILL_ID and criterion_id == CRITERION_ID else []

    adapter = ClientAdapter(
        source_modules=frozenset({"ai_tutor_core"}),
        resolve_event=resolve_event,
        resolve_skill=resolve_skill,
        list_candidates=list_candidates,
    )
    core = TutorCoreV1()
    for client_id in ("zen_trainer", "blitz_quiz", "adaptive_course"):
        core.register_client(client_id, adapter)
    return core, events, actor_user_id, SUBJECT_ID.format(subject_user_id), candidates


def _stub_source_readers(monkeypatch):
    import app.ai_lab.analytics as analytics
    import app.ai_lab.lesson_intelligence as lesson_intelligence
    import app.ai_lab.practice as practice

    monkeypatch.setattr(analytics, "stored_platform_homework_evidence", lambda **kwargs: [])
    monkeypatch.setattr(analytics, "stored_lesson_task_evidence", lambda **kwargs: [])
    monkeypatch.setattr(lesson_intelligence, "stored_lesson_evidence", lambda **kwargs: [])
    monkeypatch.setattr(practice, "stored_ai_practice_evidence", lambda **kwargs: [])


def test_three_clients_share_course_optional_memory_and_idempotent_events(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, candidates = _setup(monkeypatch, role_users)
    candidates.append(_candidate("bank:fractions:three", 3))
    zen = core.client("zen_trainer")
    blitz = core.client("blitz_quiz")
    course = core.client("adaptive_course")
    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}

    cold_start = zen.next_practice(actor_id, subject_id, goal)
    assert cold_start["action"] == "diagnostic_start"
    assert cold_start["candidate"]["exercise_id"] == "bank:fractions:one"
    assert "answer_key" not in cold_start["candidate"]

    events["attempt:one"] = _event(
        subject_id, "attempt:one", "zen:attempt:one", "bank:fractions:one", course_version=1,
    )
    recorded = zen.record_result(actor_id, subject_id, "attempt:one")
    repeated = zen.record_result(actor_id, subject_id, "attempt:one")
    assert recorded["stored"] is True and recorded["duplicate"] is False
    assert repeated["duplicate"] is True
    assert AiLabExperiment.query.filter_by(scenario_id=CLIENT_EVENT_SCENARIO).count() == 1
    stored_source_event = events["attempt:one"]
    events["attempt:one"] = _event(
        subject_id, "attempt:one", "zen:attempt:one", "bank:fractions:one", is_correct=False,
    )
    with pytest.raises(TutorCoreContractError, match="другим содержимым"):
        zen.record_result(actor_id, subject_id, "attempt:one")
    events["attempt:one"] = stored_source_event

    profile = blitz.profile(actor_id, subject_id)
    assert profile["course_required"] is False
    assert profile["evidence"]["event_count"] == 1
    assert profile["evidence"]["events"][0]["event_id"] == "zen:attempt:one"
    assert profile["evidence"]["events"][0]["response"]["value"] == "8/16"
    assert profile["evidence"]["events"][0]["course_context"]["course_version"] == 1

    next_step = zen.next_practice(actor_id, subject_id, goal)
    assert next_step["action"] == "transfer_check"
    assert next_step["candidate"]["exercise_id"] == "bank:fractions:two"
    assert next_step["evidence_refs"] == ["zen:attempt:one"]
    explanation = zen.explain_decision(actor_id, subject_id, goal)
    assert explanation["used_evidence"] == ["zen:attempt:one"]
    assert explanation["excluded_evidence"] == []
    assert explanation["teacher_explanation"]
    assert explanation["student_explanation"]

    spec = blitz.quiz_specification(
        actor_id, subject_id, skill_id=SKILL_ID, criterion_id=CRITERION_ID, question_count=3,
    )
    assert spec["status"] == "needs_author_or_generator"
    assert spec["existing_candidates"][0]["exercise_id"] == "bank:fractions:two"
    assert all("answer_key" not in item for item in spec["existing_candidates"])
    assert spec["authoring_requirements"]["additional_questions_needed"] == 1
    assert spec["authoring_requirements"]["generated_question_is_not_verified"] is True

    events["attempt:two"] = _event(
        subject_id, "attempt:two", "blitz:attempt:two", "bank:fractions:two", course_version=2,
    )
    assert blitz.record_result(actor_id, subject_id, "attempt:two")["stored"] is True
    after_independent_successes = zen.next_practice(actor_id, subject_id, goal)
    assert after_independent_successes["action"] == "increase_difficulty"
    assert after_independent_successes["candidate"]["exercise_id"] == "bank:fractions:three"
    shared_profile = course.profile(actor_id, subject_id)
    assert shared_profile["evidence"]["event_count"] == 2
    assert {event["course_context"]["course_version"] for event in shared_profile["evidence"]["events"]} == {1, 2}

    import app.ai_lab.analytics as analytics
    import app.ai_lab.course_adapter as course_adapter
    import app.ai_lab.tutor_core as tutor_core
    from types import SimpleNamespace

    projected_events = []
    monkeypatch.setattr(analytics, "all_analytics_evidence", lambda **kwargs: [])
    monkeypatch.setattr(
        course_adapter, "resolve_assigned_synthetic_copy",
        lambda student_id: {"status": "resolved", "copy": SimpleNamespace(course_id=777)},
    )

    def project_case(profile_id, profile_events, student_id, copy, reviews):
        projected_events.extend(profile_events)
        return {
            "profile_id": profile_id,
            "proposal": {"evidence_refs": [event["event_id"] for event in profile_events], "action": "keep_plan"},
            "adaptation_preview": {"status": "no_change"},
        }

    monkeypatch.setattr(tutor_core, "_platform_profile_case", project_case)
    course_result = course.course_recommendation(actor_id, subject_id, expected_course_id=777)
    assert course_result.get("course_id") == 777, course_result
    assert course_result["evidence_refs"] == ["zen:attempt:one", "blitz:attempt:two"]
    assert [event["event_id"] for event in projected_events] == ["zen:attempt:one", "blitz:attempt:two"]
    assert course_result["course_mutated"] is False
    mismatch = course.course_recommendation(actor_id, subject_id, expected_course_id=778)
    assert mismatch["status"] == "course_context_mismatch"
    assert mismatch["course_mutated"] is False


def test_unverified_or_incompatible_material_is_not_recommended(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, _, actor_id, subject_id, candidates = _setup(monkeypatch, role_users)
    zen = core.client("zen_trainer")
    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}

    candidates[0]["source"]["status"] = "draft"
    result = zen.next_practice(actor_id, subject_id, goal)
    assert result["candidate"]["exercise_id"] == "bank:fractions:two"
    assert result["next_material_requirements"]["requires_exact_skill_and_criterion_mapping"] is True
    assert result["explanation"]["teacher"]
    assert result["explanation"]["student"]

    candidates[:] = [_candidate("bank:fractions:unmapped", 2)]
    candidates[0]["criterion_ids"] = ["different_criterion"]
    unavailable = zen.next_practice(actor_id, subject_id, goal)
    assert unavailable["status"] == "unavailable"
    assert unavailable["candidate"] is None
    assert "проверенным эталоном" in unavailable["reason"]

    with pytest.raises(TutorCoreContractError, match="не разрешился"):
        zen.quiz_specification(actor_id, subject_id, skill_id=SKILL_ID, criterion_id="unknown")


def test_repeat_exposure_does_not_count_as_independent_success(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, candidates = _setup(monkeypatch, role_users)
    candidates.append(_candidate("bank:fractions:three", 3))
    zen = core.client("zen_trainer")
    events["attempt:one"] = _event(
        subject_id, "attempt:one", "zen:attempt:one", "bank:fractions:one", exposure_count=2,
    )
    events["attempt:two"] = _event(
        subject_id, "attempt:two", "zen:attempt:two", "bank:fractions:two", exposure_count=1,
    )
    zen.record_result(actor_id, subject_id, "attempt:one")
    zen.record_result(actor_id, subject_id, "attempt:two")

    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}
    result = zen.next_practice(actor_id, subject_id, goal)
    assert result["action"] == "transfer_check"
    assert result["candidate"]["exercise_id"] == "bank:fractions:three"
    assert "данных для повышения сложности пока мало" in result["reason"]


def test_mixed_results_and_missing_exposure_metadata_do_not_overstate_progress(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, candidates = _setup(monkeypatch, role_users)
    candidates.append(_candidate("bank:fractions:three", 2))
    blitz = core.client("blitz_quiz")
    zen = core.client("zen_trainer")
    events["attempt:one"] = _event(
        subject_id, "attempt:one", "zen:attempt:one", "bank:fractions:one",
        include_attempt_context=False,
    )
    events["attempt:two"] = _event(
        subject_id, "attempt:two", "blitz:attempt:two", "bank:fractions:two",
        include_attempt_context=False,
    )
    zen.record_result(actor_id, subject_id, "attempt:one")
    blitz.record_result(actor_id, subject_id, "attempt:two")

    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}
    decision = zen.next_practice(actor_id, subject_id, goal)
    assert decision["action"] == "transfer_check"
    assert decision["candidate"]["exercise_id"] == "bank:fractions:three"
    assert "Уровень задания неизвестен" in decision["reason"]
    assert decision["explanation"]["teacher"].count("не подтверждает mastery") == 1
    assert set(decision["evidence"]["used_event_ids"]) == {"zen:attempt:one", "blitz:attempt:two"}


def test_insufficient_result_is_explained_but_not_used_as_failure(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, _ = _setup(monkeypatch, role_users)
    zen = core.client("zen_trainer")
    uncertain = _event(subject_id, "attempt:unknown", "zen:unknown", "bank:fractions:one")
    uncertain["evidence_status"] = "insufficient_data"
    uncertain["outcome"] = {"score": None, "maximum": 1, "status": "insufficient_data"}
    uncertain["criteria"][0].update({
        "earned": None, "status": "insufficient_data", "evidence_status": "insufficient_data",
    })
    events["attempt:unknown"] = uncertain
    zen.record_result(actor_id, subject_id, "attempt:unknown")

    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}
    decision = zen.next_practice(actor_id, subject_id, goal)
    assert decision["action"] == "diagnostic_start"
    assert decision["candidate"]["exercise_id"] == "bank:fractions:two"
    assert decision["evidence"]["used_event_ids"] == []
    assert decision["evidence"]["excluded"] == [{
        "event_id": "zen:unknown", "reason": "event_not_confirmed",
    }]
    assert "Начни с короткого задания" in decision["explanation"]["student"]
    specification = zen.quiz_specification(
        actor_id, subject_id, skill_id=SKILL_ID, criterion_id=CRITERION_ID, question_count=2,
    )
    assert [item["exercise_id"] for item in specification["existing_candidates"]] == ["bank:fractions:two"]


def test_mixed_results_recommend_a_new_reinforcement_check(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, candidates = _setup(monkeypatch, role_users)
    candidates.append(_candidate("bank:fractions:three", 2))
    zen = core.client("zen_trainer")
    events["attempt:one"] = _event(subject_id, "attempt:one", "zen:success", "bank:fractions:one")
    events["attempt:two"] = _event(
        subject_id, "attempt:two", "zen:error", "bank:fractions:two", is_correct=False,
    )
    zen.record_result(actor_id, subject_id, "attempt:one")
    zen.record_result(actor_id, subject_id, "attempt:two")

    goal = {"description": "Проверить сокращение дроби", "skill_id": SKILL_ID, "criterion_id": CRITERION_ID}
    decision = zen.next_practice(actor_id, subject_id, goal)
    assert decision["action"] == "reinforce"
    assert decision["candidate"]["exercise_id"] == "bank:fractions:three"
    assert decision["evidence"]["used_event_ids"] == ["zen:success", "zen:error"]
    assert "не подтверждает mastery" in decision["explanation"]["teacher"]


def test_blitz_event_is_visible_as_skill_history_to_real_course_projection(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, _ = _setup(monkeypatch, role_users)
    skill_id = "skill.inf.truth-table-equivalence"
    event_id = "blitz:logic:attempt-1"
    events["attempt:logic"] = _event(
        subject_id, "attempt:logic", event_id, "bank:logic:question-1",
        skill_id=skill_id, criterion_id="truth_table_equivalence",
    )
    core.client("blitz_quiz").record_result(actor_id, subject_id, "attempt:logic")

    import app.ai_lab.analytics as analytics
    import app.ai_lab.course_adapter as course_adapter
    import app.ai_lab.tutor_core as tutor_core
    from types import SimpleNamespace

    copy = SimpleNamespace(
        course_id=777, current_version=1, parent_course_id=1, title="Synthetic copy",
        learning_goal="", expected_result="", default_lesson_duration=60,
    )
    monkeypatch.setattr(analytics, "all_analytics_evidence", lambda **kwargs: [])
    monkeypatch.setattr(
        course_adapter, "resolve_assigned_synthetic_copy",
        lambda student_id: {"status": "resolved", "copy": copy},
    )

    cases = tutor_core._platform_profile_cases(actor_id)
    case = next(item for item in cases if item["profile_id"] == subject_id)
    history = next(item for item in case["stable_skill_history"] if item["skill_id"] == skill_id)
    assert history["event_ids"] == [event_id]
    assert case["current_lesson_evidence_count"] == 0
    assert next(row for row in case["evidence"] if row["event_id"] == event_id)["skill_history_use"] == (
        "retained_as_item_observation_for_stable_skill"
    )


def test_client_cannot_claim_a_result_from_an_unregistered_source(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, _ = _setup(monkeypatch, role_users)
    events["attempt:one"] = _event(subject_id, "different-source-id", "zen:attempt:one", "bank:fractions:one")
    with pytest.raises(TutorCoreContractError, match="не совпадает"):
        core.client("zen_trainer").record_result(actor_id, subject_id, "attempt:one")
    events["foreign-source"] = _event(
        "platform-student:999999", "foreign-source", "foreign:attempt:one", "bank:fractions:one",
    )
    with pytest.raises(TutorCoreContractError, match="не совпадает"):
        core.client("zen_trainer").record_result(actor_id, subject_id, "foreign-source")


def test_unallowlisted_subject_and_oversized_answer_are_rejected(app, monkeypatch, role_users):
    _stub_source_readers(monkeypatch)
    core, events, actor_id, subject_id, _ = _setup(monkeypatch, role_users)
    zen = core.client("zen_trainer")
    with pytest.raises(TutorCoreContractError, match="не входит в разрешённый synthetic allowlist"):
        zen.profile(actor_id, "platform-student:999999")

    with app.app_context():
        other_tutor = User(username="synthetic_other_tutor", email="other-tutor@example.test",
                           role="tutor", is_active=True)
        other_student = User(username="synthetic_other_student", email="other-student@example.test",
                             role="student", is_active=True)
        db.session.add_all([other_tutor, other_student])
        db.session.flush()
        other_tutor_id = other_tutor.id
        other_student_id = other_student.id
        db.session.commit()
    import app.ai_lab.platform_homework as platform_homework
    monkeypatch.setattr(platform_homework, "_allowlisted_actor_ids", lambda: {actor_id, other_tutor_id})
    with pytest.raises(TutorCoreContractError, match="нет доступа к этому ученику"):
        zen.profile(other_tutor_id, subject_id)
    with pytest.raises(TutorCoreContractError, match="нет доступа к этому ученику"):
        zen.profile(other_student_id, subject_id)

    with pytest.raises(TutorCoreContractError, match="Источник не подтвердил"):
        zen.record_result(actor_id, subject_id, "forged-source-record")
    with pytest.raises(TutorCoreContractError, match="стабильный ID исходной попытки"):
        zen.record_result(actor_id, subject_id, {"mastered": True})

    event = _event(subject_id, "attempt:large", "zen:large", "bank:fractions:one")
    event["response"]["value"] = "x" * 16_385
    events["attempt:large"] = event
    with pytest.raises(TutorCoreContractError, match="16 КБ"):
        zen.record_result(actor_id, subject_id, "attempt:large")
    assert AiLabExperiment.query.filter_by(scenario_id=CLIENT_EVENT_SCENARIO).count() == 0


def test_history_survives_core_restart_and_new_database_connection(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app import create_app
    import app.ai_lab.analytics as analytics
    import app.ai_lab.course_adapter as course_adapter
    import app.ai_lab.database_safety as database_safety
    import app.ai_lab.lesson_intelligence as lesson_intelligence
    import app.ai_lab.platform_homework as platform_homework
    import app.ai_lab.practice as practice
    import app.ai_lab.provider as provider
    import app.ai_lab.tutor_core as tutor_core

    database_path = tmp_path / "tutor-core-restart.sqlite"
    isolated_app = create_app({
        "TESTING": True,
        "SECRET_KEY": "tutor-core-restart-test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
    })
    with isolated_app.app_context():
        db.create_all()
        teacher = User(username="synthetic_restart_tutor", email="restart-tutor@example.test",
                       role="tutor", is_active=True)
        student_user = User(username="synthetic_restart_student", email="restart-student@example.test",
                            role="student", is_active=True)
        db.session.add_all([teacher, student_user])
        db.session.flush()
        student = Student(name="Restart fixture student", user_id=student_user.id, is_active=True)
        db.session.add(student)
        db.session.flush()
        teacher_id, student_user_id, student_id = teacher.id, student_user.id, student.student_id
        db.session.add(Enrollment(student_id=student_user_id, tutor_id=teacher_id,
                                  subject="Информатика", status="active"))
        db.session.commit()

        monkeypatch.setattr(database_safety, "has_verified_safe_ai_lab_db", lambda: True)
        monkeypatch.setattr(provider, "is_local_ai_lab_enabled", lambda: True)
        monkeypatch.setattr(platform_homework, "_allowlisted_user_ids", lambda: {student_user_id})
        monkeypatch.setattr(platform_homework, "_allowlisted_actor_ids", lambda: {teacher_id})
        monkeypatch.setattr(analytics, "stored_platform_homework_evidence", lambda **kwargs: [])
        monkeypatch.setattr(analytics, "stored_lesson_task_evidence", lambda **kwargs: [])
        monkeypatch.setattr(lesson_intelligence, "stored_lesson_evidence", lambda **kwargs: [])
        monkeypatch.setattr(practice, "stored_ai_practice_evidence", lambda **kwargs: [])
        monkeypatch.setattr(analytics, "all_analytics_evidence", lambda **kwargs: [])

        skill_id = "skill.inf.truth-table-equivalence"
        criterion_id = "truth_table_equivalence"
        subject_id = SUBJECT_ID.format(student_user_id)
        source_events = {}
        exercise_specs = [
            ("bank:logic:commutativity", "Эквивалентны ли A ∧ B и B ∧ A?", "yes", 2),
            ("bank:logic:distributivity", "Эквивалентны ли A ∧ (B ∨ C) и (A ∧ B) ∨ (A ∧ C)?", "yes", 3),
        ]
        candidates = []
        for exercise_id, prompt, answer_key, difficulty in exercise_specs:
            candidates.append({
                "exercise": {
                    "exercise_id": exercise_id, "prompt": prompt, "answer_type": "single_choice",
                    "answer_key": answer_key, "skill_ids": [skill_id], "difficulty": difficulty,
                },
                "criterion_ids": [criterion_id],
                "source": {
                    "kind": "task_bank", "status": "verified", "source_id": exercise_id,
                    "version": 1, "content_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "checker_id": "truth-table-equivalence-v1", "checker_version": "1.0",
                },
            })

        adapter = ClientAdapter(
            source_modules=frozenset({"ai_tutor_core"}),
            resolve_event=lambda actor_id, subject, source_id: source_events.get(source_id),
            resolve_skill=lambda requested_skill, requested_criterion: ({
                "skill_id": skill_id, "title": "Эквивалентность логических выражений",
                "criterion_id": criterion_id,
                "criterion_description": "Проверяет равенство выражений для всех наборов входов.",
                "question_type": "single_choice",
                "answer_requirements": "Да или нет, обоснованное таблицей истинности.",
            } if (requested_skill, requested_criterion) == (skill_id, criterion_id) else None),
            list_candidates=lambda subject, requested_skill, requested_criterion: (
                candidates if (requested_skill, requested_criterion) == (skill_id, criterion_id) else []
            ),
        )
        goal = {
            "description": "Проверить эквивалентность выражений по таблице истинности",
            "skill_id": skill_id, "criterion_id": criterion_id,
        }

        initial_core = TutorCoreV1()
        for client_id in ("zen_trainer", "blitz_quiz", "adaptive_course"):
            initial_core.register_client(client_id, adapter)
        zen = initial_core.client("zen_trainer")
        cold_start = zen.next_practice(teacher_id, subject_id, goal)
        assert cold_start["action"] == "diagnostic_start"
        assert cold_start["candidate"]["exercise_id"] == "bank:logic:commutativity"
        assert "answer_key" not in cold_start["candidate"]

        source_events["trusted-attempt-1"] = _event(
            subject_id, "trusted-attempt-1", "blitz:logic:attempt-1", "bank:logic:commutativity",
            course_version=1, skill_id=skill_id, criterion_id=criterion_id,
        )
        assert zen.record_result(teacher_id, subject_id, "trusted-attempt-1")["stored"] is True
        assert zen.record_result(teacher_id, subject_id, "trusted-attempt-1")["duplicate"] is True
        del initial_core, zen
        db.session.remove()

        engine = db.engine
        with engine.connect() as connection:
            previous_dbapi_connection = connection.connection.driver_connection
        engine.dispose()
        with engine.connect() as connection:
            assert connection.connection.driver_connection is not previous_dbapi_connection
        db.session.remove()

        restarted_core = TutorCoreV1()
        for client_id in ("zen_trainer", "blitz_quiz", "adaptive_course"):
            restarted_core.register_client(client_id, adapter)
        blitz = restarted_core.client("blitz_quiz")
        profile = blitz.profile(teacher_id, subject_id)
        assert profile["evidence"]["event_count"] == 1
        assert profile["evidence"]["events"][0]["event_id"] == "blitz:logic:attempt-1"
        assert blitz.record_result(teacher_id, subject_id, "trusted-attempt-1")["duplicate"] is True
        specification = blitz.quiz_specification(
            teacher_id, subject_id, skill_id=skill_id, criterion_id=criterion_id, question_count=2,
        )
        assert [item["exercise_id"] for item in specification["existing_candidates"]] == [
            "bank:logic:distributivity",
        ]

        copy = SimpleNamespace(
            course_id=777, current_version=1, parent_course_id=1, title="Synthetic course copy",
            learning_goal="", expected_result="", default_lesson_duration=60,
        )
        monkeypatch.setattr(
            course_adapter, "resolve_assigned_synthetic_copy",
            lambda requested_student_id: ({"status": "resolved", "copy": copy}
                                          if requested_student_id == student_id else {"status": "unavailable"}),
        )
        course = restarted_core.client("adaptive_course")
        recommendation = course.course_recommendation(teacher_id, subject_id, expected_course_id=777)
        assert recommendation["status"] == "resolved"
        assert recommendation["course_mutated"] is False

        course_case = next(item for item in tutor_core._platform_profile_cases(teacher_id)
                           if item["profile_id"] == subject_id)
        skill_history = next(item for item in course_case["stable_skill_history"]
                             if item["skill_id"] == skill_id)
        assert skill_history["event_ids"] == ["blitz:logic:attempt-1"]
        assert course_case["current_lesson_evidence_count"] == 0
        db.session.remove()
        db.engine.dispose()

