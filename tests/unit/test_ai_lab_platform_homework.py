"""Focused synthetic regressions for the opt-in platform Homework bridge."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask import Flask

from app.ai_lab import platform_homework as bridge
from app.ai_lab import config as lab_config
from app.ai_lab.learning_evidence import EvidenceContractError, validate_evidence_event


@pytest.fixture
def app_context():
    app = Flask("ai-lab-platform-homework-test")
    app.config.update(ENVIRONMENT="local", AI_LAB_ENABLED=True)
    return app


def test_platform_path_fails_closed_and_requires_local_allowlisted_account(app_context, monkeypatch):
    app_context.config.update(
        ENVIRONMENT="local",
        AI_LAB_ENABLED=True,
        AI_LAB_PLATFORM_HOMEWORK_ENABLED=True,
        AI_LAB_PLATFORM_TEST_USER_IDS="17, 23",
        AI_LAB_PLATFORM_TEST_ACTOR_IDS="17",
    )
    monkeypatch.setenv("ENVIRONMENT", "local")
    with app_context.app_context():
        assert bridge.platform_homework_enabled(17)
        assert not bridge.platform_homework_enabled(23)
        assert not bridge.platform_homework_enabled(18)
        app_context.config["AI_LAB_PLATFORM_HOMEWORK_ENABLED"] = False
        assert not bridge.platform_homework_enabled(17)


def test_synthetic_user_allowlist_can_be_loaded_from_local_dotenv(app_context, monkeypatch, tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("AI_LAB_PLATFORM_TEST_USER_IDS=9311001,9312001\n", encoding="utf-8")
    monkeypatch.setattr(lab_config, "DOTENV_PATH", dotenv_path)
    monkeypatch.delenv("AI_LAB_PLATFORM_TEST_USER_IDS", raising=False)

    with app_context.app_context():
        assert bridge._allowlisted_user_ids() == {9311001, 9312001}


def test_safe_synthetic_mode_never_reads_project_dotenv(monkeypatch, tmp_path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "AI_LAB_PLATFORM_TEST_USER_IDS=999\nGIGACHAT_AUTH_KEY=must-not-be-loaded\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(lab_config, "DOTENV_PATH", dotenv_path)
    monkeypatch.setenv("AI_LAB_SAFE_DB_MODE", "1")
    monkeypatch.delenv("AI_LAB_PLATFORM_TEST_USER_IDS", raising=False)
    monkeypatch.delenv("GIGACHAT_AUTH_KEY", raising=False)

    assert lab_config.local_dotenv_values() == {}
    assert lab_config.setting_with_source("GIGACHAT_AUTH_KEY") == ("", "значение по умолчанию")


def test_linkable_task_scope_is_applied_before_result_limit(app_context, monkeypatch):
    class Column:
        def __init__(self, name):
            self.name = name

        def isnot(self, _value):
            return ("not-null", self.name)

        def in_(self, values):
            return ("in", self.name, tuple(sorted(values)))

        def desc(self):
            return ("desc", self.name)

    class Query:
        def __init__(self, rows):
            self.rows = rows
            self.filters = []
            self.limit_value = None

        def filter(self, *conditions):
            self.filters.extend(conditions)
            return self

        def order_by(self, _ordering):
            return self

        def limit(self, value):
            self.limit_value = value
            return self

        def all(self):
            return self.rows

    task = SimpleNamespace(
        task_id=7, created_by_id=4, answer_spec={"type": "code", "grading_mode": "auto"},
        content_html="SYNTHETIC ONLY · Python diagnostic", max_score=3, course_id=None,
    )
    query = Query([task])
    monkeypatch.setattr(bridge, "Tasks", SimpleNamespace(
        query=query, answer_spec=Column("answer_spec"), created_by_id=Column("created_by_id"),
        task_id=Column("task_id"),
    ))
    monkeypatch.setattr(bridge, "_allowlisted_task_author_ids", lambda: {4})
    monkeypatch.setattr(bridge, "platform_homework_enabled", lambda _user_id: True)

    with app_context.app_context():
        result = bridge.list_linkable_tasks(4)

    assert result[0]["task_id"] == 7
    assert ("in", "created_by_id", (4,)) in query.filters
    assert query.limit_value == 500


def test_bound_python_task_uses_code_judge_on_separate_submission(app_context, monkeypatch):
    from app.assignments import routes as assignment_routes

    task = SimpleNamespace(answer_spec={"type": "code", "grading_mode": "auto", "code_judge_binding": {"test_set_id": 1}})
    assignment_task = SimpleNamespace(task=task)
    expected = (True, 3)
    monkeypatch.setattr(assignment_routes, "platform_homework_enabled", lambda user_id: user_id == 12)
    monkeypatch.setattr(assignment_routes, "grade_bound_answer", lambda *_args: expected)
    monkeypatch.setattr(assignment_routes, "auto_grade_answer", lambda *_args: pytest.fail("legacy grading must not run"))

    with app_context.app_context():
        assert assignment_routes._grade_submission_answer(SimpleNamespace(), assignment_task, 12) == expected


def test_confirmed_platform_criterion_preserves_explicit_course_skill_mapping():
    from app.ai_lab.analytics import _confirmed_code_judge_report

    technical = {
        "report_type": "platform_code_judge_evidence_v1", "status": "completed", "run_status": "complete",
        "test_set_id": 8, "test_set_version": 2, "rubric_version": 3,
        "passed": 2, "failed": 0, "total": 2,
        "rubric": {
            "confirmed_score": 2, "confirmed_max_score": 2, "max_score": 2,
            "unconfirmed_max_score": 0,
            "criteria": [{"id": "base-representation", "skill_id": "exam-skill:14",
                "status": "fulfilled", "score_awarded": 2, "max_score": 2, "rationale": "Пройдено."}],
        },
    }

    complete, rubric = _confirmed_code_judge_report("completed", technical)
    criterion = rubric["criteria"][0]

    assert complete is True
    assert criterion["skill_id"] == "exam-skill:14"


def test_codejudge_grade_uses_bound_version_and_returns_only_confirmed_score(app_context, monkeypatch):
    app_context.config.update(
        ENVIRONMENT="local",
        AI_LAB_ENABLED=True,
        AI_LAB_PLATFORM_HOMEWORK_ENABLED=True,
        AI_LAB_PLATFORM_TEST_USER_IDS="23",
    )
    monkeypatch.setenv("ENVIRONMENT", "local")
    cases = [
        {"id": "visible-one", "name": "Положительное", "visibility": "public", "args": [3], "expected": 1},
        {"id": "secret-case", "name": "Секретный тест", "visibility": "hidden", "args": [-8], "expected": 2},
    ]
    rubric = [{
        "id": "criterion-main", "title": "Корректность", "description": "Верный результат",
        "max_score": 3, "policy": "all_or_nothing", "scoring_rule": "all_required", "checks": [],
    }]
    test_set = SimpleNamespace(id=8, test_set_version=2, rubric_version=3)
    task = SimpleNamespace(task_id=42, max_score=3, answer_spec={"code_judge_binding": {
        "test_set_id": 8, "test_set_version": 2, "rubric_version": 3, "task_fingerprint": "fingerprint",
    }})
    assignment_task = SimpleNamespace(task=task, assignment_task_id=99, max_score=3)
    answer = SimpleNamespace(student_code="def solve(n): return n % 3")
    raw_result = {
        "complete": True, "passed": 2, "failed": 0, "total": 2, "duration_ms": 11, "runner_version": "runner-test",
        "tests": [
            {"id": "visible-one", "status": "passed", "actual": 1},
            {"id": "secret-case", "status": "passed", "actual": 2},
        ],
        "rubric": {
            "criteria": [{"id": "criterion-main", "title": "Корректность", "description": "Верный результат",
                "skill_id": "exam-skill:14",
                "max_score": 3, "status": "fulfilled", "score_awarded": 3, "rationale": "Все связанные тесты пройдены.",
                "evidence": [{"case_id": "visible-one", "status": "passed", "expected": 1, "actual": 1},
                             {"case_id": "secret-case", "status": "passed", "expected": 2, "actual": 2}]}],
            "confirmed_score": 3, "confirmed_max_score": 3, "unconfirmed_max_score": 0, "max_score": 3,
        },
    }
    monkeypatch.setattr(bridge, "platform_homework_enabled", lambda user_id: user_id == 23)
    monkeypatch.setattr(bridge, "_task_fingerprint", lambda _task: "fingerprint")
    monkeypatch.setattr(bridge, "db", SimpleNamespace(session=SimpleNamespace(get=lambda _model, _id: test_set)))
    monkeypatch.setattr(bridge, "_serialize_test_set", lambda _set: {})
    monkeypatch.setattr(bridge, "validate_test_set", lambda _payload: {"test_cases": cases, "rubric_json": rubric})
    monkeypatch.setattr(bridge, "_run_code", lambda _code, _set: raw_result)

    with app_context.app_context():
        correct, score = bridge.grade_bound_answer(answer, assignment_task, 23)

    assert (correct, score) == (True, 3), answer._platform_code_judge_report
    report = answer._platform_code_judge_report
    assert report["limited_test_set"] is True
    hidden = next(item for item in report["tests"] if item["visibility"] == "hidden")
    assert hidden["id"] == "hidden-2"
    assert "actual" not in hidden
    assert "expected" not in str(report)
    assert report["rubric"]["criteria"][0]["skill_id"] == "exam-skill:14"


def test_student_payload_never_includes_teacher_comment_or_hidden_test_values():
    review = SimpleNamespace(
        status="completed", summary_for_teacher="СЛУЖЕБНЫЙ КОММЕНТАРИЙ", error_message=None,
        teacher_review_required=True,
        task_reviews=[{
            "task_id": 42, "assignment_task_id": 99, "student_feedback": "Проверь граничный случай.",
            "teacher_feedback": "СЛУЖЕБНЫЙ КОММЕНТАРИЙ",
            "technical": {
                "task_id": 42,
                "tests": [{"id": "hidden-1", "expected": "SECRET"}],
                "rubric": {"criteria": [{"id": "c1", "title": "Корректность", "description": "Проверка",
                    "max_score": 3, "status": "fulfilled", "score_awarded": 3, "rationale": "Проверки пройдены."}]},
            },
        }],
    )

    payload = bridge.student_review_payload(review)

    assert payload["tasks"][0]["student_feedback"] == "Проверь граничный случай."
    assert "СЛУЖЕБНЫЙ КОММЕНТАРИЙ" not in str(payload)
    assert "SECRET" not in str(payload)
    assert "tests" not in payload["tasks"][0]["technical"]


def test_platform_review_reloads_answer_after_submission_commit(app_context, monkeypatch):
    class SortColumn:
        @staticmethod
        def desc():
            return "revision_desc"

    class ReviewQuery:
        def filter_by(self, **_filters):
            return self

        def order_by(self, *_ordering):
            return self

        def first(self):
            return None

    class Review:
        query = ReviewQuery()
        revision_no = SortColumn()

        def __init__(self, **values):
            self.__dict__.update(values)

    class DetachedAnswer:
        answer_id = 71

        @property
        def assignment_task(self):
            raise AssertionError("detached relationship must not be accessed")

    task = SimpleNamespace(task_id=42, content_html="Synthetic task")
    assignment_task = SimpleNamespace(task=task, assignment_task_id=99)
    persisted_answer = SimpleNamespace(
        assignment_task=assignment_task,
        student_code="def solve(): return 1",
        value="",
    )
    submission = SimpleNamespace(attempts=[])
    session = SimpleNamespace(
        get=lambda model, identifier: submission if model is bridge.Submission else persisted_answer,
        add=lambda _row: None,
        commit=lambda: None,
    )
    monkeypatch.setattr(bridge, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(bridge, "SubmissionAiReview", Review)
    monkeypatch.setattr(
        "app.assignments.ai_review_service.compute_submission_hash",
        lambda _submission: "synthetic-hash",
    )

    with app_context.app_context():
        result = bridge.save_platform_submission_review(
            501,
            [(DetachedAnswer(), {"status": "sandbox_unavailable", "error_code": "runner_unavailable"})],
        )

    assert result.status == "unavailable"
    assert result.error_code == "CODE_JUDGE_INCOMPLETE"
    assert result.task_reviews[0]["assignment_task_id"] == 99


def test_platform_review_can_persist_code_judge_without_calling_gigachat(app_context, monkeypatch):
    class SortColumn:
        @staticmethod
        def desc():
            return "revision_desc"

    class ReviewQuery:
        def filter_by(self, **_filters):
            return self

        def order_by(self, *_ordering):
            return self

        def first(self):
            return None

    class Review:
        query = ReviewQuery()
        revision_no = SortColumn()

        def __init__(self, **values):
            self.__dict__.update(values)

    class DetachedAnswer:
        answer_id = 81

        @property
        def assignment_task(self):
            raise AssertionError("the committed answer must be reloaded")

    assignment_task = SimpleNamespace(
        task=SimpleNamespace(task_id=43, content_html="Synthetic task"),
        assignment_task_id=100,
    )
    persisted_answer = SimpleNamespace(
        assignment_task=assignment_task,
        student_code="def solve(): return 1",
        value="",
    )
    submission = SimpleNamespace(attempts=[])
    session = SimpleNamespace(
        get=lambda model, _identifier: submission if model is bridge.Submission else persisted_answer,
        add=lambda _row: None,
        commit=lambda: None,
    )
    monkeypatch.setattr(bridge, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(bridge, "SubmissionAiReview", Review)
    monkeypatch.setattr(
        "app.assignments.ai_review_service.compute_submission_hash",
        lambda _submission: "synthetic-code-judge-hash",
    )
    monkeypatch.setattr(
        bridge, "_feedback_for_submission",
        lambda *_args: pytest.fail("GigaChat must not be called for a technical-only review"),
    )

    with app_context.app_context():
        result = bridge.save_platform_submission_review(
            601,
            [(DetachedAnswer(), {"status": "completed", "score_awarded": 1})],
            generate_gigachat_feedback=False,
        )

    assert result.status == "completed"
    assert result.provider == "code_judge"
    assert result.model is None
    assert "не запрашивался" in result.summary_for_teacher
    assert result.task_reviews[0]["assignment_task_id"] == 100


def test_platform_analytics_contract_preserves_submission_and_attempt_references():
    refs = {
        "submission_id": 501, "attempt_id": 502, "assignment_id": 503,
        "assignment_task_id": 504, "task_id": 505, "student_id": 506,
        "review_id": 507, "code_judge_test_set_id": 508,
        "code_judge_test_set_version": 2, "rubric_version": 3,
    }
    raw = {
        "contract_version": "boostudy.learning-evidence.v1",
        "event_id": "platform-submission:501:attempt:1:task:505",
        "subject_id": "platform-student:506", "source_module": "ai_homework",
        "source_record_id": "submission:501", "occurred_at": "2026-10-21T10:00:00+00:00",
        "evidence_status": "technical_confirmed",
        "assignment": {"id": "platform-assignment:503", "version": 1},
        "topic_ids": [], "skill_ids": [], "error_codes": [], "limitations": [],
        "outcome": {"score": 3, "maximum": 3, "status": "complete"},
        "criteria": [], "provenance": {"source_ref": "platform-submission:501:attempt:1:task:505"},
        "platform_refs": refs,
    }

    normalized = validate_evidence_event(raw)

    assert normalized["platform_refs"] == {**refs, "course_id": None, "lesson_id": None}
    raw["platform_refs"]["submission_id"] = "501"
    with pytest.raises(EvidenceContractError, match="положительным целым числом"):
        validate_evidence_event(raw)


def test_voided_evaluation_keeps_link_metadata_but_never_counts_as_skill_evidence():
    from app.ai_lab.analytics import build_analytics_snapshot

    raw = {
        "contract_version": "boostudy.learning-evidence.v2",
        "event_id": "platform-submission:601:attempt:1:task:605",
        "subject_id": "platform-student:606",
        "source_module": "ai_homework",
        "source_record_id": "submission:601",
        "occurred_at": "2026-10-24T10:00:00+00:00",
        "evidence_status": "insufficient_data",
        "assignment": {"id": "platform-assignment:603", "version": 1},
        "topic_ids": [],
        "skill_ids": ["exam-skill:1"],
        "error_codes": [],
        "limitations": [],
        "outcome": {"score": None, "maximum": 1, "status": "insufficient_data"},
        "criteria": [{
            "criterion_id": "transfer",
            "status": "insufficient_data",
            "earned": None,
            "maximum": 1,
            "evidence_status": "insufficient_data",
            "skill_id": "exam-skill:1",
            "reason": "Оценка явно отменена.",
            "source_refs": ["submission:601:answer:7"],
        }],
        "provenance": {
            "source_ref": "platform-submission:601:attempt:1:task:605",
            "payload_hash": "",
            "model": "",
            "method": "teacher_manual",
            "evaluation_revision": {
                "id": 3, "revision_no": 3, "method": "teacher_manual",
                "actor_user_id": 1, "state": "voided",
            },
        },
    }

    normalized = validate_evidence_event(raw)
    assert normalized["skill_ids"] == ["exam-skill:1"]
    snapshot = build_analytics_snapshot([normalized], "platform-student:606")
    assert snapshot["skills"][0]["confirmed_evidence"] == 0
    assert snapshot["skills"][0]["status"] == "insufficient_data"

    raw["evidence_status"] = "technical_confirmed"
    raw["outcome"] = {"score": 1, "maximum": 1, "status": "complete"}
    raw["criteria"][0].update({
        "status": "met", "earned": 1, "evidence_status": "technical_confirmed",
    })
    with pytest.raises(EvidenceContractError, match="Происхождение оценки содержит недопустимые значения"):
        validate_evidence_event(raw)
