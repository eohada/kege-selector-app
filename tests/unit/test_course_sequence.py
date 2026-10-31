from types import SimpleNamespace

from app.courses.sequence import (
    course_sequence_state,
    lesson_is_deferred,
    record_course_sequence_decision,
    select_course_lesson_target,
    select_next_course_lesson,
    unresolved_preceding_lessons,
)


def _lesson(lesson_id, order, status, review_summaries=None):
    return SimpleNamespace(
        lesson_id=lesson_id,
        course_order_index=order,
        status=status,
        review_summaries=review_summaries or {},
    )


def test_active_lesson_wins_over_an_earlier_queued_lesson():
    earlier = _lesson(5, 1, "planned")
    active = _lesson(6, 2, "in_progress")

    target, issue = select_course_lesson_target([earlier, active])

    assert target is active
    assert issue is None


def test_multiple_active_lessons_are_reported_as_ambiguous():
    target, issue = select_course_lesson_target([
        _lesson(6, 2, "in_progress"),
        _lesson(7, 3, "in_progress"),
    ])

    assert target is None
    assert issue == "multiple_active_lessons"


def test_deferred_lesson_is_kept_in_history_but_skipped_for_next_target():
    deferred = _lesson(5, 1, "planned")
    record_course_sequence_decision(
        deferred,
        action="defer",
        reason="Проверить предпосылки перед возвратом к теме",
        actor_user_id=3,
        effective_course_version=4,
    )
    later = _lesson(6, 2, "planned")

    target, issue = select_course_lesson_target([deferred, later])

    assert lesson_is_deferred(deferred)
    assert course_sequence_state(deferred.review_summaries)["history"][0]["source"] == "teacher_manual"
    assert course_sequence_state(deferred.review_summaries)["history"][0]["effective_course_version"] == 4
    assert target is later
    assert issue is None
    assert unresolved_preceding_lessons([deferred, later], later) == []


def test_unresolved_earlier_lesson_blocks_a_later_start_until_teacher_decides():
    earlier = _lesson(5, 1, "planned")
    later = _lesson(6, 2, "planned")

    assert unresolved_preceding_lessons([earlier, later], later) == [earlier]


def test_prepare_next_selects_existing_lesson_after_active_without_creating_one():
    active = _lesson(6, 20, 'in_progress')
    future = _lesson(7, 30, 'planned')
    deferred = _lesson(5, 10, 'planned')
    record_course_sequence_decision(
        deferred, action='defer', reason='Проверить предпосылки до продолжения темы',
        actor_user_id=3, effective_course_version=2,
    )

    target, issue, blockers = select_next_course_lesson([future, active, deferred])

    assert target is future
    assert issue is None
    assert blockers == []


def test_prepare_next_reports_blocked_or_ambiguous_queue():
    active = _lesson(6, 20, 'in_progress')
    earlier = _lesson(5, 10, 'planned')
    later = _lesson(7, 30, 'planned')

    target, issue, blockers = select_next_course_lesson([active, earlier, later])

    assert target is None
    assert issue == 'unresolved_preceding_lessons'
    assert blockers == [earlier]

    target, issue, blockers = select_next_course_lesson([
        active, _lesson(8, 40, 'in_progress'), later,
    ])
    assert target is None
    assert issue == 'multiple_active_lessons'
    assert blockers == []


def test_bank_binding_accepts_cross_lesson_practice_but_not_as_independent(monkeypatch):
    from app.ai_lab import tutor_core
    from app.courses.routes import _course_task_binding

    monkeypatch.setattr(tutor_core, '_structured_mastery_criteria', lambda _skill: [{'key': 'vector_sum'}])
    skill = SimpleNamespace(skill_id=22, topic_code='math.vector.addition.v1')
    course = SimpleNamespace(course_id=8, current_version=3)
    lesson = SimpleNamespace(lesson_id=19)
    task = SimpleNamespace(
        answer='(4, 7)',
        answer_spec={
            'type': 'short_answer',
            'grading_mode': 'exact',
            'course_skill_binding': {
                'contract': 'boostudy.course-skill.v1',
                'skill_id': 'exam-skill:22',
                'topic_code': 'math.vector.addition.v1',
                'criterion_id': 'vector_sum',
                'task_fingerprint': 'sha256:source',
                'source_course_id': 4,
                'source_course_version': 1,
                'source_lesson_id': 3,
            },
        },
    )

    binding, error = _course_task_binding(task, skill, 'vector_sum', course, lesson)

    assert error is None
    assert binding['same_context'] is False
    assert binding['source_lesson_id'] == 3


def test_bank_binding_rejects_unmapped_criterion(monkeypatch):
    from app.ai_lab import tutor_core
    from app.courses.routes import _course_task_binding

    monkeypatch.setattr(tutor_core, '_structured_mastery_criteria', lambda _skill: [{'key': 'vector_sum'}])
    skill = SimpleNamespace(skill_id=22, topic_code='math.vector.addition.v1')
    task = SimpleNamespace(answer='(4, 7)', answer_spec={
        'grading_mode': 'exact',
        'course_skill_binding': {
            'contract': 'boostudy.course-skill.v1',
            'skill_id': 'exam-skill:22', 'topic_code': 'math.vector.addition.v1',
            'criterion_id': 'other', 'task_fingerprint': 'sha256:source',
            'source_course_id': 4, 'source_course_version': 1, 'source_lesson_id': 3,
        },
    })

    binding, error = _course_task_binding(
        task, skill, 'other', SimpleNamespace(course_id=8, current_version=3), SimpleNamespace(lesson_id=19),
    )

    assert binding is None
    assert error == 'Задание связано с другим критерием.'


def test_seen_or_cross_context_tasks_cannot_be_counted_as_independent():
    from app.courses.routes import _course_task_independent_allowed

    assert _course_task_independent_allowed(
        {'same_context': True, 'provenance_verified': True}, {'previously_used': False},
    )
    assert not _course_task_independent_allowed(
        {'same_context': False, 'provenance_verified': True}, {'previously_used': False},
    )
    assert not _course_task_independent_allowed(
        {'same_context': True, 'provenance_verified': True}, {'previously_used': True},
    )

