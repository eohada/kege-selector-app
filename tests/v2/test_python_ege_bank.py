import json
from pathlib import Path

from app.utils.python_bank_import import validate_package


def test_python_ege_package_is_complete_and_valid():
    path = Path(__file__).parents[2] / "data" / "task_banks" / "python_ege_full.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert validate_package(data) == []
    assert len(data["tasks"]) == 27
    assert {item["task_number"] for item in data["tasks"]} == set(range(1, 28))
    assert sum(len(item.get("variants", [])) for item in data["tasks"]) >= 54
