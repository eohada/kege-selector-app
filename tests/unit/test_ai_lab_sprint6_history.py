from __future__ import annotations

import copy

import pytest


@pytest.fixture()
def isolated_db():
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


def test_analytics_loads_homework_evidence_beyond_ui_history_pages(isolated_db):
    from app import db
    from app.ai_lab.analytics import stored_homework_evidence, synthetic_demo_events
    from core.db_models import AiLabExperiment

    with isolated_db.app_context():
        template = synthetic_demo_events()[0]
        records = []
        for index in range(1_207):
            evidence = copy.deepcopy(template)
            evidence.update({
                "event_id": f"sprint6-homework-evidence-{index:04d}",
                "subject_id": "synthetic-sprint6-scale",
                "source_ref": f"synthetic-run:{index}",
            })
            records.append(AiLabExperiment(
                actor_user_id=1,
                request_key=f"sprint6-scale-{index:04d}",
                scenario_id="synthetic-sprint6-scale",
                status="succeeded",
                provider="local",
                model="synthetic",
                prompt_version_no=1,
                prompt_snapshot="synthetic fixture",
                scenario_snapshot={},
                input_snapshot={},
                expected_snapshot={},
                quality_json={"learning_evidence": evidence},
            ))
        db.session.add_all(records)
        db.session.commit()

        evidence = stored_homework_evidence(batch_size=37)
        assert len(evidence) == 1_207
        assert evidence[0]["event_id"] == "ai-lab-experiment:1"
        assert evidence[-1]["event_id"] == "ai-lab-experiment:1207"
        assert len(stored_homework_evidence(limit=103, batch_size=37)) == 103
