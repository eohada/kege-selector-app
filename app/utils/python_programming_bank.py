"""Единый банк заданий и итоговый тест по программированию на Python.

Банк содержит 200 тщательно выверенных заданий, распределённых по 4 блокам:
1. Синтаксис, типы, арифметика и ввод-вывод (50 заданий);
2. Логика и ветвления в Python (50 заданий);
3. Циклы for, while и range (50 заданий);
4. Строки, списки, функции и файлы (50 заданий).

В каждом блоке:
- 20 заданий с одиночным выбором (single_choice);
- 15 заданий на сопоставление 4 пар (matching);
- 15 заданий с коротким ответом/выводом программы (short_answer).
"""

from __future__ import annotations

import hashlib
import html
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FOUNDATIONS_PATH = PROJECT_ROOT / "data" / "task_banks" / "python_foundations.json"
EGE_PATH = PROJECT_ROOT / "data" / "task_banks" / "python_ege_full.json"
PYTHON_200_PATH = PROJECT_ROOT / "data" / "task_banks" / "python_programming_200.json"

PROGRAMMING_EGE_TOPICS = frozenset({
    "Переменные и типы",
    "Арифметика",
    "Ввод и вывод",
    "Условия",
    "Циклы",
    "Строки",
    "Списки",
    "Матрицы",
    "Словари и множества",
    "Функции",
    "Рекурсия",
    "Перебор",
    "Делители",
    "Системы счисления",
    "Логика",
    "Файлы",
    "Сортировка",
    "Оптимизация",
    "Жадные алгоритмы",
    "Симуляция",
    "Комплексная практика",
})

CYRILLIC_TO_LATIN = {
    "А": "A", "а": "A",
    "Б": "B", "б": "B",
    "В": "C", "в": "C",
    "Г": "D", "г": "D",
    "A": "A", "a": "A",
    "B": "B", "b": "B",
    "C": "C", "c": "C",
    "D": "D", "d": "D",
}


@dataclass(frozen=True)
class ProgrammingTask:
    """Нормализованная запись задания, пригодная для выдачи ученику."""

    task_id: str
    source: str
    topic: str
    level: str
    title: str
    content_html: str
    answer: object
    solution: str
    starter_code: str = ""
    block: int = 1
    block_title: str = ""
    task_type: str = "short_answer"
    options: tuple = ()
    matching_left: tuple = ()
    matching_right: tuple = ()
    explanation: str = ""

    @property
    def fingerprint(self) -> str:
        """Стабильный отпечаток условия и эталона для удаления дублей."""
        values = (
            _clean_text(self.content_html),
            _clean_text(str(self.answer)),
            _clean_text(self.solution),
        )
        return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _clean_text(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _python_200_tasks(data: dict) -> list[ProgrammingTask]:
    tasks = []
    for item in data.get("tasks", []):
        tasks.append(
            ProgrammingTask(
                task_id=str(item.get("id") or ""),
                source="python_200",
                topic=str(item.get("topic") or "Python"),
                level=str(item.get("level") or "базовый"),
                title=str(item.get("title") or "Задание"),
                content_html=str(item.get("content_html") or ""),
                answer=item.get("answer") or "",
                solution=str(item.get("explanation") or item.get("solution") or ""),
                starter_code=str(item.get("starter_code") or ""),
                block=int(item.get("block") or 1),
                block_title=str(item.get("block_title") or ""),
                task_type=str(item.get("type") or "short_answer"),
                options=tuple(item.get("options") or ()),
                matching_left=tuple(item.get("matching_left") or ()),
                matching_right=tuple(item.get("matching_right") or ()),
                explanation=str(item.get("explanation") or ""),
            )
        )
    return tasks


def _foundation_tasks(data: dict) -> Iterable[ProgrammingTask]:
    for item in data.get("tasks", []):
        yield ProgrammingTask(
            task_id=f"foundation:{item['id']}",
            source="foundation",
            topic=str(item.get("module") or "Без темы"),
            level=str(item.get("level") or "базовый"),
            title=str(item.get("title") or item.get("module") or "Задание"),
            content_html=str(item.get("content_html") or ""),
            answer=str(item.get("answer") or ""),
            solution=str(item.get("solution") or ""),
            starter_code=str(item.get("starter_code") or ""),
            task_type="short_answer",
        )


def _ege_tasks(data: dict) -> Iterable[ProgrammingTask]:
    for topic_item in data.get("tasks", []):
        number = topic_item.get("task_number", "?")
        topic = str(topic_item.get("topic") or f"Тема {number}")
        for index, item in enumerate(topic_item.get("variants", []), start=1):
            yield ProgrammingTask(
                task_id=f"ege:{number}:{index}",
                source="ege",
                topic=topic,
                level="егэ-практика",
                title=f"{topic} — вариант {index}",
                content_html=str(item.get("content_html") or ""),
                answer=str(item.get("answer") or ""),
                solution=str(item.get("solution") or ""),
                task_type="short_answer",
            )


def load_bank(
    foundations_path: Path = FOUNDATIONS_PATH,
    ege_path: Path = EGE_PATH,
) -> list[ProgrammingTask]:
    """Загрузить объединённый foundation+ege банк для общих тестов."""
    candidates = [
        *_foundation_tasks(_read_json(foundations_path)),
        *_ege_tasks(_read_json(ege_path)),
    ]
    unique: list[ProgrammingTask] = []
    fingerprints: set[str] = set()
    for task in candidates:
        if not task.content_html.strip() or task.fingerprint in fingerprints:
            continue
        fingerprints.add(task.fingerprint)
        unique.append(task)
    return unique


def validate_bank(tasks: Optional[Iterable[ProgrammingTask]] = None, minimum: int = 200) -> dict:
    """Проверить объём и разнообразие общего банка."""
    records = list(tasks if tasks is not None else load_bank())
    topics = {task.topic for task in records}
    sources = {task.source for task in records}
    if len(records) < minimum:
        raise ValueError(f"В банке только {len(records)} уникальных заданий; требуется минимум {minimum}.")
    if len(topics) < 20:
        raise ValueError(f"Недостаточно тематического покрытия: {len(topics)} тем.")
    if sources != {"foundation", "ege"}:
        raise ValueError(f"Ожидались оба источника заданий, получены: {sorted(sources)}")
    return {"total": len(records), "topics": len(topics), "sources": sorted(sources)}


def _pick_one_per_topic(tasks: list[ProgrammingTask], topic_count: int, rng: random.Random) -> list[ProgrammingTask]:
    by_topic: dict[str, list[ProgrammingTask]] = {}
    for task in tasks:
        by_topic.setdefault(task.topic, []).append(task)
    topics = list(by_topic)
    rng.shuffle(topics)
    selected: list[ProgrammingTask] = []
    for topic in topics[:topic_count]:
        selected.append(rng.choice(by_topic[topic]))
    return selected


def build_final_test(
    size: int = 20,
    seed: Optional[int] = None,
    tasks: Optional[Iterable[ProgrammingTask]] = None,
) -> list[ProgrammingTask]:
    """Собрать итоговый вариант из foundation + ege банка (совместимость)."""
    if size < 1:
        raise ValueError("Размер итогового теста должен быть положительным.")
    records = list(tasks if tasks is not None else load_bank())
    if len(records) < size:
        raise ValueError(f"Нельзя выбрать {size} заданий из банка размером {len(records)}.")

    rng = random.Random(seed)
    foundation = [task for task in records if task.source == "foundation"]
    ege = [task for task in records if task.source == "ege"]
    foundation_count = min(round(size * 0.6), len(foundation))
    ege_count = size - foundation_count
    if ege_count > len(ege):
        ege_count = len(ege)
        foundation_count = size - ege_count

    selected = _pick_one_per_topic(foundation, foundation_count, rng)
    selected.extend(_pick_one_per_topic(ege, ege_count, rng))
    selected_ids = {task.task_id for task in selected}
    remaining = [task for task in records if task.task_id not in selected_ids]
    rng.shuffle(remaining)
    if len(selected) < size:
        selected.extend(remaining[: size - len(selected)])
    rng.shuffle(selected)
    return selected[:size]


def load_programming_bank(
    path: Path = PYTHON_200_PATH,
    tasks: Optional[Iterable[ProgrammingTask]] = None,
) -> list[ProgrammingTask]:
    """Загрузить банк программирования на 200 заданий по 4 блокам."""
    if tasks is not None:
        return list(tasks)
    if path.exists():
        data = _read_json(path)
        return _python_200_tasks(data)

    # Fallback на старый банк, если 200.json отсутствует
    records = load_bank()
    return [
        task for task in records
        if task.source == "foundation"
        or (task.source == "ege" and task.topic in PROGRAMMING_EGE_TOPICS)
    ]


def validate_programming_bank(tasks: Optional[Iterable[ProgrammingTask]] = None, minimum: int = 20) -> dict:
    """Проверить банк финального теста по программированию."""
    records = load_programming_bank(tasks=tasks)
    if len(records) < minimum:
        raise ValueError(f"В программном банке только {len(records)} заданий; требуется минимум {minimum}.")

    by_block: dict[int, list[ProgrammingTask]] = {}
    for task in records:
        by_block.setdefault(task.block, []).append(task)

    return {
        "total": len(records),
        "topics": len({task.topic for task in records}),
        "blocks": len(by_block),
        "sources": sorted({task.source for task in records}),
    }


def build_programming_final_test(
    size: int = 20,
    seed: Optional[int] = None,
    tasks: Optional[Iterable[ProgrammingTask]] = None,
    previous_task_ids: Optional[Iterable[str]] = None,
    history_task_ids: Optional[Iterable[str]] = None,
    max_overlap: int = 4,
) -> list[ProgrammingTask]:
    """Собрать итоговый вариант ровно из 4 блоков по 5 заданий.

    Задания 1–5: Блок 1 (Переменные, типы данных, операторы)
    Задания 6–10: Блок 2 (Циклы и range)
    Задания 11–15: Блок 3 (Условные конструкции)
    Задания 16–20: Блок 4 (Функции и подпрограммы)

    Если переданы previous_task_ids:
    гарантирует минимум 80% измененных заданий (overlap <= max_overlap, по умолчанию 4 из 20).
    Приоритет отдаётся заданиям, ещё не встречавшимся в history_task_ids.
    """
    records = load_programming_bank(tasks=tasks)
    validate_programming_bank(records, minimum=size)

    rng = random.Random(seed)
    prev_set = set(previous_task_ids or [])
    history_set = set(history_task_ids or [])

    by_block: dict[int, list[ProgrammingTask]] = {}
    for task in records:
        by_block.setdefault(task.block, []).append(task)

    # Если в банке есть 4 явных блока, выбираем строго по 5 из каждого
    if len(by_block) >= 4 and all(len(by_block.get(b, [])) >= 5 for b in (1, 2, 3, 4)):
        selected_variant: list[ProgrammingTask] = []
        total_overlap_allowed = max_overlap if prev_set else 0
        current_overlap_count = 0

        for block_num in (1, 2, 3, 4):
            block_pool = list(by_block[block_num])
            rng.shuffle(block_pool)

            if prev_set:
                fresh_never = [t for t in block_pool if t.task_id not in prev_set and t.task_id not in history_set]
                fresh_old = [t for t in block_pool if t.task_id not in prev_set and t.task_id in history_set]
                reused_candidates = [t for t in block_pool if t.task_id in prev_set]

                # Приоритет 1: задания, которых вообще не было в прошлых попытках
                # Приоритет 2: задания, которых не было в предыдущем варианте
                fresh_pool = fresh_never + fresh_old
                block_selected: list[ProgrammingTask] = []

                if len(fresh_pool) >= 5:
                    block_selected = list(fresh_pool[:5])
                else:
                    block_selected = list(fresh_pool)
                    needed = 5 - len(block_selected)
                    can_overlap = min(needed, total_overlap_allowed - current_overlap_count, len(reused_candidates))
                    if can_overlap > 0:
                        block_selected.extend(reused_candidates[:can_overlap])
                        current_overlap_count += can_overlap

                    if len(block_selected) < 5:
                        already_ids = {t.task_id for t in block_selected}
                        fillers = [t for t in block_pool if t.task_id not in already_ids]
                        block_selected.extend(fillers[: 5 - len(block_selected)])

                selected_variant.extend(block_selected[:5])
            else:
                selected_variant.extend(block_pool[:5])

        return selected_variant

    # Fallback при нестандартном размере или отсутствии разметки блоков
    return build_final_test(size=size, seed=seed, tasks=records)


def normalize_single_choice(value: object) -> str:
    """Нормализовать одиночный выбор (A/B/C/D или А/Б/В/Г)."""
    text = str(value or "").strip()
    return CYRILLIC_TO_LATIN.get(text, text.upper())


def normalize_matching_answer(val: object) -> dict[str, str]:
    """Привести ответ на сопоставление к словарю {'1': 'A', '2': 'B', '3': 'C', '4': 'D'}."""
    if isinstance(val, dict):
        res = {}
        for k, v in val.items():
            k_clean = str(k).strip()
            v_clean = CYRILLIC_TO_LATIN.get(str(v).strip(), str(v).strip().upper())
            res[k_clean] = v_clean
        return res

    if isinstance(val, str):
        text = val.strip()
        # Формат '1A2B3C4D' или '1-A 2-B 3-C 4-D'
        matches = re.findall(r'([1-4])\s*[:=\-]?\s*([A-Da-dА-Га-г])', text)
        if len(matches) == 4:
            return {m[0]: CYRILLIC_TO_LATIN.get(m[1], m[1].upper()) for m in matches}
        # Строка из 4 букв, например 'CBDA'
        letters = [CYRILLIC_TO_LATIN.get(ch, ch.upper()) for ch in text if ch.upper() in CYRILLIC_TO_LATIN]
        if len(letters) == 4:
            return {str(i + 1): letters[i] for i in range(4)}

    return {}


def normalize_short_answer(value: object) -> str:
    """Свести короткий ответ к безопасному сравнению без лишних кавычек и пробелов."""
    text = html.unescape(str(value or "")).strip()
    # Снимаем внешние кавычки, если ученик ввёл 'hello' или "42"
    if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
        text = text[1:-1].strip()
    return re.sub(r"\s+", " ", text).lower()


def normalize_answer(value: object) -> str:
    """Обратная совместимость со старым API нормализации."""
    return normalize_short_answer(value)


def grade_answers(answer_map: dict[str, object], tasks: Optional[Iterable[ProgrammingTask]] = None) -> dict:
    """Проверить ответы по ID заданий, корректно учитывая механику вопроса.

    - single_choice: точное совпадение выбранного варианта A/B/C/D;
    - matching: 1 балл даётся только при полном совпадении всех 4 пар;
    - short_answer: проверка нормализованной строки/числа.
    """
    records = {task.task_id: task for task in (tasks if tasks is not None else load_programming_bank())}
    results = []
    for task_id, submitted in answer_map.items():
        task = records.get(str(task_id))
        if task is None:
            continue

        is_correct = False
        user_answer_text = ""
        correct_answer_text = ""

        if task.task_type == "matching":
            expected_match = normalize_matching_answer(task.answer)
            student_match = normalize_matching_answer(submitted)
            is_correct = (
                len(expected_match) == 4
                and len(student_match) == 4
                and all(student_match.get(k) == expected_match.get(k) for k in ("1", "2", "3", "4"))
            )
            left_dict = {str(item.get("id", "")): item.get("text", "") for item in (task.matching_left or ()) if isinstance(item, dict)}
            right_dict = {str(item.get("id", "")): item.get("text", "") for item in (task.matching_right or ()) if isinstance(item, dict)}
            stu_pairs = [
                f"{k}. {left_dict.get(k, k)} → [{student_match.get(k, '—')}] {right_dict.get(student_match.get(k, ''), '')}".strip()
                for k in ("1", "2", "3", "4")
            ]
            exp_pairs = [
                f"{k}. {left_dict.get(k, k)} → [{expected_match.get(k, '—')}] {right_dict.get(expected_match.get(k, ''), '')}".strip()
                for k in ("1", "2", "3", "4")
            ]
            user_answer_text = "; ".join(stu_pairs) if student_match else "Не отвечено"
            correct_answer_text = "; ".join(exp_pairs)
        elif task.task_type == "single_choice":
            exp = normalize_single_choice(task.answer)
            stu = normalize_single_choice(submitted)
            is_correct = bool(stu and stu == exp)
            opts_dict = {str(opt.get("id", "")): opt.get("text", "") for opt in (task.options or ()) if isinstance(opt, dict)}
            user_answer_text = f"Вариант {stu}: {opts_dict.get(stu, '')}".strip(": ") if stu else "Не отвечено"
            correct_answer_text = f"Вариант {exp}: {opts_dict.get(exp, '')}".strip(": ") if exp else str(task.answer)
        else:
            exp = normalize_short_answer(task.answer)
            stu = normalize_short_answer(submitted)
            is_correct = bool(stu != "" and stu == exp)
            user_answer_text = str(submitted).strip() if submitted not in (None, "") else "Не отвечено"
            correct_answer_text = str(task.answer).strip()

        results.append({
            "id": task.task_id,
            "task_id": task.task_id,
            "correct": is_correct,
            "is_correct": is_correct,
            "task_type": task.task_type,
            "title": task.title,
            "topic": task.topic,
            "content_html": task.content_html,
            "user_answer": submitted,
            "correct_answer": task.answer,
            "user_answer_text": user_answer_text,
            "correct_answer_text": correct_answer_text,
            "options": list(task.options or ()),
            "matching_left": list(task.matching_left or ()),
            "matching_right": list(task.matching_right or ()),
            "explanation": task.explanation,
        })

    return {
        "checked": len(results),
        "correct": sum(1 for result in results if result["correct"]),
        "results": results,
        "details": results,
    }


__all__ = [
    "ProgrammingTask",
    "build_final_test",
    "build_programming_final_test",
    "grade_answers",
    "load_bank",
    "load_programming_bank",
    "normalize_answer",
    "normalize_matching_answer",
    "normalize_short_answer",
    "normalize_single_choice",
    "validate_bank",
    "validate_programming_bank",
]
