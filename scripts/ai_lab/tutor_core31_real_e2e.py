"""Seed and exercise a local, synthetic Tutor Core 3.1 acceptance scenario.

This script refuses every database except the named, isolated acceptance SQLite.
It never calls GigaChat or the Python sandbox. Platform answers and attempts are
created only through the normal submission autosave and submit endpoints.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EXPECTED_DATABASE = Path(
    r"C:\Users\eohad\Documents\BooStudy_KB_Acceptance_v6_20261023\kb_acceptance_synthetic.sqlite"
)
RUN_KEY = "tutorcore31_acceptance_20261024_v2"
ID = {
    "user": 9312001,
    "student": 9312002,
    "course": 9312003,
    "module_sql": 9312011,
    "module_game": 9312012,
    "module_quality": 9312013,
    "lesson_sql": 9312021,
    "lesson_game": 9312022,
    "lesson_quality": 9312023,
    "task_sql": 9312031,
    "task_game_initial": 9312032,
    "task_game_transfer": 9312033,
    "task_quality_manual": 9312034,
    "assignment_sql": 9312041,
    "assignment_game_initial": 9312042,
    "assignment_quality_manual": 9312043,
    "assignment_game_transfer": 9312044,
    "assignment_task_sql": 9312051,
    "assignment_task_game_initial": 9312052,
    "assignment_task_quality_manual": 9312053,
    "assignment_task_game_transfer": 9312054,
    "submission_sql": 9312061,
    "submission_game_initial": 9312062,
    "submission_quality_manual": 9312063,
    "submission_game_transfer": 9312064,
}

# These subject areas were selected before creating any answers or outcome labels.
KNOWLEDGE_KEYS = {
    "sql-relational-query": "ege.inf.sql-relational-query.v1",
    "game-strategy-initial": "ege.inf.game-strategy.v1",
    "game-strategy-transfer": "ege.inf.game-strategy.v1",
    "data-quality-manual": "ege.inf.data-quality-pipeline.v1",
}

TASKS = [
    {
        "fixture_key": "sql-relational-query",
        "id_key": "task_sql",
        "assignment_id_key": "assignment_sql",
        "assignment_task_id_key": "assignment_task_sql",
        "submission_id_key": "submission_sql",
        "lesson_id_key": "lesson_sql",
        "lesson_key": "sql",
        "task_number": 1,
        "title": "Устойчивый ключ при группировке",
        "question": "В таблице учебных групп встречаются одинаковые названия. По какому устойчивому полю безопасно выполнить GROUP BY, чтобы получить отдельный результат для каждой группы? Укажите имя поля.",
        "expected": "group_id",
        "answer": "group_id",
        "answer_type": "short_answer",
        "manual": False,
        "assistance": "independent",
    },
    {
        "fixture_key": "game-strategy-initial",
        "id_key": "task_game_initial",
        "assignment_id_key": "assignment_game_initial",
        "assignment_task_id_key": "assignment_task_game_initial",
        "submission_id_key": "submission_game_initial",
        "lesson_id_key": "lesson_game",
        "lesson_key": "game",
        "task_number": 2,
        "title": "Выигрышные первые ходы: 11 камней",
        "question": "В куче 11 камней. За ход разрешено взять ровно 1 или 4 камня. Считайте, что выигрывает игрок, забравший последний камень. Перечислите все выигрышные первые ходы.",
        "expected": "[1,4]",
        "answer": "[1]",
        "answer_type": "short_answer",
        "manual": False,
        "assistance": "independent",
    },
    {
        "fixture_key": "data-quality-manual",
        "id_key": "task_quality_manual",
        "assignment_id_key": "assignment_quality_manual",
        "assignment_task_id_key": "assignment_task_quality_manual",
        "submission_id_key": "submission_quality_manual",
        "lesson_id_key": "lesson_quality",
        "lesson_key": "quality",
        "task_number": 3,
        "title": "Проверка качества учебной таблицы",
        "question": "В учебной таблице найдены повторяющиеся идентификаторы, пустые сроки и текст в поле числовой оценки. Опишите безопасные проверки и действия до расчёта статистики.",
        "expected": None,
        "answer": "Сначала сохранить исходную копию, затем посчитать дубли ключей и проверить обязательные поля. Пустые сроки пометить как пропуски, неверные оценки вынести на ручную проверку; не заменять их нулями без правила.",
        "answer_type": "long_answer",
        "manual": True,
        "assistance": None,
    },
    {
        "fixture_key": "game-strategy-transfer",
        "id_key": "task_game_transfer",
        "assignment_id_key": "assignment_game_transfer",
        "assignment_task_id_key": "assignment_task_game_transfer",
        "submission_id_key": "submission_game_transfer",
        "lesson_id_key": "lesson_game",
        "lesson_key": "game",
        "task_number": 4,
        "title": "Выигрышные первые ходы: 14 камней",
        "question": "В другой позиции в куче 14 камней. За ход разрешено взять ровно 1, 2 или 5 камней; выигрывает забравший последний камень. Перечислите все выигрышные первые ходы.",
        "expected": "[2,5]",
        "answer": "[2,5]",
        "answer_type": "short_answer",
        "manual": False,
        "assistance": "substantive_hint",
    },
]

LESSON_PLANS = {
    "sql": [
        {"id": "warmup", "title": "Входной вопрос", "minutes": 5},
        {"id": "retrieval", "title": "Повторение ключей и связей", "minutes": 10},
        {"id": "worked_example", "title": "Разбор группировки на устойчивом ключе", "minutes": 15},
        {"id": "guided_practice", "title": "Практика запросов", "minutes": 20},
        {"id": "reflection", "title": "Разбор результата", "minutes": 10},
    ],
    "game": [
        {"id": "warmup", "title": "Короткий входной вопрос", "minutes": 5},
        {"id": "retrieval", "title": "Повторение конечных позиций", "minutes": 10},
        {"id": "worked_example", "title": "Разбор выигрышных и проигрышных позиций", "minutes": 15},
        {"id": "guided_practice", "title": "Практика стратегии на нескольких позициях", "minutes": 20},
        {"id": "reflection", "title": "Объяснение найденной закономерности", "minutes": 10},
    ],
    "quality": [
        {"id": "warmup", "title": "Постановка задачи проверки", "minutes": 5},
        {"id": "retrieval", "title": "Повторение ключей и типов данных", "minutes": 10},
        {"id": "worked_example", "title": "Разбор ошибок таблицы", "minutes": 15},
        {"id": "guided_practice", "title": "Составление правил валидации", "minutes": 20},
        {"id": "reflection", "title": "Обсуждение ограничений данных", "minutes": 10},
    ],
}


def _backup_and_check(path: Path) -> tuple[Path, int]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}_pre_tutorcore31_e2e_{stamp}.sqlite.bak")
    suffix = 1
    while backup.exists():
        backup = path.with_name(f"{path.stem}_pre_tutorcore31_e2e_{stamp}_{suffix}.sqlite.bak")
        suffix += 1
    source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(str(backup))
    try:
        source.backup(destination)
        check = destination.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Резервная копия не прошла quick_check: {check}")
        violations = destination.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"В резервной копии найдено нарушений внешних ключей: {len(violations)}")
    finally:
        destination.close()
        source.close()
    return backup, len(violations)


def _database_file_identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    if not stat.st_ino:
        raise RuntimeError("Файловая система не предоставляет идентификатор SQLite-файла.")
    return stat.st_dev, stat.st_ino


def _validate_target(path_argument: str) -> Path:
    target = Path(path_argument).resolve(strict=True)
    expected = EXPECTED_DATABASE.resolve(strict=True)
    if target != expected or not target.is_file():
        raise RuntimeError("Разрешена только явно указанная kb_acceptance_synthetic.sqlite.")
    initial_identity = _database_file_identity(target)
    connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        connected_path = Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve(strict=True)
        if connected_path != expected or _database_file_identity(connected_path) != initial_identity:
            raise RuntimeError("SQLite открыла неожиданную базу; записи запрещены.")
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        if revision != "ai_lab_tutor_core3_exam_mapping":
            raise RuntimeError(f"Схема не соответствует проверенной baseline-процедуре: {revision}")
        course_three_count = connection.execute("SELECT COUNT(*) FROM Courses WHERE course_id=3").fetchone()[0]
        if course_three_count:
            raise RuntimeError("Найден Course ID 3; приёмка остановлена, этот курс не читается и не изменяется.")
    finally:
        connection.close()
    if _database_file_identity(target) != initial_identity:
        raise RuntimeError("Файл synthetic SQLite изменился во время предварительной проверки.")
    return target


def _set_safe_environment(path: Path, file_identity: tuple[int, int]) -> None:
    conflicting_database_overrides = [
        name for name in ("DATABASE_EXTERNAL_URL", "POSTGRES_URL", "DEMO_DATABASE_URL")
        if (os.environ.get(name) or "").strip()
    ]
    if conflicting_database_overrides:
        raise RuntimeError(
            "Нельзя безопасно запустить AI Lab при активных DB-переопределителях: "
            + ", ".join(conflicting_database_overrides)
        )
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{path.as_posix()}",
        "SQLITE_DB_PATH": str(path),
        "AI_LAB_SAFE_DB_MODE": "1",
        "AI_LAB_SAFE_DB_PATH": str(path),
        "AI_LAB_SAFE_DB_FILE_ID": f"{file_identity[0]}:{file_identity[1]}",
        "BOOSTUDY_SKIP_DATABASE_BOOTSTRAP": "1",
        "BOOSTUDY_BACKGROUND_WORKERS_ENABLED": "0",
        "AUTO_DB_SCHEMA_SYNC": "0",
        "ENVIRONMENT": "local",
        "AI_LAB_ENABLED": "1",
        "AI_LAB_PLATFORM_HOMEWORK_ENABLED": "1",
        "AI_LAB_PLATFORM_TEST_ACTOR_IDS": "1",
        "AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS": "1",
    })


def _same_row(model, row_id: int, expected: dict[str, Any], create_values: dict[str, Any] | None = None):
    from core.db_models import db

    row = db.session.get(model, row_id)
    if row is not None:
        mismatches = [key for key, value in expected.items()
                      if key != "__pk__" and getattr(row, key) != value]
        if mismatches:
            raise RuntimeError(f"Стабильный ID {model.__tablename__}.{row_id} занят другой записью: {', '.join(mismatches)}")
        return row, False
    values = {key: value for key, value in expected.items() if key != "__pk__"}
    values.update(create_values or {})
    row = model(**values)
    if "__pk__" in expected:
        setattr(row, model.__mapper__.primary_key[0].key, expected["__pk__"])
    db.session.add(row)
    db.session.flush()
    return row, True


def _seed_fixture(creator_id: int) -> dict[str, Any]:
    from app.ai_lab.knowledge_base import list_knowledge_entries
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import (
        AiLabTutorDemo, Assignment, AssignmentTask, Lesson, LearningTrajectory,
        Student, Tasks, TrajectoryModule, User, Submission, db,
    )

    entries = {item["stable_key"]: item for item in list_knowledge_entries()}
    skill_keys = {}
    for fixture_key, stable_key in KNOWLEDGE_KEYS.items():
        entry = entries.get(stable_key)
        if not entry or entry.get("status") not in {"source_checked", "approved"}:
            raise RuntimeError(f"Нельзя использовать KB-материал {stable_key}: он отсутствует или не прошёл source-check.")
        skill_key = str((entry.get("content") or {}).get("assessed_skill", {}).get("skill_key") or "")
        if not skill_key:
            raise RuntimeError(f"У KB-материала {stable_key} нет устойчивого assessed_skill.skill_key.")
        skill_keys[fixture_key] = skill_key

    user, user_created = _same_row(User, ID["user"], {
        "__pk__": ID["user"], "username": f"synthetic_{RUN_KEY}", "role": "student", "is_active": True,
    })
    student, student_created = _same_row(Student, ID["student"], {
        "__pk__": ID["student"], "user_id": ID["user"], "name": "Синтетический ученик Tutor Core 3.1",
        "mentor_id": creator_id, "is_active": True,
    })
    if not user.username.startswith(("demo_", "synthetic_")) or not student.is_active:
        raise RuntimeError("Созданный профиль не соответствует синтетическому allowlist.")

    course, course_created = _same_row(LearningTrajectory, ID["course"], {
        "__pk__": ID["course"], "student_id": ID["student"], "created_by_user_id": creator_id,
        "is_template": False, "title": f"Синтетическая траектория Tutor Core 3.1 · {RUN_KEY}",
        "subject": "Информатика ЕГЭ · локальная фикстура", "description": "Только для проверки связей и адаптации Tutor Core; не является программой курса.",
        "learning_goal": "Проверить синтетические свидетельства по SQL и стратегиям конечных игр.",
        "expected_result": "Учитель видит сохранённые результаты и необязательное предложение для следующего шага.",
        "current_version": 1, "default_lesson_duration": 60, "lesson_duration_minutes": 60, "status": "active",
    })

    module_specs = [
        ("module_sql", "SQL · устойчивые ключи и группировка", f"{skill_keys['sql-relational-query']} · синтетическая связь с KB"),
        ("module_game", "Конечные игры · выигрышные позиции", f"{skill_keys['game-strategy-transfer']} · синтетическая связь с KB"),
        ("module_quality", "Качество данных · ручная диагностика", f"{skill_keys['data-quality-manual']} · синтетическая связь с KB"),
    ]
    modules = {}
    created_modules = 0
    for order, (id_key, title, result) in enumerate(module_specs, 1):
        row, created = _same_row(TrajectoryModule, ID[id_key], {
            "__pk__": ID[id_key], "course_id": ID["course"], "title": title,
            "description": "Синтетический раздел для end-to-end проверки.", "learning_result": result, "order_index": order,
        })
        modules[id_key] = row
        created_modules += int(created)

    lesson_specs = [
        ("lesson_sql", "module_sql", 1, "SQL: группировка по устойчивому ключу"),
        ("lesson_game", "module_game", 2, "Стратегии в конечных играх: выигрышные первые ходы"),
        ("lesson_quality", "module_quality", 3, "Проверка качества и ограничений учебных данных"),
    ]
    lessons = {}
    created_lessons = 0
    for id_key, module_key, order, topic in lesson_specs:
        row, created = _same_row(Lesson, ID[id_key], {
            "__pk__": ID[id_key], "student_id": ID["student"], "learning_trajectory_id": ID["course"],
            "course_module_id": ID[module_key], "lesson_type": "regular", "duration": 60,
            "course_order_index": order, "status": "planned", "topic": topic, "lesson_format": "Практикум",
            "notes": f"Только локальная синтетическая приёмка {RUN_KEY}.",
        })
        lessons[id_key] = row
        created_lessons += int(created)

    created_tasks = 0
    tasks = {}
    for spec in TASKS:
        task_id = ID[spec["id_key"]]
        source_key = f"boostudy.synthetic.tutorcore31.v1/{RUN_KEY}/{spec['fixture_key']}"
        answer_spec = {"type": spec["answer_type"]}
        values = {
            "__pk__": task_id,
            "bank_category": "synthetic_tutor_core",
            "task_number": spec["task_number"],
            "source_name": "BooStudy Tutor Core 3.1 synthetic acceptance",
            "source_key": source_key,
            "prototype_status": "unreviewed",
            "ingest_status": "ready",
            "content_html": spec["question"],
            "answer": spec["expected"],
            "created_by_id": creator_id,
            "bank_origin": "manual",
            "answer_spec": answer_spec,
            "is_active": True,
            "max_score": 1,
        }
        row = db.session.get(Tasks, task_id)
        if row is None:
            row = Tasks(**{key: value for key, value in values.items() if key != "__pk__"})
            row.task_id = task_id
            row.content_fingerprint = _task_fingerprint(row)
            db.session.add(row)
            db.session.flush()
            created_tasks += 1
        else:
            mismatches = [key for key, value in values.items() if key != "__pk__" and getattr(row, key) != value]
            if row.source_key != source_key or row.content_fingerprint != _task_fingerprint(row) or mismatches:
                raise RuntimeError(f"ID Tasks.{task_id} уже занят несовпадающим содержимым.")
        collision = Tasks.query.filter(Tasks.source_key == source_key, Tasks.task_id != task_id).first()
        if collision:
            raise RuntimeError(f"Источник {source_key} уже связан с другой задачей.")
        tasks[spec["fixture_key"]] = row

    created_assignments = created_assignment_tasks = created_submissions = 0
    assignments = {}
    for spec in TASKS:
        task = tasks[spec["fixture_key"]]
        lesson = lessons[spec["lesson_id_key"]]
        assignment_id = ID[spec["assignment_id_key"]]
        title = f"Tutor Core 3.1 synthetic · {spec['fixture_key']} · {RUN_KEY}"
        assignment, created = _same_row(Assignment, assignment_id, {
            "__pk__": assignment_id, "title": title,
            "description": "Изолированная синтетическая проверка; результат не относится к реальным ученикам.",
            "assignment_type": "homework",
            "hard_deadline": False, "hide_before_start": False, "allow_separate_submission": False,
            "max_attempts_default": 1, "attempts_per_task": False,
            "created_by_id": creator_id, "lesson_id": int(lesson.lesson_id), "is_active": True,
        }, create_values={"deadline": datetime.now(timezone.utc) + timedelta(days=30)})
        created_assignments += int(created)
        assignments[spec["fixture_key"]] = assignment
        assignment_task_id = ID[spec["assignment_task_id_key"]]
        assignment_task, created = _same_row(AssignmentTask, assignment_task_id, {
            "__pk__": assignment_task_id, "assignment_id": assignment_id, "task_id": int(task.task_id),
            "order_index": 0, "max_score": 1, "max_attempts": 1,
            "requires_manual_grading": spec["manual"], "is_error_review": False,
        })
        created_assignment_tasks += int(created)
        submission_id = ID[spec["submission_id_key"]]
        submission, created = _same_row(Submission, submission_id, {
            "__pk__": submission_id, "assignment_id": assignment_id, "student_id": ID["student"],
            "max_score": 1,
        }, create_values={"status": "ASSIGNED"})
        created_submissions += int(created)
        spec["assignment_task"] = assignment_task
        spec["submission"] = submission
        spec["task"] = task

    plan_metadata = {
        str(ID["lesson_" + key]): {"version": 1, "segments": segments}
        for key, segments in LESSON_PLANS.items()
    }
    demo_metadata = {
        "scope": "synthetic_local_acceptance_only",
        "seed_version": "tutor-core-3.1-real-e2e.v1",
        "course_version": 1,
        "lesson_plans": plan_metadata,
        "knowledge_bindings": {
            fixture_key: {
                "stable_key": stable_key,
                "version": int(entries[stable_key]["version_no"]),
                "content_sha256": entries[stable_key]["content_sha256"],
                "skill_key": skill_keys[fixture_key],
            }
            for fixture_key, stable_key in KNOWLEDGE_KEYS.items()
        },
    }
    demo = db.session.get(AiLabTutorDemo, RUN_KEY)
    if demo is None:
        demo = AiLabTutorDemo(
            demo_key=RUN_KEY, demo_version=1, seed_version="tutor-core-3.1-real-e2e.v1",
            course_id=ID["course"], student_user_id=ID["user"], student_id=ID["student"],
            metadata_json=demo_metadata,
        )
        db.session.add(demo)
    elif (demo.course_id != ID["course"] or demo.student_user_id != ID["user"]
          or demo.student_id != ID["student"] or demo.metadata_json != demo_metadata):
        raise RuntimeError("Реестр фикстуры уже существует с несовпадающей версией; история не перезаписана.")

    db.session.commit()
    return {
        "user_id": ID["user"], "student_id": ID["student"], "course_id": ID["course"],
        "creator_id": creator_id, "lesson_ids": [ID["lesson_sql"], ID["lesson_game"], ID["lesson_quality"]],
        "module_ids": [ID["module_sql"], ID["module_game"], ID["module_quality"]],
        "tasks": tasks, "assignments": assignments, "task_specs": TASKS, "skill_keys": skill_keys,
        "created_counts": {
            "user": int(user_created), "student": int(student_created), "course": int(course_created),
            "modules": created_modules, "lessons": created_lessons, "tasks": created_tasks,
            "assignments": created_assignments, "assignment_tasks": created_assignment_tasks,
            "submissions": created_submissions,
        },
        "knowledge_versions": {
            key: {"version": int(entries[key]["version_no"]), "status": entries[key]["status"],
                  "content_sha256": entries[key]["content_sha256"]}
            for key in set(KNOWLEDGE_KEYS.values())
        },
    }


def _login_client(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _record_assistance(spec: dict[str, Any], run: dict[str, Any]) -> None:
    from core.db_models import AiLabTutorDemoEvent, SubmissionAttempt, db

    if spec["assistance"] is None:
        return
    submission = spec["submission"]
    assignment_task = spec["assignment_task"]
    attempt = SubmissionAttempt.query.filter_by(submission_id=submission.submission_id).order_by(
        SubmissionAttempt.attempt_no.desc()
    ).first()
    if not attempt:
        raise RuntimeError(f"У сдачи {submission.submission_id} нет сохранённой попытки для журнала помощи.")
    submitted_at = attempt.submitted_at
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    event_id = f"{RUN_KEY}:assistance:{spec['fixture_key']}"
    payload = {
        "record_type": "synthetic_controlled_assistance",
        "submission_id": int(submission.submission_id),
        "assignment_task_id": int(assignment_task.assignment_task_id),
        "attempt_id": int(attempt.attempt_id),
        "attempt_no": int(attempt.attempt_no),
        "task_id": int(spec["task"].task_id),
        "occurred_at": (submitted_at - timedelta(milliseconds=500)).isoformat(),
        "assistance": {
            "level": spec["assistance"],
            "source_refs": [f"synthetic-action:{RUN_KEY}:{spec['fixture_key']}"],
        },
        "recording_scope": "synthetic_acceptance_script",
        "recorded_after_attempt_creation": True,
    }
    row = db.session.get(AiLabTutorDemoEvent, event_id)
    if row is not None:
        if row.demo_key != RUN_KEY or row.scenario_key != "platform_assistance" or row.event_json != payload:
            raise RuntimeError(f"Запись помощи {event_id} не совпадает с сохранённой попыткой; она не изменена.")
        return
    db.session.add(AiLabTutorDemoEvent(
        event_id=event_id, demo_key=RUN_KEY, scenario_key="platform_assistance", event_json=payload,
    ))
    db.session.commit()


def _submit_through_platform(client, spec: dict[str, Any]) -> dict[str, Any]:
    from core.db_models import Answer, AssignmentTask, Submission, SubmissionAttempt, Tasks, db

    submission_id = ID[spec["submission_id_key"]]
    assignment_task_id = ID[spec["assignment_task_id_key"]]
    task_id = ID[spec["id_key"]]
    submission = db.session.get(Submission, submission_id)
    assignment_task = db.session.get(AssignmentTask, assignment_task_id)
    task = db.session.get(Tasks, task_id)
    if not submission or not assignment_task or not task:
        raise RuntimeError(f"Не найдены сохранённые записи для synthetic fixture {spec['fixture_key']}.")
    spec["submission"] = submission
    spec["assignment_task"] = assignment_task
    spec["task"] = task
    expected = spec["expected"]
    answer = Answer.query.filter_by(
        submission_id=submission_id,
        assignment_task_id=assignment_task_id,
    ).first()
    submitted_statuses = {"SUBMITTED", "GRADED", "NEEDS_MANUAL_REVIEW"}
    answer_hidden_before_submit = None
    if submission.status not in submitted_statuses:
        answer_hidden_before_submit = True
    page = client.get(f"/submissions/{submission_id}", follow_redirects=True)
    if page.status_code != 200:
        raise RuntimeError(f"Синтетический ученик не открыл сдачу {submission_id}: HTTP {page.status_code}.")
    if (answer_hidden_before_submit is True and expected
            and expected.casefold() in page.get_data(as_text=True).casefold()):
        raise RuntimeError(f"Эталонный ответ задачи {task.task_id} отобразился в ученическом интерфейсе.")

    if answer is not None and answer.value != spec["answer"]:
        raise RuntimeError(f"Сохранённый ответ сдачи {submission_id} отличается от стабильной фикстуры.")
    attempts = SubmissionAttempt.query.filter_by(submission_id=submission_id).count()
    if submission.status in submitted_statuses:
        if attempts < 1:
            raise RuntimeError(f"Сдача {submission.submission_id} уже закрыта, но попытка не сохранена.")
    else:
        saved = client.put(
            f"/submissions/{submission_id}/autosave",
            json={"answers": [{"assignment_task_id": assignment_task_id,
                               "value": spec["answer"]}]},
        )
        if saved.status_code != 200:
            raise RuntimeError(f"Автосохранение сдачи {submission_id} вернуло HTTP {saved.status_code}.")
        submitted = client.post(f"/submissions/{submission_id}/submit", json={})
        if submitted.status_code != 200:
            raise RuntimeError(f"Отправка сдачи {submission_id} вернула HTTP {submitted.status_code}.")
        db.session.remove()
        submission = db.session.get(Submission, submission_id)
        assignment_task = db.session.get(AssignmentTask, assignment_task_id)
        spec["submission"] = submission
        spec["assignment_task"] = assignment_task
        answer = Answer.query.filter_by(
            submission_id=submission_id,
            assignment_task_id=assignment_task_id,
        ).first()
        attempts = SubmissionAttempt.query.filter_by(submission_id=submission_id).count()
        if attempts != 1 or answer is None:
            raise RuntimeError(f"Штатная сдача {submission_id} не сохранила ответ и одну попытку.")
    db.session.remove()
    submission = db.session.get(Submission, submission_id)
    assignment_task = db.session.get(AssignmentTask, assignment_task_id)
    task = db.session.get(Tasks, task_id)
    answer = Answer.query.filter_by(
        submission_id=submission_id,
        assignment_task_id=assignment_task_id,
    ).first()
    attempts = SubmissionAttempt.query.filter_by(submission_id=submission_id).count()
    if not submission or not assignment_task or not task or not answer:
        raise RuntimeError(f"После endpoint-потока не удалось повторно загрузить сдачу {submission_id}.")
    spec["submission"] = submission
    spec["assignment_task"] = assignment_task
    spec["task"] = task
    _record_assistance(spec, {"run_key": RUN_KEY})
    return {
        "fixture_key": spec["fixture_key"],
        "assignment_id": int(submission.assignment_id),
        "assignment_task_id": int(spec["assignment_task"].assignment_task_id),
        "task_id": task_id,
        "submission_id": submission_id,
        "attempt_count": attempts,
        "submission_status": submission.status,
        "answer_value": answer.value,
        "score": answer.score,
        "is_correct": answer.is_correct,
        "manual_review_required": bool(spec["manual"]),
        "assistance_recorded": spec["assistance"] is not None,
        "answer_hidden_before_submit": answer_hidden_before_submit,
    }


def _learner_for_state(state: dict[str, Any], student_id: int) -> dict[str, Any]:
    learner = next((item for item in state["learners"] if item.get("student_id") == student_id), None)
    if not learner:
        raise RuntimeError("Tutor Core не получил профиль из разрешённой связи User → Student.")
    return learner


def _final_integrity(path: Path, expected_identity: tuple[int, int]) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        exact_path = Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve(strict=True)
        if exact_path != EXPECTED_DATABASE.resolve(strict=True) or _database_file_identity(exact_path) != expected_identity:
            raise RuntimeError("Проверка целостности открыла неожиданную SQLite.")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        fk_count = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        attempts = connection.execute(
            "SELECT COUNT(*) FROM SubmissionAttempts WHERE submission_id BETWEEN ? AND ?",
            (ID["submission_sql"], ID["submission_game_transfer"]),
        ).fetchone()[0]
        course_three_count = connection.execute("SELECT COUNT(*) FROM Courses WHERE course_id=3").fetchone()[0]
    finally:
        connection.close()
    if quick_check != "ok" or fk_count != 0 or course_three_count != 0 or attempts != len(TASKS):
        raise RuntimeError(f"Итоговая проверка SQLite не прошла: quick_check={quick_check}, fk={fk_count}, attempts={attempts}.")
    return {"quick_check": quick_check, "foreign_key_violations": fk_count,
            "filesystem_identity_verified": True,
            "saved_submission_attempts": attempts, "course_3_rows": course_three_count}


def run(database_argument: str) -> dict[str, Any]:
    target = _validate_target(database_argument)
    target_identity = _database_file_identity(target)
    backup, backup_fk_count = _backup_and_check(target)
    _set_safe_environment(target, target_identity)
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    from app.ai_lab.analytics import stored_platform_homework_evidence
    from app.ai_lab.knowledge_base import list_knowledge_entries
    from app.ai_lab.tutor_core31 import get_tutor_core31_state
    from core.db_models import Assignment, AssignmentTask, Submission, SubmissionAttempt, User, db
    with app.app_context():
        with db.engine.connect() as connection:
            actual_path = Path(connection.exec_driver_sql("PRAGMA database_list").fetchone()[2]).resolve(strict=True)
        if actual_path != target or _database_file_identity(actual_path) != target_identity:
            raise RuntimeError("Приложение подключилось не к указанной synthetic SQLite; никаких seed-записей не создавалось.")
        creator = User.query.filter_by(username="creator").first()
        if not creator or creator.role not in {"creator", "admin", "superadmin", "super_admin"}:
            raise RuntimeError("В synthetic SQLite не найден ожидаемый локальный creator.")
        creator_id = int(creator.id)
        os.environ["AI_LAB_PLATFORM_TEST_USER_IDS"] = str(ID["user"])
        os.environ["AI_LAB_PLATFORM_TEST_ACTOR_IDS"] = str(creator_id)
        os.environ["AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS"] = str(creator_id)

        seeded = _seed_fixture(creator_id)
        client = app.test_client()
        _login_client(client, seeded["user_id"])
        route_results = []
        for key in ("sql-relational-query", "game-strategy-initial", "data-quality-manual"):
            spec = next(item for item in seeded["task_specs"] if item["fixture_key"] == key)
            route_results.append(_submit_through_platform(client, spec))

        state_a = get_tutor_core31_state(creator_id)
        learner_a = _learner_for_state(state_a, seeded["student_id"])
        manual_event = next((item for item in learner_a["events"] if item["fixture_key"] == "data-quality-manual"), None)
        manual_effect = next((item for item in learner_a["event_effects"]
                              if "data-quality-manual" in item["event_id"] or
                              (manual_event and item["event_id"] == manual_event["event_id"])), None)
        if not manual_event or manual_event["evidence_status"] != "insufficient_data":
            raise RuntimeError("Ручное задание не осталось в истории как недостаточно подтверждённое событие.")
        if (manual_effect is None or manual_effect["changed"]
                or manual_effect["decision_before"] != manual_effect["decision_after"]):
            raise RuntimeError("Непроверенное ручное событие неожиданно изменило состояние или предложение.")
        if (manual_effect["decision_before"] != manual_effect["decision_after"]
                or manual_effect["changed"]):
            raise RuntimeError("Ручная задача изменила общий вывод, хотя у неё нет проверяемого балла.")

        transfer_spec = next(item for item in seeded["task_specs"] if item["fixture_key"] == "game-strategy-transfer")
        route_results.append(_submit_through_platform(client, transfer_spec))
        state_b = get_tutor_core31_state(creator_id)
        learner_b = _learner_for_state(state_b, seeded["student_id"])
        game_skill = seeded["skill_keys"]["game-strategy-transfer"]
        game_state = next((item for item in learner_b["state_b"]["skills"] if item["skill_id"] == game_skill), None)
        curriculum = learner_b["curriculum"]
        if not game_state or game_state["state"] != "mixed_history_progress":
            raise RuntimeError("State B не сохранил ошибку и более поздний успех после подсказки.")
        if learner_b["comparison"]["decision"]["action"] != "independent_transfer_check":
            raise RuntimeError("Tutor Core не предложил осторожную самостоятельную проверку переноса.")
        if (curriculum.get("status") != "linked" or curriculum.get("plan_after") is None
                or curriculum.get("plan_before_total") != 60 or curriculum.get("plan_after_total") != 60
                or curriculum.get("proposal_status") != "not_applied"):
            raise RuntimeError("План не получил проверяемое 60-минутное предложение без автоматического изменения.")

        # Validate the persisted evidence through the same adapter used by the page.
        events = stored_platform_homework_evidence(actor_user_id=creator_id)
        fixture_events = [event for event in events if (event.get("provenance") or {}).get(
            "synthetic_fixture_binding", {}).get("fixture_run_key") == RUN_KEY]
        if len(fixture_events) != len(TASKS):
            raise RuntimeError(f"В сохранённой истории найдено {len(fixture_events)} из {len(TASKS)} событий фикстуры.")

        teacher_client = app.test_client()
        _login_client(teacher_client, creator_id)
        page = teacher_client.get("/admin/ai-lab/tutor-core")
        if page.status_code != 200:
            raise RuntimeError(f"Страница Tutor Core не открылась через Flask: HTTP {page.status_code}.")
        page_text = page.get_data(as_text=True)
        for marker in ("State A", "State B", "Самостоятельная проверка переноса", "Синтетическая траектория", "Code Judge не использовался"):
            if marker.casefold() not in page_text.casefold():
                raise RuntimeError(f"В странице Tutor Core отсутствует ожидаемая часть результата: {marker}.")

        student_admin_response = client.get("/admin/ai-lab/tutor-core", follow_redirects=False)
        if student_admin_response.status_code == 200:
            raise RuntimeError("Ученический синтетический сеанс получил доступ к странице Tutor Core.")

        report = {
            "run_key": RUN_KEY,
            "database": str(target),
            "backup": str(backup),
            "backup_fk_violations": backup_fk_count,
            "scope": "Только локальная синтетическая SQLite; обычная dev-БД, production и Course ID 3 не использовались.",
            "model_calls": 0,
            "docker_runner_calls": 0,
            "notification_delivery": "Штатный путь notify_user и durable outbox не подменяется; acceptance harness не запускает внешний Telegram worker.",
            "knowledge_areas_selected_before_outcomes": sorted(set(KNOWLEDGE_KEYS.values())),
            "knowledge_versions": {
                key: {**version, "skill_key": next(value for fixture, value in seeded["skill_keys"].items()
                                                    if KNOWLEDGE_KEYS[fixture] == key)}
                for key, version in seeded["knowledge_versions"].items()
            },
            "created_counts": seeded["created_counts"],
            "student_id": seeded["student_id"],
            "course_id": seeded["course_id"],
            "lesson_ids": seeded["lesson_ids"],
            "route_results": route_results,
            "state_a_decision": learner_a["comparison"]["decision"]["action"],
            "manual_event_effect": {
                "evidence_status": manual_event["evidence_status"],
                "score": manual_event["outcome"]["score"],
                "changed": manual_effect["changed"],
                "decision_before": manual_effect["decision_before"],
                "decision_after": manual_effect["decision_after"],
            },
            "state_b": {
                "game_skill_state": game_state["state"],
                "decision": learner_b["comparison"]["decision"]["action"],
                "curriculum_status": curriculum["status"],
                "plan_before_total": curriculum["plan_before_total"],
                "plan_after_total": curriculum["plan_after_total"],
                "proposal_status": curriculum["proposal_status"],
            },
            "knowledge_bindings_are_official": False,
            "knowledge_entries_modified": False,
            "integrity": _final_integrity(target, target_identity),
            "page_http_status": page.status_code,
            "student_admin_access_status": student_admin_response.status_code,
        }
        return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Полный путь к изолированной kb_acceptance_synthetic.sqlite")
    args = parser.parse_args()
    try:
        report = run(args.database)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "passed", **report}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
