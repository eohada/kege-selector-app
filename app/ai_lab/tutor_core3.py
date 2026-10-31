"""Local synthetic Tutor Core 3.0 EGE-2027 learning-chain demonstration."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.ai_lab.exam_revisions import SKILLS, revision_manifest, seed_revision_bindings
from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION, validate_evidence_event
from core.db_models import (
    AiLabExamTaskBinding,
    AiLabKnowledgeEntry,
    AiLabKnowledgeReviewEvent,
    AiLabKnowledgeSource,
    AiLabKnowledgeVersion,
    AiLabTutorDemo,
    AiLabTutorDemoEvent,
    ExamSkill,
    LearningTrajectory,
    Lesson,
    Student,
    TrajectoryModule,
    User,
    db,
)


DEMO_KEY = "ege-2027-first-chain"
DEMO_VERSION = 1
SEED_VERSION = "boostudy.tutor-core3.synthetic-ege2027.v1"
COURSE_TOKEN = "[AI_LAB_TUTOR_CORE3:ege-2027:v1]"
SYNTHETIC_USERNAME = "synthetic_tutorcore3_ege2027"
KNOWLEDGE_KEYS = (
    "ege.inf.ip-prefix-mask.v1",
    "ege.inf.sql-relational-query.v1",
    "ege.inf.spreadsheet-aggregates.v1",
    "ege.inf.task23-graph-algorithms.v1",
    "ege.inf.task27-answer-format.v1",
)


class TutorCore3Error(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


LESSON_SPECS: tuple[dict[str, Any], ...] = (
    {
        "module": "Адресация и трассировка",
        "title": "IPv4: маска и границы сети",
        "topic": "IPv4 и CIDR",
        "skill_codes": ("ege.inf.ipv4.subnet-mask.v1",),
        "content": "На синтетических адресах разобрать размер блока по префиксу, адрес сети и broadcast. Сопоставить финальное задание 13 ЕГЭ-2026 с проектным заданием 10 ЕГЭ-2027.",
        "homework": "Для двух новых префиксов найти сеть и границы блока; решения сверить независимым расчётом.",
    },
    {
        "module": "Адресация и трассировка",
        "title": "Трассировка выполнения алгоритма",
        "topic": "Алгоритмизация",
        "skill_codes": ("ege.inf.algorithm.execution-trace.v1",),
        "content": "Пошагово фиксировать значения переменных, ветвления и цикл; проектная редакция 2027 меняет тему задания 13.",
        "homework": "Составить таблицу трассировки и отдельно сверить итоговый вывод.",
    },
    {
        "module": "Графовые алгоритмы",
        "title": "Чтение ориентированного графа",
        "topic": "Вершины, рёбра и направление",
        "skill_codes": ("ege.inf.graph.representation.v1",),
        "content": "Перевести схему в список вершин, направленных рёбер и весов до выбора алгоритма. Не добавлять обратное ребро без основания.",
        "homework": "Для нового графа восстановить список рёбер и проверить его по схеме.",
    },
    {
        "module": "Графовые алгоритмы",
        "title": "Оптимальный путь",
        "topic": "Оптимизация пути в графе",
        "skill_codes": ("ege.inf.graph.optimal-paths.v1",),
        "content": "Уточнить критерий min/max, сложить веса каждого маршрута и сравнить допустимые варианты.",
        "homework": "Найти путь с заданным критерием и показать сравнение альтернатив.",
    },
    {
        "module": "Графовые алгоритмы",
        "title": "Подсчёт путей в DAG",
        "topic": "Динамическое программирование по графу",
        "skill_codes": ("ege.inf.graph.dag-path-count.v1",),
        "content": "В топологическом порядке накапливать количество путей; для небольшого графа дополнительно перечислить маршруты.",
        "homework": "Решить один небольшой DAG двумя способами: динамически и явным перечислением.",
    },
    {
        "module": "Проверка результата",
        "title": "Задание 27: формат ответа по редакции",
        "topic": "Два вычисляемых значения и формат записи",
        "skill_codes": ("ege.inf.task27.answer-format.v1",),
        "content": "Отделить вычисление двух величин от их оформления. Сверять год и статус документа: у финальной редакции 2026 и проекта 2027 форматы различаются.",
        "homework": "Вычислить две величины и записать ответ строго по выбранной редакции задания.",
    },
)


def _require_local_lab() -> None:
    from app.ai_lab.provider import is_local_ai_lab_enabled

    if not is_local_ai_lab_enabled():
        raise TutorCore3Error("local_lab_required", "Демонстрация доступна только в локальной AI Lab.", 403)


def _get_or_create_student() -> tuple[User, Student, bool]:
    user = User.query.filter_by(username=SYNTHETIC_USERNAME).first()
    created = False
    if user is None:
        user = User(
            username=SYNTHETIC_USERNAME,
            email=None,
            password_hash=None,
            role="student",
            is_active=False,
            about_me="Неактивный synthetic-only профиль Tutor Core 3.0; вход и реальные учебные данные отсутствуют.",
        )
        db.session.add(user)
        db.session.flush()
        created = True
    elif user.role != "student" or user.is_active or user.password_hash:
        raise TutorCore3Error(
            "synthetic_identity_conflict",
            "Имя локального synthetic-профиля уже занято активной или несовместимой учётной записью; она не изменена.",
            409,
        )

    student = Student.query.filter_by(user_id=user.id).first()
    if student is None:
        student = Student(
            user_id=user.id,
            name="Синтетический профиль Tutor Core 3.0",
            email=None,
            phone=None,
            category="ai_lab_synthetic",
            school_class=11,
            goal_text="Только демонстрация локального адаптивного цикла ЕГЭ-2027.",
            notes="Фиктивные события Tutor Core 3.0; не является учеником платформы.",
        )
        db.session.add(student)
        db.session.flush()
        created = True
    elif (student.name != "Синтетический профиль Tutor Core 3.0"
          or student.category != "ai_lab_synthetic"):
        raise TutorCore3Error("synthetic_profile_conflict", "Профиль с таким ID не соответствует synthetic-only контракту; запись не изменена.", 409)
    return user, student, created


def _get_skills() -> dict[str, ExamSkill]:
    result: dict[str, ExamSkill] = {}
    for code in SKILLS:
        matches = ExamSkill.query.filter_by(topic_code=code).all()
        if len(matches) != 1:
            raise TutorCore3Error("skill_seed_missing", f"Для демонстрации ожидается ровно один навык {code}.", 409)
        result[code] = matches[0]
    return result


def _create_course(*, title: str, creator_id: int, student_id: int | None,
                   is_template: bool, parent_course_id: int | None,
                   skills: dict[str, ExamSkill]) -> LearningTrajectory:
    course = LearningTrajectory(
        title=title,
        subject="Информатика",
        description=(
            f"{COURSE_TOKEN} Синтетический шестизанятийный маршрут по темам проектов ЕГЭ-2027. "
            "Материалы 2027 года помечены как проект ФИПИ. Не изменяет курс 3 и не является готовой программой подготовки."
        ),
        learning_goal="Показать связь редакции экзамена, навыков, уроков, синтетических свидетельств и осторожного предложения.",
        expected_result="Преподаватель видит основание, ограничение проверки и отдельный предпросмотр адаптации.",
        is_template=is_template,
        parent_course_id=parent_course_id,
        student_id=student_id,
        created_by_user_id=creator_id,
        current_version=1,
        default_lesson_duration=60,
        lessons_per_week=None,
        lesson_duration_minutes=60,
        status="active",
    )
    db.session.add(course)
    db.session.flush()

    modules_by_title: dict[str, TrajectoryModule] = {}
    for index, spec in enumerate(LESSON_SPECS, start=1):
        module_title = spec["module"]
        module = modules_by_title.get(module_title)
        if module is None:
            module = TrajectoryModule(
                course_id=course.course_id,
                title=module_title,
                description=f"{COURSE_TOKEN} Synthetic-only раздел.",
                learning_result="Различает предметный навык, формат редакции и проверяемое свидетельство.",
                order_index=len(modules_by_title) + 1,
            )
            db.session.add(module)
            db.session.flush()
            modules_by_title[module_title] = module
        lesson = Lesson(
            student_id=student_id,
            learning_trajectory_id=course.course_id,
            course_module_id=module.module_id,
            lesson_type="regular",
            duration=60,
            course_order_index=index * 10,
            status="planned",
            topic=spec["title"],
            lesson_format="Теория + практика",
            content=spec["content"],
            homework=spec["homework"],
            homework_status="not_assigned",
            materials=[],
        )
        lesson.skills.extend(skills[code] for code in spec["skill_codes"])
        db.session.add(lesson)
    db.session.flush()
    return course


def _graph_fixture_results() -> tuple[dict[str, Any], dict[str, Any]]:
    expected = {"A->B", "A->C", "B->D", "C->D", "B->C"}
    initial = {"A->B", "A->C", "B->D", "C->D", "B->C", "C->B"}
    corrected = {"A->B", "A->C", "B->D", "C->D", "B->C"}
    return (
        {"submitted_edges": sorted(initial), "expected_edges": sorted(expected), "matches": initial == expected},
        {"submitted_edges": sorted(corrected), "expected_edges": sorted(expected), "matches": corrected == expected},
    )


def _fixture_event(*, event_key: str, index: int, lesson: Lesson, skill: ExamSkill,
                   student_id: int, course_id: int, fixture_result: dict[str, Any]) -> dict[str, Any]:
    passed = bool(fixture_result["matches"])
    event_id = f"tutorcore3:{DEMO_KEY}:graph-reading:{event_key}"
    status = "met" if passed else "not_met"
    reason = (
        "После подсказки направление стрелок записано верно; независимый перенос ещё не проверен."
        if passed else "В ответ добавлено обратное ребро C→B, которого нет в схеме."
    )
    return validate_evidence_event({
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": event_id,
        "subject_id": f"synthetic-tutorcore3:{student_id}",
        "source_module": "ai_tutor_core",
        "source_record_id": f"tutorcore3-demo:{DEMO_KEY}:lesson:{lesson.lesson_id}:event:{index}",
        "occurred_at": datetime(2026, 10, index, 12, tzinfo=timezone.utc).isoformat(),
        "evidence_status": "technical_confirmed",
        "assignment": {"id": f"tutorcore3-graph-reading-{event_key}", "version": DEMO_VERSION},
        "course_context": {"course_id": f"synthetic-boostudy-course-{course_id}", "course_version": 1},
        "topic_ids": [f"boostudy-module:{lesson.course_module_id}"],
        "skill_ids": [f"exam-skill:{skill.skill_id}"],
        "error_codes": [] if passed else ["graph_edge_direction"],
        "limitations": [
            "Фиктивное сценарное событие создано только для Tutor Core 3.0; оно не относится к реальному ученику.",
            "Сравнение проверило конечный список рёбер одного синтетического графа; это не доказывает владение графами в целом.",
            "Использован локальный точный comparator для fixture, а не Docker Code Judge и не GigaChat.",
            "Успех после подсказки не считается самостоятельным переносом навыка.",
        ],
        "outcome": {"score": int(passed), "maximum": 1, "status": status},
        "criteria": [{
            "criterion_id": "directed-edge-list",
            "skill_id": f"exam-skill:{skill.skill_id}",
            "earned": int(passed),
            "maximum": 1,
            "status": status,
            "evidence_status": "technical_confirmed",
            "reason": reason,
            "source_refs": [event_id],
        }],
        "provenance": {
            "source_ref": event_id,
            "method": "fixed_fixture_edge_set_comparator",
        },
    })


def _lesson_payload(course: LearningTrajectory) -> list[dict[str, Any]]:
    lessons = (Lesson.query.filter_by(learning_trajectory_id=course.course_id)
               .order_by(Lesson.course_order_index, Lesson.lesson_id).all())
    return [{
        "lesson_id": lesson.lesson_id,
        "order": lesson.course_order_index,
        "title": lesson.topic or "Урок",
        "duration_minutes": lesson.duration,
        "skills": [{"code": skill.topic_code, "title": skill.title} for skill in lesson.skills],
    } for lesson in lessons]


def _knowledge_payload() -> list[dict[str, Any]]:
    result = []
    for stable_key in KNOWLEDGE_KEYS:
        entry = AiLabKnowledgeEntry.query.filter_by(stable_key=stable_key).first()
        if entry is None:
            continue
        version = (AiLabKnowledgeVersion.query.filter_by(entry_id=entry.id)
                   .order_by(AiLabKnowledgeVersion.version_no.desc()).first())
        if version is None:
            continue
        review = (AiLabKnowledgeReviewEvent.query.filter_by(version_id=version.id)
                  .order_by(AiLabKnowledgeReviewEvent.id.desc()).first())
        sources = []
        for source_key in version.source_refs_json or []:
            source = AiLabKnowledgeSource.query.filter_by(source_key=source_key).order_by(AiLabKnowledgeSource.id.desc()).first()
            if source:
                sources.append({"key": source.source_key, "title": source.title, "status": source.source_status, "url": source.url})
        result.append({
            "stable_key": stable_key,
            "knowledge_ref": f"knowledge:{stable_key}:v{version.version_no}",
            "title": version.title,
            "version": version.version_no,
            "editorial_status": review.decision if review else "draft",
            "source_refs": sources,
            "project_limited": any(source["status"] == "official_project" for source in sources),
        })
    return result


def get_tutor_core3_state() -> dict[str, Any]:
    _require_local_lab()
    demo = db.session.get(AiLabTutorDemo, DEMO_KEY)
    common = {
        "version": "3.0",
        "seed_version": SEED_VERSION,
        "knowledge_version": "boostudy.tutor-core3-knowledge.v1",
        "fipi_2027_status": "project",
        "model_calls": 0,
        "revision_manifest": revision_manifest(),
        "limits": [
            "Два посещения одного синтетического примера не подтверждают самостоятельный перенос.",
            "Курс 3 и его 72 урока не читаются и не изменяются этим демо.",
            "Реальные ученики, задания, GigaChat и Docker Runner не используются.",
            "Симуляция 2 занятий в неделю × 36 недель не записана в параметры исходного курса.",
        ],
    }
    if demo is None:
        return {**common, "seeded": False, "can_seed": True, "demo": None}

    if demo.demo_version != DEMO_VERSION or demo.seed_version != SEED_VERSION:
        raise TutorCore3Error("demo_version_mismatch", "Найдена другая версия синтетического Tutor Core demo; автоматическое обновление запрещено.", 409)
    course = db.session.get(LearningTrajectory, demo.course_id)
    if course is None or course.student_id != demo.student_id or course.is_template:
        raise TutorCore3Error("demo_course_inconsistent", "Синтетическая копия курса отсутствует или не соответствует реестру демо.", 409)
    student = db.session.get(Student, demo.student_id)
    user = db.session.get(User, demo.student_user_id)
    if student is None or user is None or user.is_active or user.password_hash:
        raise TutorCore3Error("demo_student_inconsistent", "Synthetic-профиль отсутствует, активен или имеет пароль; запись не изменена.", 409)

    events = (AiLabTutorDemoEvent.query.filter_by(demo_key=DEMO_KEY)
              .order_by(AiLabTutorDemoEvent.created_at, AiLabTutorDemoEvent.event_id).all())
    parsed_events = [event.event_json for event in events]
    independent = [event for event in parsed_events if event["evidence_event"]["evidence_status"] == "technical_confirmed"
                   and event.get("fixture", {}).get("assisted") is False
                   and event["evidence_event"]["outcome"]["status"] == "met"]
    assisted = [event for event in parsed_events if event.get("fixture", {}).get("assisted") is True
                and event["evidence_event"]["outcome"]["status"] == "met"]
    course_payload = _lesson_payload(course)
    next_lesson = course_payload[3] if len(course_payload) > 3 else None
    state = {
        **common,
        "seeded": True,
        "can_seed": False,
        "demo": {
            "key": DEMO_KEY,
            "version": demo.demo_version,
            "student": {"id": student.student_id, "username": user.username, "synthetic": True, "login_enabled": False},
            "course": {
                "id": course.course_id,
                "template_id": (demo.metadata_json or {}).get("template_course_id"),
                "version": course.current_version,
                "title": course.title,
                "is_template": course.is_template,
                "lessons": course_payload,
            },
            "events": [{
                "event_id": item["evidence_event"]["event_id"],
                "lesson_id": item["evidence_event"]["source_record_id"],
                "prompt": item["fixture"]["prompt"],
                "response": item["fixture"]["response"],
                "expected": item["fixture"]["expected"],
                "score": item["evidence_event"]["outcome"]["score"],
                "maximum": item["evidence_event"]["outcome"]["maximum"],
                "evidence_status": item["evidence_event"]["evidence_status"],
                "assisted": item["fixture"]["assisted"],
                "method": item["evidence_event"]["provenance"]["method"],
                "limitations": item["evidence_event"]["limitations"],
            } for item in parsed_events],
            "independent_skills_demonstrated": sorted({
                skill_id for item in independent for skill_id in item["evidence_event"]["skill_ids"]
            }),
            "skills_demonstrated_after_hint": sorted({
                skill_id for item in assisted for skill_id in item["evidence_event"]["skill_ids"]
            }),
            "recurring_difficulties": [],
            "resolved_in_example": ["Направление рёбер исправлено после подсказки в том же графе."],
            "unsupported_conclusions": [
                "Самостоятельный перенос на новый граф.",
                "Устойчивое затруднение: наблюдался только один синтетический эпизод.",
                "Ошибка алгоритма оптимального пути: такой ответ в демо не проверялся.",
            ],
            "next_lesson": next_lesson,
            "adaptation_preview": {
                "action": "keep_plan_add_brief_independent_diagnostic",
                "text": "В исторической фикстуре 3.0 показана ветвь «сохранить план и добавить короткую проверку». Это демонстрирует форму решения, а не рекомендацию конкретному ученику.",
                "reason": "Фикстура содержит один синтетический ответ с ошибкой и исправление после подсказки на том же примере; данные не описывают реального ученика.",
                "time_allocation": {"total_minutes": 60, "diagnostic_minutes": 8, "planned_lesson_minutes": 52},
                "course_structure_changed": False,
                "teacher_approval_required": True,
                "applied_automatically": False,
            },
            "knowledge": _knowledge_payload(),
        },
    }
    return state


def seed_tutor_core3_demo(actor_user_id: int) -> dict[str, Any]:
    """Create the local synthetic course/event fixture once; never edits course 3."""
    _require_local_lab()
    existing = db.session.get(AiLabTutorDemo, DEMO_KEY)
    if existing is not None:
        state = get_tutor_core3_state()
        return {"created": False, "state": state}

    from app.ai_lab.knowledge_base import ensure_seeded_knowledge_base, ensure_tutor_core3_knowledge

    try:
        ensure_seeded_knowledge_base()
        ensure_tutor_core3_knowledge()
        mapping_result = seed_revision_bindings()
        user, student, identity_created = _get_or_create_student()
        skills = _get_skills()

        template_title = "ЕГЭ-2027 · Tutor Core 3.0 · синтетический мастер-план"
        template = LearningTrajectory.query.filter_by(learning_goal=f"{COURSE_TOKEN} master").first()
        if template is None:
            template = _create_course(
                title=template_title,
                creator_id=int(actor_user_id),
                student_id=None,
                is_template=True,
                parent_course_id=None,
                skills=skills,
            )
            template.learning_goal = f"{COURSE_TOKEN} master"
        elif (not template.is_template or template.student_id is not None or template.title != template_title):
            raise TutorCore3Error("demo_template_conflict", "Найден несовместимый мастер-план с маркером Tutor Core 3.0; он не изменён.", 409)

        copy_title = "ЕГЭ-2027 · Tutor Core 3.0 · синтетический ученик"
        copy = _create_course(
            title=copy_title,
            creator_id=int(actor_user_id),
            student_id=student.student_id,
            is_template=False,
            parent_course_id=template.course_id,
            skills=skills,
        )

        lessons = (Lesson.query.filter_by(learning_trajectory_id=copy.course_id)
                   .order_by(Lesson.course_order_index, Lesson.lesson_id).all())
        graph_lesson = lessons[2]
        graph_skill = skills["ege.inf.graph.representation.v1"]
        first_result, corrected_result = _graph_fixture_results()
        scenario = {
            "prompt": "По схеме со стрелками перечислите рёбра: A→B, A→C, B→D, C→D, B→C.",
            "expected": "A→B, A→C, B→C, B→D, C→D; обратного ребра C→B нет.",
        }
        fixture_events = (
            {
                "key": "initial",
                "result": first_result,
                "assisted": False,
                "response": "A→B, A→C, B→D, C→D, B→C, C→B",
                "expected": scenario["expected"],
            },
            {
                "key": "after-hint",
                "result": corrected_result,
                "assisted": True,
                "response": "A→B, A→C, B→D, C→D, B→C",
                "expected": scenario["expected"],
            },
        )

        db.session.flush()
        demo = AiLabTutorDemo(
            demo_key=DEMO_KEY,
            demo_version=DEMO_VERSION,
            seed_version=SEED_VERSION,
            course_id=copy.course_id,
            student_user_id=user.id,
            student_id=student.student_id,
            metadata_json={
                "synthetic_only": True,
                "template_course_id": template.course_id,
                "student_copy_course_id": copy.course_id,
                "course_token": COURSE_TOKEN,
                "mapping_seed": mapping_result,
                "identity_created": identity_created,
                "teacher_approval_required": True,
                "giga_calls": 0,
            },
        )
        db.session.add(demo)
        db.session.flush()

        for index, fixture in enumerate(fixture_events, start=1):
            event_id = f"tutorcore3:{DEMO_KEY}:graph-reading:{fixture['key']}"
            if AiLabTutorDemoEvent.query.filter_by(event_id=event_id).first() is not None:
                continue
            evidence = _fixture_event(
                event_key=fixture["key"], index=index, lesson=graph_lesson, skill=graph_skill,
                student_id=student.student_id, course_id=copy.course_id,
                fixture_result=fixture["result"],
            )
            db.session.add(AiLabTutorDemoEvent(
                event_id=event_id,
                demo_key=DEMO_KEY,
                scenario_key="directed-graph-reading-v1",
                event_json={
                    "evidence_event": evidence,
                    "fixture": {
                        "prompt": scenario["prompt"],
                        "response": fixture["response"],
                        "expected": fixture["expected"],
                        "assisted": fixture["assisted"],
                        "matches": fixture["result"]["matches"],
                        "checker": "fixed_fixture_edge_set_comparator",
                    },
                },
            ))
        db.session.commit()
    except TutorCore3Error:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        raise TutorCore3Error("demo_seed_failed", f"Синтетический Tutor Core demo не создан: {type(exc).__name__}.", 500) from exc

    state = get_tutor_core3_state()
    return {"created": True, "state": state}

