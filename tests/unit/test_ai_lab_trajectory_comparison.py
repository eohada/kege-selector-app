from app.ai_lab.trajectory_comparison import compare_lesson_plans


def test_semantic_plan_comparison_ignores_record_identifiers():
    baseline = [{
        "id": 1,
        "order": 10,
        "topic": "Кратчайший путь",
        "content": "Сравнить маршруты по стоимости.",
        "duration": 60,
        "skills": ["exam-skill:1"],
        "pedagogy": {"objective": "minimum"},
        "exercises": ["Классная задача"],
    }]
    copy = [{**baseline[0], "id": 999}]
    assert compare_lesson_plans(baseline, copy) == []


def test_semantic_plan_comparison_reports_only_changed_lesson_fields():
    baseline = [{
        "order": 10,
        "topic": "Кратчайший путь",
        "content": "Теория и одна практика.",
        "duration": 60,
        "skills": ["exam-skill:1"],
        "pedagogy": {"criteria": ["minimum_cost"]},
        "exercises": ["Классная задача"],
    }]
    copy = [{
        "order": 10,
        "topic": "Кратчайший путь с равными оптимумами",
        "content": "Теория, сравнение альтернатив и практика.",
        "duration": 70,
        "skills": ["exam-skill:1", "exam-skill:2"],
        "pedagogy": {"criteria": ["minimum_cost", "alternatives"]},
        "exercises": ["Новая проверяемая задача"],
    }]

    changes = compare_lesson_plans(baseline, copy)

    assert len(changes) == 1
    assert changes[0]["order"] == 10
    assert set(changes[0]["fields"]) == {
        "Тема занятия",
        "Учебное содержание",
        "Продолжительность",
        "Связанные навыки",
        "Цель, критерии и этапы",
        "Набор упражнений",
    }


def test_semantic_plan_comparison_reports_added_and_removed_lessons():
    changes = compare_lesson_plans(
        [{"order": 20, "topic": "Базовый урок"}],
        [{"order": 30, "topic": "Дополнительный урок"}],
    )

    assert changes == [
        {"order": 20, "title": "Базовый урок", "fields": ["Занятие отсутствует в индивидуальной программе"]},
        {"order": 30, "title": "Дополнительный урок", "fields": ["Занятие добавлено в индивидуальную программу"]},
    ]


def test_teacher_trajectory_profile_explains_when_no_future_lesson_is_selected():
    from app.ai_lab.trajectory_profile import build_teacher_trajectory_profile

    profile = build_teacher_trajectory_profile({
        "course_copy_id": 5,
        "course_version": 2,
        "current_plan": [],
        "next_lesson": None,
    })

    assert profile["status"] == "unavailable"
    assert "нет следующего урока" in profile["reason"].lower()
    assert profile["trajectory_items"] == []
