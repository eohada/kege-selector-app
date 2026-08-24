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
    response = client.post(f'/courses/{course_id}/lessons/{lesson_id}/start', follow_redirects=False)
    assert response.status_code == 302
    assert f'/lesson/{lesson_id}/room' in response.headers['Location']
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        assert lesson.status == 'in_progress'
        assert lesson.review_summaries['_studio']['agenda']


def test_course_lesson_outcome_v2_form_persists_structured_result(client, app, role_users):
    from app import db
    from app.models import Lesson, LessonOutcome

    with app.app_context():
        course_id, lesson_id = _course_with_lesson(app, role_users)
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
        assert lesson.status == 'completed'
        assert outcome.covered == ['101', '102']
        assert outcome.mastery == 'good'
        assert outcome.homework_assigned is True
        assert outcome.content_snapshot['topic'] == lesson.topic
    snapshot = client.get(f'/courses/{course_id}/lessons/{lesson_id}/snapshot')
    assert snapshot.status_code == 200
    assert snapshot.get_json()['snapshot']['topic'] == 'Стартовая диагностика'
    status_view = client.get(f'/courses/{course_id}/status-analytics?view=1')
    assert status_view.status_code == 200
    status_json = client.get(f'/courses/{course_id}/status-analytics').get_json()
    assert status_json['counts']['completed'] == 1


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
    assert b'BooStudy | \xd0\xa3\xd1\x87\xd0\xb5\xd0\xbd\xd0\xb8\xd0\xba' in listing.data
    assert b'\xd0\x9d\xd0\xbe\xd0\xb2\xd1\x8b\xd0\xb9 \xd0\xba\xd1\x83\xd1\x80\xd1\x81' not in listing.data
    view = client.get(f'/courses/{course_id}')
    assert view.status_code == 200
    assert b'\xd0\x9f\xd0\xbe\xd0\xb4\xd0\xbe\xd0\xb1\xd1\x80\xd0\xb0\xd1\x82\xd1\x8c \xd0\xbf\xd0\xb0\xd0\xba\xd0\xb5\xd1\x82' not in view.data
    assert client.post(f'/courses/{course_id}/lessons/{lesson_id}/auto-tasks', json={}).status_code == 403


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


def test_prepare_next_lesson_creates_a_draft_from_route(client, app, role_users):
    from app import db
    from app.models import Lesson

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
    login_as(client, role_users['tutor_id'], 'tutor')
    response = client.post(f'/courses/{course_id}/lessons/prepare-next', json={})
    assert response.status_code == 201
    payload = response.get_json()
    assert payload['status'] == 'draft'
    with app.app_context():
        draft = db.session.get(Lesson, payload['lesson_id'])
        assert draft.status == 'draft'
        assert draft.review_summaries['_studio']['agenda']


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
    from app.models import ExamSkill, LearningItem

    with app.app_context():
        course_id, _ = _course_with_lesson(app, role_users)
        skill = ExamSkill(task_number=7, title='Логарифмы', subject='Информатика', is_active=True)
        db.session.add(skill)
        db.session.commit()
        skill_id = skill.skill_id
    login_as(client, role_users['tutor_id'], 'tutor')
    first = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_lesson', 'skill_id': skill_id})
    assert first.status_code == 200 and first.get_json()['created'] is True
    second = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_lesson', 'skill_id': skill_id})
    assert second.status_code == 200 and second.get_json()['created'] is False
    homework = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'add_homework', 'skill_id': skill_id})
    assert homework.status_code == 200 and homework.get_json()['created'] is True
    ignored = client.post(f'/courses/{course_id}/adaptation/actions', json={'action': 'ignore', 'skill_id': skill_id})
    assert ignored.status_code == 200 and ignored.get_json()['changed'] == 2
    with app.app_context():
        items = db.session.query(LearningItem).filter_by(course_id=course_id, skill_id=skill_id).all()
        assert {item.status for item in items} == {'skipped'}
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
