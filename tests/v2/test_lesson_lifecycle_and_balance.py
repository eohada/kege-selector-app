import pytest
from datetime import datetime
from tests.v2.test_role_lifecycle_recovery import login_as


def _lifecycle_fixture(app, role_users, *, status='planned', initial_balance=5, linked_learning_item=False):
    from app import db
    from app.models import LearningItem, LearningTrajectory, Lesson, Student, moscow_now

    with app.app_context():
        student = Student.query.get(role_users['student_id'])
        student.lessons_balance = initial_balance

        trajectory = None
        if linked_learning_item:
            trajectory = LearningTrajectory(
                title='Synthetic lifecycle trajectory',
                student_id=student.student_id,
                created_by_user_id=role_users['tutor_id'],
                is_template=False,
            )
            db.session.add(trajectory)
            db.session.flush()

        lesson = Lesson(
            student_id=student.student_id,
            learning_trajectory_id=trajectory.course_id if trajectory else None,
            lesson_date=moscow_now(),
            duration=60,
            status=status,
            topic='Тестовый урок жизненного цикла',
        )
        db.session.add(lesson)
        db.session.flush()
        if trajectory:
            db.session.add(LearningItem(
                course_id=trajectory.course_id,
                lesson_id=lesson.lesson_id,
                item_type='lesson',
                title=lesson.topic,
                status='in_progress' if status == 'in_progress' else 'planned',
            ))
        db.session.commit()
        return lesson.lesson_id, student.student_id


def test_lesson_lifecycle_waiting_room_and_start(app, client, role_users):
    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='planned', initial_balance=3, linked_learning_item=True
    )

    # 1. Студент заходит на запланированный урок -> попадает в комнату ожидания
    login_as(client, role_users['student_user_id'], 'student')
    resp = client.get(f'/lesson/{lesson_id}/room')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'Комната ожидания урока' in html
    assert 'Ожидаем сигнал преподавателя' in html
    assert 'Запланирован' in html
    assert 'room-lesson-os' not in html

    # 2. Студент опрашивает статус урока -> status=planned, is_live=False
    status_resp = client.get(f'/lesson/{lesson_id}/status')
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data['success'] is True
    assert status_data['status'] == 'planned'
    assert status_data['is_live'] is False

    # 3. Студент не может самовольно начать урок
    start_attempt = client.post(f'/lesson/{lesson_id}/start', json={})
    assert start_attempt.status_code == 403

    # 4. Преподаватель открывает комнату -> видит кнопку "Начать урок"
    login_as(client, role_users['tutor_id'], 'tutor')
    tutor_room = client.get(f'/lesson/{lesson_id}/room')
    assert tutor_room.status_code == 200
    tutor_html = tutor_room.get_data(as_text=True)
    assert 'os-start-lesson' in tutor_html
    assert 'Начать урок' in tutor_html

    # 5. Преподаватель начинает урок через API
    start_resp = client.post(f'/lesson/{lesson_id}/start', json={})
    assert start_resp.status_code == 200
    start_data = start_resp.get_json()
    assert start_data['success'] is True
    assert start_data['status'] == 'in_progress'
    tutor_live_room = client.get(f'/lesson/{lesson_id}/room')
    assert tutor_live_room.status_code == 200
    live_room_html = tutor_live_room.get_data(as_text=True)
    assert 'id="lesson-outcome-save-btn"' in live_room_html
    assert 'id="lesson-open-completion"' in live_room_html
    assert 'id="lesson-room-close-btn"' in live_room_html
    assert 'id="lesson-conducted-confirm-check"' in live_room_html
    assert 'id="lesson-conducted-confirm-reason"' in live_room_html
    assert 'id="lesson-conducted-confirm-btn"' in live_room_html
    assert 'id="lesson-conducted-confirm-btn" type="button"' in live_room_html
    confirmation_markup = live_room_html.split('id="lesson-conducted-confirm-btn"', 1)[1].split('>', 1)[0]
    assert ' disabled' in confirmation_markup
    assert 'факт проведения подтверждается отдельно в Lesson Room' in live_room_html
    from app.lessons.routes import auto_complete_overdue_lessons
    from app.models import LearningItem, Lesson, LessonOutcome, Student
    with app.app_context():
        item = LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one()
        assert item.status == 'in_progress'

    # A newly started lesson must not expire immediately when stored timestamps
    # are read back from SQLite without timezone metadata.
    auto_complete_overdue_lessons()
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'in_progress'
        assert LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one().status == 'in_progress'
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 0
        assert student.lessons_balance == 3

    # 6. Студент опрашивает статус -> is_live=True
    login_as(client, role_users['student_user_id'], 'student')
    status_resp_after = client.get(f'/lesson/{lesson_id}/status')
    assert status_resp_after.status_code == 200
    assert status_resp_after.get_json()['status'] == 'in_progress'
    assert status_resp_after.get_json()['is_live'] is True

    # 7. Студент теперь заходит в живую комнату
    live_room = client.get(f'/lesson/{lesson_id}/room')
    assert live_room.status_code == 200
    live_html = live_room.get_data(as_text=True)
    assert 'Комната ожидания урока' not in live_html
    assert 'room-lesson-os' in live_html


def test_lesson_completion_deducts_balance_idempotently(app, client, role_users):
    from app.models import LearningItem, Lesson, LessonOutcome, Student
    from core.db_models import AuditLog

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=5, linked_learning_item=True
    )

    # Закрытие комнаты завершает только работу в комнате, не урок и не расчёт.
    login_as(client, role_users['tutor_id'], 'tutor')
    finish_resp = client.post(
        f'/lesson/{lesson_id}/studio/finish',
        json={'action': 'close_room'}
    )
    assert finish_resp.status_code == 200
    assert finish_resp.get_json()['success'] is True
    assert finish_resp.get_json()['action'] == 'room_closed'
    assert finish_resp.get_json()['status'] == 'in_progress'
    assert finish_resp.get_json()['balance_deducted'] is False

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'in_progress'
        assert lesson.balance_deducted is False
        assert LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one().status == 'in_progress'
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 0
        assert student.lessons_balance == 5
        room_events = AuditLog.query.filter_by(action='lesson.room_work_closed', entity='Lesson', entity_id=lesson_id).all()
        assert len(room_events) == 1
        assert room_events[0].user_id == role_users['tutor_id']
        assert room_events[0].get_metadata()['source'] == 'lesson_room'

    # Повторное закрытие идемпотентно и не добавляет аудит-дубликат.
    finish_again = client.post(
        f'/lesson/{lesson_id}/studio/finish',
        json={'action': 'close_room'}
    )
    assert finish_again.status_code == 200

    # Только отдельное подтверждение проведённого занятия меняет статус и баланс.
    complete_resp = client.post(f'/lesson/{lesson_id}/complete', json={
        'confirm_conducted': True,
        'confirmation_reason': 'Synthetic acceptance: classwork и Assignment 7 завершены.',
    })
    assert complete_resp.status_code == 200
    assert complete_resp.get_json()['transitioned'] is True
    assert complete_resp.get_json()['balance_charged'] is True

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'completed'
        assert lesson.balance_deducted is True
        assert LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one().status == 'done'
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 0
        assert student.lessons_balance == 4
        room_events = AuditLog.query.filter_by(action='lesson.room_work_closed', entity='Lesson', entity_id=lesson_id).all()
        assert len(room_events) == 1
        transitions = [event for event in AuditLog.query.filter_by(action='lesson.status_transition', entity='Lesson', entity_id=lesson_id).all()]
        assert transitions[-1].user_id == role_users['tutor_id']
        assert transitions[-1].get_metadata()['conducted_confirmation_reason'].startswith('Synthetic acceptance')
        assert transitions[-1].get_metadata()['source'] == 'teacher_conducted_confirmation'

    duplicate = client.post(f'/lesson/{lesson_id}/complete', json={
        'confirm_conducted': True,
        'confirmation_reason': 'Synthetic acceptance: проверка идемпотентности.',
    })
    assert duplicate.status_code == 200
    assert duplicate.get_json()['transitioned'] is False
    assert duplicate.get_json()['balance_charged'] is False
    with app.app_context():
        assert Student.query.get(student_id).lessons_balance == 4


def test_studio_free_text_does_not_set_skill_mastery(app, client, role_users):
    from app import db
    from app.models import Course, ExamSkill, LearningItem, LearningTrajectory, Lesson, StudentSkill

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=5, linked_learning_item=True
    )
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        course = db.session.get(LearningTrajectory, lesson.learning_trajectory_id)
        exam_course = Course(title='Synthetic lifecycle QA', slug='synthetic-lifecycle-qa')
        db.session.add(exam_course)
        db.session.flush()
        course.exam_course_id = exam_course.id
        skill = ExamSkill(exam_course_id=exam_course.id, task_number=991, title='Synthetic skill', is_active=True)
        db.session.add(skill)
        db.session.flush()
        item = LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one()
        item.skill_id = skill.skill_id
        db.session.add(StudentSkill(
            student_id=student_id, skill_id=skill.skill_id, mastery_percent=25, state='learning'
        ))
        db.session.commit()
        skill_id = skill.skill_id

    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/lesson/{lesson_id}/studio/finish', json={'action': 'save_outcome',
        'outcome': {'completed': ['Тема пройдена успешно'], 'repeat': [], 'homework': ''}
    })
    assert response.status_code == 200

    with app.app_context():
        from app.models import LessonOutcome
        outcome = LessonOutcome.query.filter_by(lesson_id=lesson_id).one()
        skill_state = StudentSkill.query.filter_by(student_id=student_id, skill_id=skill_id).one()
        assert outcome.covered in (None, [])
        assert outcome.mastery is None
        assert outcome.next_action is None
        assert skill_state.mastery_percent == 25
        assert skill_state.state == 'learning'


def test_lesson_complete_route_deducts_balance(app, client, role_users):
    from app.models import LearningItem, Lesson, LessonOutcome, Student
    from core.db_models import AuditLog

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=10, linked_learning_item=True
    )

    login_as(client, role_users['tutor_id'], 'tutor')
    room_closed = client.post(f'/lesson/{lesson_id}/studio/finish', json={'action': 'close_room'})
    assert room_closed.status_code == 200
    complete_resp = client.post(
        f'/lesson/{lesson_id}/complete',
        json={
            'confirm_conducted': True,
            'confirmation_reason': 'Synthetic acceptance: занятие проведено.',
        }
    )
    assert complete_resp.status_code == 200

    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        student = Student.query.get(student_id)
        assert lesson.status == 'completed'
        assert lesson.balance_deducted is True
        assert LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one().status == 'done'
        # Explicitly marking the lesson complete does not fabricate pedagogical reflection.
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 0
        assert student.lessons_balance == 9
        events = AuditLog.query.filter_by(entity="Lesson", entity_id=lesson_id).all()
        transitions = [event.get_metadata() for event in events if event.action == "lesson.status_transition"]
        deductions = [event.get_metadata() for event in events if event.action == "lesson.balance_deducted"]
        assert transitions[-1]["source"] == "teacher_conducted_confirmation"
        assert transitions[-1]["from_status"] == "in_progress"
        assert transitions[-1]["to_status"] == "completed"
        assert deductions[-1]["student_balance_before"] == 10
        assert deductions[-1]["student_balance_after"] == 9
        assert not [event for event in events if event.action == "lesson.pedagogical_outcome_saved"]

        from app.lessons.lifecycle import LessonLifecycleError, transition_lesson_status
        with pytest.raises(LessonLifecycleError, match="корректировки баланса"):
            transition_lesson_status(
                lesson, "planned", source="test_reopen", reason="must_not_reverse_charge",
            )
        assert lesson.status == "completed"
        assert student.lessons_balance == 9


def test_lesson_completion_requires_explicit_confirmation_and_teacher(app, client, role_users):
    from app.models import Lesson, Student
    from app.lessons.lifecycle import LessonLifecycleError, transition_lesson_status

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=6, linked_learning_item=True
    )
    login_as(client, role_users['tutor_id'], 'tutor')
    missing_confirmation = client.post(f'/lesson/{lesson_id}/complete', json={
        'confirm_conducted': False,
        'confirmation_reason': 'Synthetic acceptance: reason present.',
    })
    assert missing_confirmation.status_code == 400
    missing_reason = client.post(f'/lesson/{lesson_id}/complete', json={'confirm_conducted': True})
    assert missing_reason.status_code == 400
    room_still_open = client.post(f'/lesson/{lesson_id}/complete', json={
        'confirm_conducted': True,
        'confirmation_reason': 'Synthetic acceptance: room remains open.',
    })
    assert room_still_open.status_code == 409
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        assert lesson.status == 'in_progress'
        assert Student.query.get(student_id).lessons_balance == 6
        with pytest.raises(LessonLifecycleError, match='отдельного подтверждения'):
            transition_lesson_status(
                lesson, 'completed', source='unexpected_route', reason='must_not_complete',
            )
        assert lesson.status == 'in_progress'

    login_as(client, role_users['student_user_id'], 'student')
    denied = client.post(f'/lesson/{lesson_id}/complete', json={
        'confirm_conducted': True,
        'confirmation_reason': 'Synthetic acceptance: ученик не может подтвердить.',
    })
    assert denied.status_code == 403
    with app.app_context():
        assert Lesson.query.get(lesson_id).status == 'in_progress'
        assert Student.query.get(student_id).lessons_balance == 6


def test_empty_outcome_is_not_created_and_saving_outcome_does_not_complete_lesson(app, client, role_users):
    from app.models import Lesson, LessonOutcome, Student

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=4, linked_learning_item=True
    )
    login_as(client, role_users['tutor_id'], 'tutor')
    empty = client.post(f'/lesson/{lesson_id}/studio/finish', json={
        'action': 'save_outcome', 'outcome': {'completed': [], 'repeat': [], 'homework': ''},
    })
    assert empty.status_code == 400
    saved = client.post(f'/lesson/{lesson_id}/studio/finish', json={
        'action': 'save_outcome', 'outcome': {'completed': ['Разобрали доказательство'], 'repeat': [], 'homework': ''},
    })
    assert saved.status_code == 200
    assert saved.get_json()['status'] == 'in_progress'
    assert saved.get_json()['balance_deducted'] is False
    with app.app_context():
        assert Lesson.query.get(lesson_id).status == 'in_progress'
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 1
        assert Student.query.get(student_id).lessons_balance == 4


def test_overdue_timer_is_observed_without_completing_or_charging_lesson(app, role_users):
    from datetime import timedelta
    from app import db
    from app.lessons.routes import auto_complete_overdue_lessons
    from app.models import LearningItem, Lesson, LessonOutcome
    from core.db_models import AuditLog, Student, moscow_now

    lesson_id, student_id = _lifecycle_fixture(
        app, role_users, status='in_progress', initial_balance=3, linked_learning_item=True
    )
    with app.app_context():
        lesson = Lesson.query.get(lesson_id)
        lesson.duration = 1
        lesson.started_at = moscow_now() - timedelta(minutes=5)
        LearningItem.query.filter_by(lesson_id=lesson_id, item_type="lesson").one().status = "in_progress"
        db.session.commit()

        assert auto_complete_overdue_lessons() == 1
        assert auto_complete_overdue_lessons() == 0
        assert lesson.status == 'in_progress'
        assert lesson.balance_deducted is False
        assert LearningItem.query.filter_by(lesson_id=lesson_id, item_type='lesson').one().status == 'in_progress'
        assert LessonOutcome.query.filter_by(lesson_id=lesson_id).count() == 0
        assert Student.query.get(student_id).lessons_balance == 3
        timer_events = AuditLog.query.filter_by(
            action="lesson.timer_elapsed", entity="Lesson", entity_id=lesson_id,
        ).all()
        assert len(timer_events) == 1
        timer_event = timer_events[0].get_metadata()
        assert timer_event["source"] == "lesson_duration_timer"
        assert timer_event["status_at_signal"] == "in_progress"
        assert "to_status" not in timer_event
        assert timer_event["balance_deducted"] is False
        assert timer_event["timezone"] == "Europe/Moscow"
        assert not AuditLog.query.filter_by(
            action="lesson.balance_deducted", entity="Lesson", entity_id=lesson_id,
        ).count()


def test_lesson_creation_api_cannot_skip_planned_status(app, client, role_users):
    from app.models import Lesson

    with app.app_context():
        before = Lesson.query.count()
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post('/api/lessons/balance/adjust', json={
        'student_id': role_users['student_id'],
        'lesson_date': datetime.now().isoformat(),
        'status': 'completed',
        'duration': 60,
    })
    assert response.status_code == 400
    assert 'штатные действия урока' in response.get_json()['error']
    with app.app_context():
        assert Lesson.query.count() == before
