from app.ai_lab.trajectory_profile import build_teacher_trajectory_profile


def _lesson(lesson_id: int, order: int, skill_id: str = "exam-skill:10") -> dict:
    return {
        "lesson_id": lesson_id,
        "order": order,
        "title": f"Тема {order}",
        "duration_minutes": 60,
        "skill_ids": [skill_id],
        "skill_titles": [f"Навык {skill_id}"],
    }


def _case() -> dict:
    return {
        "course_copy_id": 55,
        "course_title": "Синтетическая программа",
        "course_version": 3,
        "next_lesson": {"lesson_id": 2},
        "current_plan": [_lesson(index, index) for index in range(1, 7)],
        "stable_skill_history": [{
            "course_skill_ids": ["exam-skill:10"],
            "confirmed_item_observations": 2,
            "met": 1,
            "not_met": 1,
        }],
        "evidence": [],
    }


def _event(*, event_id: str = "e1", course_id: int = 55, version: int = 3,
           lesson_id: int = 2, eligible: str = "eligible", skill_id: str = "exam-skill:10",
           status: str = "technical_confirmed", attempt_eligible: bool = True) -> dict:
    return {
        "event_id": event_id,
        "source_module": "ai_homework",
        "occurred_at": "2026-10-27T10:00:00",
        "evidence_status": status,
        "score": 1,
        "maximum": 1,
        "method": "exact_match",
        "assistance_level": None,
        "curriculum_eligibility": eligible,
        "attempt_admissibility": {"pedagogically_eligible": attempt_eligible},
        "course_context": {
            "course_id": course_id,
            "course_version": version,
            "lesson_id": lesson_id,
            "semantic_compatibility": {"status": "same_version_exact_binding"},
        },
        "version_compatibility": {"status": "same_version_exact_binding"},
        "course_skill_ids": [skill_id],
        "criteria": [{
            "skill_id": skill_id,
            "status": "met",
            "evidence_status": status,
        }],
        "curriculum_mapping_reason": "Причина недопуска",
        "reason": "Ответ совпал с эталоном.",
    }


def test_window_starts_at_official_target_and_is_limited_to_five_curriculum_items():
    case = _case()
    case["current_plan"][2]["sequence_state"] = {"state": "deferred", "reason": "Нужно вернуться позже"}
    result = build_teacher_trajectory_profile(case)

    assert result["status"] == "available"
    assert [item["lesson_id"] for item in result["trajectory_items"]] == [2, 3, 4, 5, 6]
    assert result["trajectory_items"][0]["is_selected_start"] is True
    assert all(item["is_selected_start"] is False for item in result["trajectory_items"][1:])
    assert result["trajectory_items"][1]["sequence_state_label"] == "Отложено преподавателем"
    assert result["trajectory_items"][1]["sequence_reason"] == "Нужно вернуться позже"
    assert "расписание" in result["scope_note"]


def test_history_is_skill_level_and_exact_lesson_evidence_is_narrowly_scoped():
    case = _case()
    case["evidence"] = [
        _event(),
        _event(event_id="wrong-lesson", lesson_id=3),
        _event(event_id="wrong-version", version=2),
        _event(event_id="excluded", attempt_eligible=False),
        _event(event_id="unverified", status="insufficient_data"),
    ]

    result = build_teacher_trajectory_profile(case)
    first = result["trajectory_items"][0]["skills"][0]
    second = result["trajectory_items"][1]["skills"][0]

    assert first["history_observations"] == 2
    assert first["history_met"] == 1
    assert first["history_not_met"] == 1
    assert first["direct_lesson_evidence_count"] == 1
    assert second["direct_lesson_evidence_count"] == 1
    assert "не доказывают освоение" in first["interpretation"]


def test_event_timeline_explains_excluded_attempts_without_erasing_them():
    case = _case()
    case["evidence"] = [_event(event_id="excluded", eligible="excluded", attempt_eligible=False)]

    result = build_teacher_trajectory_profile(case)
    evidence = result["evidence"][0]

    assert evidence["event_id"] == "excluded"
    assert evidence["eligibility_label"] == "Исключено из педагогических выводов"
    assert evidence["exclusion_reason"] == "Причина исключения не указана в сохранённой записи."
    assert evidence["source"] == "Домашняя работа BooStudy"


def test_ambiguous_or_missing_course_target_returns_explicit_unavailable_state():
    result = build_teacher_trajectory_profile({"course_copy_id": 55, "current_plan": []})

    assert result["status"] == "unavailable"
    assert result["trajectory_items"] == []
    assert result["reason"]
