# -*- coding: utf-8 -*-
"""
Жёсткий whitelist источников по тексту span.details на kompege.ru (подстроки, lower-case).
"""

from __future__ import annotations

# Нормализуем к lower при проверке; перечисляем типичные фрагменты из ФИПИ / вариантов / сборников
SOURCE_WHITELIST_SUBSTRINGS = (
    "фипи",
    "fipi",
    "основная волна",
    "досрочн",
    "резервн",
    "демоверс",
    "демо-верс",
    "апробац",
    "егкр",
    "статград",
    "диагностическ",
    "пробный экзамен",
    "пробный",
    "репетицион",
    "рт ",
    " рт",
    "крылов",
    "чуркин",
)


def details_passes_whitelist(details: str | None) -> bool:
    if not details or not str(details).strip():
        return False
    d = str(details).lower()
    return any(s in d for s in SOURCE_WHITELIST_SUBSTRINGS)
