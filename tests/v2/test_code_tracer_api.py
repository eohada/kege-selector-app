"""
Интеграционные тесты для API Бу Трассировщика (/api/v2/code/trace).
"""
import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_api_code_trace_success(client):
    res = client.post("/api/v2/code/trace", json={
        "code": "a = 5\nb = 10\nc = a * b\n",
        "file_name": "test.py"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["total_steps"] >= 3
    assert len(data["frames"]) >= 3
    final_frame = data["frames"][-1]
    assert final_frame["locals"]["c"]["value"] == 50


def test_api_code_trace_empty_code(client):
    res = client.post("/api/v2/code/trace", json={
        "code": "   ",
        "file_name": "test.py"
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False


def test_api_code_trace_security_block(client):
    res = client.post("/api/v2/code/trace", json={
        "code": "import subprocess\n",
        "file_name": "danger.py"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is False
    assert "запрещён" in data["error"]
