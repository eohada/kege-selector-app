"""Sprint 7 frozen plan and human-only review regression tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.ai_lab.benchmark import BenchmarkDataError, load_frozen_manifest, sha256_file
from app.ai_lab import quality_review as review
from scripts.run_ai_lab_sprint7_benchmark import _assert_frozen, _resolved_cases


ROOT = Path(__file__).parents[2]


def test_frozen_sprint7_plan_has_twelve_serial_synthetic_cases_and_no_holdout():
    manifest, dataset = load_frozen_manifest(ROOT / "tests/fixtures/ai_lab_sprint7_manifest_v1.json")
    _, previous = load_frozen_manifest(ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json")
    cases = _resolved_cases(dataset, previous)
    _assert_frozen(manifest, cases)
    assert len(cases) == 12
    assert {case["module"] for case in cases.values()} == {
        "ai_homework", "ai_course", "ai_lesson_intelligence",
    }
    assert all(case["expert_review_status"] == "pending" for case in cases.values())


@pytest.fixture()
def isolated_sprint6_review(tmp_path, monkeypatch):
    original = review.BENCHMARKS["sprint6"]
    result_path = tmp_path / "immutable-model-results.jsonl"
    result_path.write_bytes(original["results"].read_bytes())
    replacement = {**original, "results": result_path, "reviews": tmp_path / "human-ratings.jsonl"}
    monkeypatch.setitem(review.BENCHMARKS, "sprint6", replacement)
    return replacement


def test_sprint6_review_excludes_four_pre_model_stops_and_starts_without_human_labels(isolated_sprint6_review):
    bundle = review.load_review_bundle("sprint6")
    assert bundle["summary"]["total_runs"] == 10
    assert bundle["summary"]["excluded_before_model_or_transport"] == 4
    assert bundle["summary"]["manual_escalations"] == 4
    assert bundle["summary"]["expert_reviewed_runs"] == 0
    assert all(metric["accuracy"] is None
               for module in bundle["summary"]["module_metrics"].values()
               for metric in module["metrics"].values())


def test_human_review_persists_separately_and_rejects_duplicate_or_invalid_label(isolated_sprint6_review):
    original_hash = sha256_file(isolated_sprint6_review["results"])
    bundle = review.load_review_bundle("sprint6")
    row = bundle["rows"][0]
    field = review.RATING_FIELDS[row["module"]][0][0]
    with pytest.raises(BenchmarkDataError):
        review.save_human_review("sprint6", run_id=row["run_id"], case_id=row["case_id"],
                                 reviewer_id=77, ratings={field: "true"}, comments="")
    review.save_human_review("sprint6", run_id=row["run_id"], case_id=row["case_id"],
                             reviewer_id=77, ratings={field: False}, comments="Проверено вручную")
    reopened = review.load_review_bundle("sprint6")
    labeled = next(item for item in reopened["rows"] if item["case_id"] == row["case_id"])
    assert labeled["expert_review"]["ratings"] == {field: False}
    assert labeled["expert_review"]["comments"] == "Проверено вручную"
    assert reopened["summary"]["expert_reviewed_runs"] == 1
    assert reopened["summary"]["module_metrics"][row["module"]]["metrics"][field]["accuracy"] == 0
    assert sha256_file(isolated_sprint6_review["results"]) == original_hash
    with pytest.raises(BenchmarkDataError, match="уже оценён"):
        review.save_human_review("sprint6", run_id=row["run_id"], case_id=row["case_id"],
                                 reviewer_id=77, ratings={field: True}, comments="duplicate")


def test_concurrent_review_submissions_create_one_label(isolated_sprint6_review):
    row = review.load_review_bundle("sprint6")["rows"][0]
    field = review.RATING_FIELDS[row["module"]][0][0]

    def submit():
        try:
            review.save_human_review("sprint6", run_id=row["run_id"], case_id=row["case_id"],
                                     reviewer_id=77, ratings={field: True}, comments="concurrent")
            return "saved"
        except BenchmarkDataError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: submit(), range(2)))
    assert sorted(outcomes) == ["duplicate", "saved"]
    assert review.load_review_bundle("sprint6")["summary"]["expert_reviewed_runs"] == 1


def test_course_regression_rejects_structural_reordering_disguised_as_material_edit():
    import json
    from app.ai_lab.course import CourseAnalysisError, _validate_model_output, course_analysis_chunks, validate_course_input

    _, previous = load_frozen_manifest(ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json")
    case = next(item for item in previous["cases"] if item["case_id"] == "course-regression-prerequisite-order")
    chunk = course_analysis_chunks(validate_course_input(case["input"]))[0]
    rows = [json.loads(line) for line in (ROOT / "docs/modules/artifacts/ai_lab_sprint7_live_run.jsonl").read_text(encoding="utf-8").splitlines()]
    raw = next(item["execution"]["full_response"] for item in rows if item["case_id"] == "s7-course-prerequisite-order")
    with pytest.raises(CourseAnalysisError, match="структурную перестановку"):
        _validate_model_output(json.loads(raw), chunk)


def test_course_material_proposal_without_structural_reordering_remains_valid():
    import json
    from app.ai_lab.course import _validate_model_output, course_analysis_chunks, validate_course_input

    _, previous = load_frozen_manifest(ROOT / "tests/fixtures/ai_lab_sprint6_manifest_v1.json")
    case = next(item for item in previous["cases"] if item["case_id"] == "course-dev-no-finding")
    chunk = course_analysis_chunks(validate_course_input(case["input"]))[0]
    rows = [json.loads(line) for line in (ROOT / "docs/modules/artifacts/ai_lab_sprint7_live_run.jsonl").read_text(encoding="utf-8").splitlines()]
    raw = next(item["execution"]["full_response"] for item in rows if item["case_id"] == "s7-course-no-finding")
    assert len(_validate_model_output(json.loads(raw), chunk)["material_proposals"]) == 1


def test_quality_review_route_requires_admin_and_saves_separate_human_rating(isolated_sprint6_review, tmp_path):
    from app import create_app, db
    from app.models import User

    app = create_app({"TESTING": True, "SECRET_KEY": "isolated-sprint7-review-test",
                      "WTF_CSRF_ENABLED": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'review-route.sqlite').as_posix()}",
                      "RUN_ENV": "local", "AI_LAB_ENABLED": True})
    with app.app_context():
        db.create_all()
        admin = User(username="s7-review-admin", email="s7-review-admin@example.test", role="admin", is_active=True)
        creator = User(username="s7-review-creator", email="s7-review-creator@example.test", role="creator", is_active=True)
        db.session.add_all([admin, creator])
        db.session.commit()
        admin_id, creator_id = admin.id, creator.id

    client = app.test_client()

    def login(user_id: int, role: str) -> None:
        with client.session_transaction() as session:
            session.clear()
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
            session["sandbox_role"] = role

    login(creator_id, "creator")
    assert client.get("/admin/ai-lab/quality-review").status_code == 403
    login(admin_id, "admin")
    page = client.get("/admin/ai-lab/quality-review")
    assert page.status_code == 200
    assert "10".encode() in page.data
    studio = client.get("/admin/ai-lab/studio")
    assert studio.status_code == 200
    with app.app_context():
        from core.db_models import AiLabPromptVersion
        from app.ai_lab.prompts import DEFAULT_PROMPT_TEXT, SEMANTIC_RELIABILITY_PROMPT_TEXT, TRUSTWORTHY_GRADING_PROMPT_TEXT

        versions = AiLabPromptVersion.query.order_by(AiLabPromptVersion.version_no.asc()).all()
        assert versions[0].content == DEFAULT_PROMPT_TEXT
        assert versions[1].content == SEMANTIC_RELIABILITY_PROMPT_TEXT
        assert versions[2].content == TRUSTWORTHY_GRADING_PROMPT_TEXT
    assert client.get("/admin/ai-lab/studio").status_code == 200
    with app.app_context():
        assert AiLabPromptVersion.query.count() == 3

    review_rows = review.load_review_bundle("sprint6")["rows"]
    row = review_rows[0]
    next_pending = next(item for item in review_rows[1:] if item["expert_review"]["status"] != "reviewed")
    field = review.RATING_FIELDS[row["module"]][0][0]
    initial_hash = sha256_file(isolated_sprint6_review["results"])
    save_response = client.post("/admin/ai-lab/quality-review", data={
        "benchmark": "sprint6", "run_id": row["run_id"], "case_id": row["case_id"],
        "rating__" + field: "no", "comments": "Человеческая проверка тестового стенда",
    }, follow_redirects=False)
    assert save_response.status_code == 302
    assert f"case_id={next_pending['case_id']}" in save_response.headers["Location"]
    saved = client.get(save_response.headers["Location"], follow_redirects=True)
    assert saved.status_code == 200
    assert "Экспертная оценка сохранена".encode() in saved.data
    assert review.load_review_bundle("sprint6")["summary"]["expert_reviewed_runs"] == 1
    assert sha256_file(isolated_sprint6_review["results"]) == initial_hash


def test_gigachat_catalogue_transport_keeps_tls_and_bypasses_only_its_stalled_system_proxy(monkeypatch):
    from app.ai_lab import provider

    calls = []
    trusted_ca = "C:/trusted/mincifry-ca.pem"
    monkeypatch.setattr(provider, "_ssl_verify", lambda: trusted_ca)
    monkeypatch.setattr(provider, "ai_lab_limits", lambda: {
        "provider_connect_timeout_seconds": 20,
        "provider_read_timeout_seconds": 240,
    })
    monkeypatch.setattr(provider.requests, "request", lambda *args, **kwargs: calls.append(kwargs) or object())
    monkeypatch.setattr(provider, "_setting", lambda name, default="": "false" if name == "GIGACHAT_USE_SYSTEM_PROXY" else default)
    provider._send("GET", "https://gigachat.devices.sberbank.ru/api/v1/models", headers={})
    assert calls[-1]["verify"] == trusted_ca
    assert calls[-1]["proxies"] == {"http": "", "https": ""}
    assert calls[-1]["timeout"] == (20, 240)

    monkeypatch.setattr(provider, "_setting", lambda name, default="": "true" if name == "GIGACHAT_USE_SYSTEM_PROXY" else default)
    provider._send("GET", "https://gigachat.devices.sberbank.ru/api/v1/models", headers={})
    assert calls[-1]["verify"] == trusted_ca
    assert calls[-1]["proxies"] is None


def test_sprint7_request_reservations_are_atomic_across_parallel_attempts(tmp_path, monkeypatch):
    from scripts import run_ai_lab_sprint7_benchmark as runner

    monkeypatch.setattr(runner, "RESERVATIONS", tmp_path / "requests.jsonl")
    manifest = {"maximum_logical_generations": 2, "dataset_sha256": "a" * 64}

    def reserve():
        try:
            runner._reserve("case-one", manifest)
            return "reserved"
        except RuntimeError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: reserve(), range(2)))
    assert sorted(outcomes) == ["rejected", "reserved"]
    assert len(runner.RESERVATIONS.read_text(encoding="utf-8").splitlines()) == 1
