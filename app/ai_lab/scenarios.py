"""Воспроизводимые синтетические сценарии AI Homework для базового Python."""
from __future__ import annotations

from copy import deepcopy
import re
from flask import has_app_context


SCENARIOS: tuple[dict, ...] = (
    {
        "id": "py-classify-judge-17",
        "assignment_id": "ai-lab.python.classify",
        "assignment_version": 1,
        "assignment_criteria": [
            {"id": "structure", "title": "Структура функции и возвращаемый тип", "description": "Функция возвращает пару логических значений.", "max_score": 1},
            {"id": "positive", "title": "Положительность ненулевых чисел", "description": "Первый элемент верно отражает n > 0 для ненулевых значений.", "max_score": 1},
            {"id": "zero", "title": "Обработка нуля", "description": "Ноль не определяется как положительное число.", "max_score": 1},
            {"id": "parity", "title": "Определение чётности", "description": "Второй элемент верно определяет чётность.", "max_score": 1},
        ],
        "title": "classify(n) · две логические ошибки",
        "type": "python",
        "subject": "Информатика",
        "topic": "Границы и чётность",
        "difficulty": "Базовый",
        "condition": "Реализуйте classify(n), возвращающую кортеж (n > 0, n % 2 == 0). Ноль не положителен, но чётен.",
        "student_solution": "def classify(n):\n    return (n >= 0, n % 2 == 1)",
        "reference_answer": "def classify(n):\n    return (n > 0, n % 2 == 0)",
        "criteria": [
            "1 балл — структура функции и возвращаемый тип.",
            "1 балл — правильность определения положительности для ненулевых чисел.",
            "1 балл — обработка нуля.",
            "1 балл — правильность определения чётности.",
        ],
        "max_score": 4,
        "expected": {
            "mistake_types": ["boundary", "logic"],
            "score": 2,
            "acceptable_conclusion": "Ненулевые числа классифицируются по положительности верно; ноль ошибочно признан положительным, а чётность перепутана.",
            "recommendations": ["Граничные значения", "Чётность числа"],
            "human_review": True,
            "coverage_terms": ["ноль", "чёт"],
        },
    },
    {
        "id": "py-types-01",
        "title": "Переменная и тип",
        "type": "short_answer",
        "subject": "Информатика",
        "topic": "Переменные и типы",
        "difficulty": "Начальный",
        "condition": "Переменной value присвоено значение 12. Какой тип имеет value в Python? Ответь названием типа.",
        "student_solution": "int",
        "reference_answer": "int",
        "criteria": ["За точное название типа начисляется 1 балл."],
        "max_score": 1,
        "expected": {
            "mistake_types": [],
            "score": 1,
            "acceptable_conclusion": "Тип переменной — int.",
            "recommendations": [],
            "human_review": False,
        },
    },
    {
        "id": "py-arithmetic-02",
        "title": "Целочисленное деление",
        "type": "short_answer",
        "subject": "Информатика",
        "topic": "Арифметика",
        "difficulty": "Начальный",
        "condition": "Чему равно выражение 17 // 5 в Python? Укажи только число.",
        "student_solution": "2",
        "reference_answer": "3",
        "criteria": ["2 балла за верный результат."],
        "max_score": 2,
        "expected": {
            "mistake_types": ["calculation"],
            "score": 0,
            "acceptable_conclusion": "Целочисленное деление даёт 3.",
            "recommendations": ["Целочисленное деление и остаток."],
            "human_review": False,
        },
    },
    {
        "id": "py-logic-03",
        "title": "Приоритет логических операторов",
        "type": "choice",
        "subject": "Информатика",
        "topic": "Логические операторы",
        "difficulty": "Начальный",
        "condition": "Какое значение получится у выражения not (2 > 1 and 0 == 0)? Выбери один ответ: A) True; B) False.",
        "student_solution": "A",
        "reference_answer": "B",
        "criteria": ["1 балл за выбор B."],
        "max_score": 1,
        "expected": {
            "mistake_types": ["logic"],
            "score": 0,
            "acceptable_conclusion": "Оба сравнения истинны, поэтому not меняет результат на False.",
            "recommendations": ["Порядок вычисления not, and и сравнений."],
            "human_review": False,
        },
    },
    {
        "id": "py-boundary-04",
        "title": "Граничное значение в условии",
        "type": "text",
        "subject": "Информатика",
        "topic": "Сравнения и условия",
        "difficulty": "Начальный",
        "condition": "Функция должна возвращать True для возраста 18 лет и старше. Ученик написал проверку age > 18. Объясни, верно ли условие, и предложи исправление.",
        "student_solution": "Условие верное: совершеннолетие начинается после 18 лет.",
        "reference_answer": "Нужно использовать age >= 18, потому что значение 18 тоже должно дать True.",
        "criteria": [
            "Замечена ошибка на границе 18 лет.",
            "Предложено сравнение age >= 18.",
            "Объяснено отличие > от >=.",
        ],
        "max_score": 3,
        "expected": {
            "mistake_types": ["boundary", "logic"],
            "score": 0,
            "acceptable_conclusion": "Условие пропускает ровно 18 лет; нужно age >= 18.",
            "recommendations": ["Граничные значения", "Операторы сравнения."],
            "human_review": True,
            "coverage_terms": ["18", ">="],
        },
    },
    {
        "id": "py-comparison-05",
        "title": "Функция с возрастным порогом",
        "type": "python",
        "subject": "Информатика",
        "topic": "Сравнения и функции",
        "difficulty": "Начальный",
        "condition": "Напиши программу: она читает целое число age и печатает True, если age не меньше 18, иначе False.",
        "student_solution": "age = int(input())\nprint(age > 18)",
        "reference_answer": "age = int(input())\nprint(age >= 18)",
        "criteria": ["Для всех входов программа печатает правильное логическое значение."],
        "max_score": 4,
        "test_cases": [
            {"input": "18\n", "output": "True"},
            {"input": "17\n", "output": "False"},
            {"input": "25\n", "output": "True"},
        ],
        "expected": {
            "mistake_types": ["boundary"],
            "score": 2.67,
            "acceptable_conclusion": "Код проходит два из трёх тестов и ошибается на значении 18.",
            "recommendations": ["Граничные значения", "Операторы сравнения."],
            "human_review": True,
            "coverage_terms": ["18", "границ"],
        },
    },
    {
        "id": "py-for-06",
        "title": "Сумма чисел циклом for",
        "type": "python",
        "subject": "Информатика",
        "topic": "Цикл for",
        "difficulty": "Начальный",
        "condition": "Прочитай n и выведи сумму целых чисел от 1 до n включительно. Гарантируется n >= 1.",
        "student_solution": "n = int(input())\ntotal = 0\nfor number in range(1, n + 1):\n    total += number\nprint(total)",
        "reference_answer": "n = int(input())\ntotal = 0\nfor number in range(1, n + 1):\n    total += number\nprint(total)",
        "criteria": ["Программа правильно обрабатывает все значения n >= 1."],
        "max_score": 4,
        "test_cases": [
            {"input": "1\n", "output": "1"},
            {"input": "5\n", "output": "15"},
            {"input": "10\n", "output": "55"},
        ],
        "expected": {
            "mistake_types": [],
            "score": 4,
            "acceptable_conclusion": "Все контрольные тесты пройдены.",
            "recommendations": [],
            "human_review": True,
        },
    },
    {
        "id": "py-while-07",
        "title": "Цикл while без изменения счётчика",
        "type": "python",
        "subject": "Информатика",
        "topic": "Цикл while",
        "difficulty": "Начальный",
        "condition": "Прочитай n и выведи числа от 0 до n включительно. Найди и исправь причину бесконечного цикла.",
        "student_solution": "n = int(input())\ni = 0\nwhile i <= n:\n    print(i)",
        "reference_answer": "n = int(input())\ni = 0\nwhile i <= n:\n    print(i)\n    i += 1",
        "criteria": ["Цикл завершается.", "Выводятся значения 0..n включительно."],
        "max_score": 4,
        "test_cases": [
            {"input": "2\n", "output": "0\n1\n2"},
            {"input": "0\n", "output": "0"},
        ],
        "expected": {
            "mistake_types": ["logic"],
            "score": 0,
            "acceptable_conclusion": "Переменная i не меняется, поэтому условие остаётся истинным.",
            "recommendations": ["Циклы while и изменение счётчика."],
            "human_review": True,
            "coverage_terms": ["счётчик"],
        },
    },
    {
        "id": "py-strings-08",
        "title": "Срез строки",
        "type": "short_answer",
        "subject": "Информатика",
        "topic": "Строки",
        "difficulty": "Начальный",
        "condition": "Чему равно выражение 'boostudy'[1:4]? Ответь строкой без кавычек.",
        "student_solution": "oos",
        "reference_answer": "oos",
        "criteria": ["2 балла за точный результат."],
        "max_score": 2,
        "expected": {
            "mistake_types": [],
            "score": 2,
            "acceptable_conclusion": "Срез содержит символы с индексами 1, 2 и 3.",
            "recommendations": [],
            "human_review": False,
        },
    },
    {
        "id": "py-function-09",
        "title": "Альтернативная реализация функции",
        "type": "text",
        "subject": "Информатика",
        "topic": "Функции",
        "difficulty": "Начальный",
        "condition": "Нужно реализовать функцию add(a, b), возвращающую сумму аргументов. Оцени решение и учти допустимые альтернативные способы.",
        "student_solution": "Можно определить add как lambda a, b: a + b. Такая функция вернёт сумму двух переданных значений.",
        "reference_answer": "Подходит любая корректная реализация, например def add(a, b): return a + b.",
        "criteria": ["Функция принимает два аргумента.", "Результат равен a + b."],
        "max_score": 5,
        "expected": {
            "mistake_types": [],
            "score": 5,
            "acceptable_conclusion": "Лямбда-выражение является допустимой альтернативной реализацией.",
            "recommendations": [],
            "human_review": True,
            "coverage_terms": ["аргумент"],
        },
    },
    {
        "id": "py-arguments-10",
        "title": "Синтаксис объявления функции",
        "type": "python",
        "subject": "Информатика",
        "topic": "Функции и аргументы",
        "difficulty": "Начальный",
        "condition": "Прочитай имя и выведи приветствие. Исправь программу так, чтобы она запускалась и использовала аргумент name.",
        "student_solution": "def greet(name\n    print('Привет, ' + name)\ngreet(input())",
        "reference_answer": "def greet(name):\n    print('Привет, ' + name)\ngreet(input())",
        "criteria": ["Программа запускается.", "Функция принимает имя и печатает приветствие."],
        "max_score": 3,
        "test_cases": [
            {"input": "Мира\n", "output": "Привет, Мира"},
            {"input": "Илья\n", "output": "Привет, Илья"},
        ],
        "expected": {
            "mistake_types": ["syntax"],
            "score": 0,
            "acceptable_conclusion": "В объявлении функции пропущены закрывающая скобка и двоеточие.",
            "recommendations": ["Синтаксис def и аргументы функций."],
            "human_review": True,
            "coverage_terms": [":", "скоб"],
        },
    },
    {
        "id": "py-equality-11",
        "title": "Равенство и идентичность",
        "type": "text",
        "subject": "Информатика",
        "topic": "Сравнения",
        "difficulty": "Начальный",
        "condition": "Объясни разницу между операторами == и is в Python.",
        "student_solution": "Оба оператора проверяют, что значения двух переменных одинаковы.",
        "reference_answer": "== сравнивает равенство значений, is проверяет, ссылаются ли переменные на один объект.",
        "criteria": [
            "Различено равенство значений и идентичность объекта.",
            "Приведено корректное назначение каждого оператора.",
        ],
        "max_score": 3,
        "expected": {
            "mistake_types": ["conceptual"],
            "score": 1,
            "acceptable_conclusion": "Ответ не различает равенство значений и идентичность объекта.",
            "recommendations": ["Операторы сравнения == и is."],
            "human_review": True,
            "coverage_terms": ["объект"],
        },
    },
    {
        "id": "py-arithmetic-alt-12",
        "title": "Допустимая форма числового ответа",
        "type": "short_answer",
        "subject": "Информатика",
        "topic": "Арифметика",
        "difficulty": "Начальный",
        "condition": "Вычисли (3 + 4) * 2. Запиши результат или равное ему выражение.",
        "student_solution": "2 * 7",
        "reference_answer": "14",
        "accepted_answers": ["14", "2*7", "7*2", "14.0"],
        "criteria": ["2 балла за численно равный ответ."],
        "max_score": 2,
        "expected": {
            "mistake_types": [],
            "score": 2,
            "acceptable_conclusion": "Выражение 2 * 7 равно 14.",
            "recommendations": [],
            "human_review": False,
        },
    },
    {
        "id": "py-logical-13",
        "title": "Логическое условие с включённой границей",
        "type": "python",
        "subject": "Информатика",
        "topic": "Логические операторы и сравнения",
        "difficulty": "Начальный",
        "condition": "Прочитай целое число n. Выведи True, если 0 <= n <= 10, иначе False.",
        "student_solution": "n = int(input())\nprint(n > 0 and n < 10)",
        "reference_answer": "n = int(input())\nprint(n >= 0 and n <= 10)",
        "criteria": ["Обе границы диапазона включены.", "Проверка верна для всех целых чисел."],
        "max_score": 3,
        "test_cases": [
            {"input": "0\n", "output": "True"},
            {"input": "5\n", "output": "True"},
            {"input": "10\n", "output": "True"},
            {"input": "11\n", "output": "False"},
        ],
        "expected": {
            "mistake_types": ["boundary", "logic"],
            "score": 1.5,
            "acceptable_conclusion": "Решение верно для внутренних значений, но исключает 0 и 10.",
            "recommendations": ["Включённые границы", "Логический оператор and."],
            "human_review": True,
            "coverage_terms": ["границ"],
        },
    },
    {
        "id": "py-condition-14",
        "title": "Условие на диапазон",
        "type": "choice",
        "subject": "Информатика",
        "topic": "Условия и логические операторы",
        "difficulty": "Начальный",
        "condition": "Какое условие проверяет, что n находится в диапазоне от 0 до 10 включительно? A) n > 0 and n < 10; B) n >= 0 and n <= 10.",
        "student_solution": "A",
        "reference_answer": "B",
        "criteria": ["1 балл за выбор B."],
        "max_score": 1,
        "expected": {
            "mistake_types": ["boundary"],
            "score": 0,
            "acceptable_conclusion": "Вариант A исключает обе границы; корректен B.",
            "recommendations": ["Включённые границы и <= / >=."],
            "human_review": False,
        },
    },
    {
        "id": "py-rubric-15",
        "title": "Недостаточно критериев для оценки",
        "type": "text",
        "subject": "Информатика",
        "topic": "Оценивание развёрнутых ответов",
        "difficulty": "Начальный",
        "condition": "Объясни, почему функция может вернуть None.",
        "student_solution": "Функция вернёт None, если выполнение дойдёт до конца тела функции без оператора return.",
        "reference_answer": "",
        "criteria": [],
        "max_score": 5,
        "expected": {
            "mistake_types": [],
            "score": None,
            "acceptable_conclusion": "Без эталона и критериев нельзя обоснованно выставить балл.",
            "recommendations": ["Оператор return и значение None."],
            "human_review": True,
        },
    },
    {
        "id": "py-digit-sum-16",
        "assignment_id": "ai-lab.python.digit-sum",
        "assignment_version": 1,
        "assignment_criteria": [
            {"id": "multi-digit", "title": "Сумма цифр многозначного числа", "description": "Суммируются все цифры многозначного входа.", "max_score": 1},
            {"id": "zero-single", "title": "Ноль и однозначные числа", "description": "Ноль и числа с одной цифрой обрабатываются корректно.", "max_score": 1},
            {"id": "embedded-zero", "title": "Внутренние и завершающие нули", "description": "Нули внутри и в конце числа не теряются.", "max_score": 1},
        ],
        "title": "Сумма цифр digit_sum(n)",
        "type": "python",
        "subject": "Информатика",
        "topic": "Функции и циклы",
        "difficulty": "Начальный",
        "condition": (
            "Реализуй функцию digit_sum(n), которая возвращает сумму цифр целого "
            "неотрицательного числа n. Число 0 должно давать 0. В решении можно "
            "использовать любой корректный алгоритм; совпадение с эталонным способом не требуется."
        ),
        "student_solution": (
            "def digit_sum(n):\n"
            "    return sum(map(int, str(n)))\n\n"
            "n = int(input())\n"
            "print(digit_sum(n))"
        ),
        "reference_answer": (
            "def digit_sum(n):\n"
            "    total = 0\n"
            "    while n > 0:\n"
            "        total += n % 10\n"
            "        n //= 10\n"
            "    return total\n\n"
            "n = int(input())\n"
            "print(digit_sum(n))"
        ),
        "criteria": [
            "1 балл — функция корректно суммирует цифры многозначного числа.",
            "1 балл — функция корректно обрабатывает 0 и однозначные числа.",
            "1 балл — функция сохраняет корректность при внутренних и завершающих нулях.",
        ],
        "max_score": 3,
        "test_cases": [
            {"input": "0\n", "output": "0"},
            {"input": "8\n", "output": "8"},
            {"input": "502\n", "output": "7"},
            {"input": "1200\n", "output": "3"},
            {"input": "9999\n", "output": "36"},
        ],
        "expected": {
            "mistake_types": [],
            "score": 3,
            "acceptable_conclusion": "Функция возвращает сумму цифр; алгоритм через строковое представление корректен и отличается от эталонного цикла.",
            "recommendations": [],
            "human_review": True,
            "coverage_terms": ["сумм", "альтернатив"],
        },
    },
)

_SCENARIO_BY_ID = {scenario["id"]: scenario for scenario in SCENARIOS}


def _assignment_definition(scenario: dict) -> dict | None:
    if scenario.get("type") != "python":
        return None
    criteria = deepcopy(scenario.get("assignment_criteria") or [])
    if not criteria:
        raw = scenario.get("criteria") or []
        raw = raw if isinstance(raw, list) else str(raw).splitlines()
        for index, line in enumerate(raw, 1):
            match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:балл(?:а|ов)?\s*)?(?:[—–:-])\s*(.+?)\s*$", str(line), re.IGNORECASE)
            if not match:
                continue
            criteria.append({
                "id": f"criterion-{index}",
                "title": str(line).strip(),
                "description": match.group(2).strip(),
                "max_score": float(match.group(1).replace(",", ".")),
            })
    if not criteria:
        return None
    return {
        "assignment_id": scenario.get("assignment_id") or scenario["id"],
        "assignment_version": int(scenario.get("assignment_version") or 1),
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "max_score": float(scenario.get("max_score") or sum(float(item["max_score"]) for item in criteria)),
        "criteria": criteria,
    }


def get_scenario(scenario_id: str) -> dict | None:
    scenario = _SCENARIO_BY_ID.get(str(scenario_id or ""))
    if scenario is None and has_app_context() and str(scenario_id or "").startswith("rubric-"):
        from app.ai_lab.rubric_builder import get_rubric

        try:
            item = get_rubric(int(str(scenario_id).split("-", 1)[1]))
        except (TypeError, ValueError):
            item = None
        scenario = _approved_rubric_scenarios([item])[0] if item and item["status"] == "approved" else None
    result = deepcopy(scenario) if scenario else None
    assignment = _assignment_definition(result) if result else None
    if assignment:
        result["assignment_id"] = assignment["assignment_id"]
        result["assignment_version"] = assignment["assignment_version"]
        result["assignment_criteria"] = assignment["criteria"]
    return result


def list_scenarios() -> list[dict]:
    result = []
    for source in SCENARIOS:
        scenario = get_scenario(source["id"])
        result.append({key: deepcopy(value) for key, value in scenario.items() if key not in {"expected", "test_cases", "accepted_answers"}})
    if has_app_context():
        from app.ai_lab.rubric_builder import list_rubrics

        result.extend(_approved_rubric_scenarios(list_rubrics(approved_only=True, limit=None)))
    return result


def list_python_assignments() -> list[dict]:
    """Return stable, non-secret assignment identities for Code Judge binding."""
    assignments = []
    for scenario in SCENARIOS:
        assignment = _assignment_definition(scenario)
        if not assignment:
            continue
        assignments.append(assignment)
    if has_app_context():
        from app.ai_lab.rubric_builder import list_rubrics

        for scenario in _approved_rubric_scenarios(list_rubrics(approved_only=True, limit=None)):
            assignment = _assignment_definition(scenario)
            if assignment:
                assignments.append(assignment)
    return assignments


def _approved_rubric_scenarios(rubrics: list[dict]) -> list[dict]:
    result = []
    for item in rubrics:
        task = item["task"]
        criteria = item["criteria"]
        result.append({
            "id": f"rubric-{item['id']}", "rubric_version_id": item["id"],
            "assignment_id": item["assignment_id"], "assignment_version": item["assignment_version"],
            "assignment_criteria": [{"id": criterion["id"], "title": criterion["title"],
                                      "description": criterion["description"], "max_score": criterion["max_score"],
                                      "policy": criterion.get("policy", "all_or_nothing")}
                                     for criterion in criteria],
            "title": task["title"] + f" · рубрика v{item['version_no']}",
            "type": "python" if task["answer_type"] == "python" else "text",
            "subject": task["subject"], "topic": task["topic"], "difficulty": "Синтетическое",
            "condition": task["condition"], "student_solution": "",
            "reference_answer": task["reference_answer"],
            "criteria": [_rubric_criterion_line(criterion) for criterion in criteria],
            "max_score": task["max_score"], "expected": {},
        })
    return result


def _rubric_criterion_line(criterion: dict) -> str:
    parts = (
        f"{criterion['max_score']:g} балл — {criterion['title']}.",
        criterion["description"],
        f"Полный балл: {criterion['full_credit']}",
        f"Частичный балл: {criterion['partial_credit'] or 'не предусмотрен'}.",
    )
    return re.sub(r"\s+", " ", " ".join(parts)).strip()
