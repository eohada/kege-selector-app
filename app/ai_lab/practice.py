"""Recommendations over existing AI Lab catalog items and analytics findings."""
from __future__ import annotations

import ast
import hashlib
import ipaddress
import itertools
import json
import random
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


SKILL_TOPIC_HINTS = {
    "python.boundary_cases": ("границ", "услов", "сравнен"),
    "python.iteration": ("цикл", "строк", "функц"),
    "python.functions": ("функц", "аргумент", "спис"),
}

SUPPORTED_EXERCISE_TYPES = frozenset({"single_choice", "multi_select", "numeric", "short_text"})
DIFFICULTY_LEVELS = {"introductory": 1, "easy": 1, "basic": 2, "medium": 3, "advanced": 4, "challenge": 5}

_PRACTICE_GENERATORS = {
    "ege.inf.ip-prefix-mask.v1": {
        "skill_id": "skill.inf.ipv4.subnet-mask",
        "topic_code": "ege.inf.ipv4.subnet-mask.v1",
        "generator": "ipv4_network",
        "title": "IPv4: сеть и границы блока",
    },
    "ege.inf.graph-degree.v1": {
        "skill_id": "skill.inf.graph-degree",
        "topic_code": None,
        "generator": "graph_degree",
        "title": "Графы: степень вершины",
    },
    "ege.inf.graph.optimal-paths.v1": {
        "skill_id": "skill.inf.graph.optimal-paths",
        "topic_code": "ege.inf.graph.optimal-paths.v1",
        "generator": "graph_optimal_paths",
        "title": "Графы: минимальная стоимость маршрута",
    },
    "ege.inf.image-sound-volume.v1": {
        "skill_id": "skill.inf.media-volume",
        "topic_code": None,
        "generator": "media_volume",
        "title": "Информация: объём несжатых данных",
    },
    "ege.inf.logic-truth-table.v1": {
        "skill_id": "skill.inf.truth-table-equivalence",
        "topic_code": None,
        "generator": "truth_table",
        "title": "Логика: проверка эквивалентности",
    },
    "ege.inf.python-sequence-processing.v1": {
        "skill_id": "skill.inf.python-sequence",
        "topic_code": None,
        "generator": "sequence_count",
        "title": "Python: обработка последовательности",
    },
}


def validate_practice_exercise(exercise: Any) -> dict[str, Any]:
    """Return a safe internal exercise record or raise a clear validation error.

    The answer key is required for deterministic grading and must never be copied
    into the learner-facing exercise payload before an attempt is submitted.
    """
    if not isinstance(exercise, dict):
        raise ValueError("Упражнение должно быть объектом.")
    exercise_id = exercise.get("exercise_id")
    prompt = exercise.get("prompt")
    answer_type = exercise.get("answer_type")
    skill_ids = exercise.get("skill_ids")
    answer_key = exercise.get("answer_key")
    if not isinstance(exercise_id, str) or not exercise_id.strip():
        raise ValueError("У упражнения должен быть стабильный exercise_id.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("У упражнения должен быть текст условия.")
    if answer_type not in SUPPORTED_EXERCISE_TYPES:
        raise ValueError("Для этого типа упражнения нет проверенного способа автоматической оценки.")
    if not isinstance(skill_ids, list) or not skill_ids or any(not isinstance(value, str) or not value.strip() for value in skill_ids):
        raise ValueError("Укажите явную связь упражнения с предметным навыком.")
    if answer_key is None:
        raise ValueError("Нет проверенного эталона ответа; упражнение требует ручной оценки.")
    normalized = dict(exercise)
    normalized["exercise_id"] = exercise_id.strip()
    normalized["prompt"] = prompt.strip()
    normalized["skill_ids"] = list(dict.fromkeys(value.strip() for value in skill_ids))
    normalized["answer_type"] = answer_type
    return normalized


def grade_practice_answer(exercise: Any, answer: Any) -> dict[str, Any]:
    """Grade supported short-answer formats without involving a model."""
    try:
        item = validate_practice_exercise(exercise)
    except ValueError as exc:
        return {"verification_status": "unverified", "is_correct": None, "reason": str(exc)}

    answer_type = item["answer_type"]
    expected = item["answer_key"]
    if answer_type in {"single_choice", "short_text"}:
        if not isinstance(answer, (str, int)) or isinstance(answer, bool):
            return {"verification_status": "unverified", "is_correct": None, "reason": "Ответ имеет неверный формат."}
        actual = str(answer).strip()
        expected_text = str(expected).strip()
        if answer_type == "short_text":
            actual = " ".join(actual.split()).casefold()
            expected_text = " ".join(expected_text.split()).casefold()
        is_correct = actual == expected_text
    elif answer_type == "multi_select":
        if not isinstance(answer, list) or any(not isinstance(value, (str, int)) or isinstance(value, bool) for value in answer):
            return {"verification_status": "unverified", "is_correct": None, "reason": "Выберите один или несколько вариантов."}
        if not isinstance(expected, list):
            return {"verification_status": "unverified", "is_correct": None, "reason": "Эталон множественного выбора настроен неверно."}
        is_correct = {str(value).strip() for value in answer} == {str(value).strip() for value in expected}
    else:
        try:
            actual_number = Decimal(str(answer).strip())
            expected_number = Decimal(str(expected).strip())
            tolerance = Decimal(str(item.get("absolute_tolerance", 0)))
            if not actual_number.is_finite() or not expected_number.is_finite() or not tolerance.is_finite() or tolerance < 0:
                raise InvalidOperation
            is_correct = abs(actual_number - expected_number) <= tolerance
        except (InvalidOperation, ValueError, TypeError):
            return {"verification_status": "unverified", "is_correct": None, "reason": "Введите конечное числовое значение."}

    return {
        "verification_status": "verified",
        "is_correct": bool(is_correct),
        "reason": "Ответ совпал с проверенным эталоном." if is_correct else "Ответ не совпал с проверенным эталоном.",
        "correct_answer": expected,
    }


def select_next_practice_exercise(
    exercises: Iterable[dict[str, Any]],
    *,
    skill_id: str,
    attempts: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Select a fresh, explicitly mapped exercise using verified recent evidence.

    Two distinct verified successes without a registered BooStudy hint permit
    a one-step difficulty increase. They do not establish independence or
    mastery because assistance outside the platform is not observed.
    """
    candidates = []
    for raw in exercises:
        try:
            item = validate_practice_exercise(raw)
        except ValueError:
            continue
        if skill_id in item["skill_ids"]:
            item["difficulty_rank"] = _difficulty_rank(item.get("difficulty"))
            candidates.append(item)
    if not candidates:
        return {"exercise": None, "action": "unavailable", "reason": "Нет доступных упражнений с проверенным эталоном и явной связью с выбранным навыком."}

    history = [item for item in attempts if isinstance(item, dict) and item.get("skill_id") == skill_id]
    attempted_ids = {str(item.get("exercise_id")) for item in history if item.get("exercise_id")}
    fresh = [item for item in candidates if item["exercise_id"] not in attempted_ids]
    if not fresh:
        return {"exercise": None, "action": "pause", "reason": "Все подходящие упражнения уже встречались; повтор не выдаётся как новый вариант."}

    verified = [item for item in history if item.get("verification_status") == "verified" and isinstance(item.get("is_correct"), bool)]
    recent = verified[-2:]
    platform_no_hint_pair = (
        len(recent) == 2
        and all(item["is_correct"] and item.get("assistance_level") in {"independent", "no_platform_hint"} for item in recent)
        and len({item.get("exercise_id") for item in recent}) == 2
    )
    latest = verified[-1] if verified else None
    if platform_no_hint_pair:
        current_rank = _difficulty_rank(recent[-1].get("difficulty"))
        target_rank = min(5, current_rank + 1)
        action = "increase_difficulty" if any(item["difficulty_rank"] == target_rank for item in fresh) else "transfer_check"
        reason = "Два разных задания решены верно без подсказки BooStudy. Внешняя помощь не наблюдалась; предлагается только проверка на следующем уровне, без вывода об освоении."
    elif latest and not latest["is_correct"]:
        current_rank = _difficulty_rank(latest.get("difficulty"))
        target_rank = max(1, current_rank - 1) if current_rank > 1 else current_rank
        action = "reinforce" if target_rank < current_rank else "practice_same_level"
        reason = "Последняя проверенная попытка была неверной; следующее упражнение закрепляет тот же навык на сопоставимом или более доступном уровне."
    elif latest:
        target_rank = _difficulty_rank(latest.get("difficulty"))
        action = "transfer_check"
        reason = "Есть один проверенный успех; требуется другое задание для проверки переноса, а данных для повышения сложности пока мало."
    else:
        target_rank = 2
        action = "diagnostic_start"
        reason = "Подтверждённых попыток по выбранному навыку нет; начинается ограниченная диагностическая практика."

    selected = min(fresh, key=lambda item: (abs(item["difficulty_rank"] - target_rank), item["exercise_id"]))
    public_exercise = {key: value for key, value in selected.items() if key not in {"answer_key", "absolute_tolerance", "difficulty_rank"}}
    return {"exercise": public_exercise, "action": action, "reason": reason}


def _difficulty_rank(value: Any) -> int:
    if isinstance(value, bool):
        return 3
    if isinstance(value, int) and 1 <= value <= 5:
        return value
    if isinstance(value, str):
        return DIFFICULTY_LEVELS.get(value.strip().lower(), 3)
    return 3


def list_practice_skills() -> list[dict[str, Any]]:
    """List only skills backed by a current Knowledge Base card and generator."""
    from app.ai_lab.knowledge_base import list_knowledge_entries

    entries = {item["stable_key"]: item for item in list_knowledge_entries(include_content=True)}
    skills = []
    for stable_key, spec in _PRACTICE_GENERATORS.items():
        skill_id = spec["skill_id"]
        fallback_title = spec["title"]
        entry = entries.get(stable_key)
        if not entry or entry.get("status") not in {"source_checked", "reviewed", "approved"}:
            continue
        assessed_skill = (entry.get("content") or {}).get("assessed_skill") or {}
        if assessed_skill.get("skill_key") != skill_id:
            continue
        skills.append({
            "skill_id": skill_id,
            "topic_code": spec.get("topic_code"),
            "title": assessed_skill.get("name") or fallback_title,
            "knowledge_stable_key": stable_key,
            "knowledge_version": entry["version_no"],
            "knowledge_status": entry["status"],
            "editorial_note": "Упражнения синтетические; статус источника Knowledge Base не означает экспертного утверждения генератора или связи навыка.",
        })
    return skills


def practice_skill_topic_code(skill_id: str) -> str | None:
    """Return an explicitly curated ExamSkill.topic_code bridge, if one exists."""
    matches = {
        str(spec["topic_code"]).strip()
        for spec in _PRACTICE_GENERATORS.values()
        if spec.get("skill_id") == skill_id and isinstance(spec.get("topic_code"), str)
        and spec["topic_code"].strip()
    }
    return next(iter(matches)) if len(matches) == 1 else None


def is_registered_practice_skill_id(skill_id: str) -> bool:
    """Return whether a stable source skill ID has an explicit practice generator."""
    normalized = str(skill_id or "").strip()
    return bool(normalized) and any(
        spec.get("skill_id") == normalized for spec in _PRACTICE_GENERATORS.values()
    )


def practice_skill_title(skill_id: str) -> str | None:
    """Return a display title only when registered generators agree on it."""
    normalized = str(skill_id or "").strip()
    titles = {
        str(spec["title"]).strip()
        for spec in _PRACTICE_GENERATORS.values()
        if spec.get("skill_id") == normalized and str(spec.get("title") or "").strip()
    }
    return next(iter(titles)) if len(titles) == 1 else None


def practice_skill_ids_for_topic_code(topic_code: str) -> list[str]:
    code = str(topic_code or "").strip()
    if not code:
        return []
    return sorted({
        str(spec["skill_id"])
        for spec in _PRACTICE_GENERATORS.values()
        if spec.get("topic_code") == code
    })


def build_practice_exercise(skill_id: str, seed: str, difficulty: int | None = None) -> dict[str, Any] | None:
    """Build one parameterized, locally checked exercise linked to current KB metadata."""
    if not isinstance(seed, str) or not seed.strip() or len(seed) > 160:
        raise ValueError("Для варианта упражнения нужен непустой ограниченный seed.")
    skill_spec = next((
        (stable_key, spec["generator"], spec["title"])
        for stable_key, spec in _PRACTICE_GENERATORS.items()
        if spec["skill_id"] == skill_id
    ), None)
    if not skill_spec:
        return None
    stable_key, generator_name, exercise_title = skill_spec
    metadata = next((item for item in list_practice_skills() if item["skill_id"] == skill_id), None)
    if not metadata:
        return None
    rng = random.Random(seed)
    requested_difficulty = _difficulty_rank(difficulty) if difficulty is not None else None
    builders = {
        "ipv4_network": _build_ipv4_network_exercise,
        "graph_degree": _build_graph_degree_exercise,
        "graph_optimal_paths": _build_graph_optimal_paths_exercise,
        "media_volume": _build_media_volume_exercise,
        "truth_table": _build_truth_table_exercise,
        "sequence_count": _build_sequence_count_exercise,
    }
    exercise = builders[generator_name](rng, requested_difficulty)
    seed_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    exercise.update({
        "title": exercise_title,
        "exercise_id": f"generator:{stable_key}:v1:kb{metadata['knowledge_version']}:{seed_hash}",
        "exercise_version": 1,
        "skill_ids": [skill_id],
        "topic_id": stable_key,
        "difficulty": exercise.get("difficulty", 2),
        "knowledge_ref": {
            "stable_key": stable_key,
            "version": metadata["knowledge_version"],
            "status": metadata["knowledge_status"],
        },
        "generator_version": "boostudy.practice-generators.v1",
    })
    validate_practice_exercise(exercise)
    return exercise


def _build_ipv4_network_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    difficulty = difficulty or rng.randint(2, 3)
    prefix_ranges = {1: (24, 24), 2: (26, 29), 3: (20, 29), 4: (16, 30), 5: (8, 30)}
    prefix = rng.randint(*prefix_ranges[difficulty])
    address = ipaddress.IPv4Address(rng.randint(int(ipaddress.IPv4Address("10.32.0.1")), int(ipaddress.IPv4Address("10.63.255.254"))))
    network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    return {
        "answer_type": "short_text",
        "prompt": f"Найдите адрес сети для {address}/{prefix}. Укажите только IPv4-адрес.",
        "answer_key": str(network.network_address),
        "hint": "Определите размер блока по длине префикса и найдите начало блока, в который попадает адрес.",
        "explanation": f"Адрес сети получается обнулением хостовой части: {network.network_address}.",
        "difficulty": difficulty,
    }


def _build_graph_degree_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    difficulty = difficulty or rng.randint(2, 3)
    vertex_count = {1: 3, 2: 4, 3: 5, 4: 6, 5: 6}[difficulty]
    labels = tuple("ABCDEF"[:vertex_count])
    edge_chance = {1: 0.3, 2: 0.35, 3: 0.4, 4: 0.45, 5: 0.5}[difficulty]
    edges = [(left, right) for left, right in itertools.combinations(labels, 2) if rng.random() < edge_chance]
    if not edges:
        edges = [(labels[0], labels[1])]
    target = rng.choice(labels)
    degree = sum(target in edge for edge in edges)
    edge_text = ", ".join(f"{left}—{right}" for left, right in edges)
    return {
        "answer_type": "numeric",
        "prompt": f"В простом неориентированном графе рёбра заданы списком: {edge_text}. Чему равна степень вершины {target}?",
        "answer_key": degree,
        "hint": "Степень вершины — количество рёбер, которые к ней примыкают.",
        "explanation": f"В списке найдено {degree} ребра, инцидентных вершине {target}; поэтому её степень равна {degree}.",
        "difficulty": difficulty,
    }


def _build_graph_optimal_paths_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    """Build a small positive-weight DAG item whose answer is exhaustively checked.

    The finite graph and unique minimum keep the answer deterministic. This
    checks the minimum route cost for this graph; it does not establish general
    graph-algorithm mastery or verify a learner's chosen algorithm.
    """
    difficulty = difficulty or rng.randint(2, 3)
    vertex_count = {1: 4, 2: 4, 3: 5, 4: 5, 5: 6}[difficulty]
    labels = tuple("ABCDEF"[:vertex_count])
    possible_edges = list(itertools.combinations(labels, 2))
    edge_chance = {1: 0.38, 2: 0.46, 3: 0.52, 4: 0.58, 5: 0.62}[difficulty]

    for _ in range(256):
        selected = {
            edge for edge in possible_edges
            if rng.random() < edge_chance
        }
        selected.update(zip(labels, labels[1:]))
        weighted_edges = {(left, right): rng.randint(1, 20) for left, right in sorted(selected)}
        adjacency: dict[str, list[tuple[str, int]]] = {label: [] for label in labels}
        for (left, right), weight in weighted_edges.items():
            adjacency[left].append((right, weight))

        paths: list[tuple[tuple[str, ...], int]] = []

        def visit(vertex: str, path: tuple[str, ...], cost: int) -> None:
            if vertex == labels[-1]:
                paths.append((path, cost))
                return
            for neighbor, weight in adjacency[vertex]:
                visit(neighbor, (*path, neighbor), cost + weight)

        visit(labels[0], (labels[0],), 0)
        costs = [cost for _, cost in paths]
        if len(paths) >= 3 and costs.count(min(costs)) == 1:
            best_path, best_cost = min(paths, key=lambda item: item[1])
            edge_text = ", ".join(
                f"{left}→{right} ({weight})"
                for (left, right), weight in sorted(weighted_edges.items())
            )
            path_sums = "; ".join(
                f"{'→'.join(path)}: {cost}"
                for path, cost in sorted(paths, key=lambda item: item[0])
            )
            return {
                "answer_type": "numeric",
                "prompt": (
                    f"Дан ориентированный ациклический граф с положительными весами рёбер: {edge_text}. "
                    f"Найдите минимальную суммарную стоимость пути из {labels[0]} в {labels[-1]}. "
                    "Введите только число."
                ),
                "answer_key": best_cost,
                "hint": "Перечислите допустимые пути, сложите веса каждого и сравните полученные суммы.",
                "explanation": f"Стоимость каждого пути: {path_sums}. Минимум {best_cost} у пути {'→'.join(best_path)}.",
                "difficulty": difficulty,
                "criterion_id": "result_check",
                "verification_scope": "Исчерпывающий перебор всех путей этого конечного DAG; общий алгоритм ученика не проверяется.",
            }

    raise ValueError("Не удалось построить граф с несколькими путями и единственным оптимумом.")


def _build_media_volume_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    difficulty = difficulty or rng.randint(2, 3)
    upper_bound = {1: 24, 2: 48, 3: 96, 4: 160, 5: 256}[difficulty]
    width = rng.randint(8, upper_bound)
    height = rng.randint(8, upper_bound)
    bit_choices = {1: (1,), 2: (1, 2, 4, 8), 3: (2, 4, 8), 4: (4, 8, 24), 5: (8, 24, 32)}
    bits_per_pixel = rng.choice(bit_choices[difficulty])
    total_bits = width * height * bits_per_pixel
    byte_count = (total_bits + 7) // 8
    return {
        "answer_type": "numeric",
        "prompt": (f"Несжатое изображение размером {width}×{height} пикселей кодируется с глубиной "
                  f"{bits_per_pixel} бит на пиксель. Найдите минимальный объём пиксельных данных в байтах; заголовок не учитывается."),
        "answer_key": byte_count,
        "hint": "Сначала найдите число бит, затем переведите его в байты с округлением вверх до целого байта.",
        "explanation": f"{width} × {height} × {bits_per_pixel} = {total_bits} бит; это {byte_count} байт после округления вверх.",
        "difficulty": difficulty,
    }


def _random_boolean_expression(rng: random.Random, depth: int, names: tuple[str, ...]) -> str:
    if depth <= 0 or rng.random() < 0.34:
        return rng.choice(names)
    left = _random_boolean_expression(rng, depth - 1, names)
    right = _random_boolean_expression(rng, depth - 1, names)
    operator = rng.choice(("and", "or"))
    expression = f"({left} {operator} {right})"
    return f"(not {expression})" if rng.random() < 0.18 else expression


def _safe_bool_expression(source: str, values: dict[str, bool]) -> bool:
    tree = ast.parse(source, mode="eval")

    def evaluate(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            parts = [evaluate(item) for item in node.values]
            return all(parts) if isinstance(node.op, ast.And) else any(parts)
        raise ValueError("Генератор создал неподдерживаемое логическое выражение.")

    return evaluate(tree)


def _build_truth_table_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    difficulty = difficulty or rng.randint(2, 3)
    variable_count = {1: 2, 2: 2, 3: 3, 4: 3, 5: 4}[difficulty]
    names = tuple("ABCD"[:variable_count])
    depth = {1: 1, 2: 2, 3: 2, 4: 3, 5: 3}[difficulty]
    left = _random_boolean_expression(rng, depth, names)
    right = _random_boolean_expression(rng, depth, names)
    if right == left:
        right = f"not ({right})"
    values = [dict(zip(names, row)) for row in itertools.product((False, True), repeat=len(names))]
    equivalent = all(_safe_bool_expression(left, row) == _safe_bool_expression(right, row) for row in values)
    return {
        "answer_type": "single_choice",
        "prompt": f"Проверьте полную эквивалентность выражений: {left} и {right}.",
        "answer_key": "yes" if equivalent else "no",
        "options": [{"value": "yes", "label": "Эквивалентны"}, {"value": "no", "label": "Не эквивалентны"}],
        "hint": f"Сравните результаты обоих выражений для всех {2 ** len(names)} наборов переменных {', '.join(names)}.",
        "explanation": (f"Сравнение таблиц истинности по всем {2 ** len(names)} наборам даёт одинаковые результаты."
                        if equivalent else "Найден хотя бы один набор переменных, на котором результаты различаются."),
        "difficulty": difficulty,
    }


def _build_sequence_count_exercise(rng: random.Random, difficulty: int | None = None) -> dict[str, Any]:
    difficulty = difficulty or rng.randint(2, 3)
    sequence_size = {1: 4, 2: 7, 3: 10, 4: 15, 5: 20}[difficulty]
    sequence = [rng.randint(-18 * difficulty, 24 * difficulty) for _ in range(sequence_size)]
    boundary = rng.randint(-8, 12)
    inclusive = rng.choice((True, False))
    operator = "≥" if inclusive else ">"
    result = sum(value >= boundary if inclusive else value > boundary for value in sequence)
    return {
        "answer_type": "numeric",
        "prompt": f"Сколько элементов последовательности {sequence} удовлетворяют условию x {operator} {boundary}?",
        "answer_key": result,
        "hint": f"Проверяйте каждый элемент по условию {operator} {boundary}; отдельно проверьте число, равное порогу.",
        "explanation": f"Условию {operator} {boundary} удовлетворяют {result} элементов.",
        "difficulty": difficulty,
    }


PRACTICE_SESSION_SCENARIO = "adaptive-practice-session.v1"
PRACTICE_ATTEMPT_SCENARIO = "adaptive-practice-attempt.v1"


def start_practice_session(
    actor_user_id: int,
    subject_id: str,
    skill_id: str,
    mode: str = "topic",
    idempotency_key: str | None = None,
    course_id: int | None = None,
    lesson_id: int | None = None,
) -> dict[str, Any]:
    _assert_safe_practice_context()
    from core.db_models import AiLabExperiment, db

    if mode not in {"continue", "topic", "gaps", "diagnostic"}:
        raise ValueError("Выберите режим практики из списка.")
    course_context = _resolve_practice_course_context(
        actor_user_id=actor_user_id, subject_id=subject_id, skill_id=skill_id,
        course_id=course_id, lesson_id=lesson_id,
    )
    if idempotency_key is not None:
        if (not isinstance(idempotency_key, str)
                or not 8 <= len(idempotency_key.strip()) <= 120):
            raise ValueError("Для защиты от повторного запуска нужен ключ длиной от 8 до 120 символов.")
        session_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"boostudy-adaptive-practice:{actor_user_id}:{subject_id}:{skill_id}:{mode}:"
            f"{(course_context or {}).get('course_id', '')}:{(course_context or {}).get('lesson_id', '')}:"
            f"{idempotency_key.strip()}",
        ).hex
        existing = _load_practice_session(actor_user_id, session_id)
        if existing:
            return _public_session(existing.result_json or {})
    else:
        session_id = uuid.uuid4().hex
    if not any(item["skill_id"] == skill_id for item in list_practice_skills()):
        raise ValueError("Для выбранной темы нет проверенного генератора в текущей базе знаний.")
    active = latest_active_practice_session(actor_user_id, subject_id)
    if active:
        if (active.get("skill_id") != skill_id
                or active.get("course_context") != course_context):
            raise ValueError("Сначала завершите активную сессию с другим навыком или контекстом курса.")
        return active
    history = [] if mode == "diagnostic" else _stored_practice_attempts(subject_id)
    session_key = _session_request_key(actor_user_id, session_id)
    candidates = _practice_candidates(skill_id, session_id, 0)
    selection = select_next_practice_exercise(candidates, skill_id=skill_id, attempts=history)
    selected = next((item for item in candidates if item["exercise_id"] == (selection.get("exercise") or {}).get("exercise_id")), None)
    if not selected:
        raise ValueError(selection.get("reason") or "Не удалось подготовить упражнение.")
    state = {
        "contract_version": "boostudy.adaptive-practice.v1",
        "session_id": session_id,
        "subject_id": subject_id,
        "skill_id": skill_id,
        "mode": mode,
        "status": "active",
        "current_exercise": selected,
        "attempt_count": 0,
        "awaiting_next": False,
        "hint_requested": False,
        "last_feedback": None,
        "decision": selection,
    }
    if course_context:
        state["course_context"] = course_context
    record = AiLabExperiment(
        actor_user_id=actor_user_id,
        request_key=session_key,
        scenario_id=PRACTICE_SESSION_SCENARIO,
        status="succeeded",
        provider="local",
        prompt_snapshot="Детерминированная синтетическая практика; вызов модели не выполнялся.",
        scenario_snapshot={"module": "ai_practice", "contract_version": state["contract_version"]},
        input_snapshot={"session_id": session_id, "subject_id": subject_id, "skill_id": skill_id, "mode": mode,
                        "course_context": course_context},
        expected_snapshot={},
        result_json=state,
        validation_status="valid",
        quality_json={"synthetic_only": True, "uses_model": False},
    )
    db.session.add(record)
    db.session.commit()
    return _public_session(state)


def get_practice_session(actor_user_id: int, session_id: str) -> dict[str, Any] | None:
    _assert_safe_practice_context()
    record = _load_practice_session(actor_user_id, session_id)
    return _public_session(record.result_json) if record else None


def latest_active_practice_session(actor_user_id: int, subject_id: str) -> dict[str, Any] | None:
    _assert_safe_practice_context()
    from core.db_models import AiLabExperiment

    rows = (AiLabExperiment.query.filter_by(actor_user_id=actor_user_id, scenario_id=PRACTICE_SESSION_SCENARIO)
            .order_by(AiLabExperiment.id.desc()).limit(100).all())
    for row in rows:
        snapshot = row.input_snapshot if isinstance(row.input_snapshot, dict) else {}
        state = row.result_json if isinstance(row.result_json, dict) else {}
        if snapshot.get("subject_id") == subject_id and state.get("status") == "active":
            return _public_session(state)
    return None


def request_practice_hint(actor_user_id: int, session_id: str) -> dict[str, Any]:
    _assert_safe_practice_context()
    from core.db_models import db

    record = _require_practice_session(actor_user_id, session_id)
    state = dict(record.result_json or {})
    if state.get("status") != "active" or state.get("awaiting_next"):
        raise ValueError("Подсказка доступна для текущего упражнения до отправки ответа.")
    exercise = state.get("current_exercise") or {}
    hint = exercise.get("hint")
    if not isinstance(hint, str) or not hint.strip():
        raise ValueError("Для этого упражнения нет проверенной подсказки.")
    state["hint_requested"] = True
    state["last_hint"] = hint
    record.result_json = state
    db.session.commit()
    return {"hint": hint, "assistance_recorded": True}


def submit_practice_answer(actor_user_id: int, session_id: str, answer: Any, idempotency_key: str) -> dict[str, Any]:
    _assert_safe_practice_context()
    from sqlalchemy.exc import IntegrityError
    from core.db_models import AiLabExperiment, db

    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key.strip()) <= 120:
        raise ValueError("Для защиты от повторной отправки нужен ключ попытки длиной от 8 до 120 символов.")
    idempotency_key = idempotency_key.strip()
    record = _require_practice_session(actor_user_id, session_id)
    attempt_key = _attempt_request_key(actor_user_id, session_id, idempotency_key)
    existing = AiLabExperiment.query.filter_by(actor_user_id=actor_user_id, request_key=attempt_key).first()
    if existing:
        return dict((existing.result_json or {}).get("learner_feedback") or {})

    state = dict(record.result_json or {})
    if state.get("status") != "active" or state.get("awaiting_next"):
        raise ValueError("Сначала откройте следующее упражнение или завершите сессию.")
    exercise = state.get("current_exercise")
    if not isinstance(exercise, dict):
        raise ValueError("В сессии нет активного упражнения.")
    feedback = grade_practice_answer(exercise, answer)
    occurred_at = datetime.now(timezone.utc).isoformat()
    attempt_id = uuid.uuid4().hex
    platform_assistance = "substantive_hint" if state.get("hint_requested") else "no_platform_hint"
    evidence_status = "technical_confirmed" if feedback["verification_status"] == "verified" else "insufficient_data"
    score = (1 if feedback["is_correct"] else 0) if evidence_status == "technical_confirmed" else None
    maximum = 1 if evidence_status == "technical_confirmed" else None
    event = {
        "contract_version": "boostudy.learning-evidence.v2",
        "event_id": f"ai-practice:{session_id}:{attempt_id}",
        "subject_id": state["subject_id"],
        "source_module": "ai_practice",
        "source_record_id": f"practice-session:{session_id}:attempt:{attempt_id}",
        "occurred_at": occurred_at,
        "evidence_status": evidence_status,
        "assignment": {"id": exercise["exercise_id"], "version": int(exercise.get("exercise_version") or 1)},
        "topic_ids": [exercise["topic_id"]],
        "skill_ids": list(exercise["skill_ids"]),
        "error_codes": [],
        "outcome": {"score": score, "maximum": maximum,
                    "status": "complete" if evidence_status == "technical_confirmed" else "insufficient_data"},
        "criteria": [{
            "criterion_id": str(exercise.get("criterion_id") or f"{exercise['exercise_id']}:answer"),
            "status": ("met" if feedback["is_correct"] else "not_met") if evidence_status == "technical_confirmed" else "insufficient_data",
            "earned": score,
            "maximum": maximum,
            "evidence_status": evidence_status,
            "skill_id": exercise["skill_ids"][0],
            "reason": feedback["reason"],
            "source_refs": [f"platform-practice:{session_id}:attempt:{attempt_id}"],
        }],
        "assistance": {"level": platform_assistance,
                       "source_refs": [f"platform-practice:{session_id}:hint:{'requested' if state.get('hint_requested') else 'not-requested'}"]},
        "provenance": {
            "source_ref": f"practice-session:{session_id}:exercise:{exercise['exercise_id']}",
            "payload_hash": hashlib.sha256(json.dumps(exercise, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "model": "",
            "method": "parameterized-generator+deterministic-short-answer-checker",
            **({"practice_knowledge_ref": dict(exercise["knowledge_ref"])}
               if isinstance(exercise.get("knowledge_ref"), dict) else {}),
        },
        "limitations": [
            "Подтверждён только ответ на этот конкретный вариант; генератор не является независимой экспертной оценкой предметной привязки.",
            "Уровень помощи описывает только подсказки внутри платформы; внешняя помощь не наблюдалась.",
        ],
    }
    from app.ai_lab.learning_evidence import validate_evidence_event

    validated_event = validate_evidence_event(event)
    course_context = state.get("course_context")
    if isinstance(course_context, dict):
        validated_event["course_context"] = dict(course_context)
    learner_feedback = {
        "attempt_id": attempt_id,
        "verification_status": feedback["verification_status"],
        "is_correct": feedback["is_correct"],
        "reason": feedback["reason"],
        "correct_answer": feedback.get("correct_answer"),
        "explanation": exercise.get("explanation") if evidence_status == "technical_confirmed" else None,
        "event_id": validated_event["event_id"],
    }
    attempt_record = AiLabExperiment(
        actor_user_id=actor_user_id,
        request_key=attempt_key,
        scenario_id=PRACTICE_ATTEMPT_SCENARIO,
        status="succeeded",
        provider="local",
        prompt_snapshot="Детерминированная проверка ответа синтетического упражнения.",
        scenario_snapshot={"module": "ai_practice", "session_id": session_id},
        input_snapshot={"session_id": session_id, "subject_id": state["subject_id"], "skill_id": state["skill_id"],
                        "exercise": exercise, "answer": answer, "idempotency_key": idempotency_key},
        expected_snapshot={},
        result_json={"event": validated_event, "learner_feedback": learner_feedback,
                     "exercise_id": exercise["exercise_id"], "skill_id": state["skill_id"],
                     "difficulty": exercise.get("difficulty"), "assistance_level": platform_assistance,
                     "verification_status": feedback["verification_status"], "is_correct": feedback["is_correct"],
                     "occurred_at": occurred_at},
        validation_status="valid" if evidence_status == "technical_confirmed" else "insufficient_data",
        quality_json={"synthetic_only": True, "uses_model": False, "evidence_status": evidence_status},
    )
    state["attempt_count"] = int(state.get("attempt_count") or 0) + 1
    state["awaiting_next"] = True
    state["hint_requested"] = False
    state["last_feedback"] = learner_feedback
    record.result_json = state
    db.session.add(attempt_record)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        duplicate = AiLabExperiment.query.filter_by(actor_user_id=actor_user_id, request_key=attempt_key).first()
        if duplicate:
            return dict((duplicate.result_json or {}).get("learner_feedback") or {})
        raise
    return learner_feedback


def _resolve_practice_course_context(*, actor_user_id: int, subject_id: str, skill_id: str,
                                     course_id: int | None, lesson_id: int | None) -> dict[str, Any] | None:
    if course_id is None and lesson_id is None:
        return None
    if course_id is None or lesson_id is None:
        raise ValueError("Для привязки практики укажите и индивидуальный курс, и урок.")
    if subject_id != f"platform-student:{int(actor_user_id)}":
        raise ValueError("Связь практики с курсом разрешена только для собственного синтетического профиля.")
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.platform_homework import _allowlisted_user_ids
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from app.ai_lab.course_adapter import resolve_assigned_synthetic_copy
    from core.db_models import ExamSkill, Lesson, Student, User, db

    if not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled():
        raise ValueError("Связанная практика доступна только в проверенном synthetic safe mode.")
    user = db.session.get(User, int(actor_user_id))
    if (not user or str(user.role or "").casefold() != "student"
            or int(user.id) not in _allowlisted_user_ids()):
        raise ValueError("Ученик не входит в локальный список синтетических профилей.")
    student = Student.query.filter_by(user_id=int(actor_user_id)).first()
    resolution = resolve_assigned_synthetic_copy(int(student.student_id)) if student else {}
    copy = resolution.get("copy") if resolution.get("status") == "resolved" else None
    if not copy or int(copy.course_id) != int(course_id):
        raise ValueError("Указанный курс не является единственной активной разрешённой копией ученика.")
    lesson = Lesson.query.filter_by(
        lesson_id=int(lesson_id), learning_trajectory_id=int(copy.course_id),
        student_id=int(student.student_id),
    ).first()
    if not lesson or str(lesson.status or "").casefold() not in {"planned", "scheduled", "in_progress"}:
        raise ValueError("Урок не принадлежит активной копии или уже начат.")
    topic_code = practice_skill_topic_code(skill_id)
    mapped = (ExamSkill.query.filter_by(topic_code=topic_code, is_active=True).all()
              if topic_code else [])
    linked_skill = next((item for item in mapped
                         if f"exam-skill:{int(item.skill_id)}" in {
                             f"exam-skill:{int(lesson_skill.skill_id)}" for lesson_skill in (lesson.skills or [])
                         }), None) if len(mapped) == 1 else None
    if not linked_skill:
        raise ValueError("Выбранный генератор практики не связан с навыком этого урока.")
    return {
        "contract": "boostudy.synthetic-practice-course-context.v1",
        "course_id": int(copy.course_id),
        "course_version": int(copy.current_version or 1),
        "lesson_id": int(lesson.lesson_id),
        "skill_id": skill_id,
        "course_skill_id": f"exam-skill:{int(linked_skill.skill_id)}",
        "topic_code": str(linked_skill.topic_code),
    }


def next_practice_exercise(actor_user_id: int, session_id: str) -> dict[str, Any]:
    _assert_safe_practice_context()
    from core.db_models import db

    record = _require_practice_session(actor_user_id, session_id)
    state = dict(record.result_json or {})
    if state.get("status") != "active" or not state.get("awaiting_next"):
        raise ValueError("Сначала отправьте ответ на текущее упражнение.")
    history = [item for item in _stored_practice_attempts(state["subject_id"])
               if item.get("skill_id") == state["skill_id"]]
    candidates = _practice_candidates(state["skill_id"], session_id, int(state.get("attempt_count") or 0))
    selection = select_next_practice_exercise(candidates, skill_id=state["skill_id"], attempts=history)
    selected = next((item for item in candidates if item["exercise_id"] == (selection.get("exercise") or {}).get("exercise_id")), None)
    state["decision"] = selection
    state["awaiting_next"] = False
    state["hint_requested"] = False
    state["last_hint"] = None
    state["last_feedback"] = None
    state["current_exercise"] = selected
    if selected is None:
        state["status"] = "paused"
    record.result_json = state
    db.session.commit()
    return _public_session(state)


def finish_practice_session(actor_user_id: int, session_id: str) -> dict[str, Any]:
    _assert_safe_practice_context()
    from core.db_models import db

    record = _require_practice_session(actor_user_id, session_id)
    state = dict(record.result_json or {})
    state["status"] = "completed"
    state["current_exercise"] = None
    state["awaiting_next"] = False
    record.result_json = state
    db.session.commit()
    return _public_session(state)


def practice_history(subject_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    records = _stored_practice_attempt_rows(subject_id)
    result = []
    for row in records[-max(1, min(limit, 100)):]:
        snapshot = row.input_snapshot if isinstance(row.input_snapshot, dict) else {}
        exercise = snapshot.get("exercise") if isinstance(snapshot.get("exercise"), dict) else {}
        details = row.result_json if isinstance(row.result_json, dict) else {}
        result.append({
            "event_id": ((details.get("event") or {}).get("event_id")),
            "occurred_at": details.get("occurred_at"),
            "skill_id": details.get("skill_id") or "",
            "title": exercise.get("title") or "Короткая практика",
            "difficulty": details.get("difficulty"),
            "verification_status": details.get("verification_status"),
            "is_correct": details.get("is_correct"),
        })
    return list(reversed(result))


def stored_ai_practice_evidence(*, actor_user_id: int | None = None) -> list[dict[str, Any]]:
    from app.ai_lab.provider import is_local_ai_lab_enabled
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.learning_evidence import validate_evidence_event
    from core.db_models import AiLabExperiment, User, db

    if not has_verified_safe_ai_lab_db() or not is_local_ai_lab_enabled():
        return []
    admin_view = False
    if actor_user_id is not None:
        actor = db.session.get(User, int(actor_user_id))
        role = str(getattr(actor, "role", "") or "").strip().casefold()
        admin_view = role in {"admin", "creator", "superadmin", "super_admin"}
    query = AiLabExperiment.query.filter_by(scenario_id=PRACTICE_ATTEMPT_SCENARIO)
    if actor_user_id is not None and not admin_view:
        query = query.filter_by(actor_user_id=int(actor_user_id))
    rows = query.order_by(AiLabExperiment.id.asc()).limit(5_000).all()
    result = []
    for row in rows:
        event = ((row.result_json or {}).get("event") if isinstance(row.result_json, dict) else None)
        if not isinstance(event, dict) or not _is_synthetic_platform_subject(event.get("subject_id")):
            continue
        try:
            result.append(validate_evidence_event(event))
        except ValueError:
            continue
    return result


def _practice_candidates(skill_id: str, session_id: str, attempt_number: int) -> list[dict[str, Any]]:
    candidates = []
    for difficulty in range(1, 6):
        seed = f"{session_id}:exercise:{attempt_number}:difficulty:{difficulty}"
        exercise = build_practice_exercise(skill_id, seed, difficulty=difficulty)
        if exercise:
            candidates.append(exercise)
    return candidates


def _practice_session_request(actor_user_id: int, session_id: str) -> str:
    raw = f"adaptive-practice-session:{actor_user_id}:{session_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:36]


def _session_request_key(actor_user_id: int, session_id: str) -> str:
    return _practice_session_request(actor_user_id, session_id)


def _attempt_request_key(actor_user_id: int, session_id: str, idempotency_key: str) -> str:
    raw = f"adaptive-practice-attempt:{actor_user_id}:{session_id}:{idempotency_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:36]


def _load_practice_session(actor_user_id: int, session_id: str):
    from core.db_models import AiLabExperiment

    if not isinstance(session_id, str) or len(session_id) != 32 or not all(char in "0123456789abcdef" for char in session_id):
        return None
    return AiLabExperiment.query.filter_by(
        actor_user_id=actor_user_id,
        request_key=_practice_session_request(actor_user_id, session_id),
        scenario_id=PRACTICE_SESSION_SCENARIO,
    ).first()


def _require_practice_session(actor_user_id: int, session_id: str):
    record = _load_practice_session(actor_user_id, session_id)
    if not record:
        raise ValueError("Сессия не найдена или недоступна этому пользователю.")
    return record


def _stored_practice_attempts(subject_id: str) -> list[dict[str, Any]]:
    result = []
    for row in _stored_practice_attempt_rows(subject_id):
        details = row.result_json if isinstance(row.result_json, dict) else {}
        if details.get("skill_id"):
            result.append({
                "exercise_id": details.get("exercise_id"),
                "skill_id": details.get("skill_id"),
                "difficulty": details.get("difficulty"),
                "verification_status": details.get("verification_status"),
                "is_correct": details.get("is_correct"),
                "assistance_level": details.get("assistance_level"),
                "occurred_at": details.get("occurred_at"),
            })
    return result


def _stored_practice_attempt_rows(subject_id: str):
    _assert_safe_practice_context()
    from core.db_models import AiLabExperiment

    if not _is_synthetic_platform_subject(subject_id):
        return []
    rows = AiLabExperiment.query.filter_by(scenario_id=PRACTICE_ATTEMPT_SCENARIO).order_by(AiLabExperiment.id.asc()).limit(5_000).all()
    return [row for row in rows
            if isinstance(row.input_snapshot, dict) and row.input_snapshot.get("subject_id") == subject_id]


def _stored_practice_events(subject_id: str) -> list[dict[str, Any]]:
    if not _is_synthetic_platform_subject(subject_id):
        return []
    return [event for event in stored_ai_practice_evidence() if event["subject_id"] == subject_id]


def _is_synthetic_platform_subject(subject_id: Any) -> bool:
    if not isinstance(subject_id, str) or not subject_id.startswith("platform-student:"):
        return False
    raw_user_id = subject_id.removeprefix("platform-student:")
    if not raw_user_id.isdigit():
        return False
    from core.db_models import Student, User

    user = User.query.filter_by(id=int(raw_user_id)).first()
    student = Student.query.filter_by(user_id=int(raw_user_id)).first() if user else None
    return bool(user and student and str(user.username or "").startswith(("demo_", "synthetic_")))


def _public_session(state: dict[str, Any]) -> dict[str, Any]:
    exercise = state.get("current_exercise")
    if isinstance(exercise, dict):
        exercise = {key: value for key, value in exercise.items() if key not in {"answer_key", "absolute_tolerance", "hint", "explanation", "difficulty_rank"}}
    return {
        "session_id": state.get("session_id"),
        "subject_id": state.get("subject_id"),
        "skill_id": state.get("skill_id"),
        "mode": state.get("mode"),
        "status": state.get("status"),
        "current_exercise": exercise,
        "attempt_count": int(state.get("attempt_count") or 0),
        "awaiting_next": bool(state.get("awaiting_next")),
        "last_feedback": state.get("last_feedback"),
        "last_hint": state.get("last_hint"),
        "decision": state.get("decision"),
    }


def _assert_safe_practice_context() -> None:
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db

    if not has_verified_safe_ai_lab_db():
        raise RuntimeError("Свободная AI Practice разрешена только в проверенном режиме synthetic SQLite.")


def recommend_practice(
    snapshot: dict[str, Any],
    catalog: Iterable[dict[str, Any]],
    completed_assignment_ids: Iterable[str] = (),
    course_outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend existing tasks only when confirmed evidence supports practice."""
    completed = set(completed_assignment_ids)
    items = list(catalog)
    recommendations = []
    course_topics = {item.get("topic_id"): item for item in (course_outline or {}).get("topics", []) if item.get("topic_id")}
    demonstrated_skills = {item.get("skill_id") for item in snapshot.get("skills", []) if item.get("status") == "demonstrated"}
    suppressed = [
        {"skill_id": skill["skill_id"], "reason": "Одного подтверждённого случая недостаточно для диагностики навыка."}
        for skill in snapshot.get("skills", []) if skill.get("single_error_warning")
    ]
    for skill in snapshot.get("skills", []):
        if skill.get("status") != "needs_support":
            continue
        hints = SKILL_TOPIC_HINTS.get(skill["skill_id"], ())
        course_targets = [topic for topic in course_topics.values() if topic.get("skill_id") == skill["skill_id"]]
        allowed_assignments: set[str] | None = None
        course_prerequisites = []
        if course_outline:
            if not course_targets:
                suppressed.append({"skill_id": skill["skill_id"], "reason": "В выбранной версии курса навык не связан с темой; рекомендация не строилась."})
                continue
            allowed_assignments = {
                str(assignment_id)
                for topic in course_targets
                for assignment_id in topic.get("assignment_ids", [])
                if isinstance(assignment_id, str) and assignment_id
            }
            for topic in course_targets:
                for prerequisite_id in topic.get("prerequisite_ids", []):
                    prerequisite = course_topics.get(prerequisite_id)
                    prerequisite_skill = prerequisite.get("skill_id") if prerequisite else None
                    course_prerequisites.append({"topic_id": prerequisite_id, "skill_id": prerequisite_skill,
                                                 "status": "demonstrated" if prerequisite_skill in demonstrated_skills else "unknown"})
            missing = [item for item in course_prerequisites if item["status"] != "demonstrated"]
            if missing:
                suppressed.append({"skill_id": skill["skill_id"],
                                   "reason": "Сначала нужно проверить предпосылки курса: " + ", ".join(item["topic_id"] for item in missing) + "."})
                continue
            if not allowed_assignments:
                suppressed.append({"skill_id": skill["skill_id"], "reason": "В выбранной версии курса нет явной связи темы с заданиями."})
                continue
        candidates = [item for item in items
                      if item.get("assignment_id") not in completed
                      and item.get("type") == "python"
                      and (allowed_assignments is None or item.get("assignment_id") in allowed_assignments)
                      and any(hint in str(item.get("topic") or "").lower() for hint in hints)]
        if not candidates:
            continue
        selected = candidates[0]
        recommendations.append({
            "skill_id": skill["skill_id"],
            "assignment_id": selected["assignment_id"],
            "assignment_version": int(selected.get("assignment_version") or 1),
            "title": selected.get("title") or "Синтетическое задание",
            "topic": selected.get("topic") or "",
            "difficulty": selected.get("difficulty") or "Не указана",
            "reason": (
                f"Навык требует поддержки: подтверждены {skill['not_met']} ошибки в "
                f"{skill['assignment_count']} разных заданиях. Рекомендация связана с этим навыком."
            ),
            "basis": {
                "evidence_status": "technical_confirmed",
                "confirmed_evidence": skill["confirmed_evidence"],
                "failed_evidence": skill["not_met"],
                "source_refs": skill["source_refs"],
                "related_lesson_observations": skill.get("qualitative_source_refs", []),
                "rule": "needs_support требует повторных подтверждённых ошибок в разных заданиях.",
            },
            "course_context": ({
                "course_id": (course_outline or {}).get("course_id"),
                "course_version": (course_outline or {}).get("course_version"),
                "topic_ids": [topic["topic_id"] for topic in course_targets],
                "prerequisites": course_prerequisites,
            } if course_outline else None),
            "limitations": ["Code Judge проверяет конечный набор синтетических тестов.", "Это рекомендация для исследования, не изменение курса."],
        })
    return {
        "subject_id": snapshot.get("subject_id"),
        "recommendations": recommendations,
        "history": {"completed_assignment_ids": sorted(completed), "completed_count": len(completed)},
        "prerequisites": {
            "status": "course_checked" if course_outline else "unknown",
            "course_id": (course_outline or {}).get("course_id"),
            "course_version": (course_outline or {}).get("course_version"),
            "note": "Предпосылки сопоставлены только по явным связям курса и подтверждённым навыкам."
                    if course_outline else "Предпосылки не выводятся из этой выборки: для них нет достаточных структурированных доказательств.",
        },
        "suppressed": suppressed,
        "catalog_size": len(items),
        "method": "Только существующие задания из AI Lab; новые темы и задания не создаются.",
    }
