import re

import pytest

from app.ai_lab import practice
from app.ai_lab.practice import grade_practice_answer, select_next_practice_exercise


@pytest.fixture()
def adaptive_practice_app():
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "adaptive-practice-test-only",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "ENVIRONMENT": "local",
        "AI_LAB_ENABLED": True,
        # The real app sets these only after the file identity check. In this
        # isolated unit fixture, the database is a private in-memory SQLite.
        "AI_LAB_SAFE_DB_PATH": "<test-memory-sqlite>",
        "AI_LAB_SAFE_DB_IDENTITY": (1, 1),
    })
    with app.app_context():
        db.create_all()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()


def _exercise(exercise_id: str, *, difficulty: int = 2, answer_type: str = "numeric", answer_key=42):
    return {
        "exercise_id": exercise_id,
        "exercise_version": 1,
        "prompt": f"Синтетическое условие {exercise_id}",
        "answer_type": answer_type,
        "answer_key": answer_key,
        "skill_ids": ["skill.inf.numeric-reasoning"],
        "difficulty": difficulty,
        "topic_id": "topic.synthetic.numeric",
    }


def test_synthetic_course_practice_context_is_preserved_and_skill_bound():
    from app.ai_lab.learning_evidence import EvidenceContractError, EVIDENCE_CONTRACT_VERSION, validate_evidence_event

    raw = {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": "practice-session:synthetic:exercise:1",
        "subject_id": "platform-student:506",
        "source_module": "ai_practice",
        "source_record_id": "practice-attempt:507",
        "occurred_at": "2026-10-24T10:00:00+00:00",
        "evidence_status": "technical_confirmed",
        "assignment": None,
        "course_context": {
            "contract": "boostudy.synthetic-practice-course-context.v1",
            "course_id": 508,
            "course_version": 2,
            "lesson_id": 509,
            "skill_id": "skill.inf.ipv4.subnet-mask",
            "course_skill_id": "exam-skill:1",
            "topic_code": "ege.inf.ipv4.subnet-mask.v1",
        },
        "topic_ids": ["ege.inf.ipv4.subnet-mask.v1"],
        "skill_ids": ["skill.inf.ipv4.subnet-mask"],
        "limitations": ["Проверен один синтетический вариант."],
        "error_codes": [],
        "outcome": {"score": 1, "maximum": 1, "status": "complete"},
        "criteria": [{
            "criterion_id": "practice-answer",
            "status": "met",
            "earned": 1,
            "maximum": 1,
            "skill_id": "skill.inf.ipv4.subnet-mask",
            "reason": "Ответ прошёл штатную проверку.",
            "source_refs": ["platform-practice:507:attempt:1"],
        }],
        "assistance": {"level": "no_platform_hint", "source_refs": []},
        "provenance": {
            "source_ref": "practice-session:synthetic:exercise:1",
            "payload_hash": "a" * 64,
            "model": "",
            "method": "parameterized-generator+deterministic-short-answer-checker",
        },
    }

    normalized = validate_evidence_event(raw)
    assert normalized["course_context"] == raw["course_context"]

    mapped = {
        **normalized,
        "skill_ids": ["exam-skill:1"],
        "criteria": [{**normalized["criteria"][0], "skill_id": "exam-skill:1"}],
    }
    assert validate_evidence_event(mapped)["course_context"] == raw["course_context"]

    raw["criteria"][0]["skill_id"] = "skill.inf.other"
    with pytest.raises(EvidenceContractError, match="Контекст практики не совпадает"):
        validate_evidence_event(raw)


def test_grade_supported_short_answer_formats_and_rejects_unverified_types():
    assert grade_practice_answer(_exercise("n1"), "42") == {
        "verification_status": "verified",
        "is_correct": True,
        "reason": "Ответ совпал с проверенным эталоном.",
        "correct_answer": 42,
    }
    assert grade_practice_answer(
        _exercise("t1", answer_type="short_text", answer_key="Сумма элементов"),
        "  Сумма   элементов ",
    )["is_correct"] is True
    assert grade_practice_answer(
        _exercise("c1", answer_type="single_choice", answer_key="option-b"), "option-a"
    )["is_correct"] is False
    assert grade_practice_answer(
        _exercise("m1", answer_type="multi_select", answer_key=["a", "c"]), ["c", "a"]
    )["is_correct"] is True
    assert grade_practice_answer({**_exercise("code1"), "answer_type": "python"}, "...")["verification_status"] == "unverified"


def test_selector_starts_diagnostically_and_does_not_expose_answer_key():
    selected = select_next_practice_exercise([_exercise("n1")], skill_id="skill.inf.numeric-reasoning")

    assert selected["action"] == "diagnostic_start"
    assert selected["exercise"]["exercise_id"] == "n1"
    assert "answer_key" not in selected["exercise"]


def test_two_distinct_independent_successes_allow_only_one_level_increase():
    exercises = [_exercise("n3", difficulty=3), _exercise("n4", difficulty=4)]
    history = [
        {"exercise_id": "n1", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 2,
         "verification_status": "verified", "is_correct": True, "assistance_level": "independent"},
        {"exercise_id": "n2", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 3,
         "verification_status": "verified", "is_correct": True, "assistance_level": "independent"},
    ]

    selected = select_next_practice_exercise(exercises, skill_id="skill.inf.numeric-reasoning", attempts=history)

    assert selected["action"] == "increase_difficulty"
    assert selected["exercise"]["exercise_id"] == "n4"
    assert "без вывода об освоении" in selected["reason"]


def test_two_successes_without_boodstudy_hint_raise_level_without_claiming_independence():
    exercises = [_exercise("n3", difficulty=3), _exercise("n4", difficulty=4)]
    history = [
        {"exercise_id": "n1", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 2,
         "verification_status": "verified", "is_correct": True, "assistance_level": "no_platform_hint"},
        {"exercise_id": "n2", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 3,
         "verification_status": "verified", "is_correct": True, "assistance_level": "no_platform_hint"},
    ]

    selected = select_next_practice_exercise(exercises, skill_id="skill.inf.numeric-reasoning", attempts=history)

    assert selected["action"] == "increase_difficulty"
    assert "Внешняя помощь не наблюдалась" in selected["reason"]
    assert "без вывода об освоении" in selected["reason"]


def test_one_success_or_unknown_assistance_never_counts_as_independent_pair():
    history = [
        {"exercise_id": "n1", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 2,
         "verification_status": "verified", "is_correct": True, "assistance_level": None},
    ]
    selected = select_next_practice_exercise([_exercise("n2", difficulty=3)],
                                             skill_id="skill.inf.numeric-reasoning", attempts=history)

    assert selected["action"] == "transfer_check"
    assert selected["exercise"]["exercise_id"] == "n2"


def test_wrong_attempt_reinforces_and_exhausted_catalog_does_not_repeat():
    history = [{"exercise_id": "n1", "skill_id": "skill.inf.numeric-reasoning", "difficulty": 3,
                "verification_status": "verified", "is_correct": False, "assistance_level": None}]
    next_item = select_next_practice_exercise([_exercise("n2", difficulty=2)],
                                              skill_id="skill.inf.numeric-reasoning", attempts=history)
    exhausted = select_next_practice_exercise([_exercise("n1", difficulty=3)],
                                              skill_id="skill.inf.numeric-reasoning", attempts=history)

    assert next_item["action"] == "reinforce"
    assert next_item["exercise"]["exercise_id"] == "n2"
    assert exhausted["exercise"] is None
    assert exhausted["action"] == "pause"


def test_parameterized_generators_are_repeatable_and_have_independent_exact_answers(monkeypatch):
    metadata = {
        "skill.inf.ipv4.subnet-mask": ("ege.inf.ip-prefix-mask.v1", "IPv4", 4),
        "skill.inf.graph.optimal-paths": ("ege.inf.graph.optimal-paths.v1", "Оптимальный путь", 1),
        "skill.inf.graph-degree": ("ege.inf.graph-degree.v1", "Графы", 1),
        "skill.inf.media-volume": ("ege.inf.image-sound-volume.v1", "Объём данных", 1),
        "skill.inf.truth-table-equivalence": ("ege.inf.logic-truth-table.v1", "Логика", 1),
        "skill.inf.python-sequence": ("ege.inf.python-sequence-processing.v1", "Последовательность", 1),
    }
    monkeypatch.setattr(practice, "list_practice_skills", lambda: [
        {"skill_id": skill_id, "title": title, "knowledge_stable_key": stable_key,
         "knowledge_version": version, "knowledge_status": "source_checked"}
        for skill_id, (stable_key, title, version) in metadata.items()
    ])

    for skill_id in metadata:
        first = practice.build_practice_exercise(skill_id, "independent-seed-2026")
        second = practice.build_practice_exercise(skill_id, "independent-seed-2026")
        assert first == second
        assert grade_practice_answer(first, first["answer_key"])["is_correct"] is True
        assert first["knowledge_ref"]["status"] == "source_checked"


def test_graph_optimal_path_generator_is_exhaustively_verifiable(monkeypatch):
    skill_id = "skill.inf.graph.optimal-paths"
    monkeypatch.setattr(practice, "list_practice_skills", lambda: [{
        "skill_id": skill_id,
        "title": "Оптимальный путь в графе",
        "knowledge_stable_key": "ege.inf.graph.optimal-paths.v1",
        "knowledge_version": 1,
        "knowledge_status": "source_checked",
    }])

    exercise = practice.build_practice_exercise(skill_id, "graph-path-independent-check", difficulty=4)
    assert exercise["answer_type"] == "numeric"
    assert exercise["criterion_id"] == "result_check"
    assert exercise["topic_id"] == "ege.inf.graph.optimal-paths.v1"
    assert exercise["knowledge_ref"]["stable_key"] == "ege.inf.graph.optimal-paths.v1"

    adjacency = {}
    for left, right, weight in re.findall(r"([A-F])→([A-F]) \((\d+)\)", exercise["prompt"]):
        adjacency.setdefault(left, []).append((right, int(weight)))
    destination = max(adjacency)
    route_costs = []

    def enumerate_routes(vertex, cost):
        if vertex == destination:
            route_costs.append(cost)
            return
        for neighbor, weight in adjacency.get(vertex, []):
            enumerate_routes(neighbor, cost + weight)

    enumerate_routes("A", 0)
    assert len(route_costs) >= 3
    assert route_costs.count(min(route_costs)) == 1
    assert min(route_costs) == exercise["answer_key"]
    assert grade_practice_answer(exercise, str(min(route_costs)))["is_correct"] is True
    assert grade_practice_answer(exercise, str(max(route_costs)))["is_correct"] is False


def test_session_and_attempt_persist_with_idempotent_retries(adaptive_practice_app, monkeypatch):
    from app import db
    from core.db_models import AiLabExperiment, Student, User

    skill_id = "skill.inf.python-sequence"
    monkeypatch.setattr(practice, "list_practice_skills", lambda: [{"skill_id": skill_id}])
    monkeypatch.setattr(
        practice,
        "_practice_candidates",
        lambda _skill, session_id, attempt_no: [
            {**_exercise(f"{session_id}:{attempt_no}"), "title": "Числовая диагностика",
             "skill_ids": [skill_id], "topic_id": "ege.inf.python-sequence-processing.v1",
             "criterion_id": "state_updates",
             "knowledge_ref": {"stable_key": "ege.inf.python-sequence-processing.v1", "version": 1, "status": "source_checked"},
             "hint": "Сверьте числа.",
             "explanation": "Эталон проверен.", "difficulty": 2}
        ],
    )
    with adaptive_practice_app.app_context():
        learner_user = User(username="demo_adaptive_learner", role="student", is_active=True)
        db.session.add(learner_user)
        db.session.flush()
        learner = Student(user_id=learner_user.id, name="Synthetic Learner")
        db.session.add(learner)
        db.session.commit()
        subject_id = f"platform-student:{learner_user.id}"

        first = practice.start_practice_session(learner_user.id, subject_id, skill_id,
                                                mode="diagnostic", idempotency_key="start-key-0001")
        retry = practice.start_practice_session(learner_user.id, subject_id, skill_id,
                                                mode="diagnostic", idempotency_key="start-key-0001")
        assert retry["session_id"] == first["session_id"]
        assert "answer_key" not in first["current_exercise"]

        feedback = practice.submit_practice_answer(
            learner_user.id, first["session_id"], 42, "attempt-key-0001"
        )
        duplicate = practice.submit_practice_answer(
            learner_user.id, first["session_id"], 0, "attempt-key-0001"
        )
        assert duplicate == feedback
        assert feedback["is_correct"] is True
        assert practice.get_practice_session(learner_user.id, first["session_id"])["awaiting_next"] is True

        db.session.remove()
        persisted = practice.practice_history(subject_id)
        assert len(persisted) == 1
        assert persisted[0]["is_correct"] is True
        events = practice.stored_ai_practice_evidence(actor_user_id=learner_user.id)
        assert len(events) == 1
        event = events[0]
        assert event["assistance"]["level"] == "no_platform_hint"
        assert event["criteria"][0]["status"] == "met"
        assert event["criteria"][0]["criterion_id"] == "state_updates"
        assert event["criteria"][0]["earned"] == event["outcome"]["score"] == 1
        assert event["outcome"]["status"] == "complete"
        from app.ai_lab.tutor_core31 import _event_summary, _result_record, _skill_state
        result = _result_record(event, skill_id, "met", event["criteria"][0]["reason"])
        state = _skill_state(skill_id, [result])
        assert state["state"] == "success_help_unobserved"
        assert state["independent_success_count"] == 0
        summary = _event_summary(event)
        assert summary["assistance_source_kind"] == "platform_hint_log"
        assert "внешняя помощь не наблюдалась" in summary["assistance_source_label"].lower()
        assert AiLabExperiment.query.filter_by(scenario_id=practice.PRACTICE_SESSION_SCENARIO).count() == 1
        assert AiLabExperiment.query.filter_by(scenario_id=practice.PRACTICE_ATTEMPT_SCENARIO).count() == 1
        from app.ai_lab.analytics import stored_lesson_task_evidence
        assert stored_lesson_task_evidence(actor_user_id=learner_user.id) == []

        practice.finish_practice_session(learner_user.id, first["session_id"])
        next_session = practice.start_practice_session(
            learner_user.id, subject_id, skill_id, mode="continue", idempotency_key="start-key-0002"
        )
        assert next_session["decision"]["action"] == "transfer_check"
        assert next_session["session_id"] != first["session_id"]
