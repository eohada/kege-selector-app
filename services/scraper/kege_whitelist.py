# -*- coding: utf-8 -*-
"""
Жёсткий whitelist источников по тексту span.details / полю comment в API (подстроки, lower-case).

Синк по умолчанию отбрасывает задачи без совпадения — на kompege у многих comment пустой или без
слов «фипи», «статград» и т.д., поэтому «в пуле» может быть сильно меньше, чем строк в API.
Узкий импорт (только эти метки в пуле): sync_kege_informatics_bank.py --whitelist-only
По умолчанию импортируются все задачи API; метка источника и уровень 1–3 — scraper/kompege_task_meta.py.
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
