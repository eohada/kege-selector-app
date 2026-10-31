"""Checks for answer disclosure in explicitly labeled student examples."""

from __future__ import annotations

import html
import re


_EXAMPLE_MARKER = re.compile(
    r"\b(?:пример|образец)(?:\s+(?:формата|ответа|результата))?\s*[:—-]\s*",
    re.IGNORECASE,
)
ANSWER_EXPOSURE_NOTICE = (
    "<p>Условие временно скрыто: пример формата совпадает с эталоном. "
    "Преподаватель подготовит безопасную редакцию задания.</p>"
)


def _answer_pattern(answer: str) -> re.Pattern[str] | None:
    normalized = " ".join(html.unescape(str(answer or "")).split())
    if not normalized:
        return None
    body = r"\s*".join(re.escape(part) for part in normalized.split())
    before = r"(?<!\w)" if normalized[0].isalnum() or normalized[0] == "_" else ""
    after = r"(?!\w)" if normalized[-1].isalnum() or normalized[-1] == "_" else ""
    return re.compile(f"{before}{body}{after}", re.IGNORECASE)


def answer_appears_in_labeled_example(content_html: str | None, answer: str | None) -> bool:
    """Return true when a labeled example contains the complete expected answer.

    This deliberately checks only explicitly labeled examples. A correct value may
    legitimately occur in the problem statement itself (for example, as an edge
    weight), so matching it anywhere in the prompt would reject valid tasks.
    """
    pattern = _answer_pattern(answer or "")
    if not pattern or not content_html:
        return False

    visible_text = html.unescape(re.sub(r"<[^>]*>", " ", str(content_html)))
    for marker in _EXAMPLE_MARKER.finditer(visible_text):
        example_tail = visible_text[marker.end():marker.end() + 400]
        example = re.split(r"[.!?](?!\d)", example_tail, maxsplit=1)[0]
        if pattern.search(example):
            return True
    return False


def student_safe_content_html(
    content_html: str | None,
    answer: str | None,
    *,
    allow_review_details: bool,
) -> tuple[str, bool]:
    """Hide a prompt that gives an unrevealed answer in its labeled example."""
    content = str(content_html or "")
    blocked = bool(
        not allow_review_details
        and answer_appears_in_labeled_example(content, answer)
    )
    return (ANSWER_EXPOSURE_NOTICE if blocked else content), blocked
