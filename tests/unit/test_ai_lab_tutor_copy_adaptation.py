import pytest


def _structured_lesson_segments():
    return [
        {"id": "opening", "title": "Цель и исходный вопрос", "minutes": 10, "mandatory": True},
        {"id": "guided_practice", "title": "Практика с разбором", "minutes": 40, "mandatory": False,
         "flexible_minutes": 10, "flexible_reason": "В плане заранее выделено до 10 минут вариативного разбора."},
        {"id": "exit_check", "title": "Итоговая проверка", "minutes": 10, "mandatory": True},
    ]


def _safe_time_plan():
    original = _structured_lesson_segments()
    proposed = [
        dict(original[0]),
        {**original[1], "minutes": 30},
        {"id": "tutor_evidence_check", "title": "Короткая проверка", "minutes": 10,
         "purpose": "Собрать новое наблюдение.", "exercise_id": "practice:synthetic:verified-1", "mandatory": False},
        dict(original[2]),
    ]
    return {
        "status": "redistributed", "lesson_minutes": 60,
        "original_segments": original, "proposed_segments": proposed,
        "cuts": [{"segment_id": "guided_practice", "minutes": 10,
                  "reason": original[1]["flexible_reason"]}],
        "inserted_segment": proposed[2],
    }


def _set_structured_lesson_plan(lesson):
    import json
    skill = next(iter(lesson.skills or []), None)
    if not skill:
        raise AssertionError("Synthetic lesson fixture needs one linked ExamSkill.")
    criteria = skill.mastery_criteria
    if isinstance(criteria, str):
        criteria = json.loads(criteria)
    if not isinstance(criteria, list) or not criteria:
        criteria = [{"key": "synthetic_check", "label": "Проверяет результат на указанном варианте",
                     "evidence": "Ответ совпадает с детерминированным эталоном."}]
        skill.mastery_criteria = criteria
    topic_code = str(skill.topic_code or "ege.inf.synthetic.lesson.v1")
    exercises = []
    structured_criteria = []
    for item in criteria:
        key = str(item["key"])
        exercise_id = f"practice-family:{topic_code}:{key}"
        exercises.append({
            "id": exercise_id, "source_type": "practice_generator", "topic_code": topic_code,
            "criterion_ids": [key], "segment_id": "guided_practice",
            "assessment_method": "deterministic_exact_answer",
            "verification_scope": "Only the generated finite variant.",
            "evidence_limitations": "A checked answer does not establish mastery or independent work.",
            "role": "diagnostic", "selection_priority": 10,
        })
        structured_criteria.append({
            "id": key, "label": str(item.get("label") or key),
            "observable_outcome": str(item.get("evidence") or "Ответ проверен на конкретном варианте."),
            "assessment_method": "deterministic_exact_answer",
            "evidence_limitations": "Проверяется только этот вариант.",
            "exercise_ids": [exercise_id],
        })
    lesson.studio_scenario = json.dumps({
        "contract": "boostudy.lesson-pedagogy.v1",
        "status": "synthetic_draft_not_expert_approved",
        "objective": {"id": f"lesson-{lesson.lesson_id}-objective", "text": "Проверить навык на новом варианте.",
                      "skill_id": f"exam-skill:{skill.skill_id}"},
        "criteria": structured_criteria,
        "prerequisites": [{
            "id": "read_prompt_and_answer_format", "label": "Прочитать условие и формат ответа",
            "skill_id": None, "registration_status": "unmapped_micro_skill",
            "status": "unknown_before_lesson", "diagnostic_method": "Короткий входной вопрос без подсказки.",
        }],
        "segments": _structured_lesson_segments(),
        "exercises": exercises,
        "assessment_limitations": ["Конечные варианты не являются доказательством полной корректности."],
    }, ensure_ascii=False)


def _verified_exercise_snapshot(skill_id="exam-skill:13", topic_code="ege.inf.synthetic.lesson.v1"):
    return {
        "exercise_id": "practice:synthetic:verified-1",
        "source_type": "practice_generator",
        "title": "Проверка границ",
        "prompt": "Определите результат для указанного граничного случая.",
        "answer_type": "numeric",
        "teacher_expected_answer": "2",
        "course_skill_id": skill_id,
        "source_skill_id": "skill.inf.synthetic",
        "topic_code": topic_code,
        "verification": {"status": "verified", "method": "existing AI Practice deterministic checker"},
    }


def _hidden_platform_exercise(db, lesson, course_id=5, course_version=1, task_id=1901):
    import json
    from app.ai_lab.platform_homework import _task_fingerprint
    from app.ai_lab.tutor_core import _verified_lesson_task_candidates
    from core.db_models import LessonTask, Tasks

    _set_structured_lesson_plan(lesson)
    skill = next(iter(lesson.skills or []))
    structure = json.loads(lesson.studio_scenario)
    criterion_id = str(structure["criteria"][0]["id"])
    task = Tasks(
        task_id=task_id, task_number=100, bank_category="synthetic_adaptive_draft",
        prototype_status="expert_approved",
        source_key=f"boostudy.synthetic.adaptive-v1/adaptive-plan-{task_id}",
        created_by_id=4, content_html="<p>Введите число рёбер кратчайшего маршрута для нового графа.</p>",
        answer="7", max_score=1, is_active=True,
        answer_spec={"type": "short_answer", "grading_mode": "exact",
                     "synthetic_course_skill_binding": {"contract": "boostudy.synthetic-course-skill.v1"}},
    )
    db.session.add(task)
    db.session.flush()
    binding = {
        "contract": "boostudy.synthetic-course-skill.v1", "course_id": course_id,
        "course_version": course_version, "lesson_id": lesson.lesson_id,
        "skill_id": f"exam-skill:{skill.skill_id}", "criterion_id": criterion_id,
        "topic_code": skill.topic_code, "task_fingerprint": _task_fingerprint(task),
    }
    task.answer_spec = {"type": "short_answer", "grading_mode": "exact",
                        "synthetic_course_skill_binding": binding}
    structure["exercises"] = [{
        "id": f"task:{task_id}", "source_type": "platform_task", "task_id": task_id,
        "title": "Кратчайший маршрут: новый граф", "topic_code": skill.topic_code,
        "criterion_ids": [criterion_id], "segment_id": "guided_practice",
        "assessment_method": "platform_exact_answer", "role": "diagnostic",
        "selection_priority": 1,
    }]
    lesson.studio_scenario = json.dumps(structure, ensure_ascii=False)
    link = LessonTask(lesson_id=lesson.lesson_id, task_id=task_id,
                      assignment_type="classwork", is_visible_to_student=False,
                      is_answer_visible_to_student=False, status="pending")
    db.session.add(link)
    db.session.flush()
    candidate = _verified_lesson_task_candidates(
        {"lesson_id": lesson.lesson_id, "status": lesson.status,
         "started_at": lesson.started_at, "pedagogical_structure": structure},
        course_id=course_id, course_version=course_version,
        skill_id=f"exam-skill:{skill.skill_id}", profile_id="platform-student:12", student_id=lesson.student_id,
    )
    assert len(candidate) == 1
    plan = _safe_time_plan()
    inserted = {**plan["inserted_segment"], "exercise_id": candidate[0]["exercise_id"]}
    plan["inserted_segment"] = inserted
    plan["proposed_segments"] = [
        inserted if item.get("id") == inserted["id"] else item for item in plan["proposed_segments"]
    ]
    return task, link, candidate[0], plan


@pytest.fixture()
def isolated_copy_app():
    from app import create_app, db

    app = create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "RUN_ENV": "local",
        "AI_LAB_ENABLED": True,
        "AI_LAB_COURSE_ADAPTER_ENABLED": True,
        "AI_LAB_SYNTHETIC_COURSE_IDS": "4",
        "AI_LAB_SYNTHETIC_COURSE_COPY_IDS": "5",
        "AI_LAB_PLATFORM_TEST_ACTOR_IDS": "4",
        "AI_LAB_PLATFORM_TEST_USER_IDS": "12",
        "AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS": "4",
        "AI_LAB_SAFE_DB_PATH": ":memory:",
        "AI_LAB_SAFE_DB_IDENTITY": (1, 1),
    })
    with app.app_context():
        db.create_all()
        from core.db_models import ExamSkill, LearningTrajectory, Lesson, Student, TrajectoryModule, User

        creator = User(id=4, username="creator", role="creator")
        learner_user = User(id=12, username="synthetic_copy_learner", role="student")
        student = Student(student_id=4, user_id=learner_user.id, name="Синтетический ученик")
        template = LearningTrajectory(
            course_id=4, is_template=True, student_id=None, title="Синтетический шаблон",
            current_version=1,
        )
        copy = LearningTrajectory(
            course_id=5, is_template=False, student_id=student.student_id, parent_course_id=template.course_id,
            title="Индивидуальная синтетическая копия", current_version=1, learning_goal="master",
        )
        module = TrajectoryModule(
            module_id=90, course_id=copy.course_id, title="Модуль синтетического навыка",
            learning_result="Проверять граничные условия функции на новых входных значениях.",
        )
        skill = ExamSkill(skill_id=13, task_number=13, title="Синтетический навык", subject="Информатика",
                          topic_code="ege.inf.synthetic.lesson.v1")
        lesson = Lesson(
            lesson_id=81, student_id=student.student_id, learning_trajectory_id=copy.course_id,
            course_order_index=10, status="planned", topic="Синтетический урок",
            studio_scenario="Исходный сценарий преподавателя.",
            content="Разберите функцию на обычных и граничных входах. Сравните фактический результат с условием.",
            course_module=module, skills=[skill],
        )
        db.session.add_all([creator, learner_user, student, template, copy, module, skill, lesson])
        db.session.commit()
        yield app, db, creator.id, student.student_id, lesson.lesson_id
        db.session.remove()
        db.drop_all()


def test_teacher_mutation_routes_reject_requests_without_csrf_token(isolated_copy_app):
    from core.db_models import AiLabExperiment, Assignment

    app, db, actor_id, _student_id, _lesson_id = isolated_copy_app
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(actor_id)
        session["_fresh"] = True

    responses = [
        client.post("/admin/ai-lab/api/tutor-core/proposals/1/assign-diagnostic", json={}),
        client.post("/admin/ai-lab/api/tutor-core/evidence-admissibility-review", json={}),
    ]

    assert [response.status_code for response in responses] == [403, 403]
    assert all("токен безопасности" in response.get_json()["error"].lower() for response in responses)
    with app.app_context():
        assert AiLabExperiment.query.count() == 0
        assert Assignment.query.count() == 0


def test_teacher_mutations_require_verified_synthetic_database(isolated_copy_app, monkeypatch):
    from app.ai_lab.database_safety import has_verified_safe_ai_lab_db
    from app.ai_lab.tutor_core import (
        TutorCoreError, assign_tutor_diagnostic, review_tutor_evidence_admissibility,
    )

    app, db, actor_id, _student_id, _lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.course_adapter.is_local_ai_lab_enabled", lambda: True)

    with app.app_context():
        app.config.pop("AI_LAB_SAFE_DB_PATH", None)
        app.config.pop("AI_LAB_SAFE_DB_IDENTITY", None)
        assert not has_verified_safe_ai_lab_db()
        for operation in (
            lambda: assign_tutor_diagnostic(actor_id, 1),
            lambda: review_tutor_evidence_admissibility(
                actor_id=actor_id, profile_id="platform-student:12", event_id="synthetic-event",
                decision="exclude", reason_code="attempt_context_unverifiable",
                reason_detail="Synthetic test of fail-closed database validation.",
            ),
        ):
            with pytest.raises(TutorCoreError) as error:
                operation()
            assert error.value.code == "synthetic_database_required"
            assert error.value.status_code == 403
        from core.db_models import AiLabExperiment, Assignment
        assert AiLabExperiment.query.count() == 0
        assert Assignment.query.count() == 0


def test_tutor_profile_action_requires_active_student_ownership(isolated_copy_app, monkeypatch):
    from core.db_models import AiLabExperiment, Assignment, Student, User

    app, db, _creator_id, _student_id, _lesson_id = isolated_copy_app
    app.config["AI_LAB_PLATFORM_TEST_ACTOR_IDS"] = "4,5"
    app.config["AI_LAB_PLATFORM_TEST_USER_IDS"] = "12,13"
    with app.app_context():
        teacher = User(id=5, username="synthetic_tutor", role="tutor", is_active=True)
        unrelated_learner = User(id=13, username="synthetic_unrelated_learner", role="student", is_active=True)
        unrelated_student = Student(student_id=5, user_id=unrelated_learner.id,
                                   name="Другой synthetic-ученик")
        db.session.add_all([teacher, unrelated_learner, unrelated_student])
        db.session.commit()

    def can_access(actor, *, student_user_id, student_platform_id):
        return actor.id == 5 and student_user_id == 12 and student_platform_id == 4

    monkeypatch.setattr("app.utils.relationship_scope.can_user_access_student", can_access)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "5"
        session["_fresh"] = True

    own_profile = client.post("/teacher/students/12/adaptive-learning", data={"action": "unknown"})
    other_profile = client.post("/teacher/students/13/adaptive-learning", data={"action": "preview"})
    assert own_profile.status_code == 302
    assert "/workspace/people/12#adaptive-learning-summary" in own_profile.headers["Location"]
    assert other_profile.status_code == 403
    app.config["WTF_CSRF_ENABLED"] = True
    missing_csrf = client.post("/teacher/students/12/adaptive-learning", data={"action": "preview"})
    assert missing_csrf.status_code == 403
    with app.app_context():
        assert AiLabExperiment.query.count() == 0
        assert Assignment.query.count() == 0


def test_registered_practice_skill_history_survives_without_course_link(isolated_copy_app):
    from app.ai_lab.tutor_core import _platform_profile_case
    from core.db_models import LearningTrajectory

    app, db, _actor_id, student_id, _lesson_id = isolated_copy_app
    event = {
        "contract_version": "boostudy.learning-evidence.v2",
        "event_id": "ai-practice:truth-table:attempt:1",
        "subject_id": "platform-student:12",
        "source_module": "ai_practice",
        "source_record_id": "practice-session:truth-table:attempt:1",
        "occurred_at": "2026-10-24T10:00:00+00:00",
        "evidence_status": "technical_confirmed",
        "assignment": None,
        "topic_ids": ["ege.inf.logic-truth-table.v1"],
        "skill_ids": ["skill.inf.truth-table-equivalence"],
        "error_codes": [],
        "outcome": {"score": 1, "maximum": 1, "status": "complete"},
        "criteria": [{
            "criterion_id": "result_check",
            "status": "met",
            "earned": 1,
            "maximum": 1,
            "evidence_status": "technical_confirmed",
            "skill_id": "skill.inf.truth-table-equivalence",
            "reason": "Все строки таблицы истинности проверены.",
            "source_refs": ["practice-session:truth-table:attempt:1"],
        }],
        "assistance": {"level": "no_platform_hint", "source_refs": []},
        "provenance": {
            "source_ref": "practice-session:truth-table:attempt:1",
            "payload_hash": "a" * 64,
            "model": "",
            "method": "parameterized-generator+deterministic-short-answer-checker",
        },
        "limitations": ["Проверен один конечный вариант задания."],
    }

    with app.app_context():
        copy = db.session.get(LearningTrajectory, 5)
        case = _platform_profile_case("platform-student:12", [event], student_id, copy)

        assert case["current_lesson_evidence_count"] == 0
        history = next(item for item in case["stable_skill_history"]
                       if item["skill_id"] == "skill.inf.truth-table-equivalence")
        assert history["title"] == "Логика: проверка эквивалентности"
        assert history["canonical_topic_code"] is None
        assert history["source_skill_ids"] == ["skill.inf.truth-table-equivalence"]
        assert history["course_skill_ids"] == []
        assert history["curriculum_mapping_statuses"] == ["unmapped_source_skill"]
        assert history["event_ids"] == [event["event_id"]]


def _make_bound_diagnostic_task(db, actor_id, lesson_id, task_id=990):
    import json
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import Lesson, LessonTask, Tasks

    lesson = db.session.get(Lesson, lesson_id)
    _set_structured_lesson_plan(lesson)
    structure = json.loads(lesson.studio_scenario)
    skill = lesson.skills[0]
    criterion_id = structure["criteria"][0]["id"]
    binding = {
        "contract": "boostudy.synthetic-course-skill.v1",
        "course_id": 5, "course_version": 1, "lesson_id": lesson_id,
        "skill_id": f"exam-skill:{skill.skill_id}", "criterion_id": criterion_id,
        "topic_code": skill.topic_code, "task_fingerprint": "pending",
    }
    task = Tasks(
        task_id=task_id, task_number=task_id, bank_category="synthetic_adaptive_draft",
        prototype_status="expert_approved",
        content_html="<p>Найдите кратчайший путь из A в D по указанным рёбрам.</p>",
        answer="A-C-D", source_key=f"boostudy.synthetic.adaptive-v1/diagnostic/{task_id}",
        created_by_id=actor_id, answer_spec={"type": "short_answer", "grading_mode": "exact",
                                             "synthetic_course_skill_binding": binding},
        max_score=1, is_active=True,
    )
    db.session.add(task)
    db.session.flush()
    task.answer_spec = {
        "type": "short_answer", "grading_mode": "exact",
        "synthetic_course_skill_binding": {**binding, "task_fingerprint": _task_fingerprint(task)},
    }
    structure["exercises"] = [{
        "id": f"task:{task_id}", "source_type": "platform_task", "task_id": task_id,
        "title": "Новый графовый вариант", "topic_code": skill.topic_code,
        "criterion_ids": [criterion_id], "segment_id": "guided_practice",
        "assessment_method": "platform_exact_answer", "role": "diagnostic",
        "selection_priority": 1, "verification_scope": "Только этот набор вершин и рёбер.",
        "evidence_limitations": "Один проверенный вариант не доказывает освоение навыка.",
    }]
    structure["criteria"][0]["exercise_ids"] = [f"task:{task_id}"]
    lesson.studio_scenario = json.dumps(structure, ensure_ascii=False)
    db.session.add(LessonTask(lesson_id=lesson_id, task_id=task_id, is_visible_to_student=False))
    db.session.commit()
    return task, criterion_id


def test_diagnostic_assignment_uses_normal_homework_and_admissibility_review_is_audited(
    isolated_copy_app, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    import json
    from datetime import datetime, timezone
    from threading import Barrier
    from app.ai_lab import analytics, tutor_core
    from app.ai_lab.tutor_core import (
            ATTEMPT_REVIEW_SCENARIO, DIAGNOSTIC_ASSIGNMENT_SCENARIO, PROPOSAL_SCENARIO,
            _latest_attempt_admissibility_reviews, _proposal_review_fingerprint,
            assign_tutor_diagnostic, review_tutor_proposal, TutorCoreError,
    )
    from app.assignments.evaluation_history import record_answer_evaluation
    from app.assignments.routes import _record_submission_attempt
    from core.db_models import (
        AiLabExperiment, Answer, Assignment, AssignmentTask, LearningTrajectory, Lesson,
        Submission, Tasks, User,
    )

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    app.config.update(
        AI_LAB_PLATFORM_TEST_ACTOR_IDS=f"{actor_id},5",
        AI_LAB_PLATFORM_TEST_USER_IDS="12",
        AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS=f"{actor_id},5",
        AI_LAB_PLATFORM_HOMEWORK_ENABLED=True,
    )
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    with app.app_context():
        db.session.add(User(id=5, username="other_synthetic_creator", role="creator"))
        db.session.commit()
        task, criterion_id = _make_bound_diagnostic_task(db, actor_id, lesson_id)
        lesson = db.session.get(Lesson, lesson_id)
        from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint
        from app.task_bank.answer_safety import answer_appears_in_labeled_example
        assert _allowlisted_task_author_ids() == {actor_id, 5}
        assert task.bank_category == "synthetic_adaptive_draft" and task.is_active and task.answer
        assert task.source_key.startswith("boostudy.synthetic.adaptive-v1/")
        assert task.answer_spec["synthetic_course_skill_binding"]["task_fingerprint"] == _task_fingerprint(task)
        assert not answer_appears_in_labeled_example(task.content_html, task.answer)
        candidate = tutor_core._verified_lesson_task_candidates(
            {"lesson_id": lesson_id, "pedagogical_structure": json.loads(lesson.studio_scenario)},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id="platform-student:12", student_id=student_id,
        )[0]
        assert candidate["previous_usage"]["status"] == "not_used"

        task.prototype_status = "unreviewed"
        db.session.flush()
        assert tutor_core._verified_lesson_task_candidates(
            {"lesson_id": lesson_id, "pedagogical_structure": json.loads(lesson.studio_scenario)},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id="platform-student:12", student_id=student_id,
        ) == []
        task.prototype_status = "expert_approved"
        db.session.flush()

        saved = {
            "profile_id": "platform-student:12", "profile_kind": "platform_synthetic",
            "student_id": student_id, "course_copy_id": 5, "course_version": 1,
            "source_refs": ["platform-submission:501:attempt:1:task:505"],
            "evidence": [{"event_id": "platform-submission:501:attempt:1:task:505",
                          "source_ref": "platform-submission:501:attempt:1:task:505",
                          "evidence_status": "technical_confirmed", "skill_ids": ["exam-skill:13"],
                          "course_skill_ids": ["exam-skill:13"],
                          "criteria": [{"criterion_id": criterion_id, "skill_id": "exam-skill:13",
                                        "status": "not_met", "evidence_status": "technical_confirmed"}]}],
            "skill_summary": {"skill_id": "exam-skill:13", "status": "developing"},
            "next_lesson": {"lesson_id": lesson_id, "skill_ids": ["exam-skill:13"]},
            "proposal": {"action": "diagnostic_without_mastery_claim", "text": "Независимая диагностика.",
                         "time_plan": {"status": "separate_activity", "separate_activity_minutes": 10},
                         "selected_exercise": candidate},
        }
        current_case = {**saved, "profile_id": "platform-student:12", "event_count": 1}
        fingerprint = _proposal_review_fingerprint(current_case)
        proposal = AiLabExperiment(
            actor_user_id=actor_id, request_key="diagnostic-proposal-for-test",
            scenario_id=PROPOSAL_SCENARIO, provider="local", status="succeeded",
            model=None, prompt_snapshot="Synthetic test", scenario_snapshot={
                "profile_id": "platform-student:12", "profile_kind": "platform_synthetic",
                "review_fingerprint": fingerprint,
            }, input_snapshot={}, expected_snapshot=saved, result_json={"proposal": saved},
        )
        stale_proposal = AiLabExperiment(
            actor_user_id=actor_id, request_key="stale-diagnostic-proposal-for-test",
            scenario_id=PROPOSAL_SCENARIO, provider="local", status="succeeded",
            model=None, prompt_snapshot="Synthetic stale-preview test", scenario_snapshot={
                "profile_id": "platform-student:12", "profile_kind": "platform_synthetic",
                "review_fingerprint": fingerprint,
            }, input_snapshot={}, expected_snapshot=saved, result_json={"proposal": saved},
        )
        db.session.add(proposal)
        db.session.add(stale_proposal)
        db.session.commit()
        proposal_id = int(proposal.id)
        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor: [current_case])
        monkeypatch.setattr("app.ai_lab.routes.is_local_ai_lab_enabled", lambda: True)
        client = app.test_client()
        with client.session_transaction() as session:
            session["_user_id"] = str(actor_id)
            session["_fresh"] = True
        original_scenario = lesson.studio_scenario
        original_course_version = db.session.get(LearningTrajectory, 5).current_version

        barrier = Barrier(2)

        def concurrent_assignment():
            with app.app_context():
                barrier.wait(timeout=5)
                return assign_tutor_diagnostic(actor_id, proposal_id).id

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_ids = list(executor.map(lambda _index: concurrent_assignment(), range(2)))
        assert concurrent_ids[0] == concurrent_ids[1]

        assignment_response = client.post(
            f"/admin/ai-lab/api/tutor-core/proposals/{proposal_id}/assign-diagnostic", json={},
        )
        assert assignment_response.status_code == 200, assignment_response.get_json()
        assignment_payload = assignment_response.get_json()
        assignment_id = assignment_payload["assignment_id"]
        submission_id = assignment_payload["submission_id"]
        assigned = assign_tutor_diagnostic(actor_id, proposal.id)
        assignment = db.session.get(Assignment, assignment_id)
        submission = db.session.get(Submission, submission_id)
        assignment_task = AssignmentTask.query.filter_by(assignment_id=assignment_id).one()
        assert assigned.scenario_id == DIAGNOSTIC_ASSIGNMENT_SCENARIO
        assert assignment.assignment_type == "homework" and assignment.lesson_id == lesson_id
        assert submission.student_id == student_id and submission.status == "ASSIGNED"
        assert assignment_task.task_id == task.task_id and not assignment_task.requires_manual_grading
        used_candidate = tutor_core._verified_lesson_task_candidates(
            {"lesson_id": lesson_id, "pedagogical_structure": json.loads(lesson.studio_scenario)},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id="platform-student:12", student_id=student_id,
        )[0]
        assert used_candidate["previous_usage"]["status"] == "previously_used"
        assert db.session.get(LearningTrajectory, 5).current_version == original_course_version
        assert db.session.get(Lesson, lesson_id).studio_scenario == original_scenario
        assert assign_tutor_diagnostic(actor_id, proposal.id).id == assigned.id
        with pytest.raises(TutorCoreError, match="Ученик уже получал этот вариант"):
            assign_tutor_diagnostic(actor_id, stale_proposal.id)
        with pytest.raises(TutorCoreError, match="Диагностика уже назначена"):
            review_tutor_proposal(actor_id, proposal.id, "rejected")

        answer = Answer(submission_id=submission_id, assignment_task_id=assignment_task.assignment_task_id,
                        value="A-C-D", is_correct=True, score=1, max_score=1)
        submission.status = "GRADED"
        submission.submitted_at = datetime.now(timezone.utc)
        submission.total_score = 1
        submission.max_score = 1
        db.session.add(answer)
        db.session.flush()
        _record_submission_attempt(submission)
        record_answer_evaluation(answer, method="automatic_answer_checker", actor_user_id=None,
                                 score=1, max_score=1, is_correct=True)
        db.session.commit()
        events = analytics.stored_platform_homework_evidence(actor_user_id=actor_id)
        event_id = next(item["event_id"] for item in events
                        if item["source_record_id"] == f"submission:{submission_id}")
        completed = next(item for item in events if item["event_id"] == event_id)
        assert completed["evidence_status"] == "technical_confirmed"
        assert completed["outcome"]["score"] == 1
        assert completed["course_context"]["lesson_id"] == lesson_id
        assert completed["topic_ids"] == []
        assert completed["skill_ids"] == []
        assert completed["criteria"][0]["status"] == "insufficient_data"
        assert completed["criteria"][0]["evidence_status"] == "insufficient_data"
        assert completed["criteria"][0]["skill_id"] is None
        assert completed["criteria"][0]["earned"] is None
        assert any("черновая привязка" in item for item in completed["limitations"])
        assert completed["provenance"]["evaluation_revision"]["actor_user_id"] is None
        assert completed["provenance"]["evaluation_revision"]["method"] == "automatic_answer_checker"

        with client.session_transaction() as session:
            session["_user_id"] = "5"
        other_teacher_response = client.post(
            "/admin/ai-lab/api/tutor-core/evidence-admissibility-review", json={
                "profile_id": "platform-student:12", "event_id": event_id,
                "decision": "exclude", "reason_code": "attempt_context_unverifiable",
                "reason_detail": "Synthetic isolation check by another allowed teacher.",
            },
        )
        assert other_teacher_response.status_code == 403
        assert other_teacher_response.get_json()["error_code"] == "attempt_teacher_mismatch"
        with client.session_transaction() as session:
            session["_user_id"] = str(actor_id)

        before_case = tutor_core._platform_profile_case(
            "platform-student:12", [completed], student_id, db.session.get(LearningTrajectory, 5),
        )
        before_fingerprint = _proposal_review_fingerprint(before_case)
        review_response = client.post(
            "/admin/ai-lab/api/tutor-core/evidence-admissibility-review", json={
                "profile_id": "platform-student:12", "event_id": event_id,
                "decision": "exclude", "reason_code": "synthetic_acceptance_only",
                "reason_detail": "Synthetic acceptance test only; submission and 1/1 score remain valid.",
            },
        )
        assert review_response.status_code == 200, review_response.get_json()
        review = db.session.get(AiLabExperiment, review_response.get_json()["review_id"])
        assert review.scenario_id == ATTEMPT_REVIEW_SCENARIO
        assert review.actor_user_id == actor_id
        assert review.created_at is not None
        assert review.input_snapshot["reason_code"] == "synthetic_acceptance_only"
        assert "score remain valid" in review.input_snapshot["reason_detail"]
        assert review.expected_snapshot["score_before_review"] == 1
        assert review.result_json["source_attempt_and_score_mutated"] is False
        assert db.session.get(Answer, answer.answer_id).score == 1
        exclusions = _latest_attempt_admissibility_reviews(actor_id, "platform-student:12")
        excluded_case = tutor_core._platform_profile_case(
            "platform-student:12", [completed], student_id, db.session.get(LearningTrajectory, 5), exclusions,
        )
        excluded_fingerprint = _proposal_review_fingerprint(excluded_case)
        assert excluded_case["excluded_attempt_count"] == 1
        assert excluded_case["current_lesson_evidence_count"] == 0
        assert excluded_case["skill_summary"]["status"] == "insufficient_data"
        assert excluded_case["evidence"][0]["attempt_admissibility"]["status"] == "excluded"
        assert excluded_fingerprint != before_fingerprint

        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor: [excluded_case])
        with pytest.raises(TutorCoreError, match="Предпросмотр устарел"):
            assign_tutor_diagnostic(actor_id, stale_proposal.id)
        assert Assignment.query.count() == 1
        with pytest.raises(TutorCoreError, match="Предпросмотр устарел"):
            review_tutor_proposal(actor_id, stale_proposal.id, "accepted")
        restored_response = client.post(
            "/admin/ai-lab/api/tutor-core/evidence-admissibility-review", json={
                "profile_id": "platform-student:12", "event_id": event_id,
                "decision": "restore", "reason_code": "teacher_reconsideration",
                "reason_detail": "Synthetic acceptance review was corrected after rechecking the submission context.",
            },
        )
        assert restored_response.status_code == 200, restored_response.get_json()
        restored = db.session.get(AiLabExperiment, restored_response.get_json()["review_id"])
        assert restored.id != review.id
        restored_reviews = _latest_attempt_admissibility_reviews(actor_id, "platform-student:12")
        assert restored_reviews[event_id]["status"] == "restored"
        restored_case = tutor_core._platform_profile_case(
            "platform-student:12", [completed], student_id, db.session.get(LearningTrajectory, 5), restored_reviews,
        )
        assert restored_case["excluded_attempt_count"] == 0
        assert restored_case["current_lesson_evidence_count"] == 0
        assert AiLabExperiment.query.filter_by(
            actor_user_id=actor_id, scenario_id=ATTEMPT_REVIEW_SCENARIO,
        ).count() == 2
        assert AiLabExperiment.query.filter_by(
            actor_user_id=actor_id, scenario_id=DIAGNOSTIC_ASSIGNMENT_SCENARIO,
        ).count() == 1


def test_synthetic_course_binding_requires_explicit_approval_and_compatible_semantics():
    from app.ai_lab.analytics import _synthetic_course_binding_is_approved

    binding = {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "pedagogical_status": "not_pedagogically_approved",
        "semantic_compatibility": {"status": "compatible"},
    }
    assert not _synthetic_course_binding_is_approved(binding)
    assert _synthetic_course_binding_is_approved({
        **binding,
        "pedagogical_status": "expert_approved",
    })
    assert not _synthetic_course_binding_is_approved({
        **binding,
        "pedagogical_status": "teacher_confirmed",
    })
    assert _synthetic_course_binding_is_approved({
        **binding,
        "pedagogical_status": "teacher_confirmed",
        "approval_basis": "ordinary_course_editor",
        "review_actor_user_id": 4,
        "reviewed_at": "2026-10-26T12:00:00+00:00",
        "review_course_version": 1,
        "course_version": 2,
    })
    assert not _synthetic_course_binding_is_approved({
        **binding,
        "pedagogical_status": "teacher_confirmed",
        "approval_basis": "ordinary_course_editor",
        "review_actor_user_id": 4,
        "reviewed_at": "2026-10-26T12:00:00+00:00",
        "review_course_version": 3,
        "course_version": 2,
    })
    assert not _synthetic_course_binding_is_approved({
        **binding,
        "pedagogical_status": "expert_approved",
        "semantic_compatibility": {"status": "unverified"},
    })


def test_teacher_confirmed_course_binding_is_temporal_and_revocable(isolated_copy_app, monkeypatch):
    import hashlib
    import json

    from app.ai_lab import analytics
    from app.ai_lab.course_evidence import course_task_checker_fingerprint
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import ExamSkill, Lesson, LessonTask, LearningTrajectory, Student, Tasks

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    monkeypatch.setattr("app.ai_lab.course_adapter._allowed_copy_ids", lambda: {5})
    monkeypatch.setattr(
        "app.ai_lab.course_adapter.resolve_assigned_synthetic_copy",
        lambda _student_id: {"status": "resolved", "copy": db.session.get(LearningTrajectory, 5)},
    )
    monkeypatch.setattr(
        "app.ai_lab.course_adapter.compare_course_task_semantics",
        lambda **_kwargs: {"status": "compatible", "matches": [], "mismatches": []},
    )

    with app.app_context():
        app.config.update(
            AI_LAB_PLATFORM_TEST_ACTOR_IDS=str(actor_id),
            AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS=str(actor_id),
            AI_LAB_PLATFORM_TEST_USER_IDS="12",
        )
        lesson = db.session.get(Lesson, lesson_id)
        skill = db.session.get(ExamSkill, 13)
        skill.mastery_criteria = [{"key": "boundary", "label": "Проверяет границу"}]
        task = Tasks(
            task_id=9401, task_number=94, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/teacher-review-temporal-test",
            created_by_id=actor_id, content_html="<p>Проверьте границу.</p>", answer="2", max_score=1,
            is_active=True,
            answer_spec={
                "type": "short_answer", "grading_mode": "exact",
                "synthetic_course_skill_binding": {
                    "contract": "boostudy.synthetic-course-skill.v1", "course_id": 5,
                    "course_version": 1, "lesson_id": lesson_id, "skill_id": "exam-skill:13",
                    "topic_code": skill.topic_code, "criterion_id": "boundary", "task_fingerprint": "pending",
                },
            },
        )
        db.session.add(task)
        db.session.flush()
        task_binding = dict(task.answer_spec["synthetic_course_skill_binding"])
        task_binding["task_fingerprint"] = _task_fingerprint(task)
        task.answer_spec = {**task.answer_spec, "synthetic_course_skill_binding": task_binding}
        db.session.add(LessonTask(
            lesson_id=lesson_id, task_id=task.task_id, assignment_type="classwork",
            is_visible_to_student=True, is_answer_visible_to_student=False,
        ))
        db.session.flush()

        checker_fingerprint = course_task_checker_fingerprint(
            answer_spec=task.answer_spec, answer=task.answer, expected_answer=task.answer,
            assessment_method="exact_answer_check", max_score=1,
        )
        review_binding = {
            "task_id": task.task_id, "skill_id": "exam-skill:13", "topic_code": skill.topic_code,
            "criterion_id": "boundary", "assessment_method": "platform_exact_answer",
            "task_fingerprint": _task_fingerprint(task),
            "checker_fingerprints": {"exact_answer_check": checker_fingerprint},
        }
        bindings = [review_binding]
        review_fingerprint = hashlib.sha256(json.dumps(
            bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        confirmed_at = "2026-10-26T10:00:00+00:00"
        revoked_at = "2026-10-26T12:00:00+00:00"
        lesson.review_summaries = {
            "_tutor_core_pedagogy_review_history": [{
                "contract": "boostudy.teacher-course-task-review.v1", "status": "teacher_confirmed",
                "course_id": 5, "lesson_id": lesson_id, "confirmed_by_user_id": actor_id,
                "confirmed_at": confirmed_at, "effective_course_version": 1,
                "binding_fingerprint": review_fingerprint, "bindings": bindings,
            }],
        }
        db.session.flush()
        student = db.session.get(Student, student_id)
        kwargs = {
            "assessment_method": "exact_answer_check", "expected_answer": "2", "max_score": 1,
        }

        old_event = analytics._synthetic_course_task_binding(
            task, lesson_id, student, int(student.user_id), actor_id,
            observed_at="2026-10-26T09:59:00+00:00", **kwargs,
        )
        assert old_event["pedagogical_status"] == "not_pedagogically_approved"

        current_event = analytics._synthetic_course_task_binding(
            task, lesson_id, student, int(student.user_id), actor_id,
            observed_at="2026-10-26T11:00:00+00:00", **kwargs,
        )
        assert current_event["pedagogical_status"] == "teacher_confirmed"
        assert analytics._synthetic_course_binding_is_approved(current_event)

        lesson.review_summaries["_tutor_core_pedagogy_review_history"].append({
            "contract": "boostudy.teacher-course-task-review.v1", "status": "revoked",
            "course_id": 5, "lesson_id": lesson_id, "revoked_by_user_id": actor_id,
            "revoked_at": revoked_at, "effective_course_version": 2,
            "reason": "teacher_unchecked_confirmation",
        })
        db.session.get(LearningTrajectory, 5).current_version = 2
        task_binding["course_version"] = 2
        task.answer_spec = {**task.answer_spec, "synthetic_course_skill_binding": task_binding}
        db.session.flush()
        pre_revocation = analytics._synthetic_course_task_binding(
            task, lesson_id, student, int(student.user_id), actor_id,
            observed_at="2026-10-26T11:00:00+00:00", **kwargs,
        )
        post_revocation = analytics._synthetic_course_task_binding(
            task, lesson_id, student, int(student.user_id), actor_id,
            observed_at="2026-10-26T13:00:00+00:00", **kwargs,
        )
        assert pre_revocation["pedagogical_status"] == "teacher_confirmed"
        assert post_revocation["pedagogical_status"] == "not_pedagogically_approved"


def test_bound_practice_uses_its_own_skill_when_another_event_follows(isolated_copy_app):
    from app.ai_lab.practice import practice_skill_topic_code
    from app.ai_lab.tutor_core import _platform_profile_case
    from core.db_models import ExamSkill, LearningTrajectory, Lesson

    app, db, _actor_id, student_id, lesson_id = isolated_copy_app
    source_skill_id = "skill.inf.ipv4.subnet-mask"
    topic_code = practice_skill_topic_code(source_skill_id)
    assert topic_code

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = db.session.get(ExamSkill, 13)
        skill.topic_code = topic_code
        lesson.topic = "Синтетический урок по IPv4"
        db.session.commit()

        event = {
            "contract_version": "boostudy.learning-evidence.v2",
            "event_id": "ai-practice:bound-ipv4:attempt:1",
            "subject_id": "platform-student:12",
            "source_module": "ai_practice",
            "source_record_id": "practice-session:bound-ipv4:attempt:1",
            "occurred_at": "2026-10-24T10:00:00+00:00",
            "evidence_status": "technical_confirmed",
            "assignment": None,
            "topic_ids": [topic_code],
            "skill_ids": [source_skill_id],
            "error_codes": [],
            "outcome": {"score": 1, "maximum": 1, "status": "complete"},
            "criteria": [{
                "criterion_id": "result_check", "status": "met", "earned": 1, "maximum": 1,
                "evidence_status": "technical_confirmed", "skill_id": source_skill_id,
                "reason": "Ответ прошёл детерминированную проверку.",
                "source_refs": ["practice-session:bound-ipv4:attempt:1"],
            }],
            "assistance": {"level": "no_platform_hint", "source_refs": []},
            "course_context": {
                "contract": "boostudy.synthetic-practice-course-context.v1",
                "course_id": 5, "course_version": 1, "lesson_id": lesson_id,
                "skill_id": source_skill_id, "course_skill_id": "exam-skill:13",
                "topic_code": topic_code,
            },
            "provenance": {
                "source_ref": "practice-session:bound-ipv4:attempt:1",
                "payload_hash": "b" * 64,
                "method": "parameterized-generator+deterministic-short-answer-checker",
            },
            "limitations": ["Проверен один синтетический вариант."],
        }
        later_event = {
            **event,
            "event_id": "ai-practice:unbound-logic:attempt:1",
            "source_record_id": "practice-session:unbound-logic:attempt:1",
            "topic_ids": ["ege.inf.logic-truth-table.v1"],
            "skill_ids": ["skill.inf.truth-table-equivalence"],
            "criteria": [{
                **event["criteria"][0],
                "skill_id": "skill.inf.truth-table-equivalence",
                "source_refs": ["practice-session:unbound-logic:attempt:1"],
            }],
            "course_context": None,
            "provenance": {
                "source_ref": "practice-session:unbound-logic:attempt:1",
                "payload_hash": "c" * 64,
                "method": "parameterized-generator+deterministic-short-answer-checker",
            },
        }

        case = _platform_profile_case(
            "platform-student:12", [event, later_event], student_id,
            db.session.get(LearningTrajectory, 5),
        )
        bound_result = next(item for item in case["evidence"] if item["event_id"] == event["event_id"])
        assert bound_result["curriculum_eligibility"] == "eligible"
        assert bound_result["curriculum_exclusion_reason"] is None


def test_teacher_approved_adjustment_changes_only_copy_and_can_be_rolled_back(isolated_copy_app):
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
    import json
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson, User

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _set_structured_lesson_plan(lesson)
        original_scenario = lesson.studio_scenario
        db.session.flush()
        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="targeted_diagnostic_and_review",
            evidence_refs=["platform-submission:501:attempt:1:task:505"],
            exercise_snapshot=_verified_exercise_snapshot(),
            time_plan=_safe_time_plan(),
        )
        assert change["old_scenario_sha256"]
        assert change["new_course_version"] == 2
        db.session.commit()

        copy = db.session.get(LearningTrajectory, 5)
        template = db.session.get(LearningTrajectory, 4)
        lesson = db.session.get(Lesson, lesson_id)
        assert copy.current_version == 2
        assert template.current_version == 1
        updated_scenario = json.loads(lesson.studio_scenario)
        assert [item["minutes"] for item in updated_scenario["segments"]] == [10, 30, 10, 10]
        assert updated_scenario["adaptation_history"][0]["cuts"][0]["reason"]
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 1
        assert LearningTrajectoryVersion.query.filter_by(course_id=4).count() == 0

        with pytest.raises(ValueError, match="изменилась после предложения"):
            apply_tutor_copy_adjustment(
                actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
                lesson_id=lesson_id, skill_id="exam-skill:13", action="targeted_diagnostic_and_review",
                evidence_refs=["platform-submission:501:attempt:1:task:505"],
                exercise_snapshot=_verified_exercise_snapshot(),
                time_plan=_safe_time_plan(),
            )

        restored = rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        db.session.commit()
        assert restored["restored_course_version"] == 3
        assert db.session.get(LearningTrajectory, 5).current_version == 3
        assert db.session.get(LearningTrajectory, 4).current_version == 1
        assert db.session.get(Lesson, lesson_id).studio_scenario == original_scenario
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 2


def test_semantic_evidence_survives_equivalent_rollback_but_not_criterion_change(isolated_copy_app, monkeypatch):
    import json
    from datetime import timedelta
    import json
    from app.ai_lab.course_adapter import (
        apply_tutor_copy_adjustment, compare_course_task_semantics, resolve_course_version_at,
        rollback_tutor_copy_adjustment,
    )
    from app.ai_lab.platform_homework import _task_fingerprint
    from core.db_models import ExamSkill, Lesson, LearningTrajectoryVersion, Tasks

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.platform_homework._allowlisted_task_author_ids", lambda: {actor_id})
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = db.session.get(ExamSkill, 13)
        skill.mastery_criteria = [{"key": "boundary", "label": "Проверяет границу", "evidence": "Проверен граничный ввод."}]
        _set_structured_lesson_plan(lesson)
        task = Tasks(
            task_id=905, task_number=99, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/test-semantic-rollback",
            created_by_id=actor_id, content_html="Проверьте граничное значение функции.",
            answer="2", max_score=1,
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
        )
        binding = {
            "contract": "boostudy.synthetic-course-skill.v1", "course_id": 5,
            "course_version": 1, "lesson_id": lesson_id, "skill_id": "exam-skill:13",
            "topic_code": "ege.inf.synthetic.lesson.v1", "criterion_id": "boundary",
        }
        task.answer_spec["synthetic_course_skill_binding"] = binding
        binding["task_fingerprint"] = _task_fingerprint(task)
        db.session.add(task)
        db.session.flush()

        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
            evidence_refs=["synthetic-event:old-version"],
            exercise_snapshot=_verified_exercise_snapshot(), time_plan=_safe_time_plan(),
        )
        db.session.flush()
        snapshot = LearningTrajectoryVersion.query.filter_by(course_id=5).one()
        semantic_coverage = snapshot.snapshot["evidence_semantics_by_lesson"]
        assert snapshot.snapshot["evidence_semantics_coverage_complete"] is True
        assert {item["lesson_id"] for item in semantic_coverage} == {lesson_id}
        assert resolve_course_version_at(5, snapshot.created_at - timedelta(seconds=1))["course_version"] == 1
        assert resolve_course_version_at(5, snapshot.created_at + timedelta(seconds=1))["course_version"] == 2
        rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        db.session.flush()

        comparison = compare_course_task_semantics(
            course_id=5, source_version=1, lesson_id=lesson_id, skill_id="exam-skill:13",
            criterion_id="boundary", task_id=905, task_fingerprint=binding["task_fingerprint"],
        )
        assert comparison["status"] == "compatible", comparison
        assert "criteria_fingerprint" in comparison["matches"]
        assert db.session.get(ExamSkill, 13).mastery_criteria == [
            {"key": "boundary", "label": "Проверяет границу", "evidence": "Проверен граничный ввод."}
        ]

        restored_lesson = db.session.get(Lesson, lesson_id)
        reordered = json.loads(restored_lesson.studio_scenario)
        reordered["segments"].reverse()
        restored_lesson.studio_scenario = json.dumps(reordered, ensure_ascii=False)
        db.session.flush()
        assert compare_course_task_semantics(
            course_id=5, source_version=1, lesson_id=lesson_id, skill_id="exam-skill:13",
            criterion_id="boundary", task_id=905, task_fingerprint=binding["task_fingerprint"],
        )["status"] == "compatible"

        skill.mastery_criteria = [{"key": "boundary", "label": "Иной критерий", "evidence": "Новое правило."}]
        db.session.flush()
        changed = compare_course_task_semantics(
            course_id=5, source_version=1, lesson_id=lesson_id, skill_id="exam-skill:13",
            criterion_id="boundary", task_id=905, task_fingerprint=binding["task_fingerprint"],
        )
        assert changed["status"] == "incompatible"
        assert "criteria_fingerprint:changed" in changed["mismatches"]


def test_manual_course_snapshot_preserves_semantics_for_safe_copy(isolated_copy_app, monkeypatch):
    from datetime import timedelta
    from flask_login import login_user
    from app.ai_lab.course_adapter import compare_course_task_semantics, resolve_course_version_at
    from app.ai_lab.platform_homework import _task_fingerprint
    from app.courses.routes import _snapshot_course
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson, Tasks, User

    app, db, actor_id, _student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    monkeypatch.setattr("app.ai_lab.platform_homework._allowlisted_task_author_ids", lambda: {actor_id})
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = next(iter(lesson.skills or []))
        skill.mastery_criteria = [{
            "key": "boundary", "label": "Проверяет границу", "evidence": "Ответ проверен exact checker.",
        }]
        binding = {
            "contract": "boostudy.synthetic-course-skill.v1", "course_id": 5,
            "course_version": 1, "lesson_id": lesson_id, "skill_id": "exam-skill:13",
            "topic_code": "ege.inf.synthetic.lesson.v1", "criterion_id": "boundary",
        }
        task = Tasks(
            task_id=906, task_number=100, bank_category="synthetic_adaptive_draft",
            source_key=f"boostudy.synthetic.adaptive-v1/5/{lesson_id}/906",
            created_by_id=actor_id, content_html="Проверьте функцию на граничном значении.",
            answer="2", max_score=1,
            answer_spec={"type": "short_answer", "grading_mode": "exact",
                         "synthetic_course_skill_binding": binding},
        )
        db.session.add(task)
        db.session.flush()
        task.answer_spec = {
            **task.answer_spec,
            "synthetic_course_skill_binding": {
                **binding, "task_fingerprint": _task_fingerprint(task),
            },
        }
        db.session.flush()

        with app.test_request_context("/"):
            login_user(db.session.get(User, actor_id))
            _snapshot_course(db.session.get(LearningTrajectory, 5), "lesson_create")
        db.session.flush()

        snapshot = LearningTrajectoryVersion.query.filter_by(course_id=5).one()
        assert snapshot.snapshot["snapshot_of_course_version"] == 1
        assert snapshot.snapshot["evidence_semantics_coverage_complete"] is True
        assert {item["lesson_id"] for item in snapshot.snapshot["evidence_semantics_by_lesson"]} == {lesson_id}
        assert resolve_course_version_at(5, snapshot.created_at - timedelta(seconds=1))["course_version"] == 1
        assert resolve_course_version_at(5, snapshot.created_at + timedelta(seconds=1))["course_version"] == 2

        comparison = compare_course_task_semantics(
            course_id=5, source_version=1, lesson_id=lesson_id, skill_id="exam-skill:13",
            criterion_id="boundary", task_id=906,
            task_fingerprint=task.answer_spec["synthetic_course_skill_binding"]["task_fingerprint"],
        )
        assert comparison["status"] == "compatible", comparison


def test_semantic_evidence_comparison_fails_closed_for_missing_context():
    from app.ai_lab.course_evidence import compare_semantic_records

    result = compare_semantic_records({}, None, {})
    assert result["status"] == "unverified"
    assert result["mismatches"] == ["semantic_record_missing"]


def test_lesson_time_preview_keeps_fully_allocated_plan_and_separates_extra_diagnostic():
    import json
    from app.ai_lab.tutor_core import _lesson_time_adjustment, _lesson_time_segments

    lesson = {"studio_scenario": (
        "0–6 мин направление рёбер\n6–16 мин выбор минимума\n16–28 мин стоимость маршрута\n"
        "28–40 мин равные маршруты\n40–50 мин достижимость\n50–57 мин перенос\n57–60 мин выходной вопрос"
    )}
    original, source = _lesson_time_segments(lesson, 60)
    assert source == "timeline_text"
    assert [item["minutes"] for item in original] == [6, 10, 12, 12, 10, 7, 3]

    time_plan = _lesson_time_adjustment(lesson, 60, 10, {"exercise_id": "practice:graph:diagnostic"})
    assert time_plan["status"] == "separate_activity"
    assert time_plan["cuts"] == []
    assert time_plan["proposed_segments"] == original
    assert time_plan["total_with_separate_activity"] == 70
    assert time_plan["can_apply_to_lesson"] is False

    structured = {"studio_scenario": json.dumps({"segments": _structured_lesson_segments()})}
    redistributed = _lesson_time_adjustment(structured, 60, 10, {"exercise_id": "practice:synthetic:verified-1"})
    assert redistributed["status"] == "redistributed"
    assert redistributed["cuts"] == [{
        "segment_id": "guided_practice", "minutes": 10,
        "reason": _structured_lesson_segments()[1]["flexible_reason"],
    }]
    assert sum(item["minutes"] for item in redistributed["proposed_segments"]) == 60


def test_lesson_time_mutation_rejects_wrong_duration_exercise_and_stage_edits():
    import json
    from types import SimpleNamespace
    from app.ai_lab.course_adapter import _validated_time_plan

    segments = _structured_lesson_segments()
    lesson = SimpleNamespace(duration=60, studio_scenario=json.dumps({"segments": segments}))
    exercise_id = "practice:synthetic:verified-1"
    plan = _safe_time_plan()

    wrong_duration = {**plan, "inserted_segment": {**plan["inserted_segment"], "minutes": 9}}
    with pytest.raises(ValueError, match="добавленный этап"):
        _validated_time_plan(lesson, wrong_duration, "diagnostic_without_mastery_claim", exercise_id)

    wrong_exercise = {**plan, "inserted_segment": {**plan["inserted_segment"], "exercise_id": "other"}}
    wrong_exercise["proposed_segments"] = [
        ({**segment, "exercise_id": "other"} if segment["id"] == "tutor_evidence_check" else segment)
        for segment in plan["proposed_segments"]
    ]
    with pytest.raises(ValueError, match="добавленный этап"):
        _validated_time_plan(lesson, wrong_exercise, "diagnostic_without_mastery_claim", exercise_id)

    changed_stage = {**plan, "proposed_segments": [
        ({**segment, "title": "Изменённый этап"} if segment["id"] == "guided_practice" else segment)
        for segment in plan["proposed_segments"]
    ]}
    with pytest.raises(ValueError, match="необоснованное сокращение"):
        _validated_time_plan(lesson, changed_stage, "diagnostic_without_mastery_claim", exercise_id)


def test_teacher_can_edit_inserted_stage_and_reallocate_only_flexible_minutes():
    import json
    from types import SimpleNamespace
    from app.ai_lab.course_adapter import apply_teacher_time_plan_edits, _validated_time_plan

    plan = _safe_time_plan()
    edited = apply_teacher_time_plan_edits(
        plan,
        action="diagnostic_without_mastery_claim",
        stage_minutes={"guided_practice": 33, "tutor_evidence_check": 7},
        stage_purpose="Попросить ученика объяснить выбор перехода и проверить новый граничный случай.",
    )
    lesson = SimpleNamespace(
        duration=60,
        studio_scenario=json.dumps({"contract": "boostudy.lesson-pedagogy.v1", "segments": plan["original_segments"]}),
    )
    applied = _validated_time_plan(
        lesson, edited, "diagnostic_without_mastery_claim", "practice:synthetic:verified-1",
    )

    assert sum(item["minutes"] for item in edited["proposed_segments"]) == 60
    assert edited["cuts"] == [{
        "segment_id": "guided_practice", "minutes": 7,
        "reason": plan["original_segments"][1]["flexible_reason"],
    }]
    assert edited["inserted_segment"]["minutes"] == 7
    assert edited["inserted_segment"]["purpose"].startswith("Попросить ученика")
    assert applied["segments"][0] == plan["original_segments"][0]
    assert applied["segments"][-1] == plan["original_segments"][-1]
    assert applied["adaptation_history"][0]["cuts"] == edited["cuts"]


def test_teacher_review_route_passes_edited_time_plan_to_tutor_core(isolated_copy_app, monkeypatch):
    from types import SimpleNamespace
    from app.ai_lab import tutor_core

    app, _db, actor_id, student_id, _lesson_id = isolated_copy_app
    received = {}

    def capture_review(actor, proposal_id, decision, **kwargs):
        received.update(actor=actor, proposal_id=proposal_id, decision=decision, **kwargs)
        return SimpleNamespace(result_json={})

    monkeypatch.setattr(tutor_core, "review_tutor_proposal", capture_review)
    monkeypatch.setattr(tutor_core, "_require_synthetic_profile_access", lambda *_args: None)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(actor_id)
        session["_fresh"] = True
        session["sandbox_role"] = "tutor"

    response = client.post(
        f"/teacher/students/{student_id}/adaptive-learning",
        data={
            "action": "review",
            "proposal_id": "401",
            "decision": "accepted",
            "stage_minutes_guided_practice": "33",
            "stage_minutes_tutor_evidence_check": "7",
            "stage_purpose": "Проверить новый вариант и попросить объяснить решение.",
        },
    )

    assert response.status_code == 302
    assert received == {
        "actor": actor_id,
        "proposal_id": 401,
        "decision": "accepted",
        "teacher_focus_text": None,
        "exercise_roles": None,
        "stage_minutes": {"guided_practice": 33, "tutor_evidence_check": 7},
        "stage_purpose": "Проверить новый вариант и попросить объяснить решение.",
    }


@pytest.mark.parametrize(
    "stage_minutes,stage_purpose,match",
    [
        ({"opening": 8, "tutor_evidence_check": 2}, None, "только явно гибкие"),
        ({"guided_practice": 35, "tutor_evidence_check": 7}, "Проверить новый пример и объяснение решения.", "полностью компенсироваться"),
        ({"guided_practice": 33, "tutor_evidence_check": 7}, "коротко", "от 20 до 500"),
        ({"unknown_stage": 30, "tutor_evidence_check": 10}, None, "только явно гибкие"),
    ],
)
def test_teacher_time_plan_edits_reject_protected_or_inconsistent_changes(stage_minutes, stage_purpose, match):
    from app.ai_lab.course_adapter import apply_teacher_time_plan_edits

    with pytest.raises(ValueError, match=match):
        apply_teacher_time_plan_edits(
            _safe_time_plan(), action="diagnostic_without_mastery_claim",
            stage_minutes=stage_minutes, stage_purpose=stage_purpose,
        )


def test_tutor_apply_exposes_verified_bank_task_and_rollback_hides_it_again(isolated_copy_app):
    import json
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
    from core.db_models import LearningTrajectory, Lesson, LearningTrajectoryVersion

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        task, link, exercise, plan = _hidden_platform_exercise(db, lesson)
        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
            evidence_refs=["synthetic-fixture:event:confirmed"], exercise_snapshot=exercise, time_plan=plan,
        )
        db.session.commit()

        copy = db.session.get(LearningTrajectory, 5)
        template = db.session.get(LearningTrajectory, 4)
        updated = json.loads(db.session.get(Lesson, lesson_id).studio_scenario)
        assert change["task_visibility_change"] == {
            "lesson_task_id": link.lesson_task_id, "task_id": task.task_id, "before": False, "after": True,
        }
        assert link.is_visible_to_student is True
        assert link.is_answer_visible_to_student is False
        assert copy.current_version == 2 and template.current_version == 1
        assert updated["segments"][-2]["exercise_id"] == f"task:{task.task_id}"
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 1
        with pytest.raises(ValueError, match="изменилась после предложения"):
            apply_tutor_copy_adjustment(
                actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
                lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
                evidence_refs=["synthetic-fixture:event:confirmed"], exercise_snapshot=exercise, time_plan=plan,
            )

        restored = rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        db.session.commit()
        assert restored["restored_task_visibility"]["is_visible_to_student"] is False
        assert link.is_visible_to_student is False
        assert copy.current_version == 3 and template.current_version == 1
        assert db.session.get(Lesson, lesson_id).studio_scenario == change["old_scenario"]


def test_time_adaptation_uses_and_restores_course_editor_pedagogy_contract(isolated_copy_app):
    import json
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
    from app.ai_lab.tutor_core import _lesson_time_segments
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        trajectory = db.session.get(LearningTrajectory, 5)
        trajectory.current_version = 3
        db.session.add_all([
            LearningTrajectoryVersion(
                course_id=5, version_number=version,
                reason=f"Synthetic historical course version {version}",
                created_by_user_id=actor_id,
                snapshot={"kind": "synthetic_history_fixture", "version": version},
            )
            for version in (1, 2)
        ])
        lesson = db.session.get(Lesson, lesson_id)
        _task, _link, exercise, plan = _hidden_platform_exercise(
            db, lesson, course_version=3, task_id=1911,
        )
        original_contract = json.loads(lesson.studio_scenario)
        original_agenda = "\n".join(
            f"{item['minutes']} мин — {item['title']}" for item in original_contract["segments"]
        )
        lesson.studio_scenario = original_agenda
        lesson.review_summaries = {
            "_studio": {"agenda": []},
            "_tutor_core_pedagogy": original_contract,
        }
        db.session.flush()

        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=3,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
            evidence_refs=["synthetic-fixture:event:confirmed"],
            exercise_snapshot=exercise, time_plan=plan,
        )
        db.session.commit()

        adapted = db.session.get(Lesson, lesson_id)
        adapted_contract = adapted.review_summaries["_tutor_core_pedagogy"]
        assert adapted.studio_scenario == original_agenda
        assert adapted_contract["segments"] == plan["proposed_segments"]
        assert adapted_contract["objective"] == original_contract["objective"]
        assert adapted_contract["criteria"] == original_contract["criteria"]
        assert adapted_contract["prerequisites"] == original_contract["prerequisites"]
        observed_segments, status = _lesson_time_segments(
            {"studio_scenario": adapted.studio_scenario,
             "pedagogical_structure": adapted_contract}, adapted.duration,
        )
        assert status == "structured_json"
        assert [item["id"] for item in observed_segments] == [item["id"] for item in plan["proposed_segments"]]
        assert sum(item["minutes"] for item in observed_segments) == adapted.duration

        apply_snapshot = LearningTrajectoryVersion.query.filter_by(
            course_id=5, version_number=3,
        ).one()
        assert apply_snapshot.snapshot["pedagogical_structure"] == original_contract
        assert db.session.get(LearningTrajectory, 5).current_version == 4

        rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        db.session.commit()
        restored = db.session.get(Lesson, lesson_id)
        assert restored.studio_scenario == original_agenda
        assert restored.review_summaries["_tutor_core_pedagogy"] == original_contract
        rollback_snapshot = LearningTrajectoryVersion.query.filter_by(
            course_id=5, version_number=4,
        ).one()
        assert rollback_snapshot.snapshot["pedagogical_structure"] == adapted_contract
        assert db.session.get(LearningTrajectory, 5).current_version == 5
        assert [row.version_number for row in LearningTrajectoryVersion.query.filter_by(
            course_id=5,
        ).order_by(LearningTrajectoryVersion.version_number.asc()).all()] == [1, 2, 3, 4]


def test_rollback_refuses_to_hide_a_task_after_student_activity(isolated_copy_app):
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
    from core.db_models import Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _, link, exercise, plan = _hidden_platform_exercise(db, lesson, task_id=1902)
        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
            evidence_refs=["synthetic-fixture:event:confirmed"], exercise_snapshot=exercise, time_plan=plan,
        )
        db.session.commit()
        link.student_answer = "7"
        db.session.commit()

        with pytest.raises(ValueError, match="появилась попытка"):
            rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        assert link.is_visible_to_student is True


def test_copy_adjustment_rejects_wrong_skill_unallowlisted_copy_and_tampered_rollback(isolated_copy_app):
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
    from core.db_models import LearningTrajectory, Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        with pytest.raises(ValueError, match="не связан"):
            apply_tutor_copy_adjustment(
                actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
                lesson_id=lesson_id, skill_id="exam-skill:14", action="targeted_diagnostic_and_review",
                evidence_refs=["synthetic-event:1"],
            )
        assert apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=6, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="targeted_diagnostic_and_review",
            evidence_refs=["synthetic-event:1"],
            exercise_snapshot=_verified_exercise_snapshot(),
        ) is None

        _set_structured_lesson_plan(db.session.get(Lesson, lesson_id))
        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="targeted_diagnostic_and_review",
            evidence_refs=["synthetic-event:1"],
            exercise_snapshot=_verified_exercise_snapshot(),
            time_plan=_safe_time_plan(),
        )
        db.session.commit()
        lesson = db.session.get(Lesson, lesson_id)
        lesson.studio_scenario += "\nВнешнее изменение."
        db.session.commit()
        with pytest.raises(ValueError, match="изменился после применения"):
            rollback_tutor_copy_adjustment(actor_id=actor_id, change=change)
        assert db.session.get(LearningTrajectory, 5).current_version == 2


def test_baseline_diagnostic_can_be_applied_without_a_mastery_claim(isolated_copy_app):
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment
    from core.db_models import Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        _set_structured_lesson_plan(db.session.get(Lesson, lesson_id))
        change = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
            evidence_refs=["platform-submission:501:attempt:1:task:505"],
            exercise_snapshot=_verified_exercise_snapshot(),
            time_plan=_safe_time_plan(),
        )
        db.session.commit()

        lesson = db.session.get(Lesson, lesson_id)
        assert change["new_course_version"] == 2
        assert "10 минут" in lesson.studio_scenario
        assert "освоение" in lesson.studio_scenario


def test_unlinked_synthetic_tutor_cannot_apply_copy_adjustment(isolated_copy_app, monkeypatch):
    from app.ai_lab.course_adapter import apply_tutor_copy_adjustment
    from core.db_models import Lesson, User

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.utils.relationship_scope.can_user_access_student", lambda *_args, **_kwargs: False)
    with app.app_context():
        actor = db.session.get(User, actor_id)
        actor.role = "tutor"
        _set_structured_lesson_plan(db.session.get(Lesson, lesson_id))
        with pytest.raises(ValueError, match="разрешённой связи"):
            apply_tutor_copy_adjustment(
                actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
                lesson_id=lesson_id, skill_id="exam-skill:13", action="diagnostic_without_mastery_claim",
                evidence_refs=["synthetic-event:unlinked-tutor"],
                exercise_snapshot=_verified_exercise_snapshot(), time_plan=_safe_time_plan(),
            )


def test_active_course_assignment_by_allowlisted_teacher_enters_copy_allowlist(isolated_copy_app, monkeypatch):
    from app.ai_lab.course_adapter import _allowed_copy_ids
    from core.db_models import LearningTrajectory

    app, db, actor_id, student_id, _lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)
    with app.app_context():
        db.session.add(LearningTrajectory(
            course_id=8, is_template=False, student_id=student_id, parent_course_id=4,
            created_by_user_id=actor_id, title="Новая штатно назначенная копия", status="active",
        ))
        db.session.flush()
        assert _allowed_copy_ids() == {5, 8}
        db.session.add(LearningTrajectory(
            course_id=9, is_template=False, student_id=student_id, parent_course_id=4,
            created_by_user_id=99, title="Копия неизвестного автора", status="active",
        ))
        db.session.flush()
        assert _allowed_copy_ids() == {5, 8}


def test_master_bound_task_resolves_only_to_matching_assigned_copy_lesson(isolated_copy_app, monkeypatch):
    from app.ai_lab import tutor_core
    from app.ai_lab.analytics import _synthetic_course_task_binding, _synthetic_master_task_link
    from app.ai_lab.course_adapter import compare_course_task_semantics
    from app.ai_lab.platform_homework import _allowlisted_task_author_ids, _task_fingerprint
    from app.task_bank.answer_safety import answer_appears_in_labeled_example
    from core.db_models import ExamSkill, Lesson, LessonTask, LearningTrajectory, Student, Tasks, TrajectoryModule, User
    import json

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)
    with app.app_context():
        app.config.update(
            AI_LAB_PLATFORM_TEST_ACTOR_IDS=str(actor_id),
            AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS=str(actor_id),
            AI_LAB_PLATFORM_TEST_USER_IDS="12",
        )
        monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
        target = db.session.get(Lesson, lesson_id)
        db.session.get(ExamSkill, 13).mastery_criteria = [
            {"key": "boundary", "label": "Проверяет границу", "evidence": "Граничный результат совпал."}
        ]
        source_module = TrajectoryModule(course_id=4, title="Шаблонный модуль")
        db.session.add(source_module)
        db.session.flush()
        scenario = json.dumps({"contract": "boostudy.lesson-pedagogy.v1", "segments": []})
        source = Lesson(
            student_id=None, learning_trajectory_id=4, course_module_id=source_module.module_id,
            course_order_index=10, status="planned", topic=target.topic, duration=target.duration,
            lesson_format=target.lesson_format, content=target.content, homework=target.homework,
            studio_scenario=scenario, skills=list(target.skills),
        )
        target.studio_scenario = scenario
        db.session.add(source)
        db.session.flush()
        binding = {
            "contract": "boostudy.synthetic-course-source-skill.v1",
            "source_course_id": 4, "source_course_version": 1,
            "source_lesson_id": source.lesson_id, "source_lesson_order_index": 10,
            "skill_id": "exam-skill:13", "topic_code": "ege.inf.synthetic.lesson.v1",
            "criterion_id": "boundary", "task_fingerprint": "pending",
        }
        task = Tasks(
            task_id=905, task_number=99, bank_category="synthetic_adaptive_draft",
            prototype_status="expert_approved",
            source_key="boostudy.synthetic.adaptive-v1/master-bound-test",
            created_by_id=actor_id, content_html="<p>Проверьте границу.</p>", answer="2", max_score=1,
            is_active=True,
            answer_spec={"type": "short_answer", "grading_mode": "exact",
                         "synthetic_course_skill_binding": binding},
        )
        db.session.add(task)
        db.session.flush()
        binding = {**binding, "task_fingerprint": _task_fingerprint(task)}
        task.answer_spec = {"type": "short_answer", "grading_mode": "exact",
                            "synthetic_course_skill_binding": binding}
        db.session.add_all([
            LessonTask(lesson_id=source.lesson_id, task_id=task.task_id, assignment_type="homework",
                      is_visible_to_student=False),
            LessonTask(lesson_id=target.lesson_id, task_id=task.task_id, assignment_type="homework",
                      is_visible_to_student=False),
        ])
        db.session.flush()
        assert _allowlisted_task_author_ids() == {actor_id}
        assert task.is_active
        assert task.created_by_id == actor_id
        assert task.bank_category == "synthetic_adaptive_draft"
        assert task.source_key.startswith("boostudy.synthetic.adaptive-v1/")
        assert task.answer_spec["type"] == "short_answer"
        assert task.answer_spec["grading_mode"] == "exact"
        assert task.answer_spec["synthetic_course_skill_binding"]["contract"] == \
            "boostudy.synthetic-course-source-skill.v1"
        mapped = _synthetic_master_task_link(task, binding, db.session.get(LearningTrajectory, 5), target)
        assert mapped

        source_scenario = json.loads(source.studio_scenario)
        target.studio_scenario = json.dumps({
            **source_scenario,
            "tutor_core_adaptive_focus": {"teacher_note": "Изменён только фокус"},
            "adaptation_history": [{"contract": "boostudy.tutor-core-guided-focus.v1"}],
        })
        assert _synthetic_master_task_link(task, binding, db.session.get(LearningTrajectory, 5), target)
        role_scenario = {**source_scenario, "exercises": [{"task_id": task.task_id, "role": "homework"}]}
        source.studio_scenario = json.dumps(role_scenario)
        target.studio_scenario = json.dumps(role_scenario)
        target.studio_scenario = json.dumps({
            **role_scenario, "exercises": [{"task_id": task.task_id, "role": "classwork"}],
        })
        assert _synthetic_master_task_link(task, binding, db.session.get(LearningTrajectory, 5), target)
        source.studio_scenario = json.dumps(source_scenario)
        target.studio_scenario = json.dumps({**source_scenario, "segments": [{"title": "Изменённый этап"}]})
        assert _synthetic_master_task_link(task, binding, db.session.get(LearningTrajectory, 5), target) is None
        target.studio_scenario = json.dumps(source_scenario)

        structure = {
            "contract": "boostudy.lesson-pedagogy.v1",
            "segments": [{"id": "guided_practice", "duration_minutes": 15}],
            "criteria": [{"id": "boundary", "title": "Проверка границы"}],
            "exercises": [{
                "id": f"task:{task.task_id}", "source_type": "platform_task",
                "task_id": task.task_id, "title": "Новый вариант для диагностики",
                "topic_code": binding["topic_code"], "criterion_ids": ["boundary"],
                "segment_id": "guided_practice", "assessment_method": "platform_exact_answer",
                "role": "diagnostic", "selection_priority": 1,
                "verification_scope": "Только этот конечный вариант графа.",
                "evidence_limitations": "Один вариант не доказывает общее освоение.",
            }],
        }
        structure_json = json.dumps(structure, ensure_ascii=False)
        source.studio_scenario = structure_json
        target.studio_scenario = structure_json
        assert f"exam-skill:{int(mapped[0].skill_id)}" == "exam-skill:13"
        assert mapped[1] == "boundary" and mapped[1] in {"boundary"}
        assert mapped[0].topic_code == structure["exercises"][0]["topic_code"]
        exercise = structure["exercises"][0]
        assert exercise["source_type"] == "platform_task"
        assert exercise["assessment_method"] == "platform_exact_answer"
        assert bool(
            mapped
            and f"exam-skill:{int(mapped[0].skill_id)}" == "exam-skill:13"
            and str(mapped[1]) in {str(item) for item in exercise["criterion_ids"]}
            and str(mapped[1]) == str(binding.get("criterion_id") or "")
            and str(mapped[0].topic_code or "") == str(exercise.get("topic_code") or "")
        )
        assert not LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=task.task_id).one().is_visible_to_student
        assert not answer_appears_in_labeled_example(task.content_html, task.answer)
        db.session.flush()
        candidate = tutor_core._verified_lesson_task_candidates(
            {"lesson_id": target.lesson_id, "pedagogical_structure": structure},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id=f"platform-student:{student_id}", student_id=student_id,
        )[0]
        assert candidate["task_id"] == task.task_id
        assert candidate["criterion_ids"] == ["boundary"]
        assert candidate["previous_usage"]["status"] == "not_used"
        target_link = LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=task.task_id).one()
        target_link.is_visible_to_student = True
        db.session.flush()
        assert tutor_core._verified_lesson_task_candidates(
            {"lesson_id": target.lesson_id, "pedagogical_structure": structure},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id=f"platform-student:{student_id}", student_id=student_id,
        ) == []
        target_link.is_visible_to_student = False
        original_content = target.content
        target.content = "Структура копии отличается от базового урока."
        db.session.flush()
        assert tutor_core._verified_lesson_task_candidates(
            {"lesson_id": target.lesson_id, "pedagogical_structure": structure},
            course_id=5, course_version=1, skill_id="exam-skill:13",
            profile_id=f"platform-student:{student_id}", student_id=student_id,
        ) == []
        target.content = original_content
        db.session.flush()

        from app.ai_lab.course_adapter import _validated_exercise_sequence
        from core.db_models import LessonTask
        second_binding = {**binding, "criterion_id": "boundary", "task_fingerprint": "pending"}
        second = Tasks(
            task_id=1906, task_number=100, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/master-bound-sequence-test",
            created_by_id=actor_id, content_html="<p>Сравните второй граничный вариант.</p>",
            answer="3", max_score=1, is_active=True,
            answer_spec={"type": "short_answer", "grading_mode": "exact",
                         "synthetic_course_skill_binding": second_binding},
        )
        db.session.add(second)
        db.session.flush()
        second_binding = {**second_binding, "task_fingerprint": _task_fingerprint(second)}
        second.answer_spec = {"type": "short_answer", "grading_mode": "exact",
                              "synthetic_course_skill_binding": second_binding}
        sequence_structure = {**structure, "exercises": [
            {**structure["exercises"][0], "role": "classwork"},
            {**structure["exercises"][0], "id": "task:1906", "task_id": 1906,
             "title": "Домашняя задача", "role": "homework"},
        ]}
        source.studio_scenario = json.dumps(sequence_structure, ensure_ascii=False)
        target.studio_scenario = json.dumps(sequence_structure, ensure_ascii=False)
        db.session.add_all([
             LessonTask(lesson_id=source.lesson_id, task_id=second.task_id,
                       assignment_type="homework", is_visible_to_student=False),
            LessonTask(lesson_id=target.lesson_id, task_id=second.task_id,
                       assignment_type="homework", is_visible_to_student=True),
        ])
        first_link = LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=task.task_id).one()
        first_link.assignment_type = "classwork"
        first_link.is_visible_to_student = True
        sequence = [
            {"task_id": task.task_id, "task_fingerprint": _task_fingerprint(task),
             "current_role": "classwork", "criterion_ids": ["boundary"],
             "course_skill_id": "exam-skill:13", "topic_code": binding["topic_code"]},
            {"task_id": second.task_id, "task_fingerprint": _task_fingerprint(second),
             "current_role": "homework", "criterion_ids": ["boundary"],
             "course_skill_id": "exam-skill:13", "topic_code": binding["topic_code"]},
        ]
        updated, role_changes, criterion = _validated_exercise_sequence(
            target, db.session.get(LearningTrajectory, 5), "exam-skill:13", sequence,
            {task.task_id: "homework", second.task_id: "classwork"},
        )
        assert criterion == "boundary"
        assert {row["to"] for row in role_changes} == {"classwork", "homework"}
        assert {item["task_id"]: item["role"] for item in updated["exercises"]} == {
            task.task_id: "homework", second.task_id: "classwork",
        }
        assert LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=task.task_id).one().assignment_type == "classwork"

        student = db.session.get(Student, student_id)
        app.config.update(
            AI_LAB_PLATFORM_TEST_ACTOR_IDS=f"{actor_id},13",
            AI_LAB_PLATFORM_TEST_TASK_AUTHOR_IDS=str(actor_id),
        )
        db.session.add(User(id=13, username="synthetic_tutor_actor", role="tutor", is_active=True))
        db.session.flush()
        resolved = _synthetic_course_task_binding(
            task, target.lesson_id, student, int(student.user_id), 13,
            assessment_method="automatic_answer_checker", expected_answer="2", max_score=1,
        )
        assert resolved["course_id"] == 5
        assert resolved["lesson_id"] == target.lesson_id
        assert resolved["semantic_compatibility"]["status"] == "compatible"
        from app.ai_lab.course_adapter import apply_tutor_copy_adjustment, rollback_tutor_copy_adjustment
        first_link = LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=task.task_id).one()
        second_link = LessonTask.query.filter_by(lesson_id=target.lesson_id, task_id=second.task_id).one()
        applied = apply_tutor_copy_adjustment(
            actor_id=actor_id, course_id=5, student_id=student_id, expected_version=1,
            lesson_id=target.lesson_id, skill_id="exam-skill:13",
            action="exercise_sequence_adjustment", evidence_refs=["synthetic-event:history-1"],
            exercise_sequence=sequence,
            exercise_roles={task.task_id: "homework", second.task_id: "classwork"},
        )
        assert applied["selected_exercise_id"] is None
        assert applied["new_course_version"] == 2
        db.session.commit()
        assert first_link.assignment_type == "homework"
        assert second_link.assignment_type == "classwork"
        assert db.session.get(LearningTrajectory, 5).current_version == 2
        restored = rollback_tutor_copy_adjustment(actor_id=actor_id, change=applied)
        db.session.commit()
        assert restored["restored_course_version"] == 3
        assert first_link.assignment_type == "classwork"
        assert second_link.assignment_type == "homework"
        assert db.session.get(LearningTrajectory, 4).current_version == 1
        assert db.session.get(LearningTrajectory, 5).current_version == 3
        persisted_binding = (task.answer_spec or {}).get("synthetic_course_skill_binding")
        assert persisted_binding["task_fingerprint"] == _task_fingerprint(task)
        assert _synthetic_master_task_link(
            task, persisted_binding, db.session.get(LearningTrajectory, 5), target,
        ) is not None
        assert _synthetic_master_task_link(
            task, binding, db.session.get(LearningTrajectory, 5), target,
        ) is not None
        from app.ai_lab.course_adapter import _course_evidence_semantics_snapshot
        current_semantics = _course_evidence_semantics_snapshot(
            course_id=5, course_version=3, lesson=target,
        )
        assert persisted_binding["contract"] == "boostudy.synthetic-course-source-skill.v1"
        assert _synthetic_master_task_link(
            task, persisted_binding, db.session.get(LearningTrajectory, 5), target,
        ) is not None
        assert any(item.get("task_id") == task.task_id for item in current_semantics["entries"]), (
            current_semantics["entries"], sorted(_allowlisted_task_author_ids()),
        )
        assert _synthetic_course_task_binding(
            task, target.lesson_id, student, int(student.user_id), student.user_id,
            assessment_method="automatic_answer_checker", expected_answer="2", max_score=1,
        ) is None
        semantic = compare_course_task_semantics(
            course_id=5, source_version=1, lesson_id=target.lesson_id,
            skill_id="exam-skill:13", criterion_id="boundary", task_id=task.task_id,
            task_fingerprint=binding["task_fingerprint"],
        )
        assert semantic["status"] == "compatible", semantic

        target.content = "Структура индивидуального урока изменилась."
        db.session.flush()
        assert _synthetic_course_task_binding(
            task, target.lesson_id, student, int(student.user_id), actor_id,
            assessment_method="automatic_answer_checker", expected_answer="2", max_score=1,
        ) is None

        from core.db_models import LessonTask
        publish_binding = {**binding, "task_fingerprint": "pending"}
        publish_task = Tasks(
            task_id=906, task_number=99, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/assignment-route-test",
            created_by_id=actor_id, content_html="<p>Проверьте новый вариант.</p>", answer="2", max_score=1,
            is_active=True,
            answer_spec={"type": "short_answer", "grading_mode": "exact",
                         "synthetic_course_skill_binding": publish_binding},
        )
        db.session.add(publish_task)
        db.session.flush()
        publish_binding["task_fingerprint"] = _task_fingerprint(publish_task)
        publish_task.answer_spec = {
            "type": "short_answer", "grading_mode": "exact",
            "synthetic_course_skill_binding": publish_binding,
        }
        db.session.add_all([
            LessonTask(lesson_id=source.lesson_id, task_id=publish_task.task_id, assignment_type="homework",
                       is_visible_to_student=False),
            LessonTask(lesson_id=target.lesson_id, task_id=publish_task.task_id, assignment_type="homework",
                       is_visible_to_student=False),
        ])
        target.content = original_content
        db.session.flush()
        monkeypatch.setattr("app.assignments.routes.audit_logger.log", lambda *args, **kwargs: None)
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(actor_id)
            session['_fresh'] = True
            session['sandbox_role'] = 'tutor'
        assignment_payload = {
            "title": "Synthetic acceptance — linked lesson task",
            "description": "Synthetic acceptance test; not an expert judgment.",
            "type": "homework",
            "deadline": "2030-01-01T00:00:00Z",
            "lesson_id": lesson_id,
            "synthetic_course_id": 5,
            "synthetic_course_version": 3,
            "recipientIds": [student_id],
            "tasks": [{"task_id": publish_task.task_id, "max_score": 1}],
        }
        published = client.post('/assignments/distribute', json=assignment_payload)
        assert published.status_code == 201, published.get_json()

        from core.db_models import Assignment, Submission
        assignment = db.session.get(Assignment, published.get_json()['assignment_id'])
        assert assignment.lesson_id == lesson_id
        assert Submission.query.filter_by(
            assignment_id=assignment.assignment_id, student_id=student_id
        ).count() == 1

        target.content = "Изменённый план урока, несовместимый с исходной привязкой."
        db.session.flush()
        stale = client.post('/assignments/distribute', json=assignment_payload)
        assert stale.status_code == 409, stale.get_json()
        assert Assignment.query.filter_by(title=assignment_payload['title']).count() == 1
        target.content = original_content


def test_assigned_copy_is_selected_and_multiple_active_copies_are_ambiguous(isolated_copy_app):
    from app.ai_lab.course_adapter import resolve_assigned_synthetic_copy
    from core.db_models import LearningTrajectory

    app, db, _actor_id, student_id, _lesson_id = isolated_copy_app
    with app.app_context():
        historical = LearningTrajectory(
            course_id=7, is_template=False, student_id=student_id, parent_course_id=None,
            title="Историческая фикстура", status="active",
        )
        db.session.add(historical)
        db.session.commit()

        selected = resolve_assigned_synthetic_copy(student_id)
        assert selected["status"] == "resolved"
        assert selected["copy"].course_id == 5

        second_copy = LearningTrajectory(
            course_id=8, is_template=False, student_id=student_id, parent_course_id=4,
            title="Вторая назначенная копия", status="active",
        )
        db.session.add(second_copy)
        app.config["AI_LAB_SYNTHETIC_COURSE_COPY_IDS"] = "5,8"
        db.session.commit()

        ambiguous = resolve_assigned_synthetic_copy(student_id)
        assert ambiguous["status"] == "ambiguous_active_copies"
        assert ambiguous["copy"] is None
        assert ambiguous["eligible_ids"] == [5, 8]

        second_copy.status = "archived"
        db.session.commit()
        selected_again = resolve_assigned_synthetic_copy(student_id)
        assert selected_again["status"] == "resolved"
        assert selected_again["copy"].course_id == 5


def test_platform_profile_uses_assigned_copy_over_student_linked_fixture(isolated_copy_app, monkeypatch):
    from app.ai_lab import analytics, platform_homework, provider, tutor_core
    from core.db_models import LearningTrajectory

    app, db, actor_id, student_id, _lesson_id = isolated_copy_app
    monkeypatch.setattr(provider, "is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr(platform_homework, "_allowlisted_user_ids", lambda: {12})
    monkeypatch.setattr(analytics, "all_analytics_evidence", lambda **_kwargs: [])
    with app.app_context():
        db.session.add(LearningTrajectory(
            course_id=7, is_template=False, student_id=student_id, parent_course_id=None,
            title="Историческая фикстура", status="active",
        ))
        db.session.commit()

        cases = tutor_core._platform_profile_cases(actor_id)

    assert len(cases) == 1
    assert cases[0]["course_copy_id"] == 5
    assert cases[0]["curriculum_resolution"]["status"] == "resolved"


def test_homework_from_historical_fixture_is_excluded_from_active_copy_evidence(isolated_copy_app):
    from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION
    from app.ai_lab.tutor_core import _platform_profile_case
    from core.db_models import LearningTrajectory

    app, db, _actor_id, student_id, _lesson_id = isolated_copy_app
    event = {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": "platform-submission:historical:attempt:1:task:1",
        "subject_id": "platform-student:12",
        "source_module": "ai_homework",
        "source_record_id": "submission:historical",
        "occurred_at": "2026-10-22T10:00:00+00:00",
        "evidence_status": "technical_confirmed",
        "assignment": {"id": "platform-assignment:historical", "version": 1},
        "topic_ids": [],
        "skill_ids": ["exam-skill:1", "skill.inf.relational-query"],
        "error_codes": [],
        "limitations": [],
        "outcome": {"score": 1, "maximum": 1, "status": "complete"},
        "criteria": [{
            "criterion_id": "historical-task:1", "skill_id": "exam-skill:1",
            "earned": 1, "maximum": 1, "status": "met",
            "evidence_status": "technical_confirmed", "reason": "Техническая проверка фикстуры.",
            "source_refs": ["submission:historical:answer:1"],
        }],
        "provenance": {
            "source_ref": "platform-submission:historical:attempt:1:task:1",
            "synthetic_fixture_binding": {
                "fixture_run_key": "tutorcore31_acceptance_20261024",
                "fixture_key": "sql-relational-query",
                "knowledge_stable_key": "ege.inf.sql-relational-query.v1",
                "knowledge_version": 2,
                "knowledge_title": "SQL grouping synthetic fixture",
                "knowledge_status": "source_checked",
                "knowledge_source_titles": ["Synthetic SQL reference"],
                "knowledge_content_sha256": "a" * 64,
                "task_id": 1,
                "task_content_sha256": "b" * 64,
                "source_key": "boostudy.synthetic.tutorcore31.v1/tutorcore31_acceptance_20261024/sql-relational-query",
                "course_id": 7,
                "course_version": 1,
                "lesson_id": 9,
                "skill_key": "skill.inf.relational-query",
            },
        },
    }

    with app.app_context():
        copy = db.session.get(LearningTrajectory, 5)
        event["provenance"]["synthetic_fixture_binding"]["course_id"] = int(copy.course_id) + 1000
        case = _platform_profile_case("platform-student:12", [event], student_id, copy)

    assert len(case["evidence"]) == 1
    assert case["evidence"][0]["curriculum_eligibility"] == "excluded"
    assert case["evidence"][0]["curriculum_exclusion_reason"] == "historical_fixture_course_mismatch"
    assert case["evidence"][0]["skill_evidence_use"] == "not_used_for_course_skill_state"
    assert case["source_refs"] == []
    assert case["skill_summary"]["status"] == "insufficient_data"
    assert case["proposal"]["action"] == "maintain_plan"

    from app.ai_lab.tutor_core31 import _event_summary
    event_summary = _event_summary(event, case["evidence"][0])
    assert event_summary["curriculum_eligibility"] == "excluded"
    assert event_summary["curriculum_mapping_reason"] == "Историческая синтетическая фикстура относится к другой копии курса."


def test_skill_resolution_is_generic_and_rejects_unmapped_practice_ids():
    from app.ai_lab.skill_identity import resolve_course_skill_ids
    from types import SimpleNamespace

    graph_skill = SimpleNamespace(skill_id=41, topic_code="ege.inf.graph.optimal-paths.v1", is_active=True)
    mapped, details = resolve_course_skill_ids(
        ["ege.inf.graph.optimal-paths.v1", "skill.inf.graph-degree"], [graph_skill],
    )

    assert mapped == ["exam-skill:41"]
    assert details[0]["method"] == "canonical_topic_code"
    assert details[1]["status"] == "unmapped_source_skill"
    assert "точный topic_code" in details[1]["reason"]


def test_tutor_core_skill_history_uses_catalog_title_instead_of_technical_id(isolated_copy_app):
    from app.ai_lab.tutor_core31 import _skill_state

    app, _db, _actor_id, _student_id, _lesson_id = isolated_copy_app
    row = {
        "result": "met", "assistance_level": "independent", "task_key": "synthetic-task-1",
        "event_id": "synthetic-event-1", "assistance_source_kind": "recorded",
    }
    with app.app_context():
        state = _skill_state("exam-skill:13", [row])
    assert state["display_title"] == "Синтетический навык"
    assert state["display_title"] != state["skill_id"]


def test_answer_evaluation_history_keeps_current_manual_correction_and_superseded_result(isolated_copy_app):
    from app.assignments.evaluation_history import current_answer_evaluation, record_answer_evaluation
    from core.db_models import Answer, AnswerEvaluationRevision

    app, db, actor_id, _student_id, _lesson_id = isolated_copy_app
    with app.app_context():
        answer = Answer(answer_id=701, submission_id=702, assignment_task_id=703, value="synthetic")
        db.session.add(answer)
        db.session.flush()
        automatic = record_answer_evaluation(
            answer, method="automatic_answer_checker", actor_user_id=actor_id,
            score=0, max_score=1, is_correct=False,
        )
        manual = record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id,
            score=1, max_score=1, is_correct=True, teacher_comment="Исправлено преподавателем.",
        )
        same_manual = record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id,
            score=1, max_score=1, is_correct=True, teacher_comment="Исправлено преподавателем.",
        )
        db.session.commit()

        assert same_manual.revision_id == manual.revision_id
        assert automatic.state == "superseded"
        assert automatic.superseded_at is not None
        assert current_answer_evaluation(answer.answer_id).revision_id == manual.revision_id
        assert AnswerEvaluationRevision.query.filter_by(answer_id=answer.answer_id).count() == 2

        voided = record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id,
            score=None, max_score=1, is_correct=None, state="voided",
        )
        db.session.commit()

        assert voided.state == "voided"
        assert current_answer_evaluation(answer.answer_id) is None
        assert AnswerEvaluationRevision.query.filter_by(answer_id=answer.answer_id).count() == 3


def test_tutor_evidence_uses_current_manual_revision_and_excludes_voided_grade(isolated_copy_app, monkeypatch):
    from datetime import datetime, timezone
    from app.ai_lab import analytics
    from app.ai_lab import tutor_core
    from app.assignments.evaluation_history import record_answer_evaluation
    from core.db_models import (Answer, Assignment, AssignmentTask, ExamSkill, LearningTrajectory,
                                Submission, SubmissionAttempt, Tasks, User)

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    app.config.update(AI_LAB_PLATFORM_HOMEWORK_ENABLED=True, AI_LAB_PLATFORM_TEST_USER_IDS="12")
    task_id, assignment_id, assignment_task_id, submission_id, answer_id = 901, 902, 903, 904, 905
    source_key = "synthetic:adaptive-v1:ipv4-homework:v1"
    binding = {
        "task_id": task_id, "content_fingerprint": "f" * 64, "source_key": source_key,
        "course_id": 4, "course_version": 1, "lesson_id": lesson_id, "skill_id": "exam-skill:13",
        "knowledge_stable_key": "synthetic.adaptive.ipv4.v1", "knowledge_version": 1,
        "knowledge_content_sha256": "a" * 64,
    }
    monkeypatch.setattr("app.ai_lab.knowledge_base.source_checked_platform_task_bindings", lambda: [binding])
    now = datetime.now(timezone.utc)

    with app.app_context():
        task = Tasks(task_id=task_id, task_number=901, bank_category="synthetic_tutor_core",
                     content_html="Synthetic only: определить адрес сети.", answer="42",
                     source_key=source_key, content_fingerprint="f" * 64, created_by_id=actor_id,
                     answer_spec={"type": "integer", "grading_mode": "auto"}, max_score=1)
        assignment = Assignment(assignment_id=assignment_id, title="Synthetic only · homework",
                                assignment_type="homework", deadline=now, created_by_id=actor_id,
                                lesson_id=lesson_id)
        assignment_task = AssignmentTask(assignment_task_id=assignment_task_id, assignment_id=assignment_id,
                                         task_id=task_id, max_score=1, requires_manual_grading=True)
        submission = Submission(submission_id=submission_id, assignment_id=assignment_id,
                                student_id=student_id, status="GRADED", submitted_at=now)
        answer = Answer(answer_id=answer_id, submission_id=submission_id,
                        assignment_task_id=assignment_task_id, value="42", is_correct=False,
                        score=0, max_score=1)
        attempt = SubmissionAttempt(submission_id=submission_id, attempt_no=1, status="GRADED",
                                   submitted_at=now, total_score=0, max_score=1)
        db.session.add_all([task, assignment, assignment_task, submission, answer, attempt])
        db.session.flush()
        record_answer_evaluation(answer, method="automatic_answer_checker", actor_user_id=None,
                                 score=0, max_score=1, is_correct=False)
        corrected = record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id, score=1, max_score=1,
            is_correct=True, teacher_comment="Синтетический ручной пересмотр.",
        )
        actor = db.session.get(User, actor_id)
        actor.role = "tutor"
        db.session.commit()

        current = analytics.stored_platform_homework_evidence(actor_user_id=actor_id)
        event = next(item for item in current if item["source_record_id"] == f"submission:{submission_id}")
        assert event["evidence_status"] == "expert_confirmed"
        assert event["outcome"]["score"] == 1
        assert event["provenance"]["evaluation_revision"]["revision_no"] == corrected.revision_no == 2
        assert event["provenance"]["evaluation_revision"]["actor_user_id"] == actor_id
        copy = db.session.get(LearningTrajectory, 5)
        active_case = tutor_core._platform_profile_case("platform-student:12", current, student_id, copy)
        assert active_case["evidence"][0]["curriculum_eligibility"] == "eligible"
        assert active_case["evidence"][0]["lesson_evidence_scope"] == "lesson_criteria_changed"
        assert active_case["evidence"][0]["version_compatibility"]["status"] == "unverified"
        assert active_case["current_lesson_evidence_count"] == 0
        assert active_case["skill_summary"]["confirmed_evidence"] == 0
        assert active_case["skill_summary"]["status"] == "insufficient_data"
        outsider = User(id=13, username="unlisted_synthetic_tutor", role="tutor", is_active=True)
        db.session.add(outsider)
        db.session.commit()
        assert analytics.stored_platform_homework_evidence(actor_user_id=outsider.id) == []
        course_skill = db.session.get(ExamSkill, 13)
        original_criteria = course_skill.mastery_criteria
        course_skill.mastery_criteria = [{"key": "changed-after-assignment"}]
        db.session.commit()
        changed_criteria_case = tutor_core._platform_profile_case(
            "platform-student:12", [event], student_id, copy,
        )
        assert changed_criteria_case["current_lesson_evidence_count"] == 0
        assert changed_criteria_case["evidence"][0]["lesson_evidence_scope"] == "lesson_criteria_changed"
        assert changed_criteria_case["evidence"][0]["skill_history_use"] == "retained_as_item_observation_for_stable_skill"
        course_skill.mastery_criteria = original_criteria
        db.session.commit()
        stale_event = {
            **event,
            "event_id": "platform-submission:905:attempt:1:task:901",
            "course_context": {**event["course_context"], "course_version": 2},
        }
        stale_case = tutor_core._platform_profile_case(
            "platform-student:12", [stale_event], student_id, copy,
        )
        assert stale_case["current_lesson_evidence_count"] == 0
        assert stale_case["evidence"][0]["curriculum_eligibility"] == "eligible"
        assert stale_case["evidence"][0]["skill_history_use"] == "retained_as_item_observation_for_stable_skill"
        assert stale_case["evidence"][0]["lesson_evidence_scope"] == "older_course_version_skill_history_only"

        voided = record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id,
            score=None, max_score=1, is_correct=None, state="voided",
        )
        db.session.commit()
        after_void = analytics.stored_platform_homework_evidence(actor_user_id=actor_id)
        voided_event = next(item for item in after_void
                            if item["source_record_id"] == f"submission:{submission_id}")
        assert voided.state == "voided"
        assert voided_event["evidence_status"] == "insufficient_data"
        assert voided_event["outcome"]["score"] is None
        assert voided_event["skill_ids"] == []
        assert voided_event["provenance"]["evaluation_revision"]["state"] == "voided"
        assert voided_event["provenance"]["evaluation_revision"]["revision_no"] == 3
        voided_case = tutor_core._platform_profile_case("platform-student:12", after_void, student_id, copy)
        assert voided_case["skill_summary"]["confirmed_evidence"] == 0
        assert voided_case["skill_summary"]["status"] == "insufficient_data"
        assert db.session.get(LearningTrajectory, 5).current_version == 1


def test_synthetic_course_homework_keeps_numeric_lesson_context(isolated_copy_app, monkeypatch):
    from datetime import datetime, timezone
    from app.ai_lab import analytics, tutor_core
    from app.assignments.evaluation_history import record_answer_evaluation
    from core.db_models import (Answer, Assignment, AssignmentTask, LearningTrajectory,
                                Submission, SubmissionAttempt, Tasks)

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    app.config.update(AI_LAB_PLATFORM_HOMEWORK_ENABLED=True, AI_LAB_PLATFORM_TEST_USER_IDS="12")
    binding = {
        "contract": "boostudy.synthetic-course-task-binding.v1",
        "task_id": 911, "task_fingerprint": "e" * 64,
        "task_content_sha256": "f" * 64,
        "course_id": 5, "course_version": 1, "lesson_id": lesson_id,
        "skill_id": "exam-skill:13", "topic_code": "ege.inf.synthetic.lesson.v1",
        "criterion_id": "route_cost", "pedagogical_status": "not_pedagogically_approved",
    }
    monkeypatch.setattr("app.ai_lab.knowledge_base.source_checked_platform_task_bindings", lambda: [])
    monkeypatch.setattr(analytics, "_synthetic_course_task_binding", lambda *_args, **_kwargs: binding)
    now = datetime.now(timezone.utc)

    with app.app_context():
        task = Tasks(
            task_id=911, task_number=911, bank_category="synthetic_adaptive_draft",
            content_html="Synthetic only: найти стоимость кратчайшего пути.", answer="5",
            source_key="boostudy.synthetic.adaptive-v1/graph-optimal-paths/homework",
            content_fingerprint="f" * 64,
            created_by_id=actor_id, answer_spec={"type": "short_answer"}, max_score=1,
        )
        assignment = Assignment(
            assignment_id=912, title="Synthetic only · graph homework",
            assignment_type="homework", deadline=now, created_by_id=actor_id,
            lesson_id=lesson_id,
        )
        assignment_task = AssignmentTask(
            assignment_task_id=913, assignment_id=assignment.assignment_id,
            task_id=task.task_id, max_score=1, requires_manual_grading=True,
        )
        submission = Submission(
            submission_id=914, assignment_id=assignment.assignment_id,
            student_id=student_id, status="GRADED", submitted_at=now,
        )
        answer = Answer(
            answer_id=915, submission_id=submission.submission_id,
            assignment_task_id=assignment_task.assignment_task_id,
            value="5", is_correct=True, score=1, max_score=1,
        )
        attempt = SubmissionAttempt(
            submission_id=submission.submission_id, attempt_no=1, status="GRADED",
            submitted_at=now, total_score=1, max_score=1,
        )
        db.session.add_all([task, assignment, assignment_task, submission, answer, attempt])
        db.session.flush()
        record_answer_evaluation(
            answer, method="teacher_manual", actor_user_id=actor_id,
            score=1, max_score=1, is_correct=True,
        )
        db.session.commit()

        events = analytics.stored_platform_homework_evidence(actor_user_id=actor_id)
        event = next(item for item in events if item["source_record_id"] == "submission:914")
        assert event["course_context"]["contract"] == "boostudy.synthetic-homework-course-context.v1"
        assert event["course_context"]["course_id"] == 5
        assert event["course_context"]["course_version"] == 1
        assert event["course_context"]["lesson_id"] == lesson_id
        assert event["course_context"]["course_skill_id"] == "exam-skill:13"
        assert event["skill_ids"] == []
        assert event["criteria"][0]["status"] == "insufficient_data"
        assert event["provenance"]["synthetic_course_task_binding"]["course_id"] == 5
        assert event["provenance"]["synthetic_course_task_binding"]["course_version"] == 1
        assert event["provenance"]["synthetic_course_task_binding"]["lesson_id"] == lesson_id
        assert event["provenance"]["synthetic_course_task_binding"]["criterion_id"] == "route_cost"

        copy = db.session.get(LearningTrajectory, 5)
        case = tutor_core._platform_profile_case("platform-student:12", events, student_id, copy)
        assert case["current_lesson_evidence_count"] == 0
        assert case["evidence"][0]["curriculum_eligibility"] == "eligible"
        assert case["evidence"][0]["lesson_evidence_scope"] == "bound_but_rejected_by_lesson_evidence_checks"
        assert case["evidence"][0]["version_compatibility"] is None
        assert case["skill_summary"]["confirmed_evidence"] == 0


def test_synthetic_lesson_homework_assignment_is_version_bound_and_idempotent(isolated_copy_app, monkeypatch):
    from datetime import timedelta

    from app.ai_lab import analytics
    from app.ai_lab.platform_homework import _task_fingerprint
    from app import db
    from core.db_models import (Assignment, AssignmentTask, ExamSkill, Lesson, LessonTask, Student,
                                LearningTrajectory, Submission, Tasks, utc_now)

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    app.config.update(AI_LAB_PLATFORM_HOMEWORK_ENABLED=True)
    skill_id = 13
    criterion_id = "synthetic_check"
    expected_answer = "SYNTHETIC-PASS-42"
    with app.app_context():
        skill = db.session.get(ExamSkill, skill_id)
        skill.mastery_criteria = [{
            "key": criterion_id,
            "label": "Определяет результат для заданного случая",
            "evidence": "Ответ совпадает с точной проверкой для этого варианта.",
        }]
        task = Tasks(
            task_number=9918,
            bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/test/lesson-homework",
            content_html="<p>Классная · Введите контрольный результат для выбранного synthetic-маршрута.</p>",
            answer=expected_answer,
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
            max_score=1,
            created_by_id=actor_id,
        )
        db.session.add(task)
        db.session.flush()
        binding = {
            "contract": "boostudy.synthetic-course-skill.v1",
            "course_id": 5,
            "course_version": 1,
            "lesson_id": lesson_id,
            "skill_id": f"exam-skill:{skill_id}",
            "topic_code": "ege.inf.synthetic.lesson.v1",
            "criterion_id": criterion_id,
            "task_fingerprint": _task_fingerprint(task),
        }
        task.answer_spec = {
            "type": "short_answer",
            "grading_mode": "exact",
            "synthetic_course_skill_binding": binding,
        }
        db.session.add(LessonTask(
            lesson_id=lesson_id,
            task_id=task.task_id,
            assignment_type="homework",
            status="pending",
            is_visible_to_student=True,
            is_answer_visible_to_student=False,
        ))
        task_id = int(task.task_id)
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(actor_id)
        session["_fresh"] = True
        session["sandbox_role"] = "creator"

    lesson_redirect = client.get(f"/lesson/{lesson_id}/homework-tasks")
    assert lesson_redirect.status_code == 302
    assert "synthetic_course_id=5" in lesson_redirect.location
    builder = client.get(lesson_redirect.location)
    assert builder.status_code == 200
    builder_html = builder.get_data(as_text=True)
    assert '"course_version": 1' in builder_html
    assert '"assignment_type": "homework"' in builder_html
    assert '"assignment_type": "homework"' in builder_html

    payload = {
        "title": "Synthetic acceptance — работа урока 81",
        "type": "homework",
        "deadline": (utc_now() + timedelta(days=2)).isoformat(),
        "lesson_id": lesson_id,
        "synthetic_course_id": 5,
        "synthetic_course_version": 1,
        "recipientIds": [student_id],
        "tasks": [{"task_id": task_id, "max_score": 1}],
    }
    with app.app_context():
        task = db.session.get(Tasks, task_id)
        valid_spec = dict(task.answer_spec)
        invalid_binding = {**binding, "criterion_id": "unknown_criterion"}
        task.answer_spec = {**valid_spec, "synthetic_course_skill_binding": invalid_binding}
        db.session.commit()
    invalid_criterion = client.post("/assignments/distribute", json=payload)
    assert invalid_criterion.status_code == 409
    with app.app_context():
        task = db.session.get(Tasks, task_id)
        task.answer_spec = valid_spec
        db.session.commit()

        task.content_html = "<p>Условие изменено после создания привязки.</p>"
        db.session.commit()
    stale_fingerprint = client.post("/assignments/distribute", json=payload)
    assert stale_fingerprint.status_code == 409
    with app.app_context():
        task = db.session.get(Tasks, task_id)
        task.content_html = "<p>Классная · Введите контрольный результат для выбранного synthetic-маршрута.</p>"
        db.session.commit()

    wrong_recipient = client.post("/assignments/distribute", json={
        **payload, "recipientIds": [student_id + 1],
    })
    assert wrong_recipient.status_code == 403
    assigned = client.post("/assignments/distribute", json=payload)
    assert assigned.status_code == 201, assigned.get_json()
    assignment_id = assigned.get_json()["assignment_id"]
    repeated = client.post("/assignments/distribute", json=payload)
    assert repeated.status_code == 200, repeated.get_json()
    assert repeated.get_json()["assignment_id"] == assignment_id
    assert repeated.get_json()["already_assigned"] is True

    with app.app_context():
        assert Assignment.query.filter_by(lesson_id=lesson_id, is_active=True).count() == 1
        assignment = db.session.get(Assignment, assignment_id)
        assert assignment.lesson_id == lesson_id
        assert {row.task_id for row in assignment.tasks} == {task_id}
        submission = Submission.query.filter_by(
            assignment_id=assignment_id, student_id=student_id,
        ).one()
        submission_id = int(submission.submission_id)
        copy = db.session.get(LearningTrajectory, 5)
        copy.current_version = 2
        db.session.commit()
    stale = client.post("/assignments/distribute", json=payload)
    assert stale.status_code == 409
    assert "версия" in stale.get_json()["error"].casefold()
    with app.app_context():
        db.session.get(LearningTrajectory, 5).current_version = 1
        db.session.commit()

    with client.session_transaction() as session:
        session["_user_id"] = "12"
        session["_fresh"] = True
        session["sandbox_role"] = "student"
    student_list = client.get("/submissions")
    assert student_list.status_code == 200
    assert payload["title"] in student_list.get_data(as_text=True)
    student_workspace = client.get(f"/submissions/{submission_id}", follow_redirects=True)
    assert student_workspace.status_code == 200
    student_html = student_workspace.get_data(as_text=True)
    assert expected_answer not in student_html
    assert "Введите контрольный результат" in student_html

    assert client.post(f"/submissions/{submission_id}/start").status_code == 200
    with app.app_context():
        assignment_task_id = AssignmentTask.query.filter_by(assignment_id=assignment_id).one().assignment_task_id
    assert client.put(f"/submissions/{submission_id}/autosave", json={
        "answers": [{"assignment_task_id": assignment_task_id, "value": expected_answer}],
    }).status_code == 200
    submitted = client.post(f"/submissions/{submission_id}/submit", json={})
    assert submitted.status_code == 200, submitted.get_json()

    with app.app_context():
        from app.ai_lab import tutor_core
        projected_task = LessonTask.query.filter_by(
            lesson_id=lesson_id,
            task_id=task_id,
            assignment_type="homework",
            is_error_review=False,
        ).one()
        assert projected_task.status == "graded"
        assert projected_task.student_submission == expected_answer
        assert projected_task.submission_correct is True
        assert projected_task.is_answer_visible_to_student is False

        from app.ai_lab import database_safety
        from app.assignments.routes import _sync_synthetic_lesson_task_projection
        before_projection = (
            projected_task.status,
            projected_task.student_submission,
            projected_task.submission_correct,
        )
        with monkeypatch.context() as unsafe_context:
            unsafe_context.setattr(database_safety, "has_verified_safe_ai_lab_db", lambda: False)
            assert _sync_synthetic_lesson_task_projection(db.session.get(Submission, submission_id)) == 0
        assert before_projection == (
            projected_task.status,
            projected_task.student_submission,
            projected_task.submission_correct,
        )

        with client.session_transaction() as session:
            session["_user_id"] = str(actor_id)
            session["_fresh"] = True
            session["sandbox_role"] = "creator"
        returned = client.post(f"/submissions/{submission_id}/grade", json={
            "scores": [{"assignment_task_id": assignment_task_id, "score": 1}],
            "return_assignment_task_ids": [assignment_task_id],
            "status": "RETURNED",
        })
        assert returned.status_code == 200, returned.get_json()
        with app.app_context():
            assert db.session.get(Submission, submission_id).status == "RETURNED"
            assert LessonTask.query.filter_by(
                lesson_id=lesson_id,
                task_id=task_id,
                assignment_type="homework",
            ).one().status == "returned"

        regraded = client.post(f"/submissions/{submission_id}/grade", json={
            "scores": [{"assignment_task_id": assignment_task_id, "score": 1}],
            "reviewed_assignment_task_ids": [assignment_task_id],
            "status": "GRADED",
        })
        assert regraded.status_code == 200, regraded.get_json()
        with app.app_context():
            assert db.session.get(Submission, submission_id).status == "GRADED"
            assert LessonTask.query.filter_by(
                lesson_id=lesson_id,
                task_id=task_id,
                assignment_type="homework",
            ).one().status == "graded"

        evidence = analytics.stored_platform_homework_evidence(actor_user_id=actor_id)
        event = next(item for item in evidence if item["source_record_id"] == f"submission:{submission_id}")
        assert event["course_context"]["course_id"] == 5
        assert event["course_context"]["course_version"] == 1
        assert event["course_context"]["lesson_id"] == lesson_id
        assert event["criteria"][0]["criterion_id"] == criterion_id
        platform_user_id = int(db.session.get(Student, student_id).user_id)
        case = tutor_core._platform_profile_case(f"platform-student:{platform_user_id}", evidence, student_id,
                                                 db.session.get(LearningTrajectory, 5))
        assert any(item.get("event_id") == event["event_id"]
                   for item in case["evidence"])


def test_source_course_bound_homework_updates_copy_lesson_projection(isolated_copy_app, monkeypatch):
    from datetime import timedelta
    import json

    from app import db
    from app.ai_lab.analytics import _synthetic_master_task_link
    from app.ai_lab.platform_homework import _task_fingerprint
    from app.assignments.routes import _sync_synthetic_lesson_task_projection
    from core.db_models import (
        Answer, Assignment, AssignmentTask, ExamSkill, Lesson, LessonTask,
        LearningTrajectory, Submission, Tasks, TrajectoryModule, utc_now,
    )

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    app.config.update(AI_LAB_PLATFORM_HOMEWORK_ENABLED=True)
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    task_answer = "SYNTHETIC-SOURCE-BOUND-7"

    with app.app_context():
        target = db.session.get(Lesson, lesson_id)
        target.homework_status = "assigned_not_done"
        target_skill = db.session.get(ExamSkill, 13)
        target_skill.mastery_criteria = [{
            "key": "boundary", "label": "Проверяет границу", "evidence": "Точный ответ совпал.",
        }]
        scenario = json.dumps({"contract": "boostudy.lesson-pedagogy.v1", "segments": []})
        target.studio_scenario = scenario
        source_module = TrajectoryModule(course_id=4, title="Базовый модуль")
        db.session.add(source_module)
        db.session.flush()
        source = Lesson(
            student_id=None, learning_trajectory_id=4, course_module_id=source_module.module_id,
            course_order_index=target.course_order_index, status="planned", topic=target.topic,
            duration=target.duration, lesson_format=target.lesson_format, content=target.content,
            homework=target.homework, studio_scenario=scenario,
            skills=list(target.skills),
        )
        task = Tasks(
            task_number=9921, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/test/source-bound-projection",
            content_html="<p>Проверьте граничный результат.</p>", answer=task_answer,
            answer_spec={"type": "short_answer", "grading_mode": "exact"},
            max_score=1, created_by_id=actor_id,
        )
        db.session.add_all([source, task])
        db.session.flush()
        binding = {
            "contract": "boostudy.synthetic-course-source-skill.v1",
            "source_course_id": 4, "source_course_version": 1,
            "source_lesson_id": source.lesson_id,
            "source_lesson_order_index": source.course_order_index,
            "skill_id": "exam-skill:13", "topic_code": target_skill.topic_code,
            "criterion_id": "boundary", "task_fingerprint": _task_fingerprint(task),
        }
        task.answer_spec = {
            "type": "short_answer", "grading_mode": "exact",
            "synthetic_course_skill_binding": binding,
        }
        db.session.add_all([
            LessonTask(lesson_id=source.lesson_id, task_id=task.task_id,
                      assignment_type="homework", is_visible_to_student=False),
            LessonTask(lesson_id=target.lesson_id, task_id=task.task_id,
                      assignment_type="homework", status="pending", is_visible_to_student=True),
        ])
        assignment = Assignment(
            title="Synthetic acceptance — привязка базового задания",
            assignment_type="homework", deadline=utc_now() + timedelta(days=2),
            created_by_id=actor_id, lesson_id=lesson_id, is_active=True,
        )
        db.session.add(assignment)
        db.session.flush()
        assignment_task = AssignmentTask(
            assignment_id=assignment.assignment_id, task_id=task.task_id, max_score=1,
        )
        submission = Submission(
            assignment_id=assignment.assignment_id, student_id=student_id, status="GRADED",
        )
        db.session.add_all([assignment_task, submission])
        db.session.flush()
        answer = Answer(
            submission_id=submission.submission_id,
            assignment_task_id=assignment_task.assignment_task_id,
            value=task_answer, is_correct=True, score=1, max_score=1,
        )
        db.session.add(answer)
        db.session.flush()

        assert _synthetic_master_task_link(
            task, binding, db.session.get(LearningTrajectory, 5), target,
        )
        assert _sync_synthetic_lesson_task_projection(submission) == 1
        projection = LessonTask.query.filter_by(
            lesson_id=lesson_id, task_id=task.task_id, assignment_type="homework",
        ).one()
        assert projection.status == "graded"
        assert projection.student_submission == task_answer
        assert projection.submission_correct is True
        assert target.homework_status == "assigned_done"

        answer.needs_revision = True
        db.session.flush()
        assert _sync_synthetic_lesson_task_projection(submission) == 1
        assert projection.status == "graded"
        assert answer.needs_revision is False

        answer.is_correct = False
        db.session.flush()
        assert _sync_synthetic_lesson_task_projection(submission) == 1
        assert projection.submission_correct is False
        assert target.homework_status == "assigned_not_done"

        answer.is_correct = True
        submission.status = "RETURNED"
        answer.needs_revision = True
        db.session.flush()
        assert _sync_synthetic_lesson_task_projection(submission) == 1
        assert projection.status == "returned"
        assert projection.student_submission == task_answer
        assert projection.submission_correct is True
        assert target.homework_status == "assigned_not_done"


def test_unapproved_course_task_binding_does_not_drive_lesson_diagnostic(isolated_copy_app, monkeypatch):
    import json

    from app.ai_lab import analytics, platform_homework, tutor_core
    from core.db_models import LearningTrajectory, Lesson, LessonTask, Tasks

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr(platform_homework, "_allowlisted_task_author_ids", lambda: {actor_id})
    topic_code = "ege.inf.synthetic.lesson.v1"
    profile_id = "platform-student:12"

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = lesson.skills[0]
        skill.mastery_criteria = [{
            "key": "minimum_cost", "label": "Минимальная стоимость пути",
            "evidence": "Ответ совпадает с точной стоимостью пути или корректно указывает, что пути нет.",
        }]
        lesson.studio_scenario = json.dumps({
            "contract": "boostudy.lesson-pedagogy.v1",
            "status": "synthetic_draft_not_expert_approved",
            "objective": {"id": "synthetic-objective", "text": "Проверить минимальную стоимость пути.",
                          "skill_id": "exam-skill:13"},
            "criteria": [{"id": "minimum_cost", "label": "Минимальная стоимость пути",
                          "observable_outcome": "Сравнивает допустимые маршруты и корректно отвечает при отсутствии пути.",
                          "assessment_method": "platform_exact_answer",
                          "evidence_limitations": "Проверяется только конечный граф.",
                          "exercise_ids": ["task:901"]}],
            "prerequisites": [{"id": "read_graph", "label": "Читает рёбра графа", "skill_id": None,
                               "registration_status": "unmapped_micro_skill", "status": "unknown_before_lesson",
                               "diagnostic_method": "Попросить прочитать одно ребро без подсказки."}],
            "segments": [
                {"id": "goal", "title": "Цель и модель", "minutes": 10, "mandatory": True},
                {"id": "examples", "title": "Примеры", "minutes": 20, "mandatory": True},
                {"id": "practice", "title": "Практика", "minutes": 20, "mandatory": True},
                {"id": "exit", "title": "Итог", "minutes": 10, "mandatory": True},
            ],
            "exercises": [{"id": "task:901", "source_type": "platform_task", "task_id": 901,
                           "title": "Проверка недостижимой вершины", "topic_code": topic_code,
                           "criterion_ids": ["minimum_cost"], "segment_id": "practice",
                           "assessment_method": "platform_exact_answer", "role": "homework",
                           "selection_priority": 1, "verification_scope": "Только показанный граф.",
                           "evidence_limitations": "Один вариант не доказывает освоение."}],
            "assessment_limitations": ["Конечный ответ не доказывает универсальную корректность."]
        }, ensure_ascii=False)

        previous = Tasks(
            task_id=900, task_number=900, bank_category="synthetic_adaptive_draft",
            content_html="<p>Рёбра A-B=2, B-D=4. Укажите стоимость пути A-D.</p>",
            answer="6", source_key="boostudy.synthetic.adaptive-v1/graph/previous",
            created_by_id=actor_id, answer_spec={"type": "short_answer", "grading_mode": "exact"}, max_score=1,
        )
        candidate = Tasks(
            task_id=901, task_number=901, bank_category="synthetic_adaptive_draft",
            content_html="<p>Есть только рёбра X-Y=1 и Z-W=2. Укажите минимальную стоимость пути X-W или ответьте «нет пути».</p>",
            answer="нет пути", source_key="boostudy.synthetic.adaptive-v1/graph/diagnostic",
            created_by_id=actor_id, answer_spec={"type": "short_answer", "grading_mode": "exact"}, max_score=1,
        )
        db.session.add_all([previous, candidate])
        db.session.flush()

        candidate_binding = {
            "contract": "boostudy.synthetic-course-skill.v1", "course_id": 5, "course_version": 1,
            "lesson_id": lesson_id, "skill_id": "exam-skill:13", "topic_code": topic_code,
            "criterion_id": "minimum_cost", "pedagogical_status": "synthetic_draft_not_expert_approved",
            "task_fingerprint": platform_homework._task_fingerprint(candidate),
        }
        candidate.answer_spec = {**candidate.answer_spec, "synthetic_course_skill_binding": candidate_binding}
        db.session.add_all([
            LessonTask(lesson_id=lesson_id, task_id=900, assignment_type="classwork",
                      is_visible_to_student=True, is_answer_visible_to_student=False),
            LessonTask(lesson_id=lesson_id, task_id=901, assignment_type="homework",
                      is_visible_to_student=False, is_answer_visible_to_student=False),
        ])
        db.session.flush()

        event = analytics._demo_event(
            profile_id, "lesson-classwork-attempt:1", "Synthetic graph", "exam-skill:13",
            1, 1, "lesson-classwork:81", None, "Точный ответ совпал на показанном варианте.",
        )
        event["source_module"] = "ai_classwork"
        event["source_record_id"] = "lesson-classwork-attempt:1"
        event["criteria"][0]["criterion_id"] = "minimum_cost"
        event["skill_ids"] = ["exam-skill:13"]
        event["criteria"][0].update({
            "skill_id": "exam-skill:13", "earned": 1, "status": "met",
            "evidence_status": "technical_confirmed",
            "reason": "Точный ответ подтверждён в synthetic acceptance fixture; помощь не записана.",
        })
        event["provenance"]["method"] = "BooStudy Lesson Room exact-answer check"
        copy = db.session.get(LearningTrajectory, 5)
        case = tutor_core._platform_profile_case(profile_id, [event], student_id, copy)
        db.session.commit()

    proposal = case["proposal"]
    assert case["skill_summary"]["status"] == "insufficient_data"
    assert proposal["action"] == "maintain_plan"
    assert proposal["selected_exercise"] is None
    assert "Нет текущего результата, точно связанного с навыком" in proposal["text"]
    assert case["adaptation_preview"]["will_mutate"] is False

    with app.app_context():
        candidate_link = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=901).one()
        candidate_link.is_visible_to_student = True
        db.session.commit()
        planned_case = tutor_core._platform_profile_case(profile_id, [event], student_id,
                                                          db.session.get(LearningTrajectory, 5))

    planned_proposal = planned_case["proposal"]
    assert planned_proposal["action"] == "maintain_plan"
    assert planned_proposal["selected_exercise"] is None
    assert planned_proposal["planned_exercises"] == []
    assert planned_case["adaptation_preview"]["will_mutate"] is False
    assert "Нет текущего результата, точно связанного с навыком" in planned_proposal["text"]
    assert "нет пути" not in planned_proposal["text"].casefold()

    with app.app_context():
        candidate_link = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=901).one()
        candidate_link.status = "graded"
        candidate_link.student_submission = "нет пути"
        candidate_link.submission_correct = True
        db.session.commit()
        used_case = tutor_core._platform_profile_case(
            profile_id, [event], student_id, db.session.get(LearningTrajectory, 5),
        )

    used_proposal = used_case["proposal"]
    assert used_proposal["action"] == "maintain_plan"
    assert used_proposal["selected_exercise"] is None
    assert used_proposal["refusal_code"] == "skill_mapping_missing"
    assert "Нет текущего результата, точно связанного с навыком" in used_proposal["text"]


def test_tutor_core_can_save_a_local_preview_without_calling_a_provider(isolated_copy_app, monkeypatch):
    from app.ai_lab import tutor_core
    from core.db_models import AiLabExperiment

    app, db, actor_id, _student_id, _lesson_id = isolated_copy_app
    proposal = {
        "profile_id": "platform-student:12",
        "profile_kind": "platform_synthetic",
        "label": "Синтетический ученик · ID 12",
        "student_id": 4,
        "course_copy_id": 5,
        "course_version": 1,
        "source_refs": ["platform-submission:501:attempt:1:task:505"],
        "evidence": [{"event_id": "platform-submission:501:attempt:1:task:505", "evidence_status": "technical_confirmed"}],
        "skill_summary": {"skill_id": "exam-skill:13", "status": "insufficient_data"},
        "next_lesson": {"lesson_id": 81, "skill_ids": ["exam-skill:13"]},
        "proposal": {"action": "diagnostic_without_mastery_claim", "text": "Короткая базовая диагностика.",
                     "uncertainty": "Одна задача не доказывает освоение.",
                     "time_allocation": {"adaptation_minutes": 10}},
        "knowledge_context": [],
        "limitations": ["Одна задача не доказывает освоение."],
        "can_generate": True,
    }
    monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor_id: [proposal])
    monkeypatch.setattr(tutor_core, "_attach_knowledge_context", lambda item: item)
    monkeypatch.setattr(tutor_core, "_safe_course", lambda: ({"course_version": 1}, []))

    with app.app_context():
        record = tutor_core.create_tutor_proposal(actor_id, "platform-student:12", include_model=False)

        assert record.status == "succeeded"
        assert record.provider == "local"
        assert record.model is None
        assert len(record.scenario_snapshot["review_fingerprint"]) == 64
        assert record.result_json["semantic_validation"]["status"] == "deterministic_preview"
        assert record.result_json["semantic_validation"]["model_text_visible_as_verified"] is False
        assert record.quality_json["provider_called"] is False
        assert record.input_tokens == record.output_tokens == 0
        assert AiLabExperiment.query.filter_by(actor_user_id=actor_id, provider="gigachat").count() == 0


def test_platform_evidence_uses_exact_course_binding_and_stays_insufficient_for_mastery(isolated_copy_app, monkeypatch):
    from app.ai_lab.learning_evidence import EVIDENCE_CONTRACT_VERSION
    from app.ai_lab import tutor_core
    from app.ai_lab.tutor_core import _platform_profile_case
    from core.db_models import ExamSkill, LearningTrajectory, Lesson

    app, db, _actor_id, student_id, lesson_id = isolated_copy_app
    verified_exercise = _verified_exercise_snapshot("exam-skill:1", "ege.inf.ipv4.subnet-mask.v1")
    verified_exercise.update({"exercise_id": "practice:ipv4:verified-1",
                              "source_skill_id": "skill.inf.ipv4.subnet-mask"})
    monkeypatch.setattr(tutor_core, "_verified_practice_candidates",
                        lambda *_args, **_kwargs: [verified_exercise, verified_exercise, verified_exercise])
    event_id = "platform-submission:501:attempt:1:task:230"
    event = {
        "contract_version": EVIDENCE_CONTRACT_VERSION,
        "event_id": event_id,
        "subject_id": "platform-student:12",
        "source_module": "ai_homework",
        "source_record_id": "submission:501",
        "occurred_at": "2026-10-22T10:00:00+00:00",
        "evidence_status": "technical_confirmed",
        "assignment": {"id": "platform-assignment:503", "version": 1},
        "topic_ids": [],
        "skill_ids": ["exam-skill:1", "skill.inf.ipv4.subnet-mask"],
        "error_codes": [],
        "limitations": ["Сохранённый ключ не проверялся независимо."],
        "outcome": {"score": 1, "maximum": 1, "status": "complete"},
        "criteria": [{
            "criterion_id": "assignment-task:504", "skill_id": "skill.inf.ipv4.subnet-mask",
            "earned": 1, "maximum": 1, "status": "met",
            "evidence_status": "technical_confirmed",
            "reason": "Ответ повторно совпал с сохранённым ключом.",
            "source_refs": ["submission:501:answer:502"],
        }],
        "provenance": {
            "source_ref": event_id,
            "method": "Повторная штатная проверка BooStudy",
            "platform_task_binding": {
                "knowledge_stable_key": "ege.inf.graph-table-task230-binding.v1",
                "knowledge_version": 1,
                "knowledge_content_sha256": "a" * 64,
                "task_id": 230,
                "content_fingerprint": "3e1fbe709a6fcb5429b2c4ad97ef12f4d9688a27012b53538cb429664fa86246",
                "source_key": "kompege-db:Tasks:222",
                "course_id": 4,
                "course_version": 1,
                "lesson_id": lesson_id,
                "skill_id": "exam-skill:1",
            },
        },
    }

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = ExamSkill(skill_id=1, task_number=1, title="IPv4: маска и границы сети", subject="Информатика",
                          topic_code="ege.inf.ipv4.subnet-mask.v1")
        db.session.add(skill)
        lesson.skills.clear()
        lesson.skills.append(skill)
        module = lesson.course_module
        module.learning_result = "master"
        skill.mastery_criteria = []
        lesson.homework = "На новом префиксе определить адрес сети и сверить вычисление."
        db.session.commit()
        from app.ai_lab.learning_evidence import course_skill_criteria_fingerprint
        event["criteria"][0]["skill_id"] = "exam-skill:1"
        event["course_context"] = {
            "contract": "boostudy.synthetic-homework-course-context.v1",
            "course_id": 5,
            "course_version": 1,
            "lesson_id": lesson_id,
            "course_skill_id": "exam-skill:1",
            "topic_code": "ege.inf.ipv4.subnet-mask.v1",
            "criteria_fingerprint": course_skill_criteria_fingerprint(skill.mastery_criteria),
        }
        copy = db.session.get(LearningTrajectory, 5)
        copy.learning_goal = "[AI_LAB_TUTOR_CORE3:ege-2027:v1] master"
        db.session.commit()

        blocked = _platform_profile_case("platform-student:12", [event], student_id, copy)
        assert blocked["proposal"]["action"] == "maintain_plan"
        assert blocked["proposal"]["selected_exercise"] is None
        assert blocked["proposal"]["curriculum_ready"] is False
        assert blocked["proposal"]["course_learning_goal_placeholder"] is True
        assert "incomplete_lesson_structure" in {
            item["code"] for item in blocked["proposal"]["refusal_causes"]
        }
        assert "машиночитаемая структура" in blocked["proposal"]["curriculum_blockers"][0]

        module.learning_result = "Рассчитать адрес сети и проверить границы блока по IPv4 и CIDR."
        db.session.commit()
        case = _platform_profile_case("platform-student:12", [event], student_id, copy)

        assert case["proposal"]["action"] == "maintain_plan", case["proposal"]
        assert case["skill_summary"]["status"] == "insufficient_data"
        assert case["adaptation_preview"]["will_mutate"] is False
        assert case["current_lesson_evidence_count"] == 0
        assert case["evidence"][0]["lesson_evidence_scope"] == "lesson_criteria_changed"
        assert case["proposal"]["selected_exercise"] is None
        assert case["proposal"]["time_plan"] is None

        module.learning_result = "master"
        skill.mastery_criteria = [
            {"key": "prefix_to_block", "label": "Определяет размер блока", "evidence": "Показывает значащий октет."},
            {"key": "network_and_broadcast", "label": "Находит границы сети", "evidence": "Указывает адрес сети и broadcast."},
            {"key": "transfer", "label": "Переносит способ", "evidence": "Решает пример с новым префиксом."},
        ]
        _set_structured_lesson_plan(lesson)
        db.session.commit()
        stale_criteria_case = _platform_profile_case("platform-student:12", [event], student_id, copy)
        assert stale_criteria_case["current_lesson_evidence_count"] == 0
        assert stale_criteria_case["evidence"][0]["lesson_evidence_scope"] == "lesson_criteria_changed"
        assert stale_criteria_case["evidence"][0]["skill_history_use"] == "retained_as_item_observation_for_stable_skill"
        copy.current_version = 2
        db.session.commit()
        revised_event = {
            **event,
            "event_id": "platform-submission:502:attempt:1:task:230",
            "source_record_id": "submission:502",
            "course_context": {
                **event["course_context"],
                "course_version": 2,
                "criteria_fingerprint": course_skill_criteria_fingerprint(skill.mastery_criteria),
            },
        }
        criteria_backed = _platform_profile_case("platform-student:12", [revised_event], student_id, copy)
        criteria_proposal = criteria_backed["proposal"]
        assert criteria_proposal["curriculum_ready"] is True
        assert criteria_proposal["learning_goal_source"] == "lesson_pedagogical_contract"
        assert len(criteria_proposal["objective_criteria"]) == 3
        assert criteria_proposal["prerequisites_recorded"] is True
        assert criteria_proposal["original_homework"] == lesson.homework
        assert criteria_proposal["selected_exercise"] is None
        assert criteria_proposal["exercise_alternatives"] == []
        assert criteria_backed["can_generate"] is False
        assert criteria_proposal["refusal_code"] == "skill_mapping_missing"
        assert "incomplete_lesson_structure" not in {
            item["code"] for item in criteria_proposal["refusal_causes"]
        }
        assert criteria_proposal["action"] == "maintain_plan"
        assert criteria_backed["adaptation_preview"]["will_mutate"] is False

        copy.parent_course_id = 6
        incompatible = _platform_profile_case("platform-student:12", [event], student_id, copy)
        assert incompatible["can_generate"] is False
        assert incompatible["proposal"]["action"] == "maintain_plan"


def test_lesson_pedagogy_contract_must_remain_unapproved_synthetic_draft(isolated_copy_app):
    import json
    from app.ai_lab.tutor_core import _validate_lesson_pedagogical_structure
    from core.db_models import Lesson

    app, db, _actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _set_structured_lesson_plan(lesson)
        payload = json.loads(lesson.studio_scenario)
        skill_ids = [f"exam-skill:{skill.skill_id}" for skill in lesson.skills]
        criteria = lesson.skills[0].mastery_criteria
        if isinstance(criteria, str):
            criteria = json.loads(criteria)

        structure, errors = _validate_lesson_pedagogical_structure(
            lesson.studio_scenario, duration=lesson.duration, skill_ids=skill_ids,
            mastery_criteria=criteria,
        )
        assert errors == []
        assert structure["status"] == "synthetic_draft_not_expert_approved"

        payload["status"] = "approved"
        rejected, errors = _validate_lesson_pedagogical_structure(
            json.dumps(payload), duration=lesson.duration, skill_ids=skill_ids,
            mastery_criteria=criteria,
        )
        assert rejected is None
        assert any("без экспертного утверждения" in error for error in errors)


def test_separate_pedagogy_contract_preserves_studio_agenda_and_course_snapshot(isolated_copy_app):
    import json
    from flask_login import login_user
    from app.ai_lab.tutor_core import (
        _lesson_time_segments,
        _structured_mastery_criteria,
        _validate_lesson_pedagogical_structure,
    )
    from app.courses.routes import _snapshot_course
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson, User

    app, db, actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _set_structured_lesson_plan(lesson)
        contract = json.loads(lesson.studio_scenario)
        lesson.studio_scenario = "\n".join(
            f"{segment['minutes']} мин — {segment['title']}" for segment in contract['segments']
        )
        lesson.review_summaries = {"_studio": {"agenda": []}, "_tutor_core_pedagogy": contract}
        skill = lesson.skills[0]
        normalized, errors = _validate_lesson_pedagogical_structure(
            lesson.studio_scenario,
            duration=lesson.duration,
            skill_ids=[f"exam-skill:{skill.skill_id}"],
            mastery_criteria=_structured_mastery_criteria(skill),
            pedagogical_structure=contract,
        )
        assert errors == []
        assert normalized["objective"] == contract["objective"]

        segments, status = _lesson_time_segments(
            {"studio_scenario": lesson.studio_scenario, "pedagogical_structure": contract},
            lesson.duration,
        )
        assert status == "structured_json"
        assert sum(item["minutes"] for item in segments) == lesson.duration

        course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id)
        with app.test_request_context("/"):
            login_user(db.session.get(User, actor_id))
            _snapshot_course(course, "lesson_edit")
        db.session.flush()
        snapshot = LearningTrajectoryVersion.query.filter_by(course_id=course.course_id).order_by(
            LearningTrajectoryVersion.version_number.desc()
        ).first()
        snap_lesson = next(item for item in snapshot.snapshot["lessons"] if item["id"] == lesson.lesson_id)
        assert snap_lesson["pedagogical_structure"] == contract


def test_course_pedagogy_contract_rejects_unsupported_flexible_time(isolated_copy_app):
    import json
    from app.ai_lab.tutor_core import _structured_mastery_criteria, _validate_lesson_pedagogical_structure
    from core.db_models import Lesson

    app, db, _actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _set_structured_lesson_plan(lesson)
        contract = json.loads(lesson.studio_scenario)
        contract["segments"][1]["mandatory"] = True
        skill = lesson.skills[0]

        normalized, errors = _validate_lesson_pedagogical_structure(
            json.dumps(contract), duration=lesson.duration,
            skill_ids=[f"exam-skill:{skill.skill_id}"],
            mastery_criteria=_structured_mastery_criteria(skill),
        )

        assert normalized is None
        assert any("резерв" in error.lower() for error in errors)


def test_course_learning_item_uses_only_unambiguous_lesson_skill(isolated_copy_app):
    from app.courses.routes import _ensure_lesson_learning_item
    from core.db_models import ExamSkill, LearningItem, LearningTrajectory, Lesson

    app, db, _actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id)

        _ensure_lesson_learning_item(course, lesson)
        item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).one()
        assert item.skill_id == lesson.skills[0].skill_id

        second_skill = ExamSkill(
            skill_id=14, task_number=14, title="Второй синтетический навык",
            subject="Информатика", topic_code="ege.inf.synthetic.second.v1",
        )
        db.session.add(second_skill)
        db.session.flush()
        lesson.skills = [lesson.skills[0], second_skill]
        _ensure_lesson_learning_item(course, lesson)

        assert item.skill_id is None


def test_teacher_course_lesson_form_renders_structured_pedagogy_editor(isolated_copy_app):
    from core.db_models import Lesson

    app, db, actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course_id = lesson.learning_trajectory_id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(actor_id)
        session["_fresh"] = True
    response = client.get(f"/courses/{course_id}/lessons/{lesson_id}/edit")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Учебная структура для Tutor Core" in html
    assert "studio_scenario" in html
    assert "data-segment-flexible-minutes" in html
    assert "data-segment-flexible-reason" in html
    assert "data-segment-purpose" in html
    import re
    assert re.search(
        r'<input\b(?=[^>]*\bname="course_order_index")(?=[^>]*\bstep="1")[^>]*>', html,
    )


def test_teacher_course_editor_keeps_task_choices_bound_to_their_criterion(isolated_copy_app):
    import json
    from app.courses.routes import _course_lesson_pedagogy_editor_context
    from core.db_models import LearningTrajectory, Lesson, LessonTask, Tasks

    app, db, _creator_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id)
        contract = {
            "contract": "boostudy.lesson-pedagogy.v1",
            "exercises": [
                {"id": "task:9701", "source_type": "platform_task", "task_id": 9701,
                 "criterion_ids": ["minimum_cost"]},
                {"id": "task:9702", "source_type": "platform_task", "task_id": 9702,
                 "criterion_ids": ["reachability"]},
            ],
        }
        for task_id in (9701, 9702):
            db.session.add(Tasks(task_id=task_id, task_number=task_id, content_html="Synthetic task",
                                 answer="1", max_score=1, is_active=True))
            db.session.add(LessonTask(lesson_id=lesson_id, task_id=task_id, assignment_type="classwork"))
        lesson.review_summaries = {"_tutor_core_pedagogy": contract}
        db.session.flush()

        context = _course_lesson_pedagogy_editor_context(course, lesson, [])
        options = {item["id"]: set(item["criterion_ids"]) for item in context["pedagogy_tasks"]}

        assert options == {9701: {"minimum_cost"}, 9702: {"reachability"}}


def test_teacher_lesson_edit_saves_pedagogy_and_active_skill_for_tutor_core(isolated_copy_app):
    import json
    from app.ai_lab import tutor_core
    from core.db_models import (
        LearningItem, LearningTrajectory, LearningTrajectoryVersion, Lesson, Student, User,
    )

    app, db, _creator_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        teacher = User(id=5, username="synthetic_tutor", role="tutor", is_active=True)
        student = db.session.get(Student, student_id)
        student.mentor_id = teacher.id
        lesson = db.session.get(Lesson, lesson_id)
        skill = lesson.skills[0]
        skill.mastery_criteria = [{
            "key": "minimum_cost",
            "label": "Находит минимальную стоимость",
            "evidence": "Ответ совпадает с независимым расчётом на конкретном графе.",
        }]
        _set_structured_lesson_plan(lesson)
        contract = json.loads(lesson.studio_scenario)
        course_id = lesson.learning_trajectory_id
        course_version = int(db.session.get(LearningTrajectory, course_id).current_version or 1)
        course_order_index = lesson.course_order_index
        db.session.add(teacher)
        db.session.commit()

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "5"
        session["_fresh"] = True

    response = client.post(
        f"/courses/{course_id}/lessons/{lesson_id}/edit",
        data={
            "module_id": "90",
            "topic": "Синтетический урок",
            "course_order_index": str(course_order_index or 0),
            "expected_course_version": str(course_version),
            "duration": "60",
            "lesson_format": "Теория + Практика",
            "lesson_type": "regular",
            "status": "planned",
            "studio_scenario": "Проверить цель и условие\nРазобрать новый вариант",
            "pedagogy_contract_json": json.dumps(contract, ensure_ascii=False),
            "content": "Условие, цель и материалы для самостоятельного разбора будущего занятия.",
            "homework": "Новое независимое упражнение.",
            "teacher_note": "Synthetic draft; экспертная проверка не проведена.",
            "program_change_reason": "Synthetic acceptance: уточнить содержание и проверку занятия.",
            "skill_ids": "13",
            "submit": "Сохранить урок",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course = db.session.get(LearningTrajectory, course_id)
        item = LearningItem.query.filter_by(course_id=course_id, lesson_id=lesson_id).one()
        assert [linked.skill_id for linked in lesson.skills] == [13]
        saved = lesson.review_summaries["_tutor_core_pedagogy"]
        snapshot = LearningTrajectoryVersion.query.filter_by(course_id=course_id).one()
        manual_change = lesson.review_summaries["_teacher_manual_plan_changes"][-1]

        assert item.skill_id == 13
        assert item.status == "planned"
        assert lesson.studio_scenario == "Проверить цель и условие\nРазобрать новый вариант"
        assert lesson.review_summaries["_studio"]["agenda"] == [
            {"id": "course-step-1", "title": "Проверить цель и условие", "done": False},
            {"id": "course-step-2", "title": "Разобрать новый вариант", "done": False},
        ]
        assert snapshot.reason == "teacher_manual_lesson_edit"
        assert "course_order_index" in snapshot.snapshot["lessons"][0]
        assert manual_change["source"] == "teacher_manual"
        assert manual_change["decision"] == "teacher_created_plan_change"
        assert manual_change["actor_user_id"] == 5
        assert manual_change["reason"].startswith("Synthetic acceptance")
        assert saved["status"] == "synthetic_draft_not_expert_approved"
        assert saved["criteria"][0]["id"] == "minimum_cost"
        assert saved["segments"][1]["flexible_minutes"] == 10
        assert saved["segments"][1]["flexible_reason"]
        assert snapshot.version_number == 1

        case = tutor_core._platform_profile_case(
            "platform-student:12", [], student_id, course,
        )
        proposal = case["proposal"]
        refusal_codes = {item["code"] for item in proposal.get("refusal_causes", [])}
        assert proposal["curriculum_ready"] is True, {
            "refusal_codes": sorted(refusal_codes),
            "curriculum_blockers": proposal.get("curriculum_blockers"),
        }
        assert "incomplete_lesson_structure" not in refusal_codes
        assert "skill_mapping_missing" in refusal_codes
        assert case["skill_summary"]["status"] == "insufficient_data"
        assert proposal["action"] == "maintain_plan"
        assert case["adaptation_preview"]["will_mutate"] is False


def test_learning_item_does_not_map_an_inactive_lesson_skill(isolated_copy_app):
    from app.courses.routes import _ensure_lesson_learning_item
    from core.db_models import LearningItem, LearningTrajectory, Lesson

    app, db, _actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id)
        lesson.skills[0].is_active = False

        _ensure_lesson_learning_item(course, lesson)

        item = LearningItem.query.filter_by(course_id=course.course_id, lesson_id=lesson.lesson_id).one()
        assert item.skill_id is None


def test_structured_lesson_may_assess_a_subset_of_course_skill_criteria(isolated_copy_app):
    import json
    from app.ai_lab.tutor_core import _validate_lesson_pedagogical_structure
    from core.db_models import Lesson

    app, db, _actor_id, _student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = lesson.skills[0]
        skill.mastery_criteria = [
            {"key": "minimum_cost", "label": "Находит минимальную стоимость",
             "evidence": "Сравнивает стоимость допустимых путей."},
            {"key": "reachability", "label": "Учитывает недостижимость",
             "evidence": "Отличает отсутствие пути от числовой стоимости."},
        ]
        _set_structured_lesson_plan(lesson)
        payload = json.loads(lesson.studio_scenario)
        selected_criterion = payload["criteria"][0]
        selected_exercise_id = selected_criterion["exercise_ids"][0]
        payload["criteria"] = [selected_criterion]
        payload["exercises"] = [
            item for item in payload["exercises"] if item["id"] == selected_exercise_id
        ]

        structure, errors = _validate_lesson_pedagogical_structure(
            json.dumps(payload), duration=lesson.duration,
            skill_ids=[f"exam-skill:{skill.skill_id}"],
            mastery_criteria=skill.mastery_criteria,
        )
        assert errors == []
        assert structure["criteria"] == [selected_criterion]

        payload["criteria"][0]["id"] = "invented_criterion"
        payload["exercises"][0]["criterion_ids"] = ["invented_criterion"]
        rejected, errors = _validate_lesson_pedagogical_structure(
            json.dumps(payload), duration=lesson.duration,
            skill_ids=[f"exam-skill:{skill.skill_id}"],
            mastery_criteria=skill.mastery_criteria,
        )
        assert rejected is None
        assert any("Критерии урока должны быть связаны с критериями ExamSkill" in error
                   for error in errors)


def test_teacher_review_applies_once_and_history_records_restoration(isolated_copy_app, monkeypatch):
    from app.ai_lab import tutor_core
    from app.ai_lab.tutor_core import (
        PROPOSAL_SCENARIO,
        review_tutor_proposal,
        rollback_tutor_copy_decision,
        tutor_history,
    )
    from core.db_models import AiLabExperiment, LearningTrajectory, LearningTrajectoryVersion, Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        _set_structured_lesson_plan(lesson)
        _task, task_link, selected_exercise, time_plan = _hidden_platform_exercise(db, lesson, task_id=1903)
        proposal = AiLabExperiment(
            actor_user_id=actor_id, request_key="synthetic-tutor-copy-proposal",
            scenario_id=PROPOSAL_SCENARIO, status="succeeded", provider="gigachat",
            model="synthetic-test", prompt_snapshot="synthetic test",
            scenario_snapshot={"profile_id": "platform-student:12", "profile_kind": "platform_synthetic"},
            input_snapshot={}, expected_snapshot={},
            result_json={"proposal": {
                "student_id": student_id, "course_copy_id": 5, "course_version": 1,
                "skill_summary": {"skill_id": "exam-skill:13", "status": "needs_support"},
                "next_lesson": {"lesson_id": lesson_id, "skill_ids": ["exam-skill:13"]},
                "evidence": [{"evidence_status": "technical_confirmed", "skill_ids": ["exam-skill:13"],
                              "course_skill_ids": ["exam-skill:13"],
                              "criteria": [{"skill_id": "exam-skill:13", "status": "met",
                                            "evidence_status": "technical_confirmed"}],
                              "skill_evidence_use": "criterion_observation_for_this_item_only",
                              "source_ref": "platform-submission:501:attempt:1:task:505"}],
                "proposal": {"action": "targeted_diagnostic_and_review", "text": "Десятиминутная проверка.",
                             "selected_exercise": selected_exercise,
                             "time_plan": time_plan},
            }},
        )
        live_case = {**proposal.result_json["proposal"], "profile_id": "platform-student:12"}
        proposal.scenario_snapshot["review_fingerprint"] = tutor_core._proposal_review_fingerprint(live_case)
        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor_id: [live_case])
        db.session.add(proposal)
        db.session.commit()

        decision = review_tutor_proposal(actor_id, proposal.id, "accepted")
        assert decision.result_json["course_copy_mutated"] is True
        assert decision.result_json["applied_change"]["lesson_id"] == lesson_id
        assert decision.result_json["applied_change"]["task_visibility_change"]["after"] is True
        assert task_link.is_visible_to_student is True
        assert db.session.get(LearningTrajectory, 5).current_version == 2
        assert db.session.get(LearningTrajectory, 4).current_version == 1
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 1

        repeated = review_tutor_proposal(actor_id, proposal.id, "accepted")
        assert repeated.id == decision.id
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 1

        rollback = rollback_tutor_copy_decision(actor_id, decision.id)
        assert rollback.result_json["restored"] is True
        assert db.session.get(LearningTrajectory, 5).current_version == 3
        assert task_link.is_visible_to_student is False
        assert db.session.get(LearningTrajectory, 4).current_version == 1
        assert LearningTrajectoryVersion.query.filter_by(course_id=5).count() == 2
        assert rollback_tutor_copy_decision(actor_id, decision.id).id == rollback.id

        history = tutor_history(actor_id, "platform-student:12")
        saved = next(item for item in history if item["id"] == proposal.id)
        assert saved["applied_change"]["course_id"] == 5
        assert saved["rollback_at"]


def test_teacher_accepts_exercise_sequence_with_zero_time_change(isolated_copy_app, monkeypatch):
    from copy import deepcopy
    from app.ai_lab import tutor_core
    from app.ai_lab.tutor_core import PROPOSAL_SCENARIO, TutorCoreError, review_tutor_proposal
    from core.db_models import AiLabExperiment

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    applied = {}

    def capture_apply(**kwargs):
        applied.update(kwargs)
        return {"course_id": 5, "student_id": student_id, "lesson_id": lesson_id,
                "new_course_version": 2, "action": "exercise_sequence_adjustment"}

    monkeypatch.setattr("app.ai_lab.course_adapter.apply_tutor_copy_adjustment", capture_apply)
    with app.app_context():
        skill_id = "exam-skill:13"
        criterion_id = "boundary"
        events = [
            {"event_id": "synthetic:met", "source_ref": "synthetic:met",
             "evidence_status": "technical_confirmed", "curriculum_eligibility": "eligible",
             "version_compatibility": {"status": "compatible"}, "course_skill_ids": [skill_id],
             "criteria": [{"criterion_id": criterion_id, "skill_id": skill_id,
                           "status": "met", "evidence_status": "technical_confirmed"}]},
            {"event_id": "synthetic:not-met", "source_ref": "synthetic:not-met",
             "evidence_status": "technical_confirmed", "curriculum_eligibility": "eligible",
             "version_compatibility": {"status": "compatible"}, "course_skill_ids": [skill_id],
             "criteria": [{"criterion_id": criterion_id, "skill_id": skill_id,
                           "status": "not_met", "evidence_status": "technical_confirmed"}]},
        ]
        case = {
            "profile_id": "platform-student:12", "profile_kind": "platform_synthetic",
            "student_id": student_id, "course_copy_id": 5, "course_version": 1,
            "evidence": events,
            "next_lesson": {"lesson_id": lesson_id, "duration_minutes": 60,
                            "skill_ids": [skill_id]},
            "proposal": {
                "action": "exercise_sequence_adjustment",
                "exercise_sequence_basis": {
                    "course_id": 5, "course_version": 1, "lesson_id": lesson_id,
                    "skill_id": skill_id, "criterion_id": criterion_id,
                    "event_ids": ["synthetic:met", "synthetic:not-met"],
                    "result_types": ["met", "not_met"],
                },
                "exercise_sequence": [
                    {"task_id": 501, "current_role": "classwork", "proposed_role": "homework"},
                    {"task_id": 502, "current_role": "homework", "proposed_role": "classwork"},
                ],
                "time_plan": {"status": "sequence_only_no_time_change", "total_minutes": 60,
                              "planned_lesson_minutes": 60, "adaptation_minutes": 0},
            },
        }
        record = AiLabExperiment(
            actor_user_id=actor_id, request_key="synthetic-sequence-zero-time-preview",
            scenario_id=PROPOSAL_SCENARIO, status="succeeded", provider="local",
            model="deterministic-test", prompt_snapshot="synthetic sequence preview",
            scenario_snapshot={"profile_id": case["profile_id"], "profile_kind": "platform_synthetic",
                               "course_copy_id": 5,
                               "review_fingerprint": tutor_core._proposal_review_fingerprint(deepcopy(case))},
            input_snapshot={}, expected_snapshot={}, result_json={"proposal": case},
            validation_status="deterministic_preview", quality_json={"synthetic_only": True},
        )
        db.session.add(record)
        db.session.commit()
        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor_id: [case])

        with pytest.raises(TutorCoreError) as error:
            review_tutor_proposal(actor_id, record.id, "accepted")
        assert error.value.code == "exercise_sequence_roles_missing"

        decision = review_tutor_proposal(
            actor_id, record.id, "accepted", exercise_roles={501: "homework", 502: "classwork"},
        )
        assert decision.result_json["course_copy_mutated"] is True
        assert applied["exercise_roles"] == {501: "homework", 502: "classwork"}
        assert applied["time_plan"]["adaptation_minutes"] == 0


@pytest.mark.parametrize("change", ["new_event", "revised_grade", "course_version"])
def test_acceptance_rejects_stale_platform_preview_without_mutating_copy(isolated_copy_app, monkeypatch, change):
    from copy import deepcopy
    from app.ai_lab import tutor_core
    from app.ai_lab.tutor_core import PROPOSAL_SCENARIO, TutorCoreError, review_tutor_proposal
    from core.db_models import AiLabExperiment, LearningTrajectory, Lesson

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        case = {
            "profile_id": "platform-student:12", "profile_kind": "platform_synthetic",
            "student_id": student_id, "course_copy_id": 5, "course_version": 1,
            "source_refs": ["synthetic-event:1"],
            "evidence": [{"event_id": "synthetic-event:1", "source_ref": "synthetic-event:1",
                          "evidence_status": "technical_confirmed", "score": 1, "maximum": 1,
                          "skill_ids": ["exam-skill:13"]}],
            "skill_summary": {"skill_id": "exam-skill:13", "status": "developing"},
            "next_lesson": {"lesson_id": lesson_id, "skill_ids": ["exam-skill:13"]},
            "proposal": {"action": "diagnostic_without_mastery_claim",
                         "selected_exercise": _verified_exercise_snapshot()},
        }
        snapshot = deepcopy(case)
        record = AiLabExperiment(
            actor_user_id=actor_id, request_key=f"stale-preview-{change}",
            scenario_id=PROPOSAL_SCENARIO, status="succeeded", provider="local",
            model="deterministic-test", prompt_snapshot="synthetic test",
            scenario_snapshot={"profile_id": case["profile_id"], "profile_kind": "platform_synthetic",
                               "course_copy_id": 5,
                               "review_fingerprint": tutor_core._proposal_review_fingerprint(snapshot)},
            input_snapshot={}, expected_snapshot={}, result_json={"proposal": snapshot},
            validation_status="deterministic_preview", quality_json={"synthetic_only": True},
        )
        db.session.add(record)
        db.session.commit()

        if change == "new_event":
            case["source_refs"].append("synthetic-event:2")
            case["evidence"].append({"event_id": "synthetic-event:2", "source_ref": "synthetic-event:2",
                                     "evidence_status": "technical_confirmed", "score": 0, "maximum": 1,
                                     "skill_ids": ["exam-skill:13"]})
        elif change == "revised_grade":
            case["evidence"][0]["score"] = 0
        else:
            case["course_version"] = 2
        monkeypatch.setattr(tutor_core, "_platform_profile_cases", lambda _actor_id: [case])

        with pytest.raises(TutorCoreError) as error:
            review_tutor_proposal(actor_id, record.id, "accepted")

        assert error.value.code == "adaptation_evidence_changed"
        if change == "new_event":
            client = app.test_client()
            with client.session_transaction() as session:
                session["_user_id"] = str(actor_id)
                session["_fresh"] = True
                session["sandbox_role"] = "creator"
            response = client.post(
                f"/admin/ai-lab/api/tutor-core/proposals/{record.id}/review",
                json={"decision": "accepted"},
            )
            assert response.status_code == 409
            assert response.get_json()["error_code"] == "adaptation_evidence_changed"
        rejected = review_tutor_proposal(actor_id, record.id, "rejected")
        assert rejected.input_snapshot["decision"] == "rejected"
        assert review_tutor_proposal(actor_id, record.id, "rejected").id == rejected.id
        assert db.session.get(LearningTrajectory, 5).current_version == 1
        assert db.session.get(Lesson, lesson_id).studio_scenario == "Исходный сценарий преподавателя."
        assert AiLabExperiment.query.filter_by(scenario_id="ai-tutor-core-decision").count() == 1


def test_completed_only_copy_reports_no_next_lesson(isolated_copy_app):
    from app.ai_lab.tutor_core import _platform_profile_case
    from core.db_models import LearningTrajectory, Lesson

    app, db, _actor_id, student_id, lesson_id = isolated_copy_app
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        lesson.status = "completed"
        db.session.commit()

        copy = db.session.get(LearningTrajectory, 5)
        case = _platform_profile_case("platform-student:12", [], student_id, copy)

        assert case["adaptation_preview"]["status"] == "no_next_lesson"
        assert "Завершённый урок не изменяется" in case["proposal"]["text"]
        assert case["can_generate"] is False
        assert db.session.get(Lesson, lesson_id).status == "completed"
        assert db.session.get(LearningTrajectory, 5).current_version == 1


def test_completed_synthetic_lesson_keeps_explicit_task_evidence(isolated_copy_app, monkeypatch):
    from app.ai_lab import analytics
    from core.db_models import ExamSkill, LearningTrajectory, Lesson, Student, Tasks

    app, db, actor_id, student_id, lesson_id = isolated_copy_app
    monkeypatch.setattr("app.ai_lab.database_safety.has_verified_safe_ai_lab_db", lambda: True)
    monkeypatch.setattr("app.ai_lab.provider.is_local_ai_lab_enabled", lambda: True)
    monkeypatch.setattr("app.ai_lab.platform_homework._allowlisted_user_ids", lambda: {12})
    monkeypatch.setattr("app.ai_lab.platform_homework._allowlisted_task_author_ids", lambda: {actor_id})
    monkeypatch.setattr("app.ai_lab.platform_homework._task_fingerprint", lambda _task: "a" * 64)
    monkeypatch.setattr("app.ai_lab.course_adapter._allowed_copy_ids", lambda: {5})
    monkeypatch.setattr(
        "app.ai_lab.course_adapter.resolve_assigned_synthetic_copy",
        lambda _student_id: {"status": "resolved", "copy": db.session.get(LearningTrajectory, 5)},
    )
    monkeypatch.setattr(
        "app.ai_lab.course_adapter.compare_course_task_semantics",
        lambda **_kwargs: {"status": "compatible", "matches": [], "mismatches": []},
    )

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        skill = db.session.get(ExamSkill, 13)
        skill.mastery_criteria = [{"key": "route_cost", "label": "Стоимость маршрута"}]
        lesson.status = "completed"
        task = Tasks(
            task_id=930, task_number=930, bank_category="synthetic_adaptive_draft",
            source_key="boostudy.synthetic.adaptive-v1/graph-completed-lesson",
            created_by_id=actor_id, content_html="Synthetic graph exercise", answer="5", max_score=1,
            answer_spec={
                "type": "short_answer",
                "grading_mode": "exact",
                "synthetic_course_skill_binding": {
                    "contract": "boostudy.synthetic-course-skill.v1",
                    "course_id": 5,
                    "course_version": 1,
                    "lesson_id": lesson_id,
                    "skill_id": "exam-skill:13",
                    "topic_code": "ege.inf.synthetic.lesson.v1",
                    "criterion_id": "route_cost",
                    "pedagogical_status": "not_pedagogically_approved",
                    "task_fingerprint": "a" * 64,
                },
            },
        )
        db.session.add(task)
        db.session.flush()

        result = analytics._synthetic_course_task_binding(
            task, lesson_id, db.session.get(Student, student_id), 12,
            assignment_created_by_id=actor_id, expected_answer="5", max_score=1,
        )

        assert result is not None
        assert result["lesson_id"] == lesson_id
        assert result["skill_id"] == "exam-skill:13"
        assert result["criterion_id"] == "route_cost"

        lesson.status = "cancelled"
        assert analytics._synthetic_course_task_binding(
            task, lesson_id, db.session.get(Student, student_id), 12,
            assignment_created_by_id=actor_id, expected_answer="5", max_score=1,
        ) is None


def test_creating_course_lesson_versions_the_previous_plan(isolated_copy_app):
    from core.db_models import LearningTrajectory, LearningTrajectoryVersion, Lesson

    app, db, actor_id, student_id, original_lesson_id = isolated_copy_app
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(actor_id)
        session["_fresh"] = True
        session["sandbox_role"] = "creator"

    response = client.post(
        "/courses/5/lessons/new",
        data={
            "topic": "Synthetic continuation",
            "module_id": "90",
            "course_order_index": "20",
            "duration": "60",
            "lesson_format": "Теория + Практика",
            "lesson_type": "regular",
            "status": "planned",
            "studio_scenario": "Проверить альтернативные маршруты",
            "content": "Synthetic draft lesson content",
            "homework": "Synthetic draft homework",
            "teacher_note": "Synthetic acceptance test; not expert approved",
            "skill_ids": "13",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        course = db.session.get(LearningTrajectory, 5)
        previous = LearningTrajectoryVersion.query.filter_by(course_id=5, version_number=1).one()
        lessons = Lesson.query.filter_by(learning_trajectory_id=5).order_by(Lesson.course_order_index.asc()).all()

        assert course.current_version == 2
        assert previous.reason == "lesson_create"
        assert [item["id"] for item in previous.snapshot["lessons"]] == [original_lesson_id]
        assert len(lessons) == 2
        assert lessons[0].lesson_id == original_lesson_id
        assert lessons[0].status == "planned"
        assert lessons[1].status == "planned"
        assert lessons[1].student_id == student_id
        assert [skill.skill_id for skill in lessons[1].skills] == [13]
