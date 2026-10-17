"""Структурированный контракт результата AI Homework."""
from __future__ import annotations

import json
import math
from typing import Any


GRADING_STATUSES = {
    "checked",
    "partially_checked",
    "insufficient_data",
    "manual_review",
}
MISTAKE_TYPES = {
    "conceptual",
    "calculation",
    "logic",
    "boundary",
    "syntax",
    "incomplete",
    "format",
    "other",
}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
MISTAKE_FIELDS = {
    "description",
    "mistake_type",
    "solution_excerpt",
    "explanation",
    "correction_recommendation",
}
CRITERION_SCORE_FIELDS = {"criterion", "score_awarded", "max_score", "rationale"}


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


MISTAKE_SCHEMA = _object_schema(
    {
        "description": {"type": "string"},
        "mistake_type": {"type": "string"},
        "solution_excerpt": {"type": "string"},
        "explanation": {"type": "string"},
        "correction_recommendation": {"type": "string"},
    },
    [
        "description",
        "mistake_type",
        "solution_excerpt",
        "explanation",
        "correction_recommendation",
    ],
)

RESPONSE_SCHEMA = _object_schema(
    {
        "score_awarded": {"type": ["number", "null"]},
        "max_score": {"type": "number"},
        "grading_status": {"type": "string"},
        "criterion_scores": {
            "type": "array",
            "items": _object_schema(
                {
                    "criterion": {"type": "string"},
                    "score_awarded": {"type": "number"},
                    "max_score": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                ["criterion", "score_awarded", "max_score", "rationale"],
            ),
        },
        "insufficient_data_reason": {"type": "string"},
        "summary": {"type": "string"},
        "mistakes": {"type": "array", "items": MISTAKE_SCHEMA},
        "student_feedback": {"type": "string"},
        "teacher_feedback": {"type": "string"},
        "recommended_topics": {"type": "array", "items": {"type": "string"}},
        "needs_human_review": {"type": "boolean"},
        "review_reason": {"type": "string"},
        "confidence_level": {"type": "string"},
    },
    [
        "score_awarded",
        "max_score",
        "grading_status",
        "criterion_scores",
        "insufficient_data_reason",
        "summary",
        "mistakes",
        "student_feedback",
        "teacher_feedback",
        "recommended_topics",
        "needs_human_review",
        "review_reason",
        "confidence_level",
    ],
)


class ResponseValidationError(ValueError):
    """Ответ модели не соответствует контракту AI Homework."""


def validate_response(
    raw: str | dict[str, Any],
    expected_max_score: float,
    expected_criteria: list[dict[str, Any]] | None = None,
    *,
    require_criteria: bool = False,
) -> dict[str, Any]:
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResponseValidationError("Ответ модели не является корректным JSON.") from exc

    if not isinstance(result, dict) or set(result) != set(RESPONSE_SCHEMA["required"]):
        raise ResponseValidationError("В ответе отсутствуют обязательные поля или присутствуют лишние поля.")

    score = result["score_awarded"]
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise ResponseValidationError("Предварительный балл должен быть числом или null.")
    if score is not None and (not math.isfinite(float(score)) or score < 0 or score > expected_max_score):
        raise ResponseValidationError("Предварительный балл выходит за допустимый диапазон.")

    max_score = result["max_score"]
    if isinstance(max_score, bool) or not isinstance(max_score, (int, float)):
        raise ResponseValidationError("Максимальный балл должен быть числом.")
    if not math.isfinite(float(max_score)) or abs(float(max_score) - expected_max_score) > 0.001:
        raise ResponseValidationError("Максимальный балл в ответе не совпадает с условием.")

    if result["grading_status"] not in GRADING_STATUSES:
        raise ResponseValidationError("Неизвестный статус проверки.")
    if not isinstance(result["criterion_scores"], list):
        raise ResponseValidationError("Оценки по критериям должны быть массивом.")
    if not isinstance(result["insufficient_data_reason"], str):
        raise ResponseValidationError("Причина недостаточности данных должна быть строкой.")
    if result["grading_status"] == "checked" and score is None:
        raise ResponseValidationError("Статус checked несовместим с отсутствующей числовой оценкой.")
    if result["grading_status"] == "insufficient_data":
        if score is not None or not result["insufficient_data_reason"].strip():
            raise ResponseValidationError("Недостаток данных требует score_awarded=null и конкретной причины.")
    elif result["grading_status"] == "manual_review":
        if not isinstance(result["review_reason"], str):
            raise ResponseValidationError("Причина ручной проверки должна быть строкой.")
        if not result["needs_human_review"]:
            raise ResponseValidationError("Статус manual_review требует ручной проверки.")
        if score is None and not (
            result["review_reason"].strip() or result["insufficient_data_reason"].strip()
        ):
            raise ResponseValidationError("Ручная проверка без балла требует конкретной причины.")
        if score is not None and not result["review_reason"].strip():
            raise ResponseValidationError("Ручная проверка с предварительным баллом требует обоснования.")
    elif result["insufficient_data_reason"].strip():
        raise ResponseValidationError("Причина недостатка данных допустима только при соответствующем статусе.")

    expected_criteria = expected_criteria or []
    scored_status = result["grading_status"] in {"checked", "partially_checked"} or (
        result["grading_status"] == "manual_review" and score is not None
    )
    if require_criteria and not expected_criteria and scored_status:
        raise ResponseValidationError("Для выставления балла нужны критерии с числовыми весами.")
    if expected_criteria:
        scores = result["criterion_scores"]
        if scored_status:
            if len(scores) != len(expected_criteria):
                raise ResponseValidationError("Нужна отдельная оценка по каждому критерию.")
            awarded_total = 0.0
            maximum_total = 0.0
            for expected, actual in zip(expected_criteria, scores):
                if not isinstance(actual, dict) or set(actual) != CRITERION_SCORE_FIELDS:
                    raise ResponseValidationError("Оценка критерия не соответствует схеме.")
                if not isinstance(actual["criterion"], str):
                    raise ResponseValidationError("Название критерия должно быть строкой.")
                if actual["criterion"].strip() != expected["criterion"].strip():
                    raise ResponseValidationError("Список критериев в ответе изменён или переставлен.")
                awarded = actual["score_awarded"]
                maximum = actual["max_score"]
                expected_maximum = expected.get("max_score")
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (awarded, maximum)):
                    raise ResponseValidationError("Баллы критерия должны быть числами.")
                if expected_maximum is None:
                    raise ResponseValidationError("У критерия не задан числовой максимум баллов.")
                if not math.isfinite(float(awarded)) or not math.isfinite(float(maximum)):
                    raise ResponseValidationError("Баллы критерия должны быть конечными числами.")
                if abs(float(maximum) - float(expected_maximum)) > 0.001 or awarded < 0 or awarded > maximum:
                    raise ResponseValidationError("Баллы критерия выходят за заданный диапазон.")
                if not isinstance(actual["rationale"], str) or not actual["rationale"].strip():
                    raise ResponseValidationError("Для каждого критерия нужно обоснование.")
                awarded_total += float(awarded)
                maximum_total += float(maximum)
            if abs(maximum_total - expected_max_score) > 0.001:
                raise ResponseValidationError("Сумма максимумов критериев не совпадает с максимальным баллом.")
            if score is None or abs(float(score) - awarded_total) > 0.001:
                raise ResponseValidationError("Итоговая оценка не равна сумме баллов по критериям.")
        elif scores:
            raise ResponseValidationError("При недостатке данных нельзя выставлять оценки по критериям.")
    elif result["criterion_scores"]:
        raise ResponseValidationError("Модель указала критерии, отсутствующие во входных данных.")
    if result["confidence_level"] not in CONFIDENCE_LEVELS:
        raise ResponseValidationError("Неизвестный уровень уверенности.")
    if not isinstance(result["needs_human_review"], bool):
        raise ResponseValidationError("Признак ручной проверки должен быть логическим.")

    for field in (
        "summary",
        "student_feedback",
        "teacher_feedback",
        "review_reason",
    ):
        if not isinstance(result[field], str):
            raise ResponseValidationError(f"Поле {field} должно быть строкой.")
    if not result["summary"].strip():
        raise ResponseValidationError("Краткое резюме проверки не должно быть пустым.")

    mistakes = result["mistakes"]
    if not isinstance(mistakes, list) or len(mistakes) > 30:
        raise ResponseValidationError("Список ошибок должен быть массивом не более чем из 30 элементов.")
    for mistake in mistakes:
        if not isinstance(mistake, dict) or set(mistake) != MISTAKE_FIELDS:
            raise ResponseValidationError("Описание ошибки не соответствует схеме.")
        if mistake["mistake_type"] not in MISTAKE_TYPES:
            raise ResponseValidationError("Неизвестный тип ошибки.")
        if any(not isinstance(mistake[key], str) for key in MISTAKE_FIELDS):
            raise ResponseValidationError("Поля описания ошибки должны быть строками.")
        if not mistake["description"].strip() or not mistake["explanation"].strip():
            raise ResponseValidationError("У ошибки должны быть описание и объяснение.")

    topics = result["recommended_topics"]
    if not isinstance(topics, list) or len(topics) > 20 or any(
        not isinstance(topic, str) for topic in topics
    ):
        raise ResponseValidationError("Рекомендованные темы должны быть списком строк.")

    return result
