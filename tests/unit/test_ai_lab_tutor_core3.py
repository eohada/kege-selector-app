"""Synthetic-only regression checks for the Tutor Core 3.0 EGE revision demo."""
from __future__ import annotations

import pytest


@pytest.fixture()
def tutor_core3_app():
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "SKIP_DATABASE_BOOTSTRAP": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "tutor-core3-test-only",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "ENVIRONMENT": "local",
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


def test_ege_revision_manifest_preserves_2026_and_labels_2027_project():
    from app.ai_lab.exam_revisions import revision_manifest

    manifest = revision_manifest()
    by_year = {item["exam_year"]: item for item in manifest}
    assert by_year[2026]["document_status"] == "approved"
    assert by_year[2027]["document_status"] == "project"
    old_2026 = {(item["task_number"], item["skill_code"]) for item in by_year[2026]["mappings"]}
    new_2027 = {(item["task_number"], item["skill_code"]) for item in by_year[2027]["mappings"]}
    assert (13, "ege.inf.ipv4.subnet-mask.v1") in old_2026
    assert (10, "ege.inf.ipv4.subnet-mask.v1") in new_2027
    assert (13, "ege.inf.algorithm.execution-trace.v1") in new_2027
    assert (23, "ege.inf.graph.dag-path-count.v1") in new_2027
    assert (27, "ege.inf.task27.answer-format.v1") in new_2027


def test_demo_seed_is_idempotent_and_never_mutates_course_three(tutor_core3_app):
    from app import db
    from app.ai_lab.exam_revisions import SKILLS
    from app.ai_lab.tutor_core3 import get_tutor_core3_state, seed_tutor_core3_demo
    from core.db_models import AiLabExamTaskBinding, AiLabTutorDemoEvent, LearningTrajectory, User

    with tutor_core3_app.app_context():
        actor = User(username="creator", role="admin", is_active=True)
        course_three = LearningTrajectory(
            course_id=3, title="Оригинальный курс 3", subject="Информатика",
            is_template=True, current_version=7, learning_goal="Не изменять",
        )
        db.session.add_all([actor, course_three])
        db.session.commit()
        original = (course_three.title, course_three.current_version, course_three.learning_goal)

        first = seed_tutor_core3_demo(actor.id)
        second = seed_tutor_core3_demo(actor.id)
        state = get_tutor_core3_state()

        assert first["created"] is True
        assert second["created"] is False
        assert state["seed_version"] == "boostudy.tutor-core3.synthetic-ege2027.v1"
        assert state["demo"]["course"]["template_id"] != 3
        assert len(state["demo"]["course"]["lessons"]) == 6
        assert len(state["demo"]["events"]) == 2
        assert state["demo"]["adaptation_preview"]["time_allocation"] == {
            "total_minutes": 60, "diagnostic_minutes": 8, "planned_lesson_minutes": 52,
        }
        assert state["demo"]["adaptation_preview"]["teacher_approval_required"] is True
        assert state["demo"]["adaptation_preview"]["applied_automatically"] is False
        assert state["demo"]["independent_skills_demonstrated"] == []
        assert state["demo"]["skills_demonstrated_after_hint"]
        assert state["model_calls"] == 0
        from flask import render_template
        from flask_login import login_user
        with tutor_core3_app.test_request_context("/admin/ai-lab/tutor-core/ege-2027"):
            login_user(actor)
            html = render_template(
                "sandbox/ai_lab_tutor_core3_demo.html",
                state=state,
                page_error=None,
                legacy_note=None,
            )
        assert "Tutor Core 3.0" in html
        assert state["revision_manifest"][1]["source_sha256"][:16] in html
        assert "52" in html and "8" in html
        assert AiLabExamTaskBinding.query.count() == 7
        assert AiLabTutorDemoEvent.query.count() == 2
        assert LearningTrajectory.query.filter_by(course_id=3).one().title == original[0]
        refreshed = LearningTrajectory.query.filter_by(course_id=3).one()
        assert (refreshed.title, refreshed.current_version, refreshed.learning_goal) == original
        assert len(SKILLS) == 6


def test_graph_demo_fixture_detects_reverse_edge_and_after_hint_correction():
    from app.ai_lab.tutor_core3 import _graph_fixture_results

    initial, corrected = _graph_fixture_results()
    assert initial["matches"] is False
    assert "C->B" in initial["submitted_edges"]
    assert corrected["matches"] is True
