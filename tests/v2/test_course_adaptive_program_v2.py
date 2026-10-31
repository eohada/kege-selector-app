from datetime import timedelta


def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def _course_with_lesson(app, role_users):
    from app import db
    from app.models import LearningTrajectory, Lesson, LearningItem
    from core.db_models import utc_now

    course = LearningTrajectory(
        student_id=role_users['student_id'],
        created_by_user_id=role_users['tutor_id'],
        title='Адаптивная программа QA',
        status='active',
        target_score=80,
    )
    db.session.add(course)
    db.session.flush()
    lesson = Lesson(student_id=role_users['student_id'], learning_trajectory_id=course.course_id,
                    topic='Стартовая диагностика', status='planned', duration=60)
    db.session.add(lesson)
    db.session.flush()
    item = LearningItem(course_id=course.course_id, lesson_id=lesson.lesson_id,
                        item_type='lesson', title='Стартовая диагностика', status='planned',
                        due_at=utc_now() + timedelta(days=1), why_now='Первый шаг маршрута')
    db.session.add(item)
    db.session.commit()
    return course.course_id, lesson.lesson_id


def test_course_lesson_start_opens_v2_room_and_changes_status(client, app, role_users):
    from app import db
    from app.models import Lesson

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/start', data={'expected_course_version': 1}, follow_redirects=False)
    assert response.status_code == 302
    assert f'/lesson/{lesson_id}/room' in response.headers['Location']
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson.status == 'in_progress'
        assert lesson.review_summaries['_studio']['agenda']


def test_sequence_conflict_requires_teacher_deferral_and_keeps_audit_history(client, app, role_users):
    from app import db
    from app.models import LearningItem, LearningTrajectory, LearningTrajectoryVersion, Lesson, Student

    with app.app_context():
        course_id, earlier_id = _course_with_lesson(app, role_users)
        course = db.session.get(LearningTrajectory, course_id)
        student = db.session.get(Student, role_users['student_id'])
        student.lessons_balance = 4
        later = Lesson(
            student_id=student.student_id,
            learning_trajectory_id=course_id,
            topic='Урок после ожидающего',
            status='planned',
            course_order_index=20,
            duration=60,
        )
        db.session.add(later)
        db.session.flush()
        db.session.add(LearningItem(
            course_id=course_id, lesson_id=later.lesson_id, item_type='lesson',
            title=later.topic, status='planned', order_index=20,
        ))
        db.session.commit()
        later_id = later.lesson_id

    login_as(client, role_users['tutor_id'], 'tutor')
    blocked = client.post(f'/courses/{course_id}/lessons/{later_id}/start', data={'expected_course_version': 1}, follow_redirects=False)
    assert blocked.status_code == 302
    with app.app_context():
        assert db.session.get(Lesson, later_id).status == 'planned'

    decision = client.post(
        f'/courses/{course_id}/lessons/{earlier_id}/sequence-decision',
        data={
            'action': 'defer',
            'reason': 'Перенос после проверки обязательных предпосылок преподавателем.',
            'prerequisite_reviewed': '1',
            'expected_course_version': '1',
        },
        follow_redirects=False,
    )
    assert decision.status_code == 302
    with app.app_context():
        earlier = db.session.get(Lesson, earlier_id)
        course = db.session.get(LearningTrajectory, course_id)
        assert earlier.status == 'planned'
        assert earlier.balance_deducted is False
        assert earlier.review_summaries['_course_sequence']['state'] == 'deferred'
        audit = earlier.review_summaries['_course_sequence']['history'][-1]
        assert audit['source'] == 'teacher_manual'
        assert audit['actor_user_id'] == role_users['tutor_id']
        assert audit['reason'].startswith('Перенос после проверки')
        assert db.session.get(Student, role_users['student_id']).lessons_balance == 4
        version = LearningTrajectoryVersion.query.filter_by(course_id=course_id).order_by(
            LearningTrajectoryVersion.version_number.desc()
        ).first()
        assert version.reason == 'teacher_manual_sequence_defer'
        assert version.snapshot['lessons'][0]['course_order_index'] == earlier.course_order_index

    with app.app_context():
        current_version = db.session.get(LearningTrajectory, course_id).current_version
    started = client.post(f'/courses/{course_id}/lessons/{later_id}/start', data={
        'expected_course_version': str(current_version),
    }, follow_redirects=False)
    assert started.status_code == 302
    with app.app_context():
        assert db.session.get(Lesson, later_id).status == 'in_progress'
        assert db.session.get(Lesson, earlier_id).status == 'planned'
    page = client.get(f'/courses/{course_id}')
    assert page.status_code == 200
    assert 'Сейчас идёт'.encode('utf-8') in page.data
    assert 'Отложены преподавателем'.encode('utf-8') in page.data


def test_student_cannot_change_individual_course_sequence(client, app, role_users):
    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
    login_as(client, role_users['student_user_id'], 'student')

    response = client.post(
        f'/courses/{course_id}/lessons/{lesson_id}/sequence-decision',
        data={'action': 'defer', 'reason': 'Недостаточно основания для решения.', 'prerequisite_reviewed': '1'},
    )

    assert response.status_code == 403


def test_course_lesson_editor_selects_exact_bank_task_and_marks_source(client, app, role_users):
    import json

    from app import db
    from app.models import ExamSkill, Lesson, LessonTask, LearningTrajectory, Tasks

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        lesson = db.session.get(Lesson, lesson_id)
        lesson.course_order_index = 10
        skill = ExamSkill(
            title='Сложение векторов',
            topic='Векторы',
            topic_code='math.vector.addition.v1',
            is_active=True,
        )
        skill.mastery_criteria = [{
            'key': 'vector_sum',
            'label': 'Складывает координаты по компонентам',
            'evidence': 'Полученная пара координат совпадает с точным ответом.',
        }]
        db.session.add(skill)
        db.session.flush()
        skill_id = skill.skill_id
        lesson.skills.append(skill)
        course = db.session.get(LearningTrajectory, course_id)
        binding = {
            'contract': 'boostudy.course-skill.v1',
            'skill_id': f'exam-skill:{skill_id}',
            'topic_code': skill.topic_code,
            'criterion_id': 'vector_sum',
            'task_fingerprint': '',
            'course_id': course_id,
            'course_version': int(course.current_version or 1),
            'lesson_id': lesson_id,
        }
        task = Tasks(
            content_html='<p>Найдите сумму векторов (1, 2) и (3, 5).</p>',
            answer='(4, 7)',
            answer_spec={'type': 'short_answer', 'grading_mode': 'exact', 'course_skill_binding': binding},
            created_by_id=role_users['tutor_id'],
            is_active=True,
            prototype_status='approved',
            task_number=1,
        )
        db.session.add(task)
        db.session.flush()
        from app.ai_lab.platform_homework import _task_fingerprint
        task_fingerprint = _task_fingerprint(task)
        binding = {**binding, 'task_fingerprint': task_fingerprint}
        task.answer_spec = {
            'type': 'short_answer', 'grading_mode': 'exact',
            'course_skill_binding': dict(binding),
        }
        db.session.add(LessonTask(
            lesson_id=lesson_id, task_id=task.task_id, assignment_type='classwork',
            status='pending', is_visible_to_student=False, is_answer_visible_to_student=False,
        ))
        db.session.commit()
        task_id = task.task_id
        task = db.session.get(Tasks, task_id)
        task_binding = task.answer_spec['course_skill_binding']
        task_fingerprint = task_binding['task_fingerprint']
        from app.courses.routes import _course_task_binding
        checked, binding_error = _course_task_binding(task, skill, 'vector_sum', course, lesson)
        assert binding_error is None, binding_error
        assert checked['provenance_verified'] is True

    login_as(client, role_users['tutor_id'], 'tutor')
    page = client.get(f'/courses/{course_id}/lessons/{lesson_id}/edit')
    assert page.status_code == 200
    assert 'Найдите сумму векторов'.encode('utf-8') in page.data
    assert b'(4, 7)' not in page.data

    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/edit', data={
        'expected_course_version': '1',
        'module_id': '0',
        'topic': 'Стартовая диагностика',
        'course_order_index': '10',
        'duration': '60',
        'lesson_format': 'Теория + Практика',
        'lesson_type': 'regular',
        'status': 'planned',
        'studio_scenario': '',
        'content': '',
        'homework': '',
        'teacher_note': '',
        'skill_ids': str(skill_id),
        'program_change_reason': 'Подобрать проверяемое упражнение для цели занятия.',
        'bank_task_ids': str(task_id),
        f'bank_task_purpose_{task_id}': 'independent',
        f'bank_task_criterion_{task_id}': 'vector_sum',
        'bank_assignment_type': 'classwork',
        'bank_tasks_confirmed': '1',
        'submit': 'Сохранить урок',
    }, follow_redirects=False)
    if response.status_code != 302:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.get_data(as_text=True), 'html.parser')
        messages = [node.get_text(' ', strip=True) for node in soup.select('[role="alert"], [class*="text-rose"], [class*="text-red"]')]
        raise AssertionError(' | '.join(messages) or soup.get_text(' ', strip=True)[2500:6000])

    with app.app_context():
        link = LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).one()
        provenance = json.loads(link.notes)
        assert link.assignment_type == 'classwork'
        assert link.is_visible_to_student is False
        assert link.is_answer_visible_to_student is False
        assert provenance['purpose'] == 'independent'
        assert provenance['source_provenance']['task_fingerprint'] == task_fingerprint
        assert provenance['source'] == 'teacher_manual_task_bank_selection'
        assert LessonTask.query.filter_by(lesson_id=lesson_id, task_id=task_id).count() == 1

    with app.app_context():
        current_version = db.session.get(LearningTrajectory, course_id).current_version
    reorder_response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/edit', data={
        'expected_course_version': str(current_version),
        'module_id': '0',
        'topic': 'Стартовая диагностика',
        'course_order_index': '20',
        'duration': '60',
        'lesson_format': 'Теория + Практика',
        'lesson_type': 'regular',
        'status': 'planned',
        'studio_scenario': '',
        'content': '',
        'homework': '',
        'teacher_note': '',
        'skill_ids': str(skill_id),
        'program_change_reason': 'Попытка изменить порядок без проверки предпосылок.',
        'submit': 'Сохранить урок',
    }, follow_redirects=False)
    assert reorder_response.status_code == 302
    with app.app_context():
        assert db.session.get(Lesson, lesson_id).course_order_index == 10


def test_course_lesson_outcome_v2_form_persists_structured_result(client, app, role_users):
    from app import db
    from app.models import LearningItem, Lesson, LessonOutcome, Student

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        student = db.session.get(Student, role_users['student_id'])
        student.lessons_balance = 3
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')
    page = client.get(f'/courses/{course_id}/lessons/{lesson_id}/outcome')
    assert page.status_code == 200
    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/outcome', data={
        'covered': ['101', '102'], 'mastery': 'good', 'next_action': 'continue',
        'homework_assigned': '1', 'teacher_note': 'Продолжаем практику.'
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        outcome = db.session.query(LessonOutcome).filter_by(lesson_id=lesson_id).one()
        assert lesson.status == 'planned'
        assert outcome.covered == ['101', '102']
        assert outcome.mastery == 'good'
        assert outcome.homework_assigned is True
        assert outcome.content_snapshot['topic'] == lesson.topic
        assert LearningItem.query.filter_by(course_id=course_id, lesson_id=lesson_id).one().status == 'planned'
        assert db.session.get(Student, role_users['student_id']).lessons_balance == 3
    snapshot = client.get(f'/courses/{course_id}/lessons/{lesson_id}/snapshot')
    assert snapshot.status_code == 200
    assert snapshot.get_json()['snapshot']['topic'] == 'Стартовая диагностика'
    status_view = client.get(f'/courses/{course_id}/status-analytics?view=1')
    assert status_view.status_code == 200
    status_json = client.get(f'/courses/{course_id}/status-analytics').get_json()
    assert status_json['counts']['planned'] == 1

    # A saved pedagogical outcome is not proof that the planned lesson took place.
    completion = client.post(f'/lesson/{lesson_id}/complete', data={}, follow_redirects=False)
    assert completion.status_code == 400
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        outcome = db.session.query(LessonOutcome).filter_by(lesson_id=lesson_id).one()
        assert lesson.status == 'planned'
        assert lesson.balance_deducted is False
        assert outcome.mastery == 'good'
        assert LearningItem.query.filter_by(course_id=course_id, lesson_id=lesson_id).one().status == 'planned'
        assert db.session.get(Student, role_users['student_id']).lessons_balance == 3


def test_course_catalog_and_versions_have_v2_views(client, app, role_users):
    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    versions = client.get(f'/courses/{course_id}/versions?view=1')
    assert versions.status_code == 200
    assert 'Версии маршрута'.encode('utf-8') in versions.data
    templates = client.get(f'/course-templates?view=1&course_id={course_id}')
    assert templates.status_code == 200
    assert 'Каталог шаблонов'.encode('utf-8') in templates.data
    skills = client.get(f'/courses/{course_id}/skills?view=1')
    assert skills.status_code == 200
    assert 'Освоение навыков'.encode('utf-8') in skills.data
    milestones = client.get(f'/courses/{course_id}/milestones')
    assert milestones.status_code == 200
    assert len(milestones.get_json()['milestones']) == 4


def test_student_course_pages_use_student_shell_and_hide_teacher_actions(client, app, role_users):
    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
    login_as(client, role_users['student_user_id'], 'student')
    listing = client.get(f'/student/{role_users["student_id"]}/courses')
    assert listing.status_code == 200
    assert 'Курсы · V2 Fixture Student'.encode('utf-8') in listing.data
    assert b'bs-student-shell' in listing.data
    assert b'\xd0\x9d\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xba\xd1\x83\xd1\x80\xd1\x81' not in listing.data
    view = client.get(f'/courses/{course_id}')
    assert view.status_code == 200
    assert b'\xd0\x9f\xd0\xbe\xd0\xb4\xd0\xbe\xd0\xb1\xd1\x80\xd0\xb0\xd1\x82\xd1\x8c \xd0\xbf\xd0\xb0\xd0\xba\xd0\xb5\xd1\x82' not in view.data
    assert client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={}).status_code == 403


def test_student_dashboard_links_to_program_and_next_planned_course_lesson(client, app, role_users):
    from app import db
    from app.models import LearningItem, Lesson

    with app.app_context():
        course_id, first_lesson_id = _course_with_lesson(app, role_users)
        first_lesson = db.session.get(Lesson, first_lesson_id)
        first_lesson.status = 'completed'
        first_item = LearningItem.query.filter_by(course_id=course_id, lesson_id=first_lesson_id).one()
        first_item.status = 'done'
        next_lesson = Lesson(
            student_id=role_users['student_id'], learning_trajectory_id=course_id,
            course_order_index=2, topic='Следующий урок по программе', status='planned', duration=60,
        )
        db.session.add(next_lesson)
        db.session.flush()
        db.session.add(LearningItem(
            course_id=course_id, lesson_id=next_lesson.lesson_id, item_type='lesson',
            title=next_lesson.topic, status='planned', order_index=2,
        ))
        db.session.commit()
        next_lesson_id = next_lesson.lesson_id

    login_as(client, role_users['student_user_id'], 'student')
    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert f'/lesson/{next_lesson_id}/room'.encode() in dashboard.data
    assert 'Следующий урок по программе'.encode('utf-8') in dashboard.data
    assert f'/student/{role_users["student_id"]}/courses'.encode() in dashboard.data
    assert b'bs-student-program-soon' not in dashboard.data


def test_auto_task_pack_refuses_to_guess_skill_from_lesson_title(client, app, role_users):
    from app import db
    from app.models import ExamSkill, Lesson, LessonTask

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        lesson = db.session.get(Lesson, lesson_id)
        lesson.topic = 'Задание №21: графы'
        db.session.add(ExamSkill(task_number=21, title='Неявный навык', subject='Информатика', is_active=True))
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={})

    assert response.status_code == 409
    assert 'однозначно определить навык' in response.get_json()['error']
    with app.app_context():
        assert LessonTask.query.filter_by(lesson_id=lesson_id).count() == 0


def test_auto_task_pack_refuses_ambiguous_lesson_skills(client, app, role_users):
    from app import db
    from app.models import ExamSkill, Lesson, LessonTask

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        lesson = db.session.get(Lesson, lesson_id)
        lesson.skills = [
            ExamSkill(task_number=4, title='Первый навык', subject='Информатика', is_active=True),
            ExamSkill(task_number=7, title='Второй навык', subject='Информатика', is_active=True),
        ]
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')

    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={})

    assert response.status_code == 409
    assert 'однозначно определить навык' in response.get_json()['error']
    with app.app_context():
        assert LessonTask.query.filter_by(lesson_id=lesson_id).count() == 0


def test_creator_can_generate_and_auto_fill_course_without_false_forbidden(client, app, role_users):
    from app import db
    from app.models import ExamSkill, LearningItem, Tasks

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=21, title='Кодирование', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.flush()
        db.session.query(LearningItem).filter_by(course_id=course_id, lesson_id=lesson_id).one().skill_id = skill.skill_id
        for index in range(20):
            db.session.add(Tasks(task_number=21, content_html=f'<p>Задача {index}</p>', difficulty_level=(index % 3) + 1, is_active=True))
        db.session.commit()
    login_as(client, role_users['creator_id'], 'creator')
    generated = client.post(f'/courses/{course_id}/plan/generate', json={'diagnostic': {}})
    assert generated.status_code == 200
    auto_tasks = client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={})
    assert auto_tasks.status_code == 200


def test_teacher_can_configure_skills_before_generating_route(client, app, role_users):
    from app import db
    from app.models import ExamSkill

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    wizard = client.get(f'/courses/{course_id}/plan/wizard')
    assert wizard.status_code == 200
    assert 'Настроить навыки'.encode('utf-8') in wizard.data
    created = client.post(f'/courses/{course_id}/skills/manage', data={
        'title': 'Построить таблицу истинности',
        'topic': 'Логика',
        'task_number': '2',
    }, follow_redirects=False)
    assert created.status_code == 302
    with app.app_context():
        skill = db.session.query(ExamSkill).filter_by(title='Построить таблицу истинности').one()
        assert skill.is_active is True
        skill_id = skill.skill_id
    generated = client.post(f'/courses/{course_id}/plan/generate', json={'diagnostic': {str(skill_id): 35}})
    assert generated.status_code == 200
    login_as(client, role_users['student_user_id'], 'student')
    assert client.get(f'/courses/{course_id}/skills/manage').status_code == 403


def test_course_template_editor_creates_template_from_v2_form(client, app, role_users):
    from app import db
    from app.models import LearningTrajectoryTemplate

    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post('/course-templates?view=1&editor=1', data={
        'title': 'Шаблон диагностики', 'description': 'Стартовый маршрут',
        'target_score': '75', 'estimated_lessons': '12',
        'modules_json': '[{"title":"База","items":[{"title":"Уравнения","type":"practice"}]}]'
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        template = db.session.query(LearningTrajectoryTemplate).filter_by(title='Шаблон диагностики').one()
        assert len(template.modules) == 1
        assert template.modules[0].items[0].title == 'Уравнения'


def test_course_weekly_plan_and_attention_have_json_and_v2_views(client, app, role_users):
    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    plan = client.get(f'/courses/{course_id}/weekly-plan')
    assert plan.status_code == 200
    assert plan.get_json()['counts']['this_week'] >= 1
    plan_view = client.get(f'/courses/{course_id}/weekly-plan?view=1')
    assert plan_view.status_code == 200
    assert 'План на неделю'.encode('utf-8') in plan_view.data
    attention = client.get(f'/courses/{course_id}/attention')
    assert attention.status_code == 200
    attention_view = client.get(f'/courses/{course_id}/attention?view=1')
    assert attention_view.status_code == 200
    assert 'Центр внимания'.encode('utf-8') in attention_view.data


def test_student_cannot_open_teacher_attention(client, app, role_users):
    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
    login_as(client, role_users['student_user_id'], 'student')
    assert client.get(f'/courses/{course_id}/attention').status_code == 403


def test_prepare_next_opens_existing_lesson_without_creating_duplicate(client, app, role_users):
    from app import db
    from app.models import Lesson

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/lessons/prepare-next', json={'expected_course_version': 1})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['lesson_id'] == lesson_id
    assert payload['created'] is False
    with app.app_context():
        assert db.session.get(Lesson, payload['lesson_id']).status == 'planned'
        assert Lesson.query.filter_by(learning_trajectory_id=course_id).count() == 1


def test_stale_course_version_cannot_save_manual_plan_or_sequence_decision(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory, Lesson

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    stale_edit = client.post(f'/courses/{course_id}/lessons/{lesson_id}/edit', data={
        'expected_course_version': '77',
        'topic': 'Изменение из устаревшей формы',
    })
    assert stale_edit.status_code == 409
    stale_decision = client.post(f'/courses/{course_id}/lessons/{lesson_id}/sequence-decision', data={
        'expected_course_version': '77', 'action': 'defer',
        'reason': 'Устаревшее решение очереди урока', 'prerequisite_reviewed': '1',
    })
    assert stale_decision.status_code == 302
    with app.app_context():
        course = db.session.get(LearningTrajectory, course_id)
        lesson = db.session.get(Lesson, lesson_id)
        assert course.current_version == 1
        assert lesson.topic == 'Стартовая диагностика'
        assert (lesson.review_summaries or {}).get('_course_sequence') is None
    repeated = client.post(f'/courses/{course_id}/lessons/prepare-next', json={'expected_course_version': 1})
    assert repeated.status_code == 200
    assert repeated.get_json()['lesson_id'] == lesson_id
    with app.app_context():
        assert Lesson.query.filter_by(learning_trajectory_id=course_id).count() == 1


def test_lesson_outcome_keeps_content_snapshot(client, app, role_users):
    from app import db
    from app.models import Lesson, LessonOutcome

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        lesson = db.session.get(Lesson, lesson_id)
        lesson.content = 'Теория до изменения'
        lesson.materials = [{'name': 'formula.pdf', 'url': '/files/formula.pdf'}]
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/outcome', json={
        'covered': ['Базовая тема'], 'mastery': 'good', 'next_action': 'continue'
    })
    assert response.status_code == 200
    with app.app_context():
        snapshot = db.session.get(LessonOutcome, lesson_id).content_snapshot
        assert snapshot['content'] == 'Теория до изменения'
        assert snapshot['materials'][0]['name'] == 'formula.pdf'


def test_auto_task_pack_keeps_manual_tasks_and_creates_categories(client, app, role_users):
    from app import db
    from app.models import Lesson, LearningItem, ExamSkill, Tasks, LessonTask

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=12, title='Производная', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.flush()
        item = db.session.query(LearningItem).filter_by(course_id=course_id, lesson_id=lesson_id).first()
        item.skill_id = skill.skill_id
        for index in range(20):
            db.session.add(Tasks(task_number=12, content_html=f'<p>Задача {index}</p>', difficulty_level=(index % 3) + 1, is_active=True))
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={})
    assert response.status_code == 200
    assert response.get_json()['count'] == 17
    with app.app_context():
        linked = LessonTask.query.filter_by(lesson_id=lesson_id).all()
        assert len(linked) == 17
        assert {row.notes for row in linked} == {'auto:warmup', 'auto:practice', 'auto:advanced', 'auto:control', 'auto:homework'}


def test_adaptation_actions_are_idempotent_and_change_route(client, app, role_users):
    from app import db
    from app.models import ExamSkill, LearningItem, LearningTrajectoryVersion

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=7, title='Логарифмы', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.commit()
        skill_id = skill.skill_id
    login_as(client, role_users['tutor_id'], 'tutor')
    first = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_lesson', 'skill_id': skill_id})
    assert first.status_code == 200 and first.get_json()['created'] is True
    with app.app_context():
        versions = LearningTrajectoryVersion.query.filter_by(course_id=course_id).all()
        assert len(versions) == 1
        assert versions[0].reason == 'manual_attention_plan_edit'
        assert len(versions[0].snapshot['learning_items']) == 1
        assert versions[0].snapshot['learning_items'][0]['title'] == 'Стартовая диагностика'
    second = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_lesson', 'skill_id': skill_id})
    assert second.status_code == 200 and second.get_json()['created'] is False
    with app.app_context():
        assert LearningTrajectoryVersion.query.filter_by(course_id=course_id).count() == 1
    homework = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_homework', 'skill_id': skill_id})
    assert homework.status_code == 200 and homework.get_json()['created'] is True
    with app.app_context():
        versions = LearningTrajectoryVersion.query.filter_by(course_id=course_id).order_by(
            LearningTrajectoryVersion.version_number.asc()
        ).all()
        assert len(versions) == 2
        assert len(versions[-1].snapshot['learning_items']) == 2
    ignored = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'ignore', 'skill_id': skill_id})
    assert ignored.status_code == 200 and ignored.get_json()['changed'] == 2
    with app.app_context():
        items = db.session.query(LearningItem).filter_by(course_id=course_id, skill_id=skill_id).all()
        assert {item.status for item in items} == {'skipped'}
        versions = LearningTrajectoryVersion.query.filter_by(course_id=course_id).order_by(
            LearningTrajectoryVersion.version_number.asc()
        ).all()
        assert len(versions) == 3
        assert len(versions[-1].snapshot['learning_items']) == 3
    assert client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'shorten', 'skill_id': skill_id}).get_json()['changed'] == 0


def test_plan_generator_persists_full_study_mode(client, app, role_users):
    from app import db
    from app.models import ExamSkill, LearningTrajectory

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
        db.session.add(ExamSkill(task_number=12, title='Производная', subject='Информатика', is_active=True))
        db.session.commit()
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/plan/generate', json={
        'target_score': 85,
        'exam_date': '2027-06-01',
        'lessons_per_week': 2,
        'lesson_duration_minutes': 90,
        'homework_hours_per_week': 3.5,
        'diagnostic_mode': 'test',
        'starting_forecast': 54,
        'diagnostic': {'1': 40},
    })
    assert response.status_code == 200
    assert response.get_json()['mode']['available_lessons'] > 0
    with app.app_context():
        course = db.session.get(LearningTrajectory, course_id)
        assert course.lessons_per_week == 2
        assert course.lesson_duration_minutes == 90
        assert float(course.homework_hours_per_week) == 3.5
        assert course.diagnostic_mode == 'test'
        assert course.starting_forecast == 54


def test_errors_and_reviews_create_one_route_review_item(client, app, role_users):
    from app import db
    from app.models import ExamSkill, LearningItem, StudentSkill

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=15, title='Экономическая задача', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.flush()
        db.session.add(StudentSkill(student_id=role_users['student_id'], skill_id=skill.skill_id, mastery_percent=40, state='learning'))
        db.session.commit()
        skill_id = skill.skill_id
    login_as(client, role_users['tutor_id'], 'tutor')
    first = client.post(f'/courses/{course_id}/errors', json={'skill_id': skill_id, 'type': 'model', 'description': 'Неверная модель'})
    second = client.post(f'/courses/{course_id}/errors', json={'skill_id': skill_id, 'type': 'model', 'description': 'Повтор'})
    assert first.status_code == second.status_code == 200
    assert second.get_json()['occurrences'] == 2
    with app.app_context():
        items = LearningItem.query.filter_by(course_id=course_id, skill_id=skill_id, item_type='review').all()
        assert len(items) == 1
        assert items[0].due_at is not None
    reviewed = client.post(f'/courses/{course_id}/reviews', json={'skill_id': skill_id, 'mastery_percent': 80})
    assert reviewed.status_code == 200
    assert reviewed.get_json()['review_item_id'] == items[0].item_id


def test_mock_replan_returns_mastery_diff_and_global_attention(client, app, role_users):
    from app import db
    from app.models import ExamSkill, LearningTrajectory, StudentDiagnosticCheckpoint
    from core.db_models import utc_now

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=18, title='Параметры', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.flush()
        db.session.add(StudentDiagnosticCheckpoint(student_id=role_users['student_id'], kind='mock_test',
            metrics={'diagnostic': {str(skill.skill_id): 72}}, created_at=utc_now()))
        db.session.commit()
        skill_id = skill.skill_id
    login_as(client, role_users['tutor_id'], 'tutor')
    replanned = client.post(f'/courses/{course_id}/mock-replan', json={'diagnostic': {str(skill_id): 41}})
    assert replanned.status_code == 200
    diff = replanned.get_json()['mock_diff']
    assert diff and diff[0]['before'] == 72 and diff[0]['after'] == 41
    overview = client.get('/courses/attention')
    assert overview.status_code == 200
    assert overview.get_json()['totals']['unfinished_lessons'] >= 1
    view = client.get('/courses/attention?view=1')
    assert view.status_code == 200
    assert 'Центр внимания'.encode('utf-8') in view.data


def test_course_adaptive_engine_full_loop(client, app, role_users):
    from app import db
    from app.models import Course, ExamSkill, LearningItem, LearningTrajectory, Lesson, LessonOutcome, StudentSkill, LearningError

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        course = db.session.get(LearningTrajectory, course_id)

        exam_course = Course(title='Информатика ЕГЭ Тест', slug='ege_test_adaptive')
        db.session.add(exam_course)
        db.session.flush()
        course.exam_course_id = exam_course.id

        skill_1 = ExamSkill(exam_course_id=exam_course.id, task_number=1, title='Анализ графов', is_active=True, weight=1.0)
        skill_2 = ExamSkill(exam_course_id=exam_course.id, task_number=2, title='Таблицы истинности', is_active=True, weight=1.0)
        db.session.add_all([skill_1, skill_2])
        db.session.flush()

        db.session.add(StudentSkill(student_id=role_users['student_id'], skill_id=skill_1.skill_id, mastery_percent=30, state='learning'))

        # Planned practice item that can be skipped if mastered
        db.session.add(LearningItem(course_id=course_id, skill_id=skill_1.skill_id, item_type='practice', title='Доп. практика по графам', status='planned'))

        db.session.commit()
        s1_id = skill_1.skill_id
        s2_id = skill_2.skill_id

    login_as(client, role_users['tutor_id'], 'tutor')

    # Send structured outcome with comprehension=4, independence=high, pacing=optimal, identified errors
    response = client.post(
        f'/courses/{course_id}/lessons/{lesson_id}/outcome',
        json={
            'covered': [str(s1_id)],
            'mastery': 'good',
            'next_action': 'continue',
            'comprehension_score': 4,
            'independence_level': 'high',
            'pacing': 'optimal',
            'identified_errors': [{'skill_id': s1_id, 'description': 'Ошибся в ориентированности ребер', 'type': 'conceptual'}],
            'auto_replan_triggered': True,
            'teacher_note': 'Тема освоена отлично, небольшая неточность в направленности.',
        },
        headers={'Accept': 'application/json'}
    )
    assert response.status_code == 200
    res_data = response.get_json()
    assert res_data['success'] is True
    assert 'adaptive_diff' in res_data
    diff = res_data['adaptive_diff']
    assert diff['comprehension_score'] == 4
    assert len(diff['skills_updated']) >= 1
    assert diff['adaptation_status'] == 'analytics_only'
    assert diff['items_inserted'] == []
    assert diff['items_skipped'] == []

    with app.app_context():
        # Check LessonOutcome recorded adaptive diff
        outcome = LessonOutcome.query.filter_by(lesson_id=lesson_id).one()
        assert outcome.comprehension_score == 4
        assert outcome.independence_level == 'high'
        assert outcome.pacing == 'optimal'
        assert outcome.adaptive_diff_summary is not None
        assert outcome.auto_replan_triggered is False

        # Check StudentSkill calibrated
        st_skill = StudentSkill.query.filter_by(student_id=role_users['student_id'], skill_id=s1_id).first()
        assert st_skill.mastery_percent > 30

        # Check LearningError recorded
        err = LearningError.query.filter_by(student_id=role_users['student_id'], skill_id=s1_id).first()
        assert err is not None
        assert 'ориентированности' in err.description

        # Analytics may update after a teacher outcome, but curriculum remains unchanged.
        assert Lesson.query.filter(Lesson.learning_trajectory_id == course_id).count() == 1
        assert LearningItem.query.filter_by(course_id=course_id, skill_id=s1_id, status='planned').count() == 1

    # Check that course view renders the adaptive summary banner
    view = client.get(f'/courses/{course_id}')
    assert view.status_code == 200
    assert 'Аналитика урока обновлена'.encode('utf-8') in view.data
    assert 'План курса автоматически не менялся'.encode('utf-8') in view.data
    assert 'Оценка понимания'.encode('utf-8') in view.data


def test_missing_mastery_defers_adaptation_without_skipping_practice(app, role_users):
    from types import SimpleNamespace

    from app import db
    from app.courses.adaptive_engine import CourseAdaptiveEngine
    from app.models import Course, ExamSkill, LearningItem, LearningTrajectory, Lesson, StudentSkill

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
        course = db.session.get(LearningTrajectory, course_id)
        exam_course = Course(title='Информатика ЕГЭ Тест', slug='ege_missing_mastery')
        db.session.add(exam_course)
        db.session.flush()
        course.exam_course_id = exam_course.id

        skill = ExamSkill(exam_course_id=exam_course.id, task_number=1, title='Анализ графов', is_active=True, weight=1.0)
        db.session.add(skill)
        db.session.flush()
        student_skill = StudentSkill(student_id=role_users['student_id'], skill_id=skill.skill_id,
                                     mastery_percent=30, state='learning')
        practice = LearningItem(course_id=course_id, skill_id=skill.skill_id, item_type='practice',
                                title='Доп. практика по графам', status='planned')
        db.session.add_all([student_skill, practice])
        db.session.commit()

        outcome = SimpleNamespace(
            covered=[str(skill.skill_id)], mastery=None, independence_level=None, pacing=None,
            comprehension_score=None, next_action=None, identified_errors=[],
            auto_replan_triggered=None, adaptive_diff_summary=None,
        )
        diff = CourseAdaptiveEngine.apply_lesson_adaptation(
            course=course, lesson=db.session.get(Lesson, lesson_id), outcome=outcome,
        )

        assert diff['adaptation_status'] == 'insufficient_evidence'
        assert diff['skills_updated'] == []
        assert diff['items_skipped'] == []
        assert diff['next_lesson_prepared'] is False
        assert student_skill.mastery_percent == 30
        assert practice.status == 'planned'
        assert outcome.auto_replan_triggered is False


def test_creator_sandbox_role_can_open_template_from_student_account(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory

    with app.app_context():
        course = LearningTrajectory(
            student_id=None,
            created_by_user_id=role_users['tutor_id'],
            is_template=True,
            title='Синтетический шаблон курса для проверки роли',
            subject='Информатика',
            status='active',
        )
        db.session.add(course)
        db.session.commit()
        course_id = course.course_id

    login_as(client, role_users['student_user_id'], 'creator')
    response = client.get(f'/courses/{course_id}')

    assert response.status_code == 200
    assert 'Синтетический шаблон курса для проверки роли'.encode('utf-8') in response.data
