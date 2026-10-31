"""
Адаптер для чтения данных Tutor Core и AI Lab.
СТРОГО READ-ONLY. Не изменяет данные, не создаёт выдуманных оценок.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_student_skills_atlas(student_user_id: Optional[int]) -> List[Dict[str, Any]]:
    """
    Возвращает подтверждённые навыки для карты знаний (Atlas).
    Использует только существующие данные. Если данных нет,
    возвращает понятные структурные темы со статусом 'no_verified_evidence'.
    """
    # Базовые кластеры созвездий информатики и программирования
    constellations = [
        {
            "id": "c-logic",
            "name": "Созвездие Логики",
            "tag": "Логика и графы",
            "x": 22,
            "y": 30,
            "stars": [
                {"id": "task-01", "num": 1, "title": "Графы и таблицы", "status": "unverified", "evidence_count": 0},
                {"id": "task-02", "num": 2, "title": "Таблицы истинности", "status": "unverified", "evidence_count": 0},
                {"id": "task-15", "num": 15, "title": "Истинность выражений", "status": "unverified", "evidence_count": 0},
            ]
        },
        {
            "id": "c-algo",
            "name": "Созвездие Алгоритмов",
            "tag": "Алгоритмика",
            "x": 50,
            "y": 20,
            "stars": [
                {"id": "task-05", "num": 5, "title": "Анализ алгоритмов", "status": "unverified", "evidence_count": 0},
                {"id": "task-06", "num": 6, "title": "Чертёжник и Черепаха", "status": "unverified", "evidence_count": 0},
                {"id": "task-12", "num": 12, "title": "Простые исполнители", "status": "unverified", "evidence_count": 0},
                {"id": "task-14", "num": 14, "title": "Позиционные системы", "status": "unverified", "evidence_count": 0},
                {"id": "task-22", "num": 22, "title": "Многопоточность", "status": "unverified", "evidence_count": 0},
            ]
        },
        {
            "id": "c-python",
            "name": "Созвездие Python",
            "tag": "Программирование",
            "x": 78,
            "y": 38,
            "stars": [
                {"id": "task-16", "num": 16, "title": "Рекурсивные функции", "status": "unverified", "evidence_count": 0},
                {"id": "task-17", "num": 17, "title": "Перебор числовых пар", "status": "unverified", "evidence_count": 0},
                {"id": "task-23", "num": 23, "title": "Динамическое программирование", "status": "unverified", "evidence_count": 0},
                {"id": "task-24", "num": 24, "title": "Обработка символьных строк", "status": "unverified", "evidence_count": 0},
                {"id": "task-25", "num": 25, "title": "Теория чисел и маски", "status": "unverified", "evidence_count": 0},
            ]
        },
        {
            "id": "c-data",
            "name": "Созвездие Данных",
            "tag": "Анализ и таблицы",
            "x": 35,
            "y": 68,
            "stars": [
                {"id": "task-03", "num": 3, "title": "Реляционные БД", "status": "unverified", "evidence_count": 0},
                {"id": "task-09", "num": 9, "title": "Электронные таблицы", "status": "unverified", "evidence_count": 0},
                {"id": "task-10", "num": 10, "title": "Текстовый поиск", "status": "unverified", "evidence_count": 0},
                {"id": "task-18", "num": 18, "title": "Динамические таблицы", "status": "unverified", "evidence_count": 0},
            ]
        },
        {
            "id": "c-olympiad",
            "name": "Созвездие Олимпиад",
            "tag": "Сложные задачи",
            "x": 68,
            "y": 72,
            "stars": [
                {"id": "task-19", "num": 19, "title": "Теория игр (1 куча)", "status": "unverified", "evidence_count": 0},
                {"id": "task-20", "num": 20, "title": "Теория игр (2 кучи)", "status": "unverified", "evidence_count": 0},
                {"id": "task-21", "num": 21, "title": "Теория игр (стратегии)", "status": "unverified", "evidence_count": 0},
                {"id": "task-26", "num": 26, "title": "Жадные алгоритмы", "status": "unverified", "evidence_count": 0},
                {"id": "task-27", "num": 27, "title": "Эффективный поиск пар", "status": "unverified", "evidence_count": 0},
            ]
        }
    ]

    if not student_user_id:
        return constellations

    # Пытаемся безопасно прочитать реальные свидетельства из AI Lab, если они есть
    try:
        from app.ai_lab.analytics import all_analytics_evidence
        subject_id = f"platform-student:{student_user_id}"
        evidence_list = [ev for ev in all_analytics_evidence() if ev.get("subject_id") == subject_id]
        
        # Индексируем доказательства по номерам задач
        evidence_by_task = {}
        for ev in evidence_list:
            task_num = ev.get("task_number") or ev.get("task_no")
            if task_num:
                evidence_by_task[int(task_num)] = evidence_by_task.get(int(task_num), 0) + 1

        for c in constellations:
            for star in c["stars"]:
                num = star["num"]
                count = evidence_by_task.get(num, 0)
                star["evidence_count"] = count
                if count >= 3:
                    star["status"] = "verified_mastery"  # Подтверждено многократно
                elif count >= 1:
                    star["status"] = "in_progress"       # В процессе изучения
                else:
                    star["status"] = "unverified"        # Нет проверенных данных
    except Exception as e:
        logger.debug(f"Tutor Core evidence read fallback: {e}")

    return constellations


def get_tutor_recommendations(student_user_id: Optional[int]) -> List[Dict[str, Any]]:
    """
    Безопасное чтение рекомендаций от Tutor Core (если они предоставлены).
    """
    if not student_user_id:
        return []

    try:
        from app.ai_lab.practice import recommend_practice
        subject_id = f"platform-student:{student_user_id}"
        recs = recommend_practice(subject_id)
        if isinstance(recs, list):
            return recs
        if isinstance(recs, dict) and "recommendations" in recs:
            return recs["recommendations"]
    except Exception as e:
        logger.debug(f"Tutor Core practice recommendation fallback: {e}")

    return []
