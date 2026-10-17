import json
import hashlib
import uuid

import pytest


def _login(client, user_id, role):
    client.delete_cookie("session")
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["sandbox_role"] = role


def _enable_local_lab(app, monkeypatch):
    app.config.update(ENVIRONMENT="local", AI_LAB_ENABLED=True)
    monkeypatch.setenv("ENVIRONMENT", "local")


def _offline_runner():
    return {
        "ready": False,
        "secure_profile_verified": False,
        "message": "Docker runner не настроен.",
        "queue": {"active": 0, "waiting": 0},
        "limits": {},
    }


def test_code_judge_page_is_admin_only_and_seeds_synthetic_scenarios(app, client, role_users, monkeypatch):
    _enable_local_lab(app, monkeypatch)
    _login(client, role_users["creator_id"], "creator")

    from app.ai_lab import routes

    monkeypatch.setattr(routes, "runner_diagnostics", _offline_runner)
    page = client.get("/admin/ai-lab/code-judge")

    assert page.status_code == 200
    assert "Runner недоступен".encode() in page.data
    assert "Hidden".encode() in page.data
    assert "128 МБ".encode() in page.data
    data = client.get("/admin/ai-lab/api/code-judge").get_json()
    assert len(data["test_sets"]) == 11
    classify = next(item for item in data["test_sets"] if item["scenario_id"] == "classify-logic-errors")
    assert len(classify["test_cases"]) == 5
    assert classify["test_cases"][-1]["expected"] == {"__type__": "tuple", "items": [False, True]}
    assert len(classify["rubric_json"]) == 4

    _login(client, role_users["student_user_id"], "student")
    assert client.get("/admin/ai-lab/code-judge").status_code == 403
    assert client.get("/admin/ai-lab/api/code-judge").status_code == 403


def test_code_judge_custom_test_set_persists_and_can_be_deleted(app, client, role_users, monkeypatch):
    _enable_local_lab(app, monkeypatch)
    _login(client, role_users["creator_id"], "creator")
    from app.ai_lab import routes

    monkeypatch.setattr(routes, "runner_diagnostics", _offline_runner)
    created = client.post(
        "/admin/ai-lab/api/code-judge/test-sets",
        json={
            "title": "Локальная функция",
            "description": "Проверка после обновления страницы.",
            "mode": "function",
            "function_name": "solve",
            "starter_code": "def solve(x): return x + 1",
            "comparator": "exact",
            "test_cases": [
                {"id": "one", "name": "Один", "visibility": "public", "args": [1], "expected": 2},
                {"id": "two", "name": "Скрытый", "visibility": "hidden", "args": [2], "expected": 3},
            ],
        },
    )
    assert created.status_code == 200
    test_set = created.get_json()["test_set"]
    page = client.get("/admin/ai-lab/code-judge")
    assert page.status_code == 200
    assert test_set["title"].encode() in page.data
    assert any(item["id"] == test_set["id"] for item in client.get("/admin/ai-lab/api/code-judge").get_json()["test_sets"])

    deleted = client.delete(f"/admin/ai-lab/api/code-judge/test-sets/{test_set['id']}")
    assert deleted.status_code == 200
    assert all(item["id"] != test_set["id"] for item in client.get("/admin/ai-lab/api/code-judge").get_json()["test_sets"])


def test_run_is_recorded_as_unavailable_without_confirmed_isolation_and_is_idempotent(
    app, client, role_users, monkeypatch
):
    _enable_local_lab(app, monkeypatch)
    _login(client, role_users["creator_id"], "creator")
    from app.ai_lab import code_judge_runner_client, routes

    monkeypatch.setattr(routes, "runner_diagnostics", _offline_runner)
    monkeypatch.setattr(code_judge_runner_client, "runner_diagnostics", _offline_runner)
    request = {
        "request_key": str(uuid.uuid4()),
        "run_type": "submit",
        "test_set": {
            "title": "Не запускать без Docker",
            "mode": "program",
            "comparator": "exact",
            "test_cases": [{"id": "one", "name": "один", "visibility": "public", "stdin": "", "expected_output": ""}],
        },
        "code": "raise RuntimeError('must never execute on the backend')",
    }

    first = client.post("/admin/ai-lab/api/code-judge/run", json=request)
    second = client.post("/admin/ai-lab/api/code-judge/run", json=request)

    assert first.status_code == 503
    assert first.get_json()["run"]["status"] == "sandbox_unavailable"
    assert first.get_json()["run"]["result"] is None
    assert second.status_code == 503
    assert second.get_json()["created"] is False
    assert second.get_json()["run"]["id"] == first.get_json()["run"]["id"]
    assert client.get("/admin/ai-lab/api/code-judge").get_json()["history"][0]["id"] == first.get_json()["run"]["id"]


def test_container_profile_is_non_root_networkless_and_resource_limited():
    from app.ai_lab.code_judge_runner_service import DockerExecutor

    options = DockerExecutor.__new__(DockerExecutor)._container_options(
        {
            "cpu_cores": 1,
            "memory_mb": 128,
            "pids_limit": 32,
        }
    )
    assert options["network_mode"] == "none"
    assert options["read_only"] is True
    assert options["user"] != "0:0"
    assert options["privileged"] is False
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["mem_limit"] == "128m"
    assert options["pids_limit"] == 32
    assert options["tmpfs"]["/tmp"].startswith("rw,noexec,nosuid,nodev")
    assert "volumes" not in options


def test_disabled_ai_lab_rejects_code_judge_requests(app, client, role_users, monkeypatch):
    app.config.update(ENVIRONMENT="local", AI_LAB_ENABLED=False)
    monkeypatch.setenv("ENVIRONMENT", "local")
    _login(client, role_users["creator_id"], "creator")

    response = client.post("/admin/ai-lab/api/code-judge/run", json={})

    assert response.status_code == 423
    assert response.get_json()["error_code"] == "lab_disabled"


def test_classify_rubric_scores_independent_tuple_conditions():
    from app.ai_lab.code_judge import _score_rubric, _seeds, validate_test_set

    suite = validate_test_set(next(item for item in _seeds() if item["scenario_id"] == "classify-logic-errors"))
    cases = suite["test_cases"]
    tests = []
    for case in cases:
        n = case["args"][0]
        tests.append({
            "id": case["id"], "status": "wrong_answer",
            "actual": {"__type__": "tuple", "items": [n >= 0, n % 2 == 1]},
        })
    result = _score_rubric(suite["rubric_json"], cases, tests)
    assert [item["score_awarded"] for item in result["criteria"]] == [1, 1, 0, 0]
    assert result["confirmed_score"] == 2
    assert result["unconfirmed_max_score"] == 0

    partial = _score_rubric(suite["rubric_json"], cases, tests[:2])
    assert partial["criteria"][2]["status"] == "insufficient_data"
    assert partial["criteria"][2]["score_awarded"] is None
    assert partial["unconfirmed_max_score"] == 3


def test_rubric_supports_grouped_checks_and_type_projection_without_zeroing_unknowns():
    from app.ai_lab.code_judge import _project, _score_rubric

    cases = [
        {"id": "small", "name": "Small", "group_id": "positive", "visibility": "public", "expected": 7},
        {"id": "large", "name": "Large", "group_id": "positive", "visibility": "hidden", "expected": 12},
    ]
    criterion = {
        "id": "integer-result", "title": "Integer result", "description": "Returns an integer.",
        "max_score": 1, "policy": "all_or_nothing", "scoring_rule": "all_required",
        "checks": [{"group_id": "positive", "projection": "type"}],
    }
    tests = [{"id": "small", "status": "passed", "actual": 7}, {"id": "large", "status": "runtime_error"}]
    result = _score_rubric([criterion], cases, tests)
    assert result["criteria"][0]["status"] == "insufficient_data"
    assert result["criteria"][0]["score_awarded"] is None
    assert result["unconfirmed_max_score"] == 1
    assert _project({"__type__": "tuple", "items": [True, 4]}, "tuple.1.type") == (True, "int")
    assert _project({"answer": [3]}, "dict.answer.type") == (True, "list")


def test_assignment_and_rubric_versions_are_independent(app, role_users):
    from app import db
    from app.ai_lab.code_judge import save_test_set
    from core.db_models import AiLabCodeJudgeTestSet

    with app.app_context():
        suite = save_test_set({
            "title": "Versioned digit sum", "description": "v1", "mode": "function", "function_name": "digit_sum",
            "starter_code": "", "test_cases": [{"id": "zero", "name": "Zero", "visibility": "public", "args": [0], "expected": 0}],
            "assignment_id": "ai-lab.python.digit-sum", "assignment_version": 1,
            "rubric_json": [{"id": "sum-zero", "assignment_criterion_id": "zero-single", "title": "Zero", "description": "Returns zero.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "zero", "projection": "whole"}]}],
        }, role_users["creator_id"])
        assert suite["test_set_version"] == suite["rubric_version"] == 1
        edited = save_test_set({**suite, "description": "v1.1"}, role_users["creator_id"])
        assert edited["test_set_version"] == 2
        assert edited["rubric_version"] == 1
        rubric_edit = [dict(item) for item in edited["rubric_json"]]
        rubric_edit[0]["description"] = "Returns zero for input zero."
        changed = save_test_set({**edited, "rubric_json": rubric_edit}, role_users["creator_id"])
        assert changed["test_set_version"] == 3
        assert changed["rubric_version"] == 2
        stored = db.session.get(AiLabCodeJudgeTestSet, suite["id"])
        assert stored.assignment_id == "ai-lab.python.digit-sum"
        assert stored.assignment_version == 1


def test_runner_rejects_unauthenticated_requests_when_token_missing(monkeypatch):
    from app.ai_lab.code_judge_runner_service import RunnerHandler

    monkeypatch.setattr("app.ai_lab.code_judge_runner_service.setting", lambda *_: "")
    handler = RunnerHandler.__new__(RunnerHandler)
    handler.headers = {}
    assert handler._authorized() is False


def test_ai_studio_accepts_only_matching_completed_judge_evidence(app, role_users):
    from app import db
    from app.ai_lab.code_judge import _score_rubric, ensure_seeded_test_sets
    from app.ai_lab.scenarios import get_scenario
    from app.ai_lab.service import LabInputError, _judge_conflict, _verified_code_judge_report
    from core.db_models import AiLabCodeJudgeRun

    with app.app_context():
        suite = next(item for item in ensure_seeded_test_sets() if item["scenario_id"] == "digit-sum-evidence-v1")
        scenario = get_scenario("py-digit-sum-16")
        code = "def digit_sum(n):\n    return sum(int(char) for char in str(n))"
        run_input = {**scenario, "student_solution": code, "max_score": float(scenario["max_score"])}
        tests = [{
            "id": case["id"], "status": "passed", "actual": sum(int(char) for char in str(case["args"][0])),
        } for case in suite["test_cases"]]
        rubric = _score_rubric(suite["rubric_json"], suite["test_cases"], tests)
        run = AiLabCodeJudgeRun(
            actor_user_id=role_users["creator_id"], test_set_id=suite["id"], request_key=str(uuid.uuid4()),
            scenario_id=suite["scenario_id"], run_type="submit", mode="function", status="accepted",
            test_set_version=suite["test_set_version"], code=code,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            result_json={"complete": True, "passed": len(tests), "total": len(tests), "tests": tests, "rubric": rubric, "test_set_snapshot": suite},
        )
        db.session.add(run)
        db.session.commit()
        report = _verified_code_judge_report(role_users["creator_id"], run.id, run_input, scenario)
        assert report["report_type"] == "criterion_evidence_report"
        assert report["assignment_id"] == "ai-lab.python.digit-sum"
        assert report["assignment_version"] == 1
        assert report["rubric"]["confirmed_score"] == 3
        assert all(item["status"] == "fulfilled" for item in report["rubric"]["criteria"])
        valid = {
            "score_awarded": 3,
            "criterion_scores": [{"score_awarded": value} for value in [1, 1, 1]],
            "mistakes": [],
        }
        assert _judge_conflict(valid, report) is None
        assert _judge_conflict({**valid, "score_awarded": 2}, report)
        with pytest.raises(LabInputError):
            _verified_code_judge_report(role_users["student_user_id"], run.id, run_input, scenario)
        with pytest.raises(LabInputError):
            _verified_code_judge_report(role_users["creator_id"], run.id, {**run_input, "student_solution": code + "\n# changed"}, scenario)
        with pytest.raises(LabInputError):
            _verified_code_judge_report(role_users["creator_id"], run.id, run_input, {**scenario, "assignment_version": 2})
