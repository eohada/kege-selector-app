# -*- coding: utf-8 -*-
"""
Метаданные задачи КЕГЭ для банка: плашка источника (ФИПИ, Апробация, …) и уровень 1–3.
Уровень: поле difficulty из API (0/1/2 → базовый/средний/сложный), иначе разбор «Уровень: …» в comment/HTML.
"""
from __future__ import annotations

import re
from typing import Any

# Соответствие уровня КЕГЭ (1–3) полю difficulty_level (лестница 1–10 в приложении)
KEGE_TIER_TO_DIFFICULTY_LEVEL = {1: 2, 2: 5, 3: 9}

# Первое совпадение по подстроке в comment + начало HTML; иначе «Авторские»
SOURCE_TAG_RULES: list[tuple[tuple[str, ...], str]] = [
    (("фипи", "fipi"), "ФИПИ"),
    (("апробац",), "Апробация"),
    (("крылов",), "Крылов"),
    (("чуркин",), "Чуркин"),
    (("статград",), "СтатГрад"),
    (("демоверс", "демо-верс"), "Демоверсия"),
    (("основная волна",), "Основная волна"),
    (("досрочн",), "Досрочная"),
    (("резервн",), "Резервная"),
    (("егкр",), "ЕГКР"),
    (("пробный экзамен",), "Пробник"),
    (("репетицион",), "Пробник"),
    (("диагностическ",), "Диагностика"),
    (("пробный",), "Пробник"),
    (("рт ", " рт"), "РТ"),
]

DEFAULT_SOURCE_TAG = "Авторские"

TIER_LABELS_RU: dict[int, str] = {1: "Базовый", 2: "Средний", 3: "Сложный"}

_LEVEL_RE = re.compile(
    r"Уровень\s*:\s*(Базовый|Средний|Сложный)",
    re.IGNORECASE | re.UNICODE,
)

_WORD_TO_TIER = {"базовый": 1, "средний": 2, "сложный": 3}


def _text_blob_from_html(html: str | None, max_len: int = 2800) -> str:
    if not html:
        return ""
    t = re.sub(r"<[^>]+>", " ", html)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def parse_kege_difficulty_tier(details: str | None, content_html: str | None) -> int:
    """1 — базовый, 2 — средний, 3 — сложный; по умолчанию 2, если в тексте нет маркера."""
    blob = f"{details or ''} {_text_blob_from_html(content_html)}"
    m = _LEVEL_RE.search(blob)
    if m:
        w = m.group(1).lower()
        return int(_WORD_TO_TIER.get(w, 2))
    return 2


def resolve_kege_source_tag(details: str | None, content_html: str | None) -> str:
    blob = f"{details or ''} {_text_blob_from_html(content_html)}".lower()
    for keys, label in SOURCE_TAG_RULES:
        if any(k in blob for k in keys):
            return label
    return DEFAULT_SOURCE_TAG


def _tier_from_api_difficulty(raw: Any) -> int | None:
    """API kompege: difficulty 0/1/2 → уровень 1/2/3 (базовый/средний/сложный)."""
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v in (0, 1, 2):
        return v + 1
    return None


def kompege_bank_fields_from_item(it: dict[str, Any], *, content_html: str) -> dict[str, Any]:
    """Поля для ORM: kege_source_tag, kege_difficulty_tier, difficulty_level."""
    details = it.get("details")
    tier = _tier_from_api_difficulty(it.get("apiDifficulty"))
    if tier is None:
        tier = parse_kege_difficulty_tier(
            str(details) if details is not None else None,
            content_html,
        )
    tag = resolve_kege_source_tag(
        str(details) if details is not None else None,
        content_html,
    )
    tier = max(1, min(3, int(tier)))
    return {
        "kege_source_tag": tag,
        "kege_difficulty_tier": tier,
        "difficulty_level": int(KEGE_TIER_TO_DIFFICULTY_LEVEL[tier]),
    }
