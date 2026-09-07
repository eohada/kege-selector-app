import json
from pathlib import Path

from app.utils.python_bank_import import _output_of, foundation_payload, validate_package


def test_python_ege_package_is_complete_and_valid():
    path = Path(__file__).parents[2] / "data" / "task_banks" / "python_ege_full.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert validate_package(data) == []
    assert len(data["tasks"]) == 27
    assert {item["task_number"] for item in data["tasks"]} == set(range(1, 28))
    assert sum(len(item.get("variants", [])) for item in data["tasks"]) >= 54


def test_foundations_import_builds_distinct_exercises_with_code_blocks():
    path = Path(__file__).parents[2] / "data" / "task_banks" / "python_foundations.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    for module in data["modules"]:
        exercises = [foundation_payload(item) for item in data["tasks"] if item["module"] == module["title"]]
        assert len(exercises) == 10
        assert len({exercise["title"] for exercise in exercises}) == 10
        assert len({exercise["content_html"] for exercise in exercises}) == 10
        assert len({exercise["solution"] for exercise in exercises}) == 10
        assert all("<pre><code>" in exercise["content_html"] for exercise in exercises)
        assert all(_output_of(exercise["solution"]) == exercise["answer"] for exercise in exercises)
