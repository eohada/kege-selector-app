import json

from app.ai_lab.provider import CompletionResult


def _task():
    return {
        "title": "Сумма цифр", "subject": "Информатика", "topic": "Циклы",
        "answer_type": "python", "condition": "Верни сумму цифр числа n, включая ноль.",
        "reference_answer": "def digit_sum(n):\n    return sum(map(int, str(n)))",
        "teacher_requirements": "Принимаются все правильные алгоритмы.", "max_score": 3,
    }


def _criterion(score=3):
    return {
        "title": "Сумма цифр", "description": "Правильная сумма цифр числа n",
        "max_score": score, "full_credit": "Верный результат на всех заданных случаях",
        "partial_credit": "", "typical_errors": ["Пропущен ноль"],
        "automatable": True, "evidence": "Тесты функции", "manual_reason": "",
    }


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["sandbox_role"] = "creator"


def test_rubric_revisions_are_immutable_and_approval_exposes_synthetic_scenario(app, role_users):
    from app.ai_lab.rubric_builder import approve_rubric, revise_rubric
    from app.ai_lab.scenarios import get_scenario, list_python_assignments
    from app import db
    from core.db_models import AiLabRubricVersion

    with app.app_context():
        user_id = role_users["creator_id"]
        source = AiLabRubricVersion(
            rubric_key="22222222-2222-4222-8222-222222222222", version_no=1,
            assignment_id="ai-lab.rubric.test", assignment_version=1,
            task_json=_task(), criteria_json=[_criterion(2)], proposed_tests_json=[],
            raw_proposal_json={"criteria": [_criterion(2)]}, edits_json=[],
            validation_json={"ok": False, "errors": ["Баллы не совпадают"], "warnings": []},
            status="draft", model="GigaChat-3-Pro", prompt_version="rubric-builder-0.1",
            generation_json={}, created_by_user_id=user_id,
        )
        db.session.add(source)
        db.session.commit()
        revised = revise_rubric(source.id, {"criteria": [_criterion(3)]}, user_id)
        assert revised["version_no"] == 2
        assert db.session.get(AiLabRubricVersion, source.id).criteria_json[0]["max_score"] == 2
        approved = approve_rubric(revised["id"], user_id, acknowledge_warnings=True)
        assert approved["status"] == "approved"
        scenario = get_scenario(f"rubric-{revised['id']}")
        assert scenario["assignment_id"] == approved["assignment_id"]
        assert scenario["assignment_version"] == 2
        assert scenario["max_score"] == 3
        assert "Полный балл:" in scenario["criteria"][0]
        assert any(item["assignment_id"] == approved["assignment_id"] for item in list_python_assignments())


def test_rubric_generation_route_saves_proposal_but_does_not_approve(app, client, role_users, monkeypatch):
    from app.ai_lab import rubric_builder

    app.config.update(ENVIRONMENT="local", AI_LAB_ENABLED=True, GIGACHAT_AUTH_KEY="test-key")
    monkeypatch.setenv("ENVIRONMENT", "local")
    _login(client, role_users["creator_id"])
    proposal = {"criteria": [_criterion()], "warnings": [], "proposed_tests": [{
        "name": "Ноль", "input_json": "[0]", "expected_json": "0",
        "criterion_title": "Сумма цифр", "purpose": "Граница",
    }]}

    calls = []

    class FakeProvider:
        def __init__(self, settings):
            assert settings["auth_key"] == "test-key"

        def list_models(self):
            return ["GigaChat-3-Pro"]

        def complete_structured(self, model, system_prompt, payload, schema):
            calls.append(model)
            assert model == "GigaChat-3-Pro"
            assert "secret" not in json.dumps(payload)
            return CompletionResult(json.dumps(proposal), model, 120, 80, payload_id="request-1", payload_sha256="abc")

    monkeypatch.setattr(rubric_builder, "GigaChatProvider", FakeProvider)
    payload = {"task": _task(), "model": "GigaChat-3-Pro", "request_key": "55555555-5555-4555-8555-555555555555"}
    response = client.post("/admin/ai-lab/api/rubrics/generate", json=payload)
    assert response.status_code == 200
    item = response.get_json()["rubric"]
    assert item["status"] == "draft"
    assert item["validation"]["ok"] is True
    assert item["proposed_tests"][0]["status"] == "unverified"
    assert item["raw_proposal"] == proposal
    repeated = client.post("/admin/ai-lab/api/rubrics/generate", json=payload)
    assert repeated.get_json()["rubric"]["id"] == item["id"]
    assert calls == ["GigaChat-3-Pro"]


def test_bad_rubric_sum_cannot_be_approved(app, role_users):
    from app.ai_lab.rubric_builder import RubricError, approve_rubric
    from app import db
    from core.db_models import AiLabRubricVersion
    with app.app_context():
        user_id = role_users["creator_id"]
        item = AiLabRubricVersion(
            rubric_key="33333333-3333-4333-8333-333333333333", version_no=1,
            assignment_id="ai-lab.rubric.bad", assignment_version=1,
            task_json=_task(), criteria_json=[_criterion(2)], proposed_tests_json=[],
            edits_json=[], validation_json={}, status="draft", model="test",
            prompt_version="rubric-builder-0.1", generation_json={}, created_by_user_id=user_id,
        )
        db.session.add(item)
        db.session.commit()
        try:
            approve_rubric(item.id, user_id)
        except RubricError as exc:
            assert "Сумма критериев" in str(exc)
        else:
            raise AssertionError("Invalid rubric was approved")


def test_validator_holds_unjustified_partial_credit_and_invented_sorting_rules():
    from app.ai_lab.rubric_builder import validate_criteria, validate_task

    single = _task()
    single["max_score"] = 1
    single["teacher_requirements"] = "Один балл за правильный результат."
    criteria = [_criterion(.5), {**_criterion(.5), "title": "Граничные случаи"}]
    _, validation = validate_criteria(criteria, validate_task(single))
    assert not validation["ok"]
    assert any("разделён" in error for error in validation["errors"])
    _, validation = validate_criteria([{**_criterion(1), "partial_credit": "Часть случаев"}], validate_task(single))
    assert any("частичное начисление" in error for error in validation["errors"])
    single["teacher_requirements"] = "1 балл за результат. Частичный балл не предусмотрен."
    _, validation = validate_criteria(criteria, validate_task(single))
    assert not validation["ok"]

    vague = _task()
    vague["teacher_requirements"] = "Не задано направление сортировки и не указано изменение исходного списка."
    vague["condition"] = "Отсортируйте список."
    invented = {**_criterion(), "title": "Сортировка", "description": "Список отсортирован по возрастанию и остался неизменным"}
    _, validation = validate_criteria([invented], validate_task(vague))
    assert not validation["ok"]
    assert len(validation["errors"]) >= 2


def test_proposed_python_tests_use_verified_sandbox_and_save_evidence(app, role_users, monkeypatch):
    from app import db
    from app.ai_lab.rubric_builder import verify_proposed_tests, latest_test_verification
    from app.ai_lab import code_judge_runner_client
    from core.db_models import AiLabRubricVersion

    calls = []
    monkeypatch.setattr(code_judge_runner_client, "runner_diagnostics", lambda: {"ready": True, "secure_profile_verified": True})

    def fake_run(payload):
        calls.append(payload)
        return {"runner_version": "test-sandbox", "tests": [
            {"id": case["id"], "status": "passed", "actual": case["expected"]}
            for case in payload["test_cases"]
        ]}

    monkeypatch.setattr(code_judge_runner_client, "run_isolated", fake_run)
    with app.app_context():
        actor = role_users["creator_id"]
        item = AiLabRubricVersion(
            rubric_key="44444444-4444-4444-8444-444444444444", version_no=1,
            assignment_id="ai-lab.rubric.verify", assignment_version=1,
            task_json=_task(), criteria_json=[_criterion()],
            proposed_tests_json=[{"name": "Ноль", "input_json": '{"n": 0}',
                                  "expected_json": '{"result": 0}', "criterion_title": "Сумма цифр", "purpose": "Граница"}],
            edits_json=[], validation_json={"ok": True}, status="draft", model="test",
            prompt_version="rubric-builder-0.1", generation_json={}, created_by_user_id=actor,
        )
        db.session.add(item)
        db.session.commit()
        report = verify_proposed_tests(item.id, {
            "reference_confirmed": True,
            "reference_code": "def digit_sum(n):\n    return sum(map(int, str(n)))",
            "edge_cases": [{"name": "Нули внутри", "input_json": "[101]", "expected_json": "2"}],
        }, actor)
        assert report["overall_ok"] is True
        assert report["suggested_count"] == 1
        assert report["teacher_edge_count"] == 1
        assert calls[0]["test_cases"][0]["args"] == [0]
        assert calls[0]["test_cases"][0]["expected"] == 0
        assert latest_test_verification(item.id)["tests"][1]["origin"] == "teacher_edge"


def test_repair_changes_only_selected_criterion_and_creates_draft(app, role_users, monkeypatch):
    from app import db
    from app.ai_lab import rubric_builder
    from core.db_models import AiLabRubricVersion

    first = {**_criterion(1), "id": "a", "title": "Первый"}
    second = {**_criterion(2), "id": "b", "title": "Второй"}
    proposal = {"criteria": [{**first, "description": "Исправленное описание"},
                             {**second, "description": "Модель попыталась изменить и это"}],
                "warnings": [], "proposed_tests": []}

    class FakeProvider:
        def __init__(self, settings):
            pass

        def list_models(self):
            return ["GigaChat-3-Pro"]

        def complete_structured(self, model, prompt, payload, schema):
            assert payload["problematic_criterion_ids"] == ["a"]
            return CompletionResult(json.dumps(proposal), model, 40, 70, payload_id="repair-1", payload_sha256="hash")

    monkeypatch.setattr(rubric_builder, "GigaChatProvider", FakeProvider)
    monkeypatch.setattr(rubric_builder, "provider_settings", lambda: {"configured": True, "default_model": "GigaChat-3-Pro"})
    with app.app_context():
        actor = role_users["creator_id"]
        source = AiLabRubricVersion(rubric_key="55555555-5555-4555-8555-555555555555", version_no=1,
            assignment_id="ai-lab.rubric.repair", assignment_version=1, task_json=_task(),
            criteria_json=[first, second], proposed_tests_json=[], raw_proposal_json={}, edits_json=[],
            validation_json={"ok": True, "warnings": []}, status="approved", model="GigaChat-3-Pro",
            prompt_version="rubric-builder-0.1", generation_json={}, created_by_user_id=actor)
        db.session.add(source)
        db.session.commit()
        repaired = rubric_builder.repair_rubric(source.id, {"criterion_ids": ["a"], "reason": "Уточнить первый критерий",
            "request_key": "77777777-7777-4777-8777-777777777777"}, actor)
        assert repaired["status"] == "draft"
        assert repaired["version_no"] == 2
        assert repaired["criteria"][0]["description"] == "Исправленное описание"
        assert repaired["criteria"][1]["description"] == second["description"]
        assert repaired["criteria"][1]["max_score"] == second["max_score"]
        assert db.session.get(AiLabRubricVersion, source.id).status == "approved"
        assert repaired["parent_version"] == 1
        assert rubric_builder.repair_rubric(source.id, {"criterion_ids": ["a"], "reason": "Уточнить первый критерий",
            "request_key": "77777777-7777-4777-8777-777777777777"}, actor)["id"] == repaired["id"]


def test_expert_review_is_append_only_and_dashboard_counts_labeled_sample(app, role_users):
    from app import db
    from app.ai_lab.rubric_builder import review_rubric
    from app.ai_lab.quality_dashboard import quality_snapshot
    from core.db_models import AiLabRubricVersion, AiLabRubricReview

    with app.app_context():
        actor = role_users["creator_id"]
        item = AiLabRubricVersion(rubric_key="66666666-6666-4666-8666-666666666666", version_no=1,
            assignment_id="ai-lab.rubric.review", assignment_version=1, task_json=_task(),
            criteria_json=[_criterion()], proposed_tests_json=[], edits_json=[],
            validation_json={"ok": True}, status="draft", model="test", prompt_version="rubric-builder-0.1",
            generation_json={}, created_by_user_id=actor)
        db.session.add(item)
        db.session.commit()
        review_rubric(item.id, {"verdict": "fail", "issues": [{"category": "point_allocation", "criterion_id": "", "detail": "Неверный вес"}]}, actor)
        review_rubric(item.id, {"verdict": "pass", "issues": [], "note": "Исправлено после обсуждения"}, actor)
        assert AiLabRubricReview.query.filter_by(rubric_version_id=item.id).count() == 2
        assert quality_snapshot()["rubric_expert"] == {"matched": 1, "sample": 1, "percent": 100.0}


def test_adaptive_feedback_requires_failed_judge_evidence():
    from app.ai_lab.pedagogical_feedback import build_feedback_layers

    model = {"mistakes": [], "recommended_topics": ["Циклы"], "student_feedback": "Хорошо", "teacher_feedback": "Проверьте"}
    assert build_feedback_layers(model, None)["adaptive"] == []
    report = {"rubric": {"criteria": [
        {"title": "Циклы", "description": "Циклы в Python", "status": "not_fulfilled",
         "rationale": "Не пройдена проверка", "evidence": [{"case_id": "visible-1", "status": "failed"}]},
        {"title": "Функция", "status": "insufficient_data", "evidence": []},
    ]}}
    layers = build_feedback_layers(model, report)
    assert layers["adaptive"][0]["skill"] == "Циклы"
    assert layers["adaptive"][0]["suggested_review"] == "Циклы"
    assert layers["teacher"]["manual_check"] == ["Функция"]


def test_quality_dashboard_has_sample_and_method_without_invented_recommendation_score(app, client, role_users, monkeypatch):
    app.config.update(ENVIRONMENT="local", AI_LAB_ENABLED=True)
    monkeypatch.setenv("ENVIRONMENT", "local")
    _login(client, role_users["creator_id"])
    response = client.get("/admin/ai-lab/quality")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Экспертная оценка рубрик" in page
    assert "Отдельная содержательная экспертная разметка рекомендаций пока отсутствует" in page
    assert "Автоматический сигнал quality_json" in page


def test_malformed_model_rubric_is_saved_as_unapproved_draft(app, role_users, monkeypatch):
    from app.ai_lab import rubric_builder

    class FakeProvider:
        def __init__(self, settings):
            pass

        def list_models(self):
            return ["GigaChat-3-Pro"]

        def complete_structured(self, model, prompt, payload, schema):
            proposal = {"criteria": [{**_criterion(), "typical_errors": [""]}], "warnings": [], "proposed_tests": []}
            return CompletionResult(json.dumps(proposal), model, 30, 60, payload_id="malformed", payload_sha256="hash")

    monkeypatch.setattr(rubric_builder, "GigaChatProvider", FakeProvider)
    monkeypatch.setattr(rubric_builder, "provider_settings", lambda: {"configured": True, "default_model": "GigaChat-3-Pro"})
    with app.app_context():
        item = rubric_builder.generate_rubric(_task(), "GigaChat-3-Pro", role_users["creator_id"])
        assert item["status"] == "draft"
        assert item["validation"]["ok"] is False
        assert item["raw_proposal"]["criteria"][0]["typical_errors"] == [""]
