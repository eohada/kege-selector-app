import io
from datetime import datetime, timedelta


def login_as(client, user_id: int, role: str):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
        session['sandbox_role'] = role


def test_master_course_creation_and_catalog(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory

    login_as(client, role_users['tutor_id'], 'tutor')

    # 1. Open catalog
    catalog = client.get('/courses')
    assert catalog.status_code == 200
    assert 'Каталог программ'.encode('utf-8') in catalog.data or 'Программы обучения'.encode('utf-8') in catalog.data

    # 2. Create master course (is_template=True, student_id=None)
    response = client.post('/courses/templates', data={
        'title': 'ЕГЭ Информатика 2025/2026 (Мастер)',
        'subject': 'Информатика',
        'target_score': '85',
        'default_lesson_duration': '90',
        'description': 'Базовый шаблон полного курса',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        master = LearningTrajectory.query.filter_by(title='ЕГЭ Информатика 2025/2026 (Мастер)').first()
        assert master is not None
        assert master.is_template is True
        assert master.student_id is None
        assert master.target_score == 85
        assert master.default_lesson_duration == 90

        # View master course
        view = client.get(f'/courses/{master.course_id}')
        assert view.status_code == 200
        assert 'Базовый мастер-курс'.encode('utf-8') in view.data or 'Базовый курс'.encode('utf-8') in view.data


def test_master_course_modules_and_control_exam(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory, TrajectoryModule

    login_as(client, role_users['tutor_id'], 'tutor')

    with app.app_context():
        master = LearningTrajectory(
            is_template=True,
            created_by_user_id=role_users['tutor_id'],
            title='Мастер-курс Модули',
            status='active',
        )
        db.session.add(master)
        db.session.commit()
        master_id = master.course_id

    # 1. Add regular module
    client.post(f'/courses/{master_id}/modules/new', data={
        'title': 'Модуль 1. Основы',
        'order_index': '10',
        'learning_result': 'Базовые навыки освоены',
    }, follow_redirects=True)

    # 2. Add control exam module (is_control_exam=True)
    client.post(f'/courses/{master_id}/modules/new', data={
        'title': 'Модуль 2. Пробный экзамен №1',
        'order_index': '20',
        'is_control_exam': 'y',
        'learning_result': 'Проверка среза знаний',
    }, follow_redirects=True)

    with app.app_context():
        m1 = TrajectoryModule.query.filter_by(course_id=master_id, title='Модуль 1. Основы').first()
        m2 = TrajectoryModule.query.filter_by(course_id=master_id, title='Модуль 2. Пробный экзамен №1').first()
        assert m1 is not None and not m1.is_control_exam
        assert m2 is not None and m2.is_control_exam

    # View course page renders control exam badge
    view = client.get(f'/courses/{master_id}')
    assert view.status_code == 200
    assert 'Контрольный рубеж'.encode('utf-8') in view.data


def test_course_skills_manage_with_topic_code_and_prerequisites(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory, ExamSkill

    login_as(client, role_users['tutor_id'], 'tutor')

    with app.app_context():
        course = LearningTrajectory(
            is_template=True,
            created_by_user_id=role_users['tutor_id'],
            title='Мастер Тематический',
            status='active',
        )
        db.session.add(course)
        db.session.commit()
        course_id = course.course_id

    # Add prerequisite skill
    client.post(f'/courses/{course_id}/skills/manage', data={
        'title': 'Двоичная система счисления',
        'topic': 'Системы счисления',
        'task_number': '1',
        'topic_code': 'EGE_INF_01_BIN',
    }, follow_redirects=True)

    with app.app_context():
        base_skill = ExamSkill.query.filter_by(topic_code='EGE_INF_01_BIN').first()
        assert base_skill is not None
        base_id = base_skill.skill_id

    # Add dependent skill with prerequisite_ids
    client.post(f'/courses/{course_id}/skills/manage', data={
        'title': 'IP-адреса и маски',
        'topic': 'Компьютерные сети',
        'task_number': '13',
        'topic_code': 'EGE_INF_13_IPV4',
        'prerequisite_ids': [str(base_id)],
    }, follow_redirects=True)

    with app.app_context():
        dep_skill = ExamSkill.query.filter_by(topic_code='EGE_INF_13_IPV4').first()
        assert dep_skill is not None
        assert dep_skill.topic_code == 'EGE_INF_13_IPV4'
        assert base_id in (dep_skill.prerequisite_ids or [])


def test_lesson_creation_skills_and_attachments(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory, TrajectoryModule, ExamSkill, Lesson, LessonAttachment

    login_as(client, role_users['tutor_id'], 'tutor')

    with app.app_context():
        course = LearningTrajectory(
            is_template=True,
            created_by_user_id=role_users['tutor_id'],
            title='Мастер Уроков',
            status='active',
        )
        db.session.add(course)
        db.session.flush()

        module = TrajectoryModule(course_id=course.course_id, title='Блок 1', order_index=10)
        skill = ExamSkill(title='Динамика префиксов', topic_code='EGE_INF_27_PREF', task_number=27, is_active=True)
        db.session.add(module)
        db.session.add(skill)
        db.session.commit()
        course_id, mod_id, skill_id = course.course_id, module.module_id, skill.skill_id

    # Create lesson with skills and scenario
    res = client.post(f'/courses/{course_id}/lessons/new', data={
        'topic': 'Урок 1: Префиксные суммы',
        'module_id': str(mod_id),
        'course_order_index': '10',
        'duration': '90',
        'lesson_format': 'Теория + Практика',
        'status': 'planned',
        'studio_scenario': '1. Разминка\n2. Теория\n3. Практика',
        'content': 'Конспект по префиксным суммам',
        'homework': 'Решить 5 задач',
        'skill_ids': [str(skill_id)],
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        lesson = Lesson.query.filter_by(learning_trajectory_id=course_id, topic='Урок 1: Префиксные суммы').first()
        assert lesson is not None
        assert lesson.lesson_format == 'Теория + Практика'
        assert lesson.duration == 90
        assert 'Разминка' in (lesson.studio_scenario or '')
        assert len(lesson.skills) == 1
        assert lesson.skills[0].topic_code == 'EGE_INF_27_PREF'
        lesson_id = lesson.lesson_id

    # Upload attachment to lesson
    file_data = (io.BytesIO(b"data,values\n1,10\n2,20\n"), "test_data.csv")
    upload_res = client.post(
        f'/courses/{course_id}/lessons/{lesson_id}/attachments/upload',
        data={'file': file_data, 'target': 'theory'},
        content_type='multipart/form-data'
    )
    assert upload_res.status_code == 200
    upload_json = upload_res.get_json()
    assert upload_json['success'] is True
    att_id = upload_json['attachment']['id']

    with app.app_context():
        att = db.session.get(LessonAttachment, att_id)
        assert att is not None
        assert att.file_name == 'test_data.csv'
        assert att.target == 'theory'

    # Delete attachment
    del_res = client.post(f'/courses/{course_id}/lessons/{lesson_id}/attachments/{att_id}/delete')
    assert del_res.status_code == 200
    assert del_res.get_json()['success'] is True


def test_master_course_duplication_and_student_fork(client, app, role_users):
    from app import db
    from app.models import LearningTrajectory, TrajectoryModule, ExamSkill, Lesson

    login_as(client, role_users['tutor_id'], 'tutor')

    with app.app_context():
        master = LearningTrajectory(
            is_template=True,
            created_by_user_id=role_users['tutor_id'],
            title='Оригинальный Мастер-Курс',
            subject='Информатика',
            target_score=90,
            status='active',
        )
        db.session.add(master)
        db.session.flush()

        module = TrajectoryModule(course_id=master.course_id, title='Модуль Графы', order_index=10)
        db.session.add(module)
        db.session.flush()

        lesson1 = Lesson(
            learning_trajectory_id=master.course_id,
            course_module_id=module.module_id,
            topic='Теория графов',
            lesson_format='Теория + Практика',
            duration=60,
            course_order_index=10,
            status='planned',
        )
        lesson2 = Lesson(
            learning_trajectory_id=master.course_id,
            course_module_id=module.module_id,
            topic='Поиск в глубину DFS',
            lesson_format='Практикум',
            duration=60,
            course_order_index=20,
            status='planned',
        )
        db.session.add(lesson1)
        db.session.add(lesson2)
        db.session.commit()
        master_id = master.course_id

    # 1. Test Duplication of Master Course
    dup_res = client.post(f'/courses/{master_id}/duplicate', follow_redirects=False)
    assert dup_res.status_code == 302
    with app.app_context():
        copied = LearningTrajectory.query.filter_by(title='Оригинальный Мастер-Курс (Копия)').first()
        assert copied is not None
        assert copied.is_template is True
        assert copied.parent_course_id == master_id
        assert len(copied.modules) == 1
        assert len(copied.lessons) == 2

    # 2. Test Forking to Student with weekly slots (Tuesday 18:00, Friday 16:00)
    start_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    assign_res = client.post(f'/courses/{master_id}/assign-to-student', data={
        'student_id': str(role_users['student_id']),
        'start_date': start_date,
        'slot_weekday': ['1', '4'],  # Tuesday and Friday
        'slot_time': ['18:00', '16:00'],
    }, follow_redirects=False)

    assert assign_res.status_code == 302
    with app.app_context():
        student_course = LearningTrajectory.query.filter_by(
            parent_course_id=master_id,
            student_id=role_users['student_id'],
            is_template=False
        ).first()
        assert student_course is not None
        assert len(student_course.lessons) == 2
        # Lessons must have dates set according to slots
        l1, l2 = sorted(student_course.lessons, key=lambda x: x.course_order_index)
        assert l1.course_display_date is not None
        assert l2.course_display_date is not None
        assert l1.course_display_date < l2.course_display_date
        assert l1.course_display_date.weekday() in [1, 4]
        assert l2.course_display_date.weekday() in [1, 4]
