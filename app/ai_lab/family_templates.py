"""Small, trusted generators for deterministic synthetic Python task families."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from typing import Any, Callable


def _count_divisible(params: dict[str, Any]) -> dict[str, Any]:
    lower = params["lower_bound"]
    upper = params["upper_bound"]
    divisor = params["divisor"]
    if upper <= lower or upper - lower < divisor:
        raise ValueError("Верхняя граница должна быть выше нижней минимум на величину делителя.")

    def count(a: int, b: int) -> int:
        return sum(1 for value in range(a, b + 1) if value % divisor == 0)

    first_multiple = math.ceil(lower / divisor) * divisor
    last_multiple = (upper // divisor) * divisor
    first_nonmultiple = next((value for value in range(lower, upper + 1) if value % divisor), None)
    if first_multiple > upper or last_multiple < lower or first_nonmultiple is None:
        raise ValueError("Выберите диапазон с кратными и некратными значениями.")

    middle_start = first_multiple
    middle_end = min(upper, first_multiple + 2 * divisor)
    tests = [
        {"id": "lower-bound", "name": "Левая граница", "visibility": "public", "args": [first_multiple, first_multiple], "expected": 1},
        {"id": "upper-bound", "name": "Правая граница", "visibility": "public", "args": [last_multiple, last_multiple], "expected": 1},
        {"id": "non-multiple", "name": "Число не делится без остатка", "visibility": "public", "args": [first_nonmultiple, first_nonmultiple], "expected": 0},
        {"id": "full-range", "name": "Весь допустимый диапазон", "visibility": "hidden", "args": [lower, upper], "expected": count(lower, upper)},
        {"id": "mixed-range", "name": "Поддиапазон с несколькими значениями", "visibility": "hidden", "args": [middle_start, middle_end], "expected": count(middle_start, middle_end)},
    ]
    code = (
        f"DIVISOR = {divisor}\n\n"
        "def count_divisible(a, b):\n"
        "    return b // DIVISOR - (a - 1) // DIVISOR\n"
    )
    alternative = (
        f"DIVISOR = {divisor}\n\n"
        "def count_divisible(a, b):\n"
        "    return sum(x % DIVISOR == 0 for x in range(a, b + 1))\n"
    )
    mutant = (
        f"DIVISOR = {divisor}\n\n"
        "def count_divisible(a, b):\n"
        "    return b // DIVISOR - a // DIVISOR\n"
    )
    return {
        "title": f"Подсчёт чисел, кратных {divisor}",
        "condition": (
            f"Реализуйте функцию count_divisible(a, b), которая возвращает количество целых чисел x "
            f"включительно на отрезке a ≤ x ≤ b, делящихся на {divisor} без остатка. "
            f"Границы вызова удовлетворяют {lower} ≤ a ≤ b ≤ {upper}. "
            "Возвращаемое значение должно быть целым числом."
        ),
        "starter_code": "def count_divisible(a, b):\n    # верните количество чисел, кратных указанному в условии делителю\n    pass\n",
        "reference_code": code,
        "alternative_code": alternative,
        "mutant_code": mutant,
        "test_cases": tests,
        "rubric_json": [
            {"id": "integer-result", "assignment_criterion_id": "integer-result", "title": "Целый результат", "description": "Функция возвращает целое число.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "full-range", "projection": "type"}]},
            {"id": "inclusive-range", "assignment_criterion_id": "inclusive-range", "title": "Включительные границы отрезка", "description": "Учитываются кратные значения на обеих границах.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "lower-bound", "projection": "whole"}, {"case_id": "upper-bound", "projection": "whole"}]},
            {"id": "divisor-rule", "assignment_criterion_id": "divisor-rule", "title": "Проверка делимости", "description": "Считаются только числа, делящиеся на параметр без остатка.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "non-multiple", "projection": "whole"}, {"case_id": "mixed-range", "projection": "whole"}]},
        ],
        "criteria": [
            "1 балл — функция возвращает целое количество чисел.",
            "1 балл — учитывает включительные границы отрезка.",
            "1 балл — считает только значения, кратные делителю из условия.",
        ],
        "max_score": 3,
        "metadata": {"subject": "Информатика", "topic": "Целочисленная арифметика и циклы", "skill_ids": ["python.integer-division", "python.range-boundaries"]},
    }


def _remove_character(params: dict[str, Any]) -> dict[str, Any]:
    target = params["target_character"]
    maximum = params["max_length"]
    if not isinstance(target, str) or len(target) != 1:
        raise ValueError("Параметр должен задавать ровно один символ.")

    mixed = f"{target}bc{target}a{target}"
    no_match = "xyzw" if target not in "xyzw" else "bcdf"
    cases = [
        {"id": "repeated-target", "name": "Несколько вхождений", "visibility": "public", "args": [mixed], "expected": "".join(char for char in mixed if char != target)},
        {"id": "no-target", "name": "Искомого символа нет", "visibility": "public", "args": [no_match], "expected": no_match},
        {"id": "all-target", "name": "Строка из искомых символов", "visibility": "hidden", "args": [target * 3], "expected": ""},
        {"id": "empty-string", "name": "Пустая строка", "visibility": "hidden", "args": [""], "expected": ""},
        {"id": "maximum-length", "name": "Верхняя граница длины", "visibility": "hidden", "args": ["b" * maximum], "expected": "b" * maximum},
    ]
    code = (
        f"TARGET = {target!r}\n\n"
        "def remove_character(text):\n"
        "    return ''.join(char for char in text if char != TARGET)\n"
    )
    alternative = (
        f"TARGET = {target!r}\n\n"
        "def remove_character(text):\n"
        "    return text.replace(TARGET, '')\n"
    )
    mutant = (
        f"TARGET = {target!r}\n\n"
        "def remove_character(text):\n"
        "    return text.replace(TARGET, '', 1)\n"
    )
    return {
        "title": f"Удаление символа {target!r} из строки",
        "condition": (
            f"Реализуйте функцию remove_character(text), которая удаляет из строки все вхождения символа {target!r}. "
            f"Порядок остальных символов сохраняется; сравнение точное и чувствительно к регистру. "
            f"Длина входной строки не превышает {maximum} символов."
        ),
        "starter_code": "def remove_character(text):\n    # верните строку без символов, указанных в условии\n    pass\n",
        "reference_code": code,
        "alternative_code": alternative,
        "mutant_code": mutant,
        "test_cases": cases,
        "rubric_json": [
            {"id": "string-result", "assignment_criterion_id": "string-result", "title": "Строковый результат", "description": "Функция возвращает строку.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "empty-string", "projection": "type"}]},
            {"id": "remove-all", "assignment_criterion_id": "remove-all", "title": "Удаление всех вхождений", "description": "Удалены все, а не только первое, вхождения целевого символа.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "repeated-target", "projection": "whole"}, {"case_id": "all-target", "projection": "whole"}]},
            {"id": "preserve-others", "assignment_criterion_id": "preserve-others", "title": "Сохранение остальных символов", "description": "Остальные символы и их порядок не меняются.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "no-target", "projection": "whole"}, {"case_id": "repeated-target", "projection": "whole"}]},
        ],
        "criteria": [
            "1 балл — результатом функции является строка.",
            "1 балл — удаляются все вхождения целевого символа.",
            "1 балл — остальные символы сохраняются в исходном порядке.",
        ],
        "max_score": 3,
        "metadata": {"subject": "Информатика", "topic": "Строки и последовательности", "skill_ids": ["python.string-iteration", "python.string-methods"]},
    }


_TEMPLATES: dict[str, dict[str, Any]] = {
    "python.divisibility-count.v1": {
        "family_id": "python.divisibility-count", "title": "Подсчёт кратных чисел на отрезке",
        "assignment_id": "ai-lab.python.divisibility-count", "assignment_version": 1,
        "function_name": "count_divisible", "builder": _count_divisible,
        "parameter_schema": [
            {"name": "lower_bound", "type": "integer", "minimum": 0, "maximum": 1000, "default": 0, "required": True},
            {"name": "upper_bound", "type": "integer", "minimum": 10, "maximum": 2000, "default": 100, "required": True},
            {"name": "divisor", "type": "integer", "minimum": 2, "maximum": 20, "default": 3, "required": True},
        ],
        "requirements": [
            {"id": "integer-result", "criterion_id": "integer-result", "description": "Вернуть целое количество значений."},
            {"id": "inclusive-range", "criterion_id": "inclusive-range", "description": "Учесть левую и правую границы отрезка."},
            {"id": "divisor-rule", "criterion_id": "divisor-rule", "description": "Считать значения, кратные заданному делителю."},
        ],
    },
    "python.remove-character.v1": {
        "family_id": "python.remove-character", "title": "Удаление выбранного символа из строки",
        "assignment_id": "ai-lab.python.remove-character", "assignment_version": 1,
        "function_name": "remove_character", "builder": _remove_character,
        "parameter_schema": [
            {"name": "target_character", "type": "enum", "values": ["a", "e", "0", "_"], "default": "a", "required": True},
            {"name": "max_length", "type": "integer", "minimum": 10, "maximum": 256, "default": 80, "required": True},
        ],
        "requirements": [
            {"id": "string-result", "criterion_id": "string-result", "description": "Вернуть строку."},
            {"id": "remove-all", "criterion_id": "remove-all", "description": "Удалить все вхождения выбранного символа."},
            {"id": "preserve-others", "criterion_id": "preserve-others", "description": "Сохранить порядок остальных символов."},
        ],
    },
}


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def template_manifest(template_id: str) -> dict[str, Any]:
    item = _TEMPLATES.get(str(template_id or ""))
    if item is None:
        raise ValueError("Выберите один из поддерживаемых типов семейства.")
    builder: Callable = item["builder"]
    source = inspect.getsource(builder)
    manifest = {key: value for key, value in item.items() if key != "builder"}
    manifest["template_id"] = template_id
    manifest["version"] = 1
    manifest["builder_source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    manifest["template_sha256"] = _canonical_json_hash(manifest)
    return manifest


def list_family_templates() -> list[dict[str, Any]]:
    result = []
    for template_id in _TEMPLATES:
        manifest = template_manifest(template_id)
        result.append({key: value for key, value in manifest.items() if key != "template_sha256"})
    return result


def default_template_parameters(template_id: str) -> dict[str, Any]:
    item = _TEMPLATES.get(str(template_id or ""))
    if item is None:
        raise ValueError("Выберите один из поддерживаемых типов семейства.")
    return {spec["name"]: spec["default"] for spec in item["parameter_schema"] if "default" in spec}


def materialize_template(template_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    item = _TEMPLATES.get(str(template_id or ""))
    if item is None:
        raise ValueError("Утверждённая версия использует неподдерживаемый генератор.")
    return item["builder"](parameters)
