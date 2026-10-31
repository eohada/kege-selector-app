"""Deterministic Sprint 10 assignment-family checks using isolated synthetic data."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture()
def sprint10_app(tmp_path):
    from app import create_app, db

    database_path = tmp_path / "sprint10-families.sqlite"
    app = create_app({
        "TESTING": True,
        "SKIP_DATABASE_BOOTSTRAP": True,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "sprint10-family-test",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
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


def _create_approved_family(template_id: str, actor_id: int, *, real_runner: bool = False):
    from app import db
    from app.ai_lab.assignment_families import (
        approve_family_version,
        create_family_version,
        verify_family_version,
    )
    from app.ai_lab.code_judge import _serialize_test_set, ensure_seeded_test_sets
    from app.ai_lab.family_templates import list_family_templates, materialize_template
    from app.models import User
    from core.db_models import AiLabCodeJudgeRun, AiLabCodeJudgeTestSet, AiLabRubricVersion

    admin = User(username=f"sprint10-admin-{actor_id}",
                 email=f"sprint10-admin-{actor_id}@example.test", role="admin", is_active=True)
    db.session.add(admin)
    db.session.commit()

    manifest = next(item for item in list_family_templates() if item["template_id"] == template_id)
    suite = next(item for item in ensure_seeded_test_sets()
                 if item["scenario_id"] == "family-base-" + manifest["family_id"].removeprefix("python."))
    test_set = AiLabCodeJudgeTestSet.query.filter_by(scenario_id=suite["scenario_id"]).one()
    rubric_criteria = [{
        "id": item["assignment_criterion_id"],
        "title": item["title"],
        "description": item["description"],
        "max_score": item["max_score"],
        "full_credit": "Все связанные проверки пройдены.",
        "partial_credit": "",
    } for item in (test_set.rubric_json or [])]
    rubric = AiLabRubricVersion(
        rubric_key=f"sprint10-{manifest['family_id']}", version_no=1,
        assignment_id=manifest["assignment_id"], assignment_version=manifest["assignment_version"],
        task_json={
            "assignment_id": manifest["assignment_id"],
            "assignment_version": manifest["assignment_version"],
            "title": manifest["title"], "subject": "Информатика", "topic": "Синтетическая проверка",
            "answer_type": "python", "max_score": sum(item["max_score"] for item in rubric_criteria),
            "condition": suite["description"], "reference_answer": suite["starter_code"],
        },
        criteria_json=rubric_criteria, proposed_tests_json=[], edits_json=[],
        validation_json={"ok": True}, status="approved", prompt_version="sprint10-test-v1",
        generation_json={}, created_by_user_id=admin.id, approved_by_user_id=admin.id,
    )
    db.session.add(rubric)
    db.session.commit()

    generated = materialize_template(template_id, {
        spec["name"]: spec["default"] for spec in manifest["parameter_schema"]
    })
    if real_runner:
        from app.ai_lab.code_judge import run_request

        reference_result, _ = run_request(admin.id, {
            "request_key": str(uuid.uuid4()), "run_type": "submit",
            "code": generated["reference_code"], "test_set_id": test_set.id,
            "test_set_version": test_set.test_set_version,
            "test_set": _serialize_test_set(test_set),
        })
        assert reference_result["status"] == "accepted", reference_result.get("technical_error")
        assert reference_result["result"]["complete"] is True
        reference = db.session.get(AiLabCodeJudgeRun, reference_result["id"])
    else:
        reference = AiLabCodeJudgeRun(
            actor_user_id=admin.id, test_set_id=test_set.id,
            request_key=f"sprint10-reference-{actor_id}", scenario_id=test_set.scenario_id,
            run_type="submit", mode="function", status="accepted",
            test_set_version=test_set.test_set_version, code=generated["reference_code"],
            code_hash=hashlib.sha256(generated["reference_code"].encode("utf-8")).hexdigest(),
            result_json={"test_set_snapshot": _serialize_test_set(test_set), "tests": []},
        )
        db.session.add(reference)
        db.session.commit()

    draft = create_family_version({
        "family_id": manifest["family_id"], "title": manifest["title"],
        "template_id": template_id, "assignment_id": manifest["assignment_id"],
        "assignment_version": manifest["assignment_version"], "rubric_version_id": rubric.id,
        "test_set_id": test_set.id, "reference_run_id": reference.id,
        # Template-backed contracts must derive hashes from persisted canonical sources.
        "contract": {"source_refs": [{"source_ref": "forged", "version": 1, "sha256": "f" * 64}]},
    }, admin.id)
    verified = verify_family_version(draft["id"])
    approved = approve_family_version(verified["id"], admin.id)
    return admin, manifest, test_set, approved


def test_family_templates_are_repeatable_and_parameters_change_materialized_content():
    from app.ai_lab.family_templates import (
        default_template_parameters,
        materialize_template,
        template_manifest,
    )

    template_id = "python.remove-character.v1"
    defaults = default_template_parameters(template_id)
    first = materialize_template(template_id, defaults)
    assert first == materialize_template(template_id, defaults)
    assert first["test_cases"][-1]["id"] == "maximum-length"
    assert len(first["test_cases"][-1]["args"][0]) == defaults["max_length"]

    changed = materialize_template(template_id, {"target_character": "e", "max_length": 24})
    assert changed["condition"] != first["condition"]
    assert changed["test_cases"] != first["test_cases"]
    assert template_manifest(template_id)["template_sha256"] == template_manifest(template_id)["template_sha256"]


def test_template_family_uses_canonical_source_hashes_and_detects_stale_sources(sprint10_app):
    from app import db
    from app.ai_lab.assignment_families import AssignmentFamilyError, resolve_family_version
    from core.db_models import AiLabCodeJudgeRun, AiLabCodeJudgeTestSet

    with sprint10_app.app_context():
        admin, manifest, test_set, approved = _create_approved_family(
            "python.divisibility-count.v1", 3101,
        )
        refs = approved["contract"]["source_refs"]
        assert all(item["source_ref"] != "forged" for item in refs)
        assert any(item["source_ref"] == "template:python.divisibility-count.v1" for item in refs)
        assert approved["contract"]["template_id"] == manifest["template_id"]

        resolved = resolve_family_version(
            family_id=approved["family_id"], version_no=approved["version_no"],
            assignment_id=manifest["assignment_id"], assignment_version=manifest["assignment_version"],
            variant_parameters={},
        )
        assert resolved["compatibility_status"] == "exact_version_match"

        saved = db.session.get(AiLabCodeJudgeTestSet, test_set.id)
        saved.description += " Изменённый источник."
        db.session.commit()
        with pytest.raises(AssignmentFamilyError, match="больше не совместимо"):
            resolve_family_version(
                family_id=approved["family_id"], version_no=approved["version_no"],
                assignment_id=manifest["assignment_id"], assignment_version=manifest["assignment_version"],
                variant_parameters={},
            )


def test_materialized_variant_is_bounded_idempotent_and_reloads_as_a_scenario(sprint10_app, monkeypatch):
    from app.ai_lab import assignment_variants
    from app.ai_lab.assignment_variants import materialize_family_variant
    from app.ai_lab.family_templates import default_template_parameters, list_family_templates
    from app.ai_lab.scenarios import get_scenario, list_scenarios
    from app import create_app, db
    from flask import render_template
    from flask_login import login_user
    from core.db_models import AiLabAssignmentVariant

    calls = []

    def fake_run(actor_user_id, variant, code, purpose, bundle_no):
        calls.append((actor_user_id, purpose, bundle_no))
        status = "wrong_answer" if purpose == "mutation" else "accepted"
        passed = 3 if purpose != "mutation" else 1
        return {"purpose": purpose, "run_id": len(calls), "created": True, "status": status,
                "passed": passed, "total": 3, "complete": True, "duration_ms": 1,
                "runner_version": "test-runner", "technical_error": None}

    monkeypatch.setattr(assignment_variants, "_run_code", fake_run)
    with sprint10_app.app_context():
        admin, manifest, _test_set, approved = _create_approved_family(
            "python.remove-character.v1", 3102,
        )
        variant = materialize_family_variant(
            approved["id"], default_template_parameters(manifest["template_id"]), admin.id,
        )
        assert variant["status"] == "available"
        assert variant["validation"]["status"] == "passed"
        assert [entry[1] for entry in calls] == ["reference", "alternative", "mutation"]
        assert variant["family_version_id"] == approved["id"]

        duplicate = materialize_family_variant(
            approved["id"], default_template_parameters(manifest["template_id"]), admin.id,
        )
        assert duplicate["id"] == variant["id"]
        assert len(calls) == 3

        scenario = get_scenario(variant["scenario_id"])
        assert scenario["family_variant"]["variant_id"] == variant["variant_id"]
        assert len(scenario["test_cases"]) == 5
        listed = next(item for item in list_scenarios() if item["id"] == variant["scenario_id"])
        assert "test_cases" not in listed
        with sprint10_app.test_request_context():
            login_user(admin)
            rendered = render_template(
                "sandbox/ai_lab_assignment_families.html", families=[approved], assignments=[],
                rubrics=[], test_sets=[], history=[], family_templates=list_family_templates(),
                family_variants=[variant], family_storage_ready=True,
            )
        assert "Создать вариант" in rendered
        assert "максимум" in rendered
        database_uri = sprint10_app.config["SQLALCHEMY_DATABASE_URI"]
        db.session.remove()

    restarted = create_app({
        "TESTING": True, "SKIP_DATABASE_BOOTSTRAP": True, "SECRET_KEY": "sprint10-restart-test",
        "SQLALCHEMY_DATABASE_URI": database_uri, "RUN_ENV": "local", "AI_LAB_ENABLED": True,
    })
    with restarted.app_context():
        saved = AiLabAssignmentVariant.query.filter_by(variant_id=variant["variant_id"]).one()
        assert saved.status == "available"
        assert saved.content_sha256 == variant["content_sha256"]
        assert get_scenario(saved.scenario_id)["family_variant"]["variant_id"] == saved.variant_id


def test_family_parameter_constraints_reject_out_of_domain_values():
    from app.ai_lab.assignment_families import AssignmentFamilyError, validate_variant_parameters
    from app.ai_lab.family_templates import template_manifest

    contract = {
        "variant_parameters": template_manifest("python.divisibility-count.v1")["parameter_schema"],
    }
    with pytest.raises(AssignmentFamilyError, match="диапазоне"):
        validate_variant_parameters(contract, {"lower_bound": -1, "upper_bound": 100, "divisor": 3})


def test_homework_preserves_python_source_for_code_judge_hash_binding():
    from app.ai_lab.scenarios import get_scenario
    from app.ai_lab.service import _merge_input

    source = "def classify(n):\n    return (n > 0, n % 2 == 0)\n  \n"
    merged = _merge_input(get_scenario("py-classify-judge-17"), {"student_solution": source})

    assert merged["student_solution"] == source
    assert hashlib.sha256(merged["student_solution"].encode("utf-8")).hexdigest() == hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


@pytest.mark.skipif(os.environ.get("BOOSTUDY_SPRINT10_LIVE_RUNNER") != "1",
                    reason="set BOOSTUDY_SPRINT10_LIVE_RUNNER=1 to use the local sandbox Runner")
def test_live_runner_validates_two_families_and_binds_homework_without_gigachat(sprint10_app, monkeypatch):
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(".env"), override=False)
    from app import create_app, db
    from app.ai_lab import service
    from app.ai_lab.assignment_variants import materialize_family_variant
    from app.ai_lab.code_judge import _serialize_test_set, run_request
    from app.ai_lab.code_judge_runner_client import runner_diagnostics
    from app.ai_lab.family_templates import default_template_parameters, materialize_template
    from app.ai_lab.scenarios import get_scenario
    from app.ai_lab.service import ensure_initial_prompt, run_experiment
    from core.db_models import AiLabAssignmentVariant, AiLabCodeJudgeRun, AiLabCodeJudgeTestSet, AiLabExperiment

    with sprint10_app.app_context():
        diagnostics = runner_diagnostics()
        assert diagnostics["ready"] is True
        assert diagnostics["secure_profile_verified"] is True
        assert diagnostics["queue"]["concurrency_limit"] == 1
        for key in ("network_disabled", "non_root", "not_privileged", "no_host_mounts", "no_injected_secrets"):
            assert diagnostics["security_profile"][key] is True

        class SyntheticHomeworkProvider:
            name = "synthetic-replay"
            model = "Synthetic-Replay"

            def __init__(self):
                self.payloads = []

            def list_models(self):
                return [self.model]

            def complete(self, _model, _prompt, payload, **_kwargs):
                self.payloads.append(payload)
                criteria = payload["scoring_criteria"]
                content = json.dumps({
                    "score_awarded": 3, "max_score": 3, "grading_status": "checked",
                    "criterion_scores": [{
                        "criterion": item["criterion"], "score_awarded": 1,
                        "max_score": 1, "rationale": "Синтетический ответ для проверки интеграции.",
                    } for item in criteria],
                    "insufficient_data_reason": "", "summary": "Синтетическая проверка.",
                    "mistakes": [], "student_feedback": "Техническая проверка завершена.",
                    "teacher_feedback": "Оценка подтверждена Runner.", "recommended_topics": [],
                    "needs_human_review": False, "review_reason": "", "confidence_level": "medium",
                })
                return SimpleNamespace(
                    content=content, model=self.model, input_tokens=40, output_tokens=60,
                    prompt_tokens=40, precached_prompt_tokens=0, total_tokens=100,
                    payload_id=f"sprint10-{len(self.payloads)}", payload_sha256="a" * 64,
                    request_payload={"synthetic": True},
                    generation_parameters={"temperature": 0, "max_tokens": 512, "top_p": 1},
                )

        provider = SyntheticHomeworkProvider()
        monkeypatch.setattr(service, "is_local_ai_lab_enabled", lambda: True)
        monkeypatch.setattr(service, "provider_settings", lambda: {
            "configured": True, "default_model": provider.model,
        })
        monkeypatch.setattr(service, "ai_lab_limits", lambda: {
            "runs_per_admin_per_hour": 120, "runs_per_lab_per_hour": 300,
            "max_completion_attempts": 1, "auto_retry_enabled": False,
            "max_input_bytes": 128 * 1024,
        })
        prompt = ensure_initial_prompt()
        actor_ids = []

        for index, template_id in enumerate((
            "python.divisibility-count.v1", "python.remove-character.v1",
        ), 1):
            admin, manifest, _base_test_set, family = _create_approved_family(
                template_id, 3200 + index, real_runner=True,
            )
            actor_ids.append(admin.id)
            variant = materialize_family_variant(
                family["id"], default_template_parameters(template_id), admin.id,
            )
            assert variant["status"] == "available"
            bundle = variant["validation"]["bundles"][0]
            assert [(item["purpose"], item["status"], item["passed"], item["total"]) for item in bundle["checks"]] == [
                ("reference", "accepted", bundle["checks"][0]["total"], bundle["checks"][0]["total"]),
                ("alternative", "accepted", bundle["checks"][1]["total"], bundle["checks"][1]["total"]),
                ("mutation", "wrong_answer", bundle["checks"][2]["passed"], bundle["checks"][2]["total"]),
            ]
            assert bundle["checks"][2]["passed"] < bundle["checks"][2]["total"]

            scenario = get_scenario(variant["scenario_id"])
            generated = materialize_template(template_id, variant["parameters"])
            test_set = db.session.get(AiLabCodeJudgeTestSet, variant["test_set_id"])
            student_code = generated["alternative_code"]
            judge_run, _ = run_request(admin.id, {
                "request_key": str(uuid.uuid4()), "run_type": "submit", "code": student_code,
                "test_set_id": test_set.id, "test_set_version": test_set.test_set_version,
                "test_set": _serialize_test_set(test_set),
            })
            assert judge_run["status"] == "accepted"
            persisted_judge_run = db.session.get(AiLabCodeJudgeRun, judge_run["id"])
            assert persisted_judge_run.run_type == "submit"
            assert persisted_judge_run.status == "accepted"
            assert persisted_judge_run.result_json and persisted_judge_run.result_json.get("complete") is True, {
                "status": persisted_judge_run.status,
                "run_type": persisted_judge_run.run_type,
                "result_keys": sorted((persisted_judge_run.result_json or {}).keys()),
                "complete": (persisted_judge_run.result_json or {}).get("complete"),
            }

            experiment = run_experiment(
                actor_user_id=admin.id, provider=provider, max_completion_attempts=1,
                payload={
                    "request_key": str(uuid.uuid4()), "scenario_id": scenario["id"],
                    "model": provider.model, "prompt_version_id": prompt.id,
                    "code_judge_run_id": judge_run["id"],
                    "input": {"student_solution": student_code},
                },
            )
            assert experiment.status == "succeeded"
            assert provider.payloads[-1]["verified_assignment_family"]["variant_id"] == variant["variant_id"]
            assert provider.payloads[-1]["verified_code_judge_report"]["schema_version"] == 1
            from app.ai_lab.analytics import all_analytics_evidence

            assert any(
                event["source_module"] == "ai_homework"
                and event["source_record_id"] == f"ai-lab-experiment:{experiment.id}"
                for event in all_analytics_evidence()
            )
        assert len(provider.payloads) == 2
        database_uri = sprint10_app.config["SQLALCHEMY_DATABASE_URI"]
        db.session.remove()

    restarted = create_app({
        "TESTING": True, "SKIP_DATABASE_BOOTSTRAP": True, "SECRET_KEY": "sprint10-live-restart",
        "SQLALCHEMY_DATABASE_URI": database_uri, "RUN_ENV": "local", "AI_LAB_ENABLED": True,
    })
    with restarted.app_context():
        for actor_id in actor_ids:
            assert AiLabExperiment.query.filter_by(actor_user_id=actor_id, status="succeeded").count() == 1
        assert AiLabAssignmentVariant.query.filter_by(status="available").count() == 2
