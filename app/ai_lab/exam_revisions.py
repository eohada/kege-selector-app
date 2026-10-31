"""Versioned, source-backed links between EGE document revisions and skills.

The 2027 entries intentionally remain marked as a project. Stable skill codes
survive a task-number move; each mapping version records the year-specific task
and its input/answer contract separately.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.db_models import AiLabExamTaskBinding, ExamSkill, db


REVISION_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "revision_key": "fipi.ege.informatics.2026.final",
        "exam_year": 2026,
        "document_version": "2026-final:sha256:e2d7280d7c4bcac279ef7c09c43b70c4ea34a11d61e132ceab160e5fce29f713",
        "document_status": "approved",
        "source_key": "fipi.informatics.2026",
        "source_url": "https://doc.fipi.ru/ege/demoversii-specifikacii-kodifikatory/2026/inf_11_2026.zip",
        "source_sha256": "e2d7280d7c4bcac279ef7c09c43b70c4ea34a11d61e132ceab160e5fce29f713",
        "editorial_status": "source_checked",
        "mappings": (
            {
                "task_number": 13,
                "skill_code": "ege.inf.ipv4.subnet-mask.v1",
                "task_type": "IPv4: определение маски и адресного диапазона",
                "input_format": "Адрес IPv4 и условие с маской или префиксом из редакции ЕГЭ-2026",
                "answer_format": "Формат проверяется по конкретному условию задания; общий шаблон ответа не зашит в навык",
                "change_reason": "Финальные документы ЕГЭ-2026 связывают маску подсети с заданием 13.",
            },
            {
                "task_number": 27,
                "skill_code": "ege.inf.task27.answer-format.v1",
                "task_type": "Вычислительная задача с двумя требуемыми значениями",
                "input_format": "Данные и две вычисляемые величины по условию задания 27 финальной редакции 2026",
                "answer_format": "Две строки; в каждой указывается пара чисел согласно формату редакции 2026",
                "change_reason": "Базовый формат фиксируется отдельно, чтобы не переносить проектное изменение 2027 назад.",
            },
        ),
    },
    {
        "revision_key": "fipi.ege.informatics.2027.project",
        "exam_year": 2027,
        "document_version": "2027-project:sha256:10805acfde358f4855ed5b5d866ebb47b0f14cb3e70113da45de2d65a097312c",
        "document_status": "project",
        "source_key": "fipi.informatics.2027",
        "source_url": "https://doc.fipi.ru/ege/demoversii-specifikacii-kodifikatory/2027/inf_11_2027.zip",
        "source_sha256": "10805acfde358f4855ed5b5d866ebb47b0f14cb3e70113da45de2d65a097312c",
        "editorial_status": "project_source_checked",
        "mappings": (
            {
                "task_number": 10,
                "skill_code": "ege.inf.ipv4.subnet-mask.v1",
                "task_type": "IPv4: вычисление маски или адресного диапазона",
                "input_format": "Адрес IPv4 и параметры подсети согласно проекту 2027",
                "answer_format": "Следует условию конкретного задания; не выводится из одной только темы",
                "change_reason": "В проекте ФИПИ-2027 тема маски подсети перемещена из задания 13 в задание 10.",
            },
            {
                "task_number": 13,
                "skill_code": "ege.inf.algorithm.execution-trace.v1",
                "task_type": "Трассировка выполнения алгоритма",
                "input_format": "Фрагмент алгоритма и заданные входные значения проекта 2027",
                "answer_format": "Результат выполнения по формату конкретного задания",
                "change_reason": "Проект 2027 меняет тему задания 13 с маски подсети на трассировку алгоритма.",
            },
            {
                "task_number": 23,
                "skill_code": "ege.inf.graph.optimal-paths.v1",
                "task_type": "Графовые алгоритмы: поиск оптимального пути",
                "input_format": "Ориентированный или неориентированный граф с весами по условию проекта",
                "answer_format": "Оптимальное значение или путь согласно критерию задачи",
                "change_reason": "Отдельный стабильный навык для поиска пути по указанному критерию; не смешивается с чтением графа.",
            },
            {
                "task_number": 23,
                "skill_code": "ege.inf.graph.dag-path-count.v1",
                "task_type": "Графовые алгоритмы: подсчёт путей в DAG",
                "input_format": "Ориентированный ациклический граф по условию проекта",
                "answer_format": "Число допустимых направленных путей",
                "change_reason": "Подсчёт путей представлен отдельным навыком и проверяется отдельно от оптимизации.",
            },
            {
                "task_number": 27,
                "skill_code": "ege.inf.task27.answer-format.v1",
                "task_type": "Вычислительная задача с двумя требуемыми значениями",
                "input_format": "Данные и две вычисляемые величины по условию проекта 2027",
                "answer_format": "Одна строка с двумя числами в порядке, заданном условием",
                "change_reason": "В плане изменений ФИПИ указана одна строка с двумя числами вместо двух строк с парами чисел.",
            },
        ),
    },
)


SKILLS: dict[str, dict[str, Any]] = {
    "ege.inf.ipv4.subnet-mask.v1": {
        "title": "IPv4: маска, сеть и адресный диапазон",
        "topic": "Адресация IPv4",
        "subtopic": "CIDR, маска и границы сети",
        "mastery_criteria": [
            {"key": "prefix_to_block", "label": "Определяет размер блока по префиксу", "evidence": "Показаны маска и значащий октет."},
            {"key": "network_and_broadcast", "label": "Находит границы сети", "evidence": "Адрес сети и broadcast проверены на граничном примере."},
            {"key": "transfer", "label": "Переносит способ на другую границу октета", "evidence": "Независимая задача с новым префиксом; конечная проба не является доказательством полной корректности."},
        ],
    },
    "ege.inf.algorithm.execution-trace.v1": {
        "title": "Трассировка выполнения алгоритма",
        "topic": "Алгоритмизация",
        "subtopic": "Пошаговое выполнение программы",
        "mastery_criteria": [
            {"key": "state_updates", "label": "Верно обновляет состояние переменных", "evidence": "Таблица трассировки соответствует каждому шагу."},
            {"key": "branch_and_loop", "label": "Корректно прослеживает ветвления и циклы", "evidence": "Условия проверены в фактическом порядке исполнения."},
            {"key": "output", "label": "Получает итоговый вывод", "evidence": "Вывод пересчитан независимой ручной трассировкой."},
        ],
    },
    "ege.inf.graph.representation.v1": {
        "title": "Чтение ориентированного графа",
        "topic": "Графы",
        "subtopic": "Вершины, направления и веса рёбер",
        "mastery_criteria": [
            {"key": "vertices_edges", "label": "Перечисляет вершины и рёбра", "evidence": "Список рёбер соответствует исходному представлению."},
            {"key": "direction", "label": "Сохраняет направление ребра", "evidence": "Обратное ребро не добавлено без основания."},
            {"key": "weights", "label": "Правильно считывает веса", "evidence": "Каждый используемый вес связан с конкретным ребром."},
        ],
    },
    "ege.inf.graph.optimal-paths.v1": {
        "title": "Поиск оптимального пути в графе",
        "topic": "Графы",
        "subtopic": "Оптимизация пути по весу или иному условию",
        "mastery_criteria": [
            {"key": "criterion", "label": "Определяет min/max-критерий", "evidence": "Критерий назван до сравнения маршрутов."},
            {"key": "route_cost", "label": "Сравнивает полные маршруты", "evidence": "Сложены веса всех рёбер каждого кандидата."},
            {"key": "result_check", "label": "Проверяет выбранный оптимум", "evidence": "Сверены альтернативы на данном конечном графе."},
        ],
    },
    "ege.inf.graph.dag-path-count.v1": {
        "title": "Подсчёт путей в ориентированном ациклическом графе",
        "topic": "Графы",
        "subtopic": "Динамическое программирование по DAG",
        "mastery_criteria": [
            {"key": "topological_order", "label": "Выбирает порядок обработки DAG", "evidence": "Каждая вершина обрабатывается после предшественников."},
            {"key": "accumulate_paths", "label": "Аккумулирует число путей", "evidence": "Число путей суммируется по всем входящим рёбрам."},
            {"key": "small_graph_check", "label": "Сверяет результат перечислением", "evidence": "Для маленького графа динамический результат совпадает с явным перебором."},
        ],
    },
    "ege.inf.task27.answer-format.v1": {
        "title": "Формат ответа задания 27 по версии документа",
        "topic": "Проверка ответа",
        "subtopic": "Порядок и сериализация нескольких значений",
        "mastery_criteria": [
            {"key": "edition", "label": "Определяет год и статус редакции", "evidence": "Оформление связано с выбранной финальной редакцией или проектом."},
            {"key": "values", "label": "Извлекает требуемые значения в нужном порядке", "evidence": "Порядок сопоставлен с условием."},
            {"key": "serialization", "label": "Соблюдает формат строк", "evidence": "Запись отдельно проверена для года задания; формат не обобщается на другие годы."},
        ],
    },
}


def revision_manifest() -> list[dict[str, Any]]:
    """Return a defensive copy suitable for UI/API responses."""
    return deepcopy(list(REVISION_BINDINGS))


def seed_revision_bindings() -> dict[str, int]:
    """Idempotently seed stable skills and append-only year-specific bindings."""
    created_skills = 0
    created_bindings = 0
    skills_by_code: dict[str, ExamSkill] = {}

    for skill_code, spec in SKILLS.items():
        matches = ExamSkill.query.filter_by(topic_code=skill_code).all()
        if len(matches) > 1:
            raise ValueError(f"Код навыка {skill_code} дублируется в ExamSkills.")
        skill = matches[0] if matches else None
        if skill is None:
            skill = ExamSkill(
                topic_code=skill_code,
                task_number=None,
                title=spec["title"],
                subject="Информатика",
                topic=spec["topic"],
                subtopic=spec["subtopic"],
                mastery_criteria=deepcopy(spec["mastery_criteria"]),
                is_active=True,
            )
            db.session.add(skill)
            db.session.flush()
            created_skills += 1
        elif (skill.subject != "Информатика" or not skill.mastery_criteria):
            raise ValueError(f"Существующий навык {skill_code} имеет несовместимые предметные критерии.")
        skills_by_code[skill_code] = skill

    for revision in REVISION_BINDINGS:
        for mapping in revision["mappings"]:
            skill = skills_by_code[mapping["skill_code"]]
            binding_key = f"{revision['revision_key']}:task{mapping['task_number']}:{mapping['skill_code']}"
            expected = {
                "binding_key": binding_key,
                "mapping_version": 1,
                "revision_key": revision["revision_key"],
                "exam_year": revision["exam_year"],
                "document_version": revision["document_version"],
                "document_status": revision["document_status"],
                "task_number": mapping["task_number"],
                "skill_code": mapping["skill_code"],
                "skill_id": skill.skill_id,
                "task_type": mapping["task_type"],
                "input_format": mapping["input_format"],
                "answer_format": mapping["answer_format"],
                "source_key": revision["source_key"],
                "source_url": revision["source_url"],
                "source_sha256": revision["source_sha256"],
                "change_reason": mapping["change_reason"],
                "editorial_status": revision["editorial_status"],
            }
            existing = AiLabExamTaskBinding.query.filter_by(binding_key=binding_key, mapping_version=1).first()
            if existing is None:
                db.session.add(AiLabExamTaskBinding(**expected))
                created_bindings += 1
                continue
            for key, value in expected.items():
                if getattr(existing, key) != value:
                    raise ValueError(f"Связь {binding_key} версии 1 отличается от зафиксированной; история не перезаписана.")

    db.session.commit()
    return {"created_skills": created_skills, "created_bindings": created_bindings}
