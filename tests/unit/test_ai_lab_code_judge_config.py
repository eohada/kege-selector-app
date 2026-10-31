import pytest
from flask import Flask

from app.ai_lab import code_judge
from app.ai_lab.config import code_judge_docker_api_timeout_seconds


def test_docker_api_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("AI_LAB_CODE_JUDGE_DOCKER_API_TIMEOUT_SECONDS", "47")

    assert code_judge_docker_api_timeout_seconds() == 47


def test_docker_api_timeout_rejects_values_outside_supported_range(monkeypatch):
    monkeypatch.setenv("AI_LAB_CODE_JUDGE_DOCKER_API_TIMEOUT_SECONDS", "7")

    assert code_judge_docker_api_timeout_seconds() == 30


def test_code_judge_preserves_a_valid_explicit_skill_mapping(monkeypatch):
    app = Flask("code-judge-skill-map-test")
    monkeypatch.setattr(code_judge, "code_judge_limits", lambda: {
        "max_test_cases": 30, "max_source_bytes": 24_000, "max_test_set_bytes": 500_000,
    })
    monkeypatch.setattr(code_judge, "list_python_assignments", lambda: [])
    payload = {
        "title": "Синтетическая проверка позиционной записи", "mode": "function",
        "function_name": "convert_base", "comparator": "exact", "tolerance": 0,
        "test_cases": [{"id": "base-2", "name": "Двоичная запись", "visibility": "public",
                        "args": [13, 2], "expected": "1101"}],
        "rubric_json": [{"id": "base-notation", "title": "Позиционная запись",
                         "description": "Цифры и порядок разрядов соответствуют основанию.",
                         "max_score": 1, "policy": "all_or_nothing", "skill_id": "exam-skill:14",
                         "checks": [{"case_id": "base-2", "projection": "whole"}]}],
    }

    with app.app_context():
        result = code_judge.validate_test_set(payload)

    assert result["rubric_json"][0]["skill_id"] == "exam-skill:14"


def test_code_judge_rejects_malformed_skill_mapping(monkeypatch):
    app = Flask("code-judge-skill-map-invalid-test")
    monkeypatch.setattr(code_judge, "code_judge_limits", lambda: {
        "max_test_cases": 30, "max_source_bytes": 24_000, "max_test_set_bytes": 500_000,
    })
    monkeypatch.setattr(code_judge, "list_python_assignments", lambda: [])
    payload = {
        "title": "Синтетическая проверка", "mode": "function", "function_name": "solve",
        "test_cases": [{"id": "one", "name": "Один", "args": [1], "expected": 1}],
        "rubric_json": [{"id": "c1", "title": "Критерий", "description": "Результат", "max_score": 1,
                         "skill_id": "arbitrary-user-input", "checks": [{"case_id": "one", "projection": "whole"}]}],
    }

    with app.app_context(), pytest.raises(code_judge.CodeJudgeError, match="стабильный ID навыка"):
        code_judge.validate_test_set(payload)
