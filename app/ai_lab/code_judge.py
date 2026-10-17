"""Local-only Code Judge persistence and request validation."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.ai_lab.config import code_judge_limits
from app.ai_lab.scenarios import list_python_assignments
from core.db_models import AiLabCodeJudgeRun, AiLabCodeJudgeTestSet, db


class CodeJudgeError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_request", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class RunnerUnavailable(CodeJudgeError):
    def __init__(self, message: str = "Изолированный runner недоступен. Произвольный код не запускался."):
        super().__init__(message, code="sandbox_unavailable", status=503)


_COMPARATORS = {"exact", "normalize_newlines", "trim_whitespace", "ignore_whitespace", "numeric_tolerance"}
_VISIBILITIES = {"public", "hidden"}
_SAFE_RESULT_STATUSES = {
    "passed", "wrong_answer", "syntax_error", "runtime_error", "time_limit_exceeded",
    "memory_limit_exceeded", "output_limit_exceeded", "internal_error", "sandbox_unavailable",
}


def _case(case_id: str, name: str, visibility: str, *, stdin: str = "", expected_output: str = "", args=None, expected=None):
    value = {"id": case_id, "name": name, "visibility": visibility}
    if args is None:
        value.update({"stdin": stdin, "expected_output": expected_output})
    else:
        value.update({"args": args, "expected": expected})
    return value


def _seeds() -> list[dict[str, Any]]:
    tuple_value = lambda *items: {"__type__": "tuple", "items": list(items)}
    return [
        {
            "scenario_id": "positive-number", "title": "Положительность числа", "mode": "program",
            "description": "Выведите YES для положительного числа и NO для нуля или отрицательного числа.",
            "starter_code": "n = int(input())\nprint('YES' if n > 0 else 'NO')",
            "test_cases": [_case("positive", "Положительное", "public", stdin="7\n", expected_output="YES\n"), _case("zero", "Ноль", "public", stdin="0\n", expected_output="NO\n"), _case("negative", "Отрицательное", "hidden", stdin="-4\n", expected_output="NO\n")],
        },
        {
            "scenario_id": "even-number", "title": "Чётность числа", "mode": "function", "function_name": "is_even",
            "description": "Реализуйте is_even(n), возвращающую True для чётных целых чисел.",
            "starter_code": "def is_even(n):\n    return n % 2 == 0",
            "test_cases": [_case("even-positive", "Положительное чётное", "public", args=[8], expected=True), _case("odd-negative", "Отрицательное нечётное", "public", args=[-3], expected=False), _case("zero", "Ноль", "hidden", args=[0], expected=True)],
        },
        {
            "scenario_id": "digit-sum", "title": "Сумма цифр", "mode": "function", "function_name": "digit_sum",
            "description": "Верните сумму цифр целого неотрицательного числа.",
            "starter_code": "def digit_sum(n):\n    return sum(int(d) for d in str(n))",
            "test_cases": [_case("digits", "Несколько цифр", "public", args=[507], expected=12), _case("single", "Одна цифра", "public", args=[4], expected=4), _case("zero", "Ноль", "hidden", args=[0], expected=0)],
        },
        {
            "scenario_id": "palindrome", "title": "Палиндром", "mode": "function", "function_name": "is_palindrome",
            "description": "Проверьте, читается ли строка одинаково слева направо и справа налево.",
            "starter_code": "def is_palindrome(text):\n    return text == text[::-1]",
            "test_cases": [_case("even", "Чётная длина", "public", args=["abba"], expected=True), _case("odd", "Нечётная длина", "public", args=["level"], expected=True), _case("false", "Не палиндром", "hidden", args=["python"], expected=False)],
        },
        {
            "scenario_id": "string-slice", "title": "Срезы строк", "mode": "function", "function_name": "middle",
            "description": "Верните символы строки без первого и последнего.",
            "starter_code": "def middle(text):\n    return text[1:-1]",
            "test_cases": [_case("long", "Обычная строка", "public", args=["boostudy"], expected="oostud"), _case("short", "Короткая строка", "hidden", args=["ab"], expected="")],
        },
        {
            "scenario_id": "count-characters", "title": "Подсчёт символов", "mode": "function", "function_name": "count_char",
            "description": "Посчитайте, сколько раз символ встречается в строке.",
            "starter_code": "def count_char(text, char):\n    return text.count(char)",
            "test_cases": [_case("repeated", "Повторения", "public", args=["banana", "a"], expected=3), _case("missing", "Нет совпадений", "hidden", args=["code", "x"], expected=0)],
        },
        {
            "scenario_id": "while-sum", "title": "Цикл while", "mode": "program",
            "description": "Считайте n и выведите сумму целых чисел от 1 до n включительно.",
            "starter_code": "n = int(input())\ni = 1\ntotal = 0\nwhile i <= n:\n    total += i\n    i += 1\nprint(total)",
            "test_cases": [_case("three", "Сумма до трёх", "public", stdin="3\n", expected_output="6\n"), _case("one", "Граница цикла", "hidden", stdin="1\n", expected_output="1\n")],
        },
        {
            "scenario_id": "clamp", "title": "Функция с несколькими аргументами", "mode": "function", "function_name": "clamp",
            "description": "Ограничьте значение диапазоном от low до high.",
            "starter_code": "def clamp(value, low, high):\n    return max(low, min(value, high))",
            "test_cases": [_case("inside", "Значение внутри", "public", args=[5, 0, 10], expected=5), _case("below", "Ниже границы", "public", args=[-3, 0, 10], expected=0), _case("above", "Выше границы", "hidden", args=[14, 0, 10], expected=10)],
        },
        {
            "scenario_id": "classify-logic-errors", "title": "Границы и логические условия", "mode": "function", "function_name": "classify",
            "assignment_id": "ai-lab.python.classify", "assignment_version": 1,
            "description": "Верните кортеж (n > 0, n % 2 == 0). Ноль не является положительным и является чётным.",
            "starter_code": "def classify(n):\n    return (n >= 0, n % 2 == 1)",
            "test_cases": [
                _case("positive-even", "Положительное чётное", "public", args=[2], expected=tuple_value(True, True)),
                _case("positive-odd", "Положительное нечётное", "public", args=[3], expected=tuple_value(True, False)),
                _case("negative-even", "Отрицательное чётное", "hidden", args=[-2], expected=tuple_value(False, True)),
                _case("negative-odd", "Отрицательное нечётное", "hidden", args=[-3], expected=tuple_value(False, False)),
                _case("zero", "Ноль", "hidden", args=[0], expected=tuple_value(False, True)),
            ],
            "rubric_json": [
                {"id": "structure", "assignment_criterion_id": "structure", "title": "Структура функции и возвращаемый тип", "description": "Возвращается пара из двух логических значений.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "positive-even", "projection": "tuple_bool_pair"}]},
                {"id": "positive", "assignment_criterion_id": "positive", "title": "Положительность ненулевых чисел", "description": "Первый элемент верно классифицирует ненулевые значения.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": case_id, "projection": "tuple.0"} for case_id in ("positive-even", "positive-odd", "negative-even", "negative-odd")]},
                {"id": "zero", "assignment_criterion_id": "zero", "title": "Обработка нуля", "description": "Ноль не определяется как положительное число.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "zero", "projection": "tuple.0"}]},
                {"id": "parity", "assignment_criterion_id": "parity", "title": "Определение чётности", "description": "Второй элемент верно определяет чётность.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": case_id, "projection": "tuple.1"} for case_id in ("positive-even", "positive-odd", "negative-even", "negative-odd", "zero")]},
            ],
        },
        {
            "scenario_id": "digit-sum-alternative", "title": "Альтернативная сумма цифр", "mode": "function", "function_name": "digit_sum",
            "assignment_id": "ai-lab.python.digit-sum", "assignment_version": 1,
            "description": "Задача на сумму цифр: примите любую корректную реализацию, не только эталонный алгоритм.",
            "starter_code": "def digit_sum(n):\n    total = 0\n    while n:\n        total += n % 10\n        n //= 10\n    return total",
            "test_cases": [_case("large", "Несколько разрядов", "public", args=[2026], expected=10), _case("zeros", "Нули внутри числа", "hidden", args=[1002], expected=3)],
            "rubric_json": [
                {"id": "multi-digit", "assignment_criterion_id": "multi-digit", "title": "Сумма цифр многозначного числа", "description": "Все цифры многозначного аргумента складываются.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "large", "projection": "whole"}, {"case_id": "large", "projection": "type"}, {"case_id": "zeros", "projection": "whole"}]},
                {"id": "embedded-zero", "assignment_criterion_id": "embedded-zero", "title": "Внутренние и завершающие нули", "description": "Нули не теряются при обработке разрядов.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "zeros", "projection": "whole"}]},
            ],
        },
        {
            "scenario_id": "digit-sum-evidence-v1", "title": "Сумма цифр · полный набор доказательств", "mode": "function", "function_name": "digit_sum",
            "assignment_id": "ai-lab.python.digit-sum", "assignment_version": 1,
            "description": "Синтетическая версия задания для Code Judge + AI. Входы включают ноль, границы, внутренние и завершающие нули.",
            "starter_code": "def digit_sum(n):\n    return sum(int(char) for char in str(n))",
            "test_cases": [
                _case("zero", "Ноль", "public", args=[0], expected=0),
                _case("single", "Однозначное число", "public", args=[8], expected=8),
                _case("pair", "Две цифры", "public", args=[19], expected=10),
                _case("internal-zero", "Внутренний ноль", "hidden", args=[502], expected=7),
                _case("trailing-zeros", "Завершающие нули", "hidden", args=[1200], expected=3),
                _case("all-nines", "Граница разрядов", "hidden", args=[99999], expected=45),
                _case("long", "Длинное число", "hidden", args=[9876543214], expected=49),
            ],
            "rubric_json": [
                {"id": "multi-digit", "assignment_criterion_id": "multi-digit", "title": "Сумма цифр многозначного числа", "description": "Все разряды складываются для малых и длинных значений.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "pair", "projection": "whole"}, {"case_id": "all-nines", "projection": "whole"}, {"case_id": "long", "projection": "whole"}, {"case_id": "long", "projection": "type"}]},
                {"id": "zero-single", "assignment_criterion_id": "zero-single", "title": "Ноль и однозначные числа", "description": "Ноль и любое однозначное значение возвращают правильную сумму.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "zero", "projection": "whole"}, {"case_id": "single", "projection": "whole"}]},
                {"id": "embedded-zero", "assignment_criterion_id": "embedded-zero", "title": "Внутренние и завершающие нули", "description": "Нули внутри числа и в конце не меняют разрядную логику.", "max_score": 1, "policy": "all_or_nothing", "checks": [{"case_id": "internal-zero", "projection": "whole"}, {"case_id": "trailing-zeros", "projection": "whole"}]},
            ],
        },
    ]


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise CodeJudgeError("Данные должны быть корректным JSON без бесконечных чисел.") from exc


def _validate_value(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        raise CodeJudgeError("Структура аргумента или результата слишком вложенная.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise CodeJudgeError("NaN и бесконечность не поддерживаются.")
        return value
    if isinstance(value, list):
        if len(value) > 2_000:
            raise CodeJudgeError("Слишком большой список аргументов.")
        return [_validate_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 2_000:
            raise CodeJudgeError("Слишком большой объект аргументов.")
        if value.get("__type__") == "tuple":
            items = value.get("items")
            if not isinstance(items, list):
                raise CodeJudgeError("Кортеж должен содержать список items.")
            return {"__type__": "tuple", "items": [_validate_value(item, depth + 1) for item in items]}
        if not all(isinstance(key, str) and len(key) <= 256 for key in value):
            raise CodeJudgeError("Ключи словаря должны быть строками длиной до 256 символов.")
        return {key: _validate_value(item, depth + 1) for key, item in value.items()}
    raise CodeJudgeError("Поддерживаются только безопасные JSON-типы: int, float, str, bool, list, tuple и dict.")


def validate_test_set(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CodeJudgeError("Ожидались данные набора тестов.")
    title = str(payload.get("title") or "").strip()[:180]
    if not title:
        raise CodeJudgeError("Укажите название тестового набора.")
    mode = str(payload.get("mode") or "")
    if mode not in {"program", "function"}:
        raise CodeJudgeError("Режим должен быть program или function.")
    function_name = str(payload.get("function_name") or "").strip()
    if mode == "function" and (len(function_name) > 80 or not function_name.isidentifier()):
        raise CodeJudgeError("Укажите корректное имя Python-функции.")
    if mode == "program":
        function_name = ""
    comparator = str(payload.get("comparator") or "exact")
    if comparator not in _COMPARATORS:
        raise CodeJudgeError("Неизвестная стратегия сравнения результатов.")
    try:
        tolerance = float(payload.get("tolerance", 1e-6))
    except (TypeError, ValueError, OverflowError) as exc:
        raise CodeJudgeError("Допуск числового сравнения должен быть числом.") from exc
    if not (0 <= tolerance <= 1):
        raise CodeJudgeError("Допуск числового сравнения должен быть от 0 до 1.")
    raw_cases = payload.get("test_cases")
    limits = code_judge_limits()
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= limits["max_test_cases"]:
        raise CodeJudgeError(f"Набор должен содержать от 1 до {limits['max_test_cases']} тестов.")
    cases = []
    for index, raw in enumerate(raw_cases, 1):
        if not isinstance(raw, dict):
            raise CodeJudgeError(f"Тест №{index}: ожидался объект.")
        visibility = str(raw.get("visibility") or "public")
        if visibility not in _VISIBILITIES:
            raise CodeJudgeError(f"Тест №{index}: выберите видимость public или hidden.")
        case_id = str(raw.get("id") or f"case-{index}")[:80]
        name = str(raw.get("name") or f"Тест {index}").strip()[:120]
        if mode == "program":
            stdin = raw.get("stdin", "")
            expected_output = raw.get("expected_output", "")
            if not isinstance(stdin, str) or not isinstance(expected_output, str):
                raise CodeJudgeError(f"Тест №{index}: вход и ожидаемый вывод должны быть строками.")
            if len(stdin.encode("utf-8")) > 16_384 or len(expected_output.encode("utf-8")) > 16_384:
                raise CodeJudgeError(f"Тест №{index}: размер входа или ответа превышает 16 КБ.")
            group_id = str(raw.get("group_id") or "").strip()[:80]
            cases.append({"id": case_id, "name": name, "visibility": visibility, "stdin": stdin, "expected_output": expected_output, **({"group_id": group_id} if group_id else {})})
        else:
            args = raw.get("args", [])
            if not isinstance(args, list) or len(args) > 64:
                raise CodeJudgeError(f"Тест №{index}: передайте до 64 аргументов функции.")
            checked_args = [_validate_value(value) for value in args]
            expected = _validate_value(raw.get("expected"))
            if _json_size({"args": checked_args, "expected": expected}) > 16_384:
                raise CodeJudgeError(f"Тест №{index}: аргументы и ожидаемый результат превышают 16 КБ.")
            cases.append({
                "id": case_id,
                "name": name,
                "visibility": visibility,
                "args": checked_args,
                "expected": expected,
                **({"group_id": str(raw.get("group_id")).strip()[:80]} if str(raw.get("group_id") or "").strip() else {}),
            })
    starter_code = payload.get("starter_code") or ""
    if not isinstance(starter_code, str) or len(starter_code.encode("utf-8")) > limits["max_source_bytes"]:
        raise CodeJudgeError(f"Стартовый код превышает {limits['max_source_bytes'] // 1024} КБ.")
    assignment_id = str(payload.get("assignment_id") or "").strip() or None
    assignment_version = payload.get("assignment_version")
    assignment = next((item for item in list_python_assignments() if item["assignment_id"] == assignment_id and str(item["assignment_version"]) == str(assignment_version)), None)
    if assignment_id:
        if not assignment:
            raise CodeJudgeError("Связь можно создать только с известным синтетическим Python-заданием.")
        try:
            assignment_version = int(assignment_version)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CodeJudgeError("Укажите версию задания.") from exc
        if assignment_version != assignment["assignment_version"]:
            raise CodeJudgeError("Версия задания устарела. Обновите список назначений и набор тестов.")
    else:
        assignment_version = None
    rubric = _validate_rubric(payload.get("rubric_json", []), cases, mode, assignment=assignment)
    if assignment:
        criteria_by_id = {item["id"]: item for item in assignment["criteria"]}
        linked_ids = [item.get("assignment_criterion_id") for item in rubric if item.get("assignment_criterion_id")]
        if len(linked_ids) != len(set(linked_ids)):
            raise CodeJudgeError("Каждый критерий задания можно связать только с одним критерием Code Judge.")
        for item in rubric:
            linked_id = item.get("assignment_criterion_id")
            if not linked_id:
                raise CodeJudgeError("Связанная рубрика должна привязать каждый критерий к стабильному ID критерия задания.")
            if linked_id not in criteria_by_id or abs(item["max_score"] - criteria_by_id[linked_id]["max_score"]) > 0.001:
                raise CodeJudgeError("ID или максимум критерия не совпадает с версией задания.")
    normalized = {
        "title": title,
        "description": str(payload.get("description") or "")[:12_000],
        "mode": mode,
        "function_name": function_name or None,
        "comparator": comparator,
        "tolerance": tolerance,
        "starter_code": starter_code,
        "test_cases": cases,
        "rubric_json": rubric,
        "assignment_id": assignment_id,
        "assignment_version": assignment_version,
    }
    if _json_size(normalized) > limits["max_test_set_bytes"]:
        raise CodeJudgeError(f"Размер набора превышает {limits['max_test_set_bytes'] // 1024} КБ.")
    return normalized


def _validate_rubric(raw: Any, cases: list[dict], mode: str, *, assignment: dict | None = None) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > 20:
        raise CodeJudgeError("Рубрика должна содержать не более 20 критериев.")
    case_ids = {case["id"] for case in cases}
    group_ids = {case.get("group_id") for case in cases if case.get("group_id")}
    if len(case_ids) != len(cases):
        raise CodeJudgeError("Идентификаторы тестов должны быть уникальными.")
    result = []
    seen = set()
    for index, criterion in enumerate(raw, 1):
        if not isinstance(criterion, dict):
            raise CodeJudgeError(f"Критерий №{index}: ожидался объект.")
        criterion_id = str(criterion.get("id") or f"criterion-{index}")[:80]
        title = str(criterion.get("title") or "").strip()[:200]
        description = str(criterion.get("description") or title).strip()[:1000]
        assignment_criterion_id = str(criterion.get("assignment_criterion_id") or "").strip() or None
        try:
            maximum = float(criterion.get("max_score"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise CodeJudgeError(f"Критерий №{index}: укажите максимальный балл.") from exc
        checks = criterion.get("checks")
        policy = str(criterion.get("policy") or criterion.get("scoring_rule") or "all_or_nothing")
        policy = {"all_required": "all_or_nothing", "proportional": "proportional"}.get(policy, policy)
        if not title or not description or criterion_id in seen or not 0 < maximum <= 100 or policy not in {"all_or_nothing", "proportional"}:
            raise CodeJudgeError(f"Критерий №{index}: проверьте название, балл и политику «всё или ничего».")
        if not isinstance(checks, list) or len(checks) > 30:
            raise CodeJudgeError(f"Критерий №{index}: требуется список из 0–30 проверок.")
        checked = []
        for check in checks:
            if not isinstance(check, dict):
                raise CodeJudgeError(f"Критерий №{index}: тест проверки не найден.")
            case_id = check.get("case_id")
            group_id = check.get("group_id")
            if (case_id is None) == (group_id is None) or (case_id is not None and case_id not in case_ids) or (group_id is not None and group_id not in group_ids):
                raise CodeJudgeError(f"Критерий №{index}: выберите существующий тест или группу тестов.")
            projection = check.get("projection", "whole")
            if not _valid_projection(projection, mode):
                raise CodeJudgeError(f"Критерий №{index}: неизвестное проверяемое условие.")
            checked.append({("case_id" if case_id is not None else "group_id"): case_id if case_id is not None else group_id, "projection": projection})
        seen.add(criterion_id)
        result.append({"id": criterion_id, "assignment_criterion_id": assignment_criterion_id, "title": title, "description": description, "max_score": maximum, "policy": policy, "scoring_rule": "all_required" if policy == "all_or_nothing" else "proportional", "checks": checked})
    return result


def _valid_projection(projection: Any, mode: str) -> bool:
    if not isinstance(projection, str):
        return False
    if projection in {"whole", "type"}:
        return mode == "function" or projection == "whole"
    if projection == "tuple_bool_pair":
        return mode == "function"
    return bool(re.fullmatch(r"(?:tuple|list)\.\d+(?:\.type)?|dict\..+(?:\.type)?", projection)) and mode == "function"


def _serialize_test_set(item: AiLabCodeJudgeTestSet) -> dict[str, Any]:
    return {
        "id": item.id,
        "scenario_id": item.scenario_id,
        "title": item.title,
        "description": item.description or "",
        "mode": item.mode,
        "function_name": item.function_name or "",
        "comparator": item.comparator,
        "tolerance": item.tolerance,
        "starter_code": item.starter_code or "",
        "test_cases": item.test_cases or [],
        "rubric_json": item.rubric_json or [],
        "assignment_id": item.assignment_id,
        "assignment_version": item.assignment_version,
        "test_set_version": item.test_set_version,
        "rubric_version": item.rubric_version or 1,
        "is_seeded": bool(item.is_seeded),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def ensure_seeded_test_sets() -> list[dict[str, Any]]:
    for seed in _seeds():
        exists = AiLabCodeJudgeTestSet.query.filter_by(scenario_id=seed["scenario_id"]).first()
        if exists:
            changed = False
            if not exists.rubric_json and seed.get("rubric_json"):
                exists.rubric_json = seed["rubric_json"]
                exists.rubric_version = max(1, exists.rubric_version or 1) + 1
                changed = True
            if not exists.assignment_id and seed.get("assignment_id"):
                exists.assignment_id = seed["assignment_id"]
                exists.assignment_version = seed["assignment_version"]
                rubric_ids = {item.get("id") for item in (seed.get("rubric_json") or [])}
                for criterion in exists.rubric_json or []:
                    if criterion.get("id") in rubric_ids and not criterion.get("assignment_criterion_id"):
                        criterion["assignment_criterion_id"] = criterion["id"]
                if exists.rubric_json:
                    exists.rubric_json = list(exists.rubric_json)
                    exists.rubric_version = max(1, exists.rubric_version or 1) + 1
                changed = True
            if exists.assignment_id == seed.get("assignment_id") and exists.rubric_json:
                normalized_rubric = _validate_rubric(
                    exists.rubric_json,
                    exists.test_cases or [],
                    exists.mode,
                    assignment=next((item for item in list_python_assignments() if item["assignment_id"] == exists.assignment_id), None),
                )
                if normalized_rubric != exists.rubric_json:
                    exists.rubric_json = normalized_rubric
                    exists.rubric_version = max(1, exists.rubric_version or 1) + 1
                    changed = True
            if changed:
                exists.test_set_version += 1
            continue
        normalized = validate_test_set(seed)
        db.session.add(AiLabCodeJudgeTestSet(**normalized, scenario_id=seed["scenario_id"], is_seeded=True, test_set_version=1, rubric_version=1))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return [_serialize_test_set(item) for item in AiLabCodeJudgeTestSet.query.order_by(AiLabCodeJudgeTestSet.id.asc()).all()]


def save_test_set(payload: Any, actor_user_id: int) -> dict[str, Any]:
    data = validate_test_set(payload)
    raw_id = payload.get("id") if isinstance(payload, dict) else None
    try:
        parsed_id = int(raw_id) if raw_id else None
    except (TypeError, ValueError, OverflowError) as exc:
        raise CodeJudgeError("Идентификатор тестового набора некорректен.") from exc
    item = db.session.get(AiLabCodeJudgeTestSet, parsed_id) if parsed_id else None
    if raw_id and item is None:
        raise CodeJudgeError("Тестовый набор не найден.", code="test_set_not_found", status=404)
    if item is None:
        scenario_id = "custom-" + uuid.uuid4().hex[:16]
        item = AiLabCodeJudgeTestSet(scenario_id=scenario_id, test_set_version=1, rubric_version=1, is_seeded=False)
        db.session.add(item)
    else:
        if (item.rubric_json or []) != data["rubric_json"]:
            item.rubric_version = max(1, item.rubric_version or 1) + 1
        item.test_set_version += 1
    for key, value in data.items():
        setattr(item, key, value)
    item.created_by_user_id = item.created_by_user_id or actor_user_id
    db.session.commit()
    return _serialize_test_set(item)


def delete_test_set(test_set_id: int) -> None:
    item = db.session.get(AiLabCodeJudgeTestSet, test_set_id)
    if item is None:
        raise CodeJudgeError("Тестовый набор не найден.", code="test_set_not_found", status=404)
    if item.is_seeded:
        raise CodeJudgeError("Готовые системные сценарии нельзя удалить.", code="seeded_test_set", status=409)
    db.session.delete(item)
    db.session.commit()


def _serialize_run(item: AiLabCodeJudgeRun) -> dict[str, Any]:
    return {
        "id": item.id,
        "scenario_id": item.scenario_id,
        "test_set_id": item.test_set_id,
        "run_type": item.run_type,
        "mode": item.mode,
        "status": item.status,
        "test_set_version": item.test_set_version,
        "runner_version": item.runner_version,
        "code": item.code,
        "code_hash": item.code_hash,
        "result": item.result_json,
        "duration_ms": item.duration_ms,
        "technical_error": item.technical_error,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _project(value: Any, projection: str) -> tuple[bool, Any]:
    if projection == "whole":
        return True, value
    def type_name(item: Any) -> str:
        if isinstance(item, dict) and item.get("__type__") == "tuple":
            return "tuple"
        if item is None:
            return "NoneType"
        if isinstance(item, bool):
            return "bool"
        if isinstance(item, int):
            return "int"
        if isinstance(item, float):
            return "float"
        if isinstance(item, str):
            return "str"
        if isinstance(item, list):
            return "list"
        if isinstance(item, dict):
            return "dict"
        return type(item).__name__
    if projection == "type":
        return True, type_name(value)
    if projection == "tuple_bool_pair":
        if not isinstance(value, dict) or value.get("__type__") != "tuple" or not isinstance(value.get("items"), list):
            return False, None
        return True, len(value["items"]) == 2 and all(type(item) is bool for item in value["items"])
    dict_match = re.fullmatch(r"dict\.(.+?)(\.type)?", projection)
    if dict_match:
        if not isinstance(value, dict) or value.get("__type__") == "tuple":
            return False, None
        key, typed = dict_match.groups()
        if key not in value:
            return False, None
        selected = value[key]
        return (True, type_name(selected)) if typed else (True, selected)
    match = re.fullmatch(r"(tuple|list)\.(\d+)(\.type)?", projection)
    if not match:
        return False, None
    kind, raw_index, typed = match.groups()
    index = int(raw_index)
    if kind == "tuple":
        if not isinstance(value, dict) or value.get("__type__") != "tuple":
            return False, None
        items = value.get("items")
    else:
        items = value if isinstance(value, list) else None
    if not isinstance(items, list) or len(items) <= index:
        return False, None
    selected = items[index]
    return (True, type_name(selected)) if typed else (True, selected)


def _score_rubric(rubric: list[dict], cases: list[dict], tests: list[dict]) -> dict[str, Any]:
    case_by_id = {case["id"]: case for case in cases}
    test_by_id = {test.get("id"): test for test in tests}
    case_ids_by_group: dict[str, list[str]] = {}
    for case in cases:
        if case.get("group_id"):
            case_ids_by_group.setdefault(case["group_id"], []).append(case["id"])
    scores = []
    for criterion in rubric:
        evidence = []
        check_results: list[bool | None] = []
        for check in criterion["checks"]:
            case_ids = [check["case_id"]] if check.get("case_id") else case_ids_by_group.get(check["group_id"], [])
            for case_id in case_ids:
                test = test_by_id.get(case_id)
                case = case_by_id[case_id]
                if not test or test.get("status") in {"internal_error", "sandbox_unavailable", "time_limit_exceeded", "memory_limit_exceeded", "output_limit_exceeded", "syntax_error", "runtime_error"}:
                    check_results.append(None)
                    evidence.append({"case_id": case_id, "status": "unconfirmed", "reason": "Тест не дал достоверного результата исполнения."})
                    continue
                projection = check["projection"]
                expected_value = case.get("expected") if "expected" in case else case.get("expected_output")
                if "actual" not in test:
                    check_results.append(None)
                    evidence.append({"case_id": case_id, "status": "unconfirmed", "reason": "Runner не вернул фактический результат."})
                    continue
                actual_value = test["actual"]
                if projection == "tuple_bool_pair":
                    actual_ok, actual = _project(actual_value, projection)
                    expected_ok, expected = True, True
                elif projection == "type":
                    actual_ok, actual = _project(actual_value, "type")
                    expected_ok, expected = _project(expected_value, "type")
                else:
                    expected_ok, expected = _project(expected_value, projection)
                    actual_ok, actual = _project(actual_value, projection)
                if not expected_ok or not actual_ok:
                    check_results.append(None)
                    evidence.append({"case_id": case_id, "status": "unconfirmed", "reason": "Результат не содержит выбранного элемента или типа."})
                    continue
                matched = test.get("status") == "passed" if projection == "whole" else type(expected) is type(actual) and expected == actual
                check_results.append(matched)
                evidence_item = {"case_id": case_id, "status": "passed" if matched else "failed", "projection": projection}
                if case.get("visibility") != "hidden":
                    evidence_item.update({"expected": expected, "actual": actual})
                evidence.append(evidence_item)
        uncertain = not check_results or any(value is None for value in check_results)
        passed_count = sum(value is True for value in check_results)
        failed_count = sum(value is False for value in check_results)
        if uncertain:
            status = "insufficient_data"
            awarded = None
            rationale = "Недостаточно достоверных результатов связанных тестов для этого критерия."
        elif criterion["policy"] == "proportional":
            status = "fulfilled" if passed_count == len(check_results) else "not_fulfilled"
            awarded = round(criterion["max_score"] * passed_count / len(check_results), 4)
            rationale = f"Пройдено {passed_count} из {len(check_results)} связанных проверок; балл рассчитан по правилу proportional."
        else:
            status = "fulfilled" if failed_count == 0 else "not_fulfilled"
            awarded = criterion["max_score"] if failed_count == 0 else 0
            rationale = "Все связанные проверки пройдены." if failed_count == 0 else f"Не пройдены связанные проверки: {failed_count} из {len(check_results)}."
        scores.append({
            "id": criterion["id"], "title": criterion["title"], "max_score": criterion["max_score"],
            "assignment_criterion_id": criterion.get("assignment_criterion_id"),
            "description": criterion.get("description") or criterion["title"], "policy": criterion.get("policy", "all_or_nothing"),
            "scoring_rule": criterion.get("scoring_rule", "all_required"), "status": status,
            "score_awarded": awarded, "rationale": rationale,
            "evidence": evidence,
        })
    return {
        "criteria": scores,
        "confirmed_score": sum(item["score_awarded"] or 0 for item in scores if item["score_awarded"] is not None),
        "confirmed_max_score": sum(item["max_score"] for item in scores if item["status"] != "insufficient_data"),
        "unconfirmed_max_score": sum(item["max_score"] for item in scores if item["status"] == "insufficient_data"),
        "max_score": sum(item["max_score"] for item in scores),
    }


def get_run(run_id: int) -> dict[str, Any] | None:
    item = db.session.get(AiLabCodeJudgeRun, run_id)
    return _serialize_run(item) if item else None


def list_history(limit: int = 40) -> list[dict[str, Any]]:
    rows = AiLabCodeJudgeRun.query.order_by(AiLabCodeJudgeRun.created_at.desc()).limit(max(1, min(100, limit))).all()
    return [_serialize_run(item) for item in rows]


def _normalize_result(result: Any, expected_count: int) -> dict[str, Any]:
    if not isinstance(result, dict) or not isinstance(result.get("tests"), list):
        raise RunnerUnavailable("Runner вернул неполный структурированный результат.")
    tests = []
    for raw in result["tests"]:
        if not isinstance(raw, dict) or raw.get("status") not in _SAFE_RESULT_STATUSES:
            raise RunnerUnavailable("Runner вернул неизвестный статус теста.")
        tests.append({
            key: raw.get(key)
            for key in ("id", "name", "visibility", "status", "execution_time_ms", "expected", "actual", "stdout", "stderr", "error_message", "diff")
            if key in raw
        })
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    passed = sum(test["status"] == "passed" for test in tests)
    total = len(tests)
    if total > expected_count:
        raise RunnerUnavailable("Runner вернул больше тестов, чем было отправлено.")
    return {
        "status": "completed" if total == expected_count else "incomplete",
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "execution_time_ms": max(0, int(summary.get("execution_time_ms") or 0)),
        "tests": tests,
        "expected_total": expected_count,
        "complete": total == expected_count,
    }


def run_request(actor_user_id: int, payload: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(payload, dict):
        raise CodeJudgeError("Ожидался JSON-запрос.")
    request_key = str(payload.get("request_key") or "")
    try:
        request_key = str(uuid.UUID(request_key))
    except (ValueError, AttributeError) as exc:
        raise CodeJudgeError("Обновите страницу и повторите запрос.", code="invalid_request_key") from exc
    existing = AiLabCodeJudgeRun.query.filter_by(actor_user_id=actor_user_id, request_key=request_key).first()
    if existing:
        return _serialize_run(existing), False

    run_type = str(payload.get("run_type") or "run")
    if run_type not in {"run", "submit"}:
        raise CodeJudgeError("Тип запуска должен быть run или submit.")
    data = validate_test_set(payload.get("test_set"))
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip() or "\x00" in code:
        raise CodeJudgeError("Добавьте Python-код для проверки.")
    limits = code_judge_limits()
    if len(code.encode("utf-8")) > limits["max_source_bytes"]:
        raise CodeJudgeError(f"Исходный код превышает {limits['max_source_bytes'] // 1024} КБ.")
    cases = data["test_cases"] if run_type == "submit" else [case for case in data["test_cases"] if case["visibility"] == "public"]
    if not cases:
        raise CodeJudgeError("Для кнопки «Запустить» нужен хотя бы один публичный тест.")
    test_set_id = payload.get("test_set_id")
    try:
        parsed_test_set_id = int(test_set_id) if test_set_id else None
    except (TypeError, ValueError, OverflowError) as exc:
        raise CodeJudgeError("Идентификатор тестового набора некорректен.") from exc
    test_set = db.session.get(AiLabCodeJudgeTestSet, parsed_test_set_id) if parsed_test_set_id else None
    if test_set_id and test_set is None:
        raise CodeJudgeError("Выбранный тестовый набор не найден.", code="test_set_not_found", status=404)
    if test_set:
        try:
            requested_version = int(payload.get("test_set_version") or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CodeJudgeError("Версия сохранённого тестового набора некорректна.") from exc
        if requested_version != test_set.test_set_version:
            raise CodeJudgeError("Набор тестов изменился. Обновите страницу и сохраните актуальную версию.", code="stale_test_set", status=409)
        saved_data = validate_test_set(_serialize_test_set(test_set))
        if data != saved_data:
            raise CodeJudgeError("Сначала сохраните изменения набора: отчёт AI использует только его неизменяемую версию.", code="unsaved_test_set", status=409)
        data = saved_data
    scenario_id = test_set.scenario_id if test_set else "adhoc-" + uuid.uuid4().hex[:12]
    version = test_set.test_set_version if test_set else max(1, int(payload.get("test_set_version") or 1))
    item = AiLabCodeJudgeRun(
        actor_user_id=actor_user_id,
        test_set_id=test_set.id if test_set else None,
        request_key=request_key,
        scenario_id=scenario_id,
        run_type=run_type,
        mode=data["mode"],
        status="queued",
        test_set_version=version,
        code=code,
        code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
    )
    db.session.add(item)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = AiLabCodeJudgeRun.query.filter_by(actor_user_id=actor_user_id, request_key=request_key).first()
        if existing:
            return _serialize_run(existing), False
        raise

    started = __import__("time").monotonic()
    item.status = "running"
    db.session.commit()
    try:
        from app.ai_lab.code_judge_runner_client import run_isolated, runner_diagnostics

        diagnostics = runner_diagnostics()
        if not diagnostics.get("ready") or diagnostics.get("secure_profile_verified") is not True:
            raise RunnerUnavailable(diagnostics.get("message") or "Изолированный runner недоступен.")
        request_data = {
            "code": code,
            "mode": data["mode"],
            "function_name": data["function_name"],
            "comparator": data["comparator"],
            "tolerance": data["tolerance"],
            "test_cases": cases,
            "limits": limits,
        }
        raw_result = run_isolated(request_data)
        result = _normalize_result(raw_result, len(cases))
        result["test_set_snapshot"] = data
        result["test_set_snapshot"]["test_set_version"] = version
        result["test_set_snapshot"]["rubric_version"] = test_set.rubric_version if test_set else 1
        result["rubric"] = _score_rubric(data["rubric_json"], data["test_cases"], result["tests"])
        item.result_json = result
        item.runner_version = str(raw_result.get("runner_version") or "unknown")
        item.duration_ms = max(0, round((__import__("time").monotonic() - started) * 1000))
        if result["complete"]:
            item.status = "accepted" if run_type == "submit" and result["failed"] == 0 else "wrong_answer" if run_type == "submit" else "completed"
        else:
            item.status = "incomplete"
            item.technical_error = "Не все тесты были выполнены. Требуется повторная проверка."
    except RunnerUnavailable as exc:
        item.status = "sandbox_unavailable"
        item.technical_error = str(exc)
        item.duration_ms = max(0, round((__import__("time").monotonic() - started) * 1000))
    except Exception as exc:
        current_app.logger.exception("Code Judge failed: run_id=%s exception_type=%s", item.id, type(exc).__name__)
        item.status = "internal_error"
        item.technical_error = "Внутренняя ошибка Code Judge. Код и тестовые данные сохранены в локальной истории."
        item.duration_ms = max(0, round((__import__("time").monotonic() - started) * 1000))
    db.session.commit()
    return _serialize_run(item), True
