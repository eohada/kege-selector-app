#!/usr/bin/env python3
"""Prepare and run a private, synthetic-only BooStudy Adaptive Lab on Linux."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DB_NAME = "adaptive_learning_synthetic.sqlite"
MANIFEST_NAME = "adaptive_learning_synthetic.manifest.json"
MANIFEST_FORMAT = "boostudy.adaptive-lab-synthetic.v1"
SQLITE_APPLICATION_ID = 0x42534C41  # "BSLA"
SAFE_DIRECTORY_PREFIX = "BooStudy_Adaptive_Lab_Synthetic_Linux_"
SYNTHETIC_DEFAULT_PASSWORDS = {
    "creator": "creator123",
    "synthetic_adaptive_student": "student123",
    "synthetic_tutor": "teacher123",
    "synthetic_graph_learner_1": "student123",
    "synthetic_graph_learner_2": "student123",
    "synthetic_graph_learner_3": "student123",
}
SYNTHETIC_ACCOUNT_ROLES = {
    "creator": "creator",
    "synthetic_adaptive_student": "student",
    "synthetic_tutor": "tutor",
    "synthetic_graph_learner_1": "student",
    "synthetic_graph_learner_2": "student",
    "synthetic_graph_learner_3": "student",
}


def _validated_path(raw_path: str, *, must_exist: bool) -> Path:
    path = Path(raw_path).expanduser()
    if path.name != DB_NAME or path.is_symlink():
        raise RuntimeError(f"Путь должен указывать на обычный {DB_NAME} без symlink.")
    if not path.parent.name.startswith(SAFE_DIRECTORY_PREFIX) or path.parent.is_symlink():
        raise RuntimeError(f"База должна находиться в отдельном каталоге {SAFE_DIRECTORY_PREFIX}*.")
    home = Path.home().resolve()
    parent = path.parent.resolve() if path.parent.exists() else path.parent.absolute()
    if not parent.is_relative_to(home):
        raise RuntimeError("Synthetic база разрешена только внутри домашнего каталога пользователя Linux.")
    if must_exist:
        if not path.is_file():
            raise RuntimeError("Synthetic SQLite не найдена.")
        return path.resolve(strict=True)
    if path.exists() or path.parent.exists():
        raise RuntimeError("Каталог или SQLite уже существуют; существующая база не будет перезаписана.")
    return path.absolute()


def _file_identity(path: Path) -> str:
    info = path.stat()
    if not info.st_ino:
        raise RuntimeError("Файловая система не сообщает inode для synthetic SQLite.")
    return f"{info.st_dev}:{info.st_ino}"


def _manifest_path(db_path: Path) -> Path:
    return db_path.with_name(MANIFEST_NAME)


def _validate_manifest_and_database(db_path: Path) -> dict:
    manifest_path = _manifest_path(db_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("Нет проверенного synthetic-манифеста рядом с SQLite.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Synthetic-манифест повреждён или недоступен.") from error
    if manifest.get("format") != MANIFEST_FORMAT or manifest.get("synthetic") is not True:
        raise RuntimeError("Манифест не подтверждает отдельную synthetic-базу BooStudy.")
    if manifest.get("db_identity") != _file_identity(db_path):
        raise RuntimeError("Идентификатор SQLite отличается от проверенного манифеста.")

    ids = manifest.get("ids") or {}
    groups = {
        "actor_user_ids": ("Users", "id", {"creator", "admin", "tutor", "teacher"}),
        "student_user_ids": ("Users", "id", {"student"}),
        "student_ids": ("Students", "student_id", None),
        "template_course_ids": ("Courses", "course_id", None),
        "course_copy_ids": ("Courses", "course_id", None),
        "lesson_ids": ("Lessons", "lesson_id", None),
        "task_ids": ("Tasks", "task_id", None),
    }
    if any(not isinstance(ids.get(key), list) or not ids[key] for key in groups):
        raise RuntimeError("В манифесте отсутствует обязательный synthetic allowlist.")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            if connection.execute("PRAGMA application_id").fetchone()[0] != SQLITE_APPLICATION_ID:
                raise RuntimeError("SQLite не содержит маркер BooStudy Synthetic Lab.")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity_check завершился ошибкой.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("В synthetic SQLite найдены нарушения внешних ключей.")
            for key, (table, column, roles) in groups.items():
                for raw_id in ids[key]:
                    try:
                        record_id = int(raw_id)
                    except (TypeError, ValueError) as error:
                        raise RuntimeError(f"Некорректный ID в allowlist {key}.") from error
                    row = connection.execute(
                        f"SELECT role FROM {table} WHERE {column} = ?" if roles
                        else f"SELECT 1 FROM {table} WHERE {column} = ?",
                        (record_id,),
                    ).fetchone()
                    if not row or (roles and row[0] not in roles):
                        raise RuntimeError(f"Allowlist {key} ссылается на отсутствующую synthetic-запись.")
            for course_id in ids["template_course_ids"]:
                row = connection.execute(
                    "SELECT is_template FROM Courses WHERE course_id = ?", (int(course_id),)
                ).fetchone()
                if not row or row[0] != 1:
                    raise RuntimeError("Мастер-курс allowlist не является synthetic-шаблоном.")
            for course_id in ids["course_copy_ids"]:
                row = connection.execute(
                    "SELECT student_id, is_template, status FROM Courses WHERE course_id = ?",
                    (int(course_id),),
                ).fetchone()
                if not row or row[0] not in {int(value) for value in ids["student_ids"]} or row[1] != 0 or row[2] != "active":
                    raise RuntimeError("Индивидуальная программа не связана с разрешённым synthetic-учеником.")
            for lesson_id in ids["lesson_ids"]:
                row = connection.execute(
                    "SELECT learning_trajectory_id, student_id FROM Lessons WHERE lesson_id = ?",
                    (int(lesson_id),),
                ).fetchone()
                if not row or int(row[0]) not in {int(value) for value in ids["course_copy_ids"]} or int(row[1]) not in {int(value) for value in ids["student_ids"]}:
                    raise RuntimeError("Урок не привязан к разрешённой synthetic-копии курса и ученику.")
    except sqlite3.Error as error:
        raise RuntimeError("Не удалось проверить synthetic SQLite в read-only режиме.") from error
    return manifest


def _safe_environment(db_path: Path, manifest: dict, port: int | None = None) -> dict[str, str]:
    ids = manifest["ids"]
    database_url = f"sqlite:///{db_path.as_posix()}"
    environment = {
        "HOME": str(Path.home()),
        "PATH": f"{ROOT / 'venv' / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
        "ENVIRONMENT": "local",
        "RUN_ENV": "local",
        "SECRET_KEY": secrets.token_urlsafe(32),
        "AI_LAB_ENABLED": "1",
        "AI_LAB_COURSE_ADAPTER_ENABLED": "1",
        "AI_LAB_PLATFORM_HOMEWORK_ENABLED": "1",
        "AI_LAB_SAFE_DB_MODE": "1",
        "AI_LAB_SAFE_DB_PATH": str(db_path),
        "AI_LAB_SAFE_DB_FILE_ID": _file_identity(db_path),
        "AI_LAB_SYNTHETIC_COURSE_IDS": ",".join(map(str, ids["template_course_ids"])),
        "AI_LAB_SYNTHETIC_COURSE_COPY_IDS": ",".join(map(str, ids["course_copy_ids"])),
        "AI_LAB_PLATFORM_TEST_USER_IDS": ",".join(map(str, ids["student_user_ids"])),
        "AI_LAB_PLATFORM_TEST_ACTOR_IDS": ",".join(map(str, ids["actor_user_ids"])),
        "AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS": ",".join(map(str, ids.get("task_author_ids", ids["actor_user_ids"]))),
        "DATABASE_URL": database_url,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLITE_DB_PATH": str(db_path),
        "BOOSTUDY_SKIP_DATABASE_BOOTSTRAP": "1",
        "BOOSTUDY_BACKGROUND_WORKERS_ENABLED": "0",
        "DISABLE_BACKGROUND_WORKERS": "1",
        "STORAGE_BACKEND": "local",
    }
    if port is not None:
        environment["AI_LAB_LOCAL_PORT"] = str(port)
    return environment


def _seed_database(db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, mode=0o700)
    os.chmod(db_path.parent, 0o700)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
        connection.execute("PRAGMA user_version = 1")
    os.chmod(db_path, 0o600)
    os.environ.clear()
    os.environ.update(_safe_environment(db_path, {"ids": {
        "template_course_ids": [1], "course_copy_ids": [2], "student_user_ids": [1],
        "actor_user_ids": [1], "student_ids": [1], "lesson_ids": [1], "task_ids": [1],
    }}))

    from app import create_app, db
    from app.ai_lab.knowledge_base import (
        ensure_seeded_knowledge_base,
        ensure_tutor_core3_knowledge,
    )
    from app.ai_lab.knowledge_data import KNOWLEDGE_DATA_VERSION
    from app.models import Enrollment, Student, User
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import ExamSkill, LearningItem, LearningTrajectory, Lesson, LessonTask, TrajectoryModule, Tasks

    app = create_app()
    with app.app_context():
        db.create_all()
        ensure_seeded_knowledge_base()
        ensure_tutor_core3_knowledge()
        creator = User(username="creator", email="creator@adaptive-lab.example.test", role="creator", is_active=True)
        creator.set_password(SYNTHETIC_DEFAULT_PASSWORDS[creator.username])
        learner_user = User(username="synthetic_adaptive_student", email="adaptive-student@adaptive-lab.example.test", role="student", is_active=True)
        learner_user.set_password(SYNTHETIC_DEFAULT_PASSWORDS[learner_user.username])
        teacher_user = User(username="synthetic_tutor", email="synthetic-tutor@adaptive-lab.example.test", role="tutor", is_active=True)
        teacher_user.set_password(SYNTHETIC_DEFAULT_PASSWORDS[teacher_user.username])
        db.session.add_all([creator, learner_user, teacher_user])
        db.session.flush()

        student = Student(
            name="Синтетический ученик Linux", user_id=learner_user.id,
            mentor_id=creator.id, is_active=True,
        )
        db.session.add(student)
        db.session.flush()
        db.session.add(Enrollment(
            student_id=learner_user.id, tutor_id=creator.id,
            subject="Информатика", status="active",
        ))

        linked_learners = []
        for index in range(1, 4):
            learner = User(
                username=f"synthetic_graph_learner_{index}",
                email=f"synthetic-graph-{index}@adaptive-lab.example.test",
                role="student", is_active=True,
            )
            learner.set_password(SYNTHETIC_DEFAULT_PASSWORDS[learner.username])
            db.session.add(learner)
            db.session.flush()
            profile = Student(
                name=f"Синтетический графовый ученик {index}", user_id=learner.id,
                mentor_id=teacher_user.id, lessons_balance=5, is_active=True,
            )
            db.session.add(profile)
            db.session.flush()
            db.session.add(Enrollment(
                student_id=learner.id, tutor_id=teacher_user.id,
                subject="Информатика", status="active",
            ))
            linked_learners.append((learner, profile))

        template = LearningTrajectory(
            is_template=True, student_id=None, created_by_user_id=creator.id,
            title="Графы: оптимальные пути · synthetic master",
            subject="Информатика", description="Изолированный синтетический материал; не является банком ЕГЭ.",
            learning_goal="Находить минимальную стоимость маршрута, учитывать равные оптимумы и отличать недостижимость от нулевой стоимости.",
            expected_result="Ученик сравнивает допустимые пути на новых конечных графах и объясняет, какие случаи проверены.",
            current_version=1, default_lesson_duration=60, status="active",
        )
        db.session.add(template)
        db.session.flush()
        copy = LearningTrajectory(
            is_template=False, student_id=student.student_id, parent_course_id=template.course_id,
            created_by_user_id=creator.id,
            title="Индивидуальная программа · графы",
            subject="Информатика",
            description="Синтетическая индивидуальная копия для локальной приёмки Adaptive Learning V1.",
            learning_goal="[AI_LAB_TUTOR_CORE3:ege-2027:v1] Находить минимальную стоимость маршрута и обосновывать ответ на новых графах.",
            expected_result="Ученик рассчитывает минимальную стоимость на конечном варианте и отмечает, если пути нет.",
            current_version=1, default_lesson_duration=60, status="active",
        )
        db.session.add(copy)
        db.session.flush()

        module = TrajectoryModule(
            course_id=copy.course_id, title="Оптимальные пути в графах",
            description="Практикум с разными схемами связности и неоднозначностью кратчайшего маршрута.",
            learning_result="Находит минимальную стоимость пути; не требует единственного маршрута, когда оптимальных маршрутов несколько.",
            order_index=1,
        )
        skill = ExamSkill(
            title="Графы: оптимальные пути", subject="Информатика", topic="Графы",
            topic_code="ege.inf.graph.optimal-paths.v1", is_active=True,
            mastery_criteria=[{
                "key": "minimum_cost", "label": "Находит минимальную стоимость маршрута",
                "evidence": "Ответ совпадает с независимым расчётом стоимости на конкретном графе; альтернативный маршрут допустим.",
            }, {
                "key": "reachability", "label": "Определяет достижимость между вершинами",
                "evidence": "Ответ различает отсутствие пути и путь с нулевой стоимостью на конкретном графе.",
            }],
        )
        db.session.add_all([module, skill])
        db.session.flush()

        master_module = TrajectoryModule(
            course_id=template.course_id, title="Маршруты и связность",
            description="Учебная последовательность: модель графа → сравнение стоимостей → проверка достижимости.",
            learning_result="Ученик суммирует веса допустимых маршрутов, сравнивает альтернативы и сообщает об отсутствии пути.",
            order_index=1,
        )
        db.session.add(master_module)
        db.session.flush()
        master_lesson_specs = [
            {
                "key": "route_cost", "order": 1,
                "topic": "Минимальная стоимость пути: сравнение маршрутов",
                "objective": "Суммировать веса рёбер и выбрать маршрут с минимальной общей стоимостью.",
                "content": "Сначала выписать допустимые маршруты, затем отдельно сложить веса каждого ребра и сравнить итоговые суммы.",
                "homework": "На новом графе сравнить две цепочки и записать минимальную стоимость, сохраняя вычисления.",
                "prerequisite": "Складывает веса рёбер заданного маршрута",
                "exercises": [
                    {"key": "classwork", "number": 9911, "kind": "classwork", "criterion": "minimum_cost",
                     "title": "Классная · два равных оптимальных пути",
                     "prompt": "Рёбра: A–B=2, B–D=4, A–C=3, C–D=3, A–D=7. Найдите минимальную стоимость A→D. Допустимы разные оптимальные маршруты.", "answer": "6"},
                    {"key": "homework", "number": 9912, "kind": "homework", "criterion": "minimum_cost",
                     "title": "Домашняя · сравнение маршрутов",
                     "prompt": "Рёбра: P–Q=4, Q–R=2, P–R=9, P–S=3, S–R=4. Укажите минимальную стоимость P→R.", "answer": "6"},
                ],
            },
            {
                "key": "equal_optima", "order": 2,
                "topic": "Равные оптимумы и альтернативные маршруты",
                "objective": "Принимать несколько разных маршрутов, если их суммарная стоимость минимальна.",
                "content": "Сравнить прямые и составные маршруты; маршрут как последовательность вершин не путать с его стоимостью.",
                "homework": "Найти все минимальные стоимости в заданной схеме и не требовать единственного оптимального пути.",
                "prerequisite": "Сравнивает суммы весов допустимых маршрутов",
                "exercises": [
                    {"key": "tie_classwork", "number": 9914, "kind": "classwork", "criterion": "minimum_cost",
                     "title": "Классная · альтернативные кратчайшие пути",
                     "prompt": "Рёбра: A–B=3, B–D=5, A–C=2, C–D=6, A–D=9. Найдите минимальную стоимость A→D.", "answer": "8"},
                    {"key": "tie_homework", "number": 9915, "kind": "homework", "criterion": "minimum_cost",
                     "title": "Домашняя · равенство стоимости двух цепочек",
                     "prompt": "Рёбра: A–B=2, B–D=5, A–C=4, C–D=3, A–D=8. Найдите минимальную стоимость A→D.", "answer": "7"},
                ],
            },
            {
                "key": "reachability", "order": 3,
                "topic": "Достижимость, отсутствие пути и нулевая стоимость",
                "objective": "Отличать недостижимость от существующего маршрута с нулевой стоимостью.",
                "content": "Сначала проверить связность вершин, и только при существовании пути вычислять его стоимость. Нулевая стоимость ребра не означает отсутствия ребра.",
                "homework": "Проверить достижимость в новой схеме и отдельно рассмотреть маршрут с ребром нулевого веса.",
                "prerequisite": "Проверяет связность до сравнения стоимостей",
                "exercises": [
                    {"key": "unreachable_classwork", "number": 9916, "kind": "classwork", "criterion": "reachability",
                     "title": "Классная · вершины в разных компонентах",
                     "prompt": "Есть только рёбра X–Y=1 и Z–W=2. Укажите минимальную стоимость X→W или ответьте «нет пути».", "answer": "нет пути"},
                    {"key": "zero_homework", "number": 9917, "kind": "homework", "criterion": "minimum_cost",
                     "title": "Домашняя · существующий маршрут нулевой стоимости",
                     "prompt": "Рёбра: L–M=0, L–N=2, N–M=1. Найдите минимальную стоимость L→M.", "answer": "0"},
                ],
            },
        ]
        criterion_labels = {
            "minimum_cost": "Находит минимальную стоимость маршрута",
            "reachability": "Определяет достижимость между вершинами",
        }
        master_lesson_ids = []
        master_tasks = []
        for lesson_spec in master_lesson_specs:
            master_lesson = Lesson(
                student_id=None, learning_trajectory_id=template.course_id,
                course_module_id=master_module.module_id, course_order_index=lesson_spec["order"],
                status="planned", duration=60, topic=lesson_spec["topic"],
                lesson_format="Практикум", content=lesson_spec["content"], homework=lesson_spec["homework"],
            )
            master_lesson.skills.append(skill)
            db.session.add(master_lesson)
            db.session.flush()
            master_lesson_ids.append(master_lesson.lesson_id)

            lesson_tasks = []
            for spec in lesson_spec["exercises"]:
                source_binding = {
                    "contract": "boostudy.synthetic-course-source-skill.v1",
                    "source_course_id": template.course_id,
                    "source_course_version": int(template.current_version or 1),
                    "source_lesson_id": master_lesson.lesson_id,
                    "source_lesson_order_index": master_lesson.course_order_index,
                    "skill_id": f"exam-skill:{skill.skill_id}", "topic_code": skill.topic_code,
                    "criterion_id": spec["criterion"],
                    "pedagogical_status": "synthetic_draft_not_expert_approved",
                    "task_fingerprint": "pending",
                }
                task = Tasks(
                    task_number=spec["number"], bank_category="synthetic_adaptive_draft",
                    bank_origin="manual", source_name="BooStudy synthetic adaptive lab",
                    source_key=f"boostudy.synthetic.adaptive-v1/graph-teacher-product/{spec['key']}",
                    content_html=f"<h3>{spec['title']}</h3><p>{spec['prompt']}</p>", answer=spec["answer"],
                    created_by_id=creator.id, is_active=True,
                    answer_spec={"type": "short_answer", "grading_mode": "exact",
                                 "synthetic_course_skill_binding": source_binding},
                )
                db.session.add(task)
                db.session.flush()
                master_tasks.append((spec, task))
                task.answer_spec = {"type": "short_answer", "grading_mode": "exact",
                                    "synthetic_course_skill_binding": {
                                        **source_binding, "task_fingerprint": _task_fingerprint(task)}}
                lesson_tasks.append((spec, task))
                db.session.add(LessonTask(
                    lesson_id=master_lesson.lesson_id, task_id=task.task_id,
                    assignment_type=spec["kind"], status="pending",
                    is_visible_to_student=True, is_answer_visible_to_student=False,
                    notes="Synthetic draft; not expert-approved.",
                ))

            criteria = sorted({spec["criterion"] for spec, _ in lesson_tasks})
            master_scenario = {
                "contract": "boostudy.lesson-pedagogy.v1",
                "status": "synthetic_draft_not_expert_approved",
                "objective": {"id": f"lesson-{master_lesson.lesson_id}-{lesson_spec['key']}",
                              "text": lesson_spec["objective"],
                              "skill_id": f"exam-skill:{skill.skill_id}"},
                "criteria": [{"id": criterion, "label": criterion_labels[criterion],
                              "observable_outcome": ("Верно сравнивает стоимость допустимых путей; альтернативный оптимум допустим."
                                                     if criterion == "minimum_cost" else
                                                     "Различает отсутствие пути и путь, стоимость которого равна нулю."),
                              "assessment_method": "platform_exact_answer",
                              "evidence_limitations": "Проверяются только указанные конечные графы.",
                              "exercise_ids": [f"task:{task.task_id}" for spec, task in lesson_tasks
                                               if spec["criterion"] == criterion]}
                             for criterion in criteria],
                "prerequisites": [{"id": f"prerequisite_{lesson_spec['key']}",
                                   "label": lesson_spec["prerequisite"], "skill_id": None,
                                   "registration_status": "unmapped_micro_skill",
                                   "status": "unknown_before_lesson",
                                   "diagnostic_method": "Короткий входной пример без подсказки."}],
                "segments": [
                    {"id": "goal_and_model", "title": "Цель и модель графа", "minutes": 10, "mandatory": True},
                    {"id": "worked_examples", "title": "Разбор маршрутов", "minutes": 20, "mandatory": True},
                    {"id": "independent_practice", "title": "Самостоятельная практика", "minutes": 20, "mandatory": True},
                    {"id": "exit_check", "title": "Итоговая проверка", "minutes": 10, "mandatory": True},
                ],
                "exercises": [{"id": f"task:{task.task_id}", "source_type": "platform_task",
                               "task_id": task.task_id, "title": spec["title"], "topic_code": skill.topic_code,
                               "criterion_ids": [spec["criterion"]], "segment_id": "independent_practice",
                               "assessment_method": "platform_exact_answer", "role": spec["kind"],
                               "verification_scope": "Проверяется только показанный граф и указанная пара вершин.",
                               "evidence_limitations": "Одна конечная проверка не подтверждает общее освоение навыка.",
                               "selection_priority": 5}
                              for spec, task in lesson_tasks],
                "assessment_limitations": [
                    "Точные ответы подтверждают результат только для этих графов.",
                    "Самостоятельность и устойчивое освоение не выводятся из одного ответа.",
                ],
            }
            master_lesson.studio_scenario = json.dumps(master_scenario, ensure_ascii=False)

        lesson = Lesson(
            student_id=student.student_id, learning_trajectory_id=copy.course_id,
            course_module_id=module.module_id, course_order_index=1,
            status="planned", duration=60,
            topic="Оптимальные пути: стоимость, альтернативы и недостижимость",
            lesson_format="Практикум",
            content=("Сравнить несколько маршрутов по суммарному весу рёбер. "
                     "Различать стоимость пути и сам маршрут; отдельно проверить случай отсутствия пути."),
            homework="Решить новый графовый вариант самостоятельно и записать только минимальную стоимость либо «нет пути».",
        )
        lesson.skills.append(skill)
        db.session.add(lesson)
        db.session.flush()

        exercise_specs = [
            {
                "key": "classwork", "number": 9901, "kind": "classwork",
                "title": "Классная работа · равные оптимальные маршруты",
                "prompt": "Рёбра имеют веса A–B=2, B–D=4, A–C=3, C–D=3, A–D=7. Укажите минимальную стоимость пути A→D. Возможны разные оптимальные маршруты.",
                "answer": "6",
            },
            {
                "key": "homework", "number": 9902, "kind": "homework",
                "title": "Домашняя работа · сравнение маршрутов",
                "prompt": "Рёбра имеют веса P–Q=4, Q–R=2, P–R=9, P–S=3, S–R=4. Укажите минимальную стоимость пути P→R.",
                "answer": "6",
            },
            {
                "key": "diagnostic", "number": 9903, "kind": "diagnostic",
                "title": "Диагностика · проверка недостижимой вершины",
                "prompt": "Есть только рёбра X–Y=1 и Z–W=2. Укажите минимальную стоимость пути X→W или ответьте «нет пути».",
                "answer": "нет пути",
            },
        ]
        tasks = []
        from app.ai_lab.platform_homework import _task_fingerprint
        for spec in exercise_specs:
            binding = {
                "contract": "boostudy.synthetic-course-skill.v1",
                "course_id": copy.course_id, "course_version": 1, "lesson_id": lesson.lesson_id,
                "skill_id": f"exam-skill:{skill.skill_id}", "topic_code": skill.topic_code,
                "criterion_id": "minimum_cost", "pedagogical_status": "synthetic_draft_not_expert_approved",
                "task_fingerprint": "pending",
            }
            task = Tasks(
                task_number=spec["number"], bank_category="synthetic_adaptive_draft",
                bank_origin="manual", source_name="BooStudy synthetic adaptive lab",
                source_key=f"boostudy.synthetic.adaptive-v1/graph-optimal-paths/{spec['key']}",
                content_html=f"<h3>{spec['title']}</h3><p>{spec['prompt']}</p>",
                answer=spec["answer"], created_by_id=creator.id, is_active=True,
                answer_spec={"type": "short_answer", "grading_mode": "exact", "synthetic_course_skill_binding": binding},
            )
            db.session.add(task)
            db.session.flush()
            task.answer_spec = {
                "type": "short_answer", "grading_mode": "exact",
                "synthetic_course_skill_binding": {**binding, "task_fingerprint": _task_fingerprint(task)},
            }
            tasks.append((spec, task))

        scenario = {
            "contract": "boostudy.lesson-pedagogy.v1",
            "status": "synthetic_draft_not_expert_approved",
            "objective": {
                "id": f"lesson-{lesson.lesson_id}-minimum-cost",
                "text": "Сравнивать суммарные веса маршрутов и определять минимальную стоимость, допуская несколько оптимальных маршрутов.",
                "skill_id": f"exam-skill:{skill.skill_id}",
            },
            "criteria": [{
                "id": "minimum_cost", "label": "Минимальная стоимость пути",
                "observable_outcome": "Верно определяет минимальную стоимость; не подменяет стоимость одним фиксированным маршрутом.",
                "assessment_method": "platform_exact_answer",
                "evidence_limitations": "Проверяются только перечисленные конечные графы; универсальная корректность не доказывается.",
                "exercise_ids": [f"task:{task.task_id}" for _, task in tasks],
            }],
            "prerequisites": [{
                "id": "sum_edge_weights", "label": "Складывает веса рёбер заданного маршрута",
                "skill_id": None, "registration_status": "unmapped_micro_skill",
                "status": "unknown_before_lesson", "diagnostic_method": "Короткий входной вопрос без подсказки.",
            }],
            "segments": [
                {"id": "goal_and_model", "title": "Цель и модель графа", "minutes": 10, "mandatory": True},
                {"id": "worked_examples", "title": "Сравнение маршрутов с разбором", "minutes": 20, "mandatory": True},
                {"id": "independent_practice", "title": "Самостоятельная практика", "minutes": 20, "mandatory": True},
                {"id": "exit_check", "title": "Итоговая проверка", "minutes": 10, "mandatory": True},
            ],
            "exercises": [{
                "id": f"task:{task.task_id}", "source_type": "platform_task", "task_id": task.task_id,
                "title": spec["title"], "topic_code": skill.topic_code,
                "criterion_ids": ["minimum_cost"], "segment_id": "independent_practice",
                "assessment_method": "platform_exact_answer", "role": spec["kind"],
                "verification_scope": "Только показанный граф и конкретная целевая пара вершин.",
                "evidence_limitations": "Ответ на один вариант не подтверждает освоение навыка.",
                "selection_priority": 10 if spec["key"] == "diagnostic" else 5,
            } for spec, task in tasks],
            "assessment_limitations": [
                "Точный ответ для перечисленных графов не является доказательством корректности для произвольного графа.",
                "Освоение не выводится из одной правильной попытки; самостоятельность фиксируется отдельно.",
            ],
        }
        lesson.studio_scenario = json.dumps(scenario, ensure_ascii=False)
        for spec, task in tasks:
            if spec["kind"] in {"classwork", "homework", "diagnostic"}:
                db.session.add(LessonTask(
                    lesson_id=lesson.lesson_id, task_id=task.task_id,
                    assignment_type="homework" if spec["kind"] == "diagnostic" else spec["kind"],
                    status="pending",
                    is_visible_to_student=spec["kind"] != "diagnostic",
                    is_answer_visible_to_student=False,
                    notes="Synthetic draft; not expert-approved.",
                ))
        db.session.add(LearningItem(
            course_id=copy.course_id, module_id=module.module_id, lesson_id=lesson.lesson_id,
            skill_id=skill.skill_id, item_type="lesson", title=lesson.topic,
            status="planned", order_index=1,
            metadata_json={"provenance": "synthetic-linux-seed-v1", "expert_approved": False},
        ))
        db.session.commit()

        ids = {
            "actor_user_ids": [creator.id, teacher_user.id],
            "task_author_ids": [creator.id, teacher_user.id],
            "teacher_user_id": teacher_user.id,
            "student_user_ids": [learner_user.id, *[item[0].id for item in linked_learners]],
            "student_ids": [student.student_id, *[item[1].student_id for item in linked_learners]],
            "template_course_ids": [template.course_id],
            "course_copy_ids": [copy.course_id],
            "lesson_ids": [lesson.lesson_id],
            "template_lesson_ids": master_lesson_ids,
            "skill_ids": [skill.skill_id],
            "task_ids": [task.task_id for _, task in tasks] + [task.task_id for _, task in master_tasks],
        }
        manifest = {
            "format": MANIFEST_FORMAT, "synthetic": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "db_identity": _file_identity(db_path), "ids": ids,
            "provenance": "Fresh SQLAlchemy create_all baseline plus explicit synthetic draft seed; no imported records.",
            "knowledge_base_seed_version": KNOWLEDGE_DATA_VERSION,
            "migration_state": "fresh-current-model-synthetic-schema; no historical Alembic chain applied",
            "expert_approved": False,
        }

    manifest_path = _manifest_path(db_path)
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary_manifest, 0o600)
    temporary_manifest.replace(manifest_path)
    checked = _validate_manifest_and_database(db_path)
    return checked


def prepare(raw_path: str) -> None:
    db_path = _validated_path(raw_path, must_exist=False)
    try:
        manifest = _seed_database(db_path)
    except Exception:
        if db_path.parent.exists() and db_path.parent.name.startswith(SAFE_DIRECTORY_PREFIX):
            import shutil

            shutil.rmtree(db_path.parent)
        raise
    ids = manifest["ids"]
    print(f"Synthetic база создана и проверена: {db_path}")
    print(f"Creator={ids['actor_user_ids'][0]} · student={ids['student_ids'][0]} · copy={ids['course_copy_ids'][0]} · lesson={ids['lesson_ids'][0]}")
    print("Статус учебных материалов: synthetic draft; экспертное утверждение отсутствует.")


def reset_credentials(raw_path: str, username: str) -> None:
    db_path = _validated_path(raw_path, must_exist=True)
    manifest = _validate_manifest_and_database(db_path)
    if username not in SYNTHETIC_DEFAULT_PASSWORDS:
        raise RuntimeError("Разрешено восстановить только перечисленные synthetic-аккаунты.")

    ids = manifest["ids"]
    safe_ids = {int(value) for key in ("actor_user_ids", "student_user_ids") for value in ids[key]}
    environment = _safe_environment(db_path, manifest)
    os.environ.clear()
    os.environ.update(environment)

    from app import create_app, db
    from app.models import User

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user or user.id not in safe_ids or user.role != SYNTHETIC_ACCOUNT_ROLES[username]:
            raise RuntimeError("Учётная запись не входит в synthetic allowlist этой базы.")
        user.set_password(SYNTHETIC_DEFAULT_PASSWORDS[username])
        db.session.commit()
    print(f"Восстановлен пароль только для synthetic-аккаунта {username}; секрет не выводится.")


def refresh_task_author_allowlist(raw_path: str) -> None:
    """Allow the manifest's verified synthetic tutor to author lab exercises."""
    db_path = _validated_path(raw_path, must_exist=True)
    manifest = _validate_manifest_and_database(db_path)
    ids = manifest["ids"]
    teacher_user_id = int(ids.get("teacher_user_id") or 0)
    if teacher_user_id not in {int(value) for value in ids["actor_user_ids"]}:
        raise RuntimeError("Synthetic-преподаватель не входит в проверенный список акторов.")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT username, role FROM Users WHERE id = ?", (teacher_user_id,)
        ).fetchone()
    if (not row or row[0] not in SYNTHETIC_ACCOUNT_ROLES
            or SYNTHETIC_ACCOUNT_ROLES[row[0]] not in {"teacher", "tutor"}
            or row[1] != SYNTHETIC_ACCOUNT_ROLES[row[0]]):
        raise RuntimeError("Запись преподавателя не подтверждена как разрешённый synthetic-аккаунт.")

    ids["task_author_ids"] = sorted({
        *[int(value) for value in ids.get("task_author_ids", [])
          if int(value) in {int(actor_id) for actor_id in ids["actor_user_ids"]}],
        teacher_user_id,
    })
    manifest_path = _manifest_path(db_path)
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(temporary_manifest, 0o600)
    temporary_manifest.replace(manifest_path)
    _validate_manifest_and_database(db_path)
    print("Synthetic task-author allowlist обновлён; база и пароли не изменены.")


def serve(raw_path: str, port: int) -> None:
    if not 1 <= port <= 65535:
        raise RuntimeError("Порт должен быть числом от 1 до 65535.")
    db_path = _validated_path(raw_path, must_exist=True)
    manifest = _validate_manifest_and_database(db_path)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Permit a safe restart after the prior localhost listener left TCP connections
        # in TIME_WAIT. A live listener still prevents this bind and is never replaced.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"Порт 127.0.0.1:{port} занят; существующий процесс не будет остановлен.") from error

    environment = _safe_environment(db_path, manifest, port)
    os.environ.clear()
    os.environ.update(environment)

    from app import create_app, db
    from sqlalchemy import text

    app = create_app()
    with app.app_context():
        db.session.execute(text("SELECT 1"))
        if app.config.get("AI_LAB_SAFE_DB_PATH") != str(db_path):
            raise RuntimeError("Фабрика Flask выбрала не ту synthetic SQLite.")
    print(f"AI Lab synthetic safe mode: {db_path} · identity={environment['AI_LAB_SAFE_DB_FILE_ID']}")
    print(f"Allowlist actor={environment['AI_LAB_PLATFORM_TEST_ACTOR_IDS']} student={environment['AI_LAB_PLATFORM_TEST_USER_IDS']} copy={environment['AI_LAB_SYNTHETIC_COURSE_COPY_IDS']}")
    print(f"Serving only on http://127.0.0.1:{port}; bootstrap/workers/reloader disabled.")
    app.run(host="127.0.0.1", port=port, use_reloader=False, threaded=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="create a new isolated synthetic database and profile")
    prepare_parser.add_argument("--db-path", required=True)
    reset_parser = subparsers.add_parser(
        "reset-credentials",
        help="restore a seed password for one explicitly allowlisted synthetic account",
    )
    reset_parser.add_argument("--db-path", required=True)
    reset_parser.add_argument("--username", required=True, choices=sorted(SYNTHETIC_DEFAULT_PASSWORDS))
    authors_parser = subparsers.add_parser(
        "refresh-task-author-allowlist",
        help="allow only the verified synthetic tutor to author local lab exercises",
    )
    authors_parser.add_argument("--db-path", required=True)
    serve_parser = subparsers.add_parser("serve", help="validate and start the isolated local backend")
    serve_parser.add_argument("--db-path", required=True)
    serve_parser.add_argument("--port", type=int, default=5185)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        prepare(arguments.db_path)
    elif arguments.command == "reset-credentials":
        reset_credentials(arguments.db_path, arguments.username)
    elif arguments.command == "refresh-task-author-allowlist":
        refresh_task_author_allowlist(arguments.db_path)
    else:
        serve(arguments.db_path, arguments.port)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Adaptive Lab безопасно остановлен: {error}", file=sys.stderr)
        raise SystemExit(2)
