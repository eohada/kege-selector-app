import json
from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from app import create_app, db
from core.db_models import User, Student, Lesson, Assignment, Submission
from werkzeug.security import generate_password_hash


@pytest.fixture
def app_instance():
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        # Создаем двух тестовых учеников для изоляции и проверки
        st_user1 = User.query.filter_by(username='test_evo_student1').first()
        if not st_user1:
            st_user1 = User(
                username='test_evo_student1',
                email='test_evo1@example.com',
                password_hash=generate_password_hash('pass123'),
                role='student',
                full_name='Алексей Иванов'
            )
            db.session.add(st_user1)
            db.session.commit()

            st1 = Student(
                user_id=st_user1.id,
                name='Алексей Иванов',
                is_active=True
            )
            db.session.add(st1)
            db.session.commit()

        st_user2 = User.query.filter_by(username='test_evo_student2').first()
        if not st_user2:
            st_user2 = User(
                username='test_evo_student2',
                email='test_evo2@example.com',
                password_hash=generate_password_hash('pass123'),
                role='student',
                full_name='Мария Смирнова'
            )
            db.session.add(st_user2)
            db.session.commit()

            st2 = Student(
                user_id=st_user2.id,
                name='Мария Смирнова',
                is_active=True
            )
            db.session.add(st2)
            db.session.commit()

    return app


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def test_student_schedule_page_structure_and_no_mocks(client, app_instance):
    """Проверка загрузки расписания студента и отсутствия устаревших статических моков."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        assert student_user is not None

        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'ЛИЧНЫЙ МАРШРУТ' in html
        assert 'Моё расписание' in html
        assert 'id="schedule-data"' in html
        assert 'id="unified-ribbon-track"' in html
        assert 'id="unified-day-workspace"' in html

        # Проверяем отсутствие захардкоженных дат и текстов из мока
        assert '12 октября' not in html
        assert 'Вложенные условия и логические операторы' not in html


def test_student_schedule_real_lesson_and_rbac(client, app_instance):
    """Проверка отображения реального урока и строгой изоляции данных (RBAC)."""
    with app_instance.app_context():
        user1 = User.query.filter_by(username='test_evo_student1').first()
        user2 = User.query.filter_by(username='test_evo_student2').first()
        assert user1 and user2

        st1 = Student.query.filter_by(user_id=user1.id).first()
        st2 = Student.query.filter_by(user_id=user2.id).first()
        assert st1 and st2

        now = datetime.now(dt_timezone.utc)
        test_topic_1 = "Урок ученика 1 - Реальная тема"
        test_topic_secret = "Секретный урок ученика 2 - Чужая тема"

        lesson_1 = Lesson(
            student_id=st1.student_id,
            topic=test_topic_1,
            lesson_date=now,
            duration=60,
            status='planned',
            lesson_type='individual'
        )
        lesson_2 = Lesson(
            student_id=st2.student_id,
            topic=test_topic_secret,
            lesson_date=now,
            duration=60,
            status='planned',
            lesson_type='individual'
        )
        db.session.add(lesson_1)
        db.session.add(lesson_2)
        db.session.commit()

        try:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user1.id)
                sess['_fresh'] = True

            resp = client.get('/schedule')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert test_topic_1 in html
            assert test_topic_secret not in html
        finally:
            db.session.delete(lesson_1)
            db.session.delete(lesson_2)
            db.session.commit()


def test_student_schedule_week_navigation(client, app_instance):
    """Проверка смещения недели через параметр ?week=N."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp_next = client.get('/schedule?week=1')
        assert resp_next.status_code == 200
        html_next = resp_next.get_data(as_text=True)
        assert '"week_offset": 1' in html_next or '"week_offset":1' in html_next

        resp_prev = client.get('/schedule?week=-1')
        assert resp_prev.status_code == 200
        html_prev = resp_prev.get_data(as_text=True)
        assert '"week_offset": -1' in html_prev or '"week_offset":-1' in html_prev


def test_student_schedule_data_contract_fields(client, app_instance):
    """Проверка полноты и типов полей в JSON-контракте schedule_page_data."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        start_tag = '<script type="application/json" id="schedule-data">'
        end_tag = '</script>'
        assert start_tag in html
        json_str = html.split(start_tag)[1].split(end_tag)[0]
        data = json.loads(json_str)

        assert 'weekdays' in data
        assert len(data['weekdays']) == 7
        assert 'weekly_stats' in data
        assert 'weekly_bars' in data
        assert 'weekly_goals' in data
        assert 'default_selected_day_index' in data
        assert 'today_iso' in data
        assert 'teacher_name' in data
        assert 'teacher_avatar' in data

        for day in data['weekdays']:
            assert 'name' in day
            assert 'full_name' in day
            assert 'date' in day
            assert 'iso' in day
            assert 'is_today' in day
            assert 'day_index' in day
            assert 'events' in day
            assert len(day['events']) >= 1
            main_ev = day['main_event']
            assert 'title' in main_ev
            assert 'subtitle' in main_ev
            assert 'badge' in main_ev
            assert 'color' in main_ev
            assert 'icon' in main_ev
            assert 'action_url' in main_ev


def test_student_schedule_undefined_defense(client, app_instance):
    """
    Регрессионный тест на устранение первопричины HTTP 500 (UndefinedError).
    Проверяет, что шаблон sandbox/student_schedule.html корректно и безопасно рендерится,
    даже если schedule_page_data пуст или в нем отсутствуют ключи.
    """
    from flask import render_template
    from flask_login import login_user
    with app_instance.test_request_context('/schedule'):
        student_user = User.query.filter_by(username='test_evo_student1').first()
        login_user(student_user)
        # Должен отрендериться без исключения UndefinedError: list object has no element Undefined
        html = render_template('sandbox/student_schedule.html', schedule_page_data={})
        assert 'id="unified-ribbon-track"' in html
        assert 'id="schedule-data"' in html


def test_student_schedule_empty_week_state(client, app_instance):
    """Проверка чистого пустого состояния недели (отдых, 0% прогресса, никаких фейковых занятий)."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule?week=25')  # Будущая пустая неделя
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert '0%' in html
        assert '0 из 0' in html or 'weekly-progress-total">0' in html
        assert 'Отдых' in html or 'Самостоятельное закрепление' in html


def test_student_schedule_multi_lesson_day(client, app_instance):
    """Проверка отображения нескольких занятий в один день и счетчика +N."""
    with app_instance.app_context():
        user1 = User.query.filter_by(username='test_evo_student1').first()
        st1 = Student.query.filter_by(user_id=user1.id).first()

        # Фиксируем дневное время, чтобы исключить переход через полночь в локальной таймзоне
        now = datetime.now(dt_timezone.utc).replace(hour=10, minute=0, second=0)
        lesson_a = Lesson(
            student_id=st1.student_id,
            topic="Урок A - Первый",
            lesson_date=now,
            duration=45,
            status='completed',
            lesson_type='individual'
        )
        lesson_b = Lesson(
            student_id=st1.student_id,
            topic="Урок B - Второй",
            lesson_date=now + timedelta(hours=2),
            duration=60,
            status='planned',
            lesson_type='individual'
        )
        db.session.add(lesson_a)
        db.session.add(lesson_b)
        db.session.commit()

        try:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user1.id)
                sess['_fresh'] = True

            resp = client.get('/schedule')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert 'Урок A - Первый' in html
            assert 'Урок B - Второй' in html
            # Счетчик +1 для нескольких событий на один день
            assert '+1' in html
        finally:
            db.session.delete(lesson_a)
            db.session.delete(lesson_b)
            db.session.commit()


def test_student_schedule_neutral_teacher_fallback(client, app_instance):
    """Проверка нейтрального разрешения преподавателя при отсутствии назначенного ментора."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        st = Student.query.filter_by(user_id=student_user.id).first()
        st.mentor_id = None
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'Преподаватель курса' in html
        # Никаких фейковых фамилий вроде Смирнов или Иванов для преподавателя
        assert 'Александр Смирнов' not in html


def test_student_schedule_extreme_week_offset_clamped(client, app_instance):
    """Защита от переполнения дат (OverflowError) при экстремальных смещениях ?week=N."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp_far_future = client.get('/schedule?week=99999999')
        assert resp_far_future.status_code == 200

        resp_far_past = client.get('/schedule?week=-99999999')
        assert resp_far_past.status_code == 200


def test_student_schedule_unauthenticated_redirect(client):
    """Неавторизованный запрос на /schedule должен редиректить на страницу логина."""
    resp = client.get('/schedule', follow_redirects=False)
    assert resp.status_code in (302, 301)
    assert '/login' in resp.headers.get('Location', '')


def test_student_schedule_homework_statuses_and_deduplication(client, app_instance):
    """Проверка дедупликации заданий и корректного отображения статусов ДЗ."""
    with app_instance.app_context():
        user1 = User.query.filter_by(username='test_evo_student1').first()
        st1 = Student.query.filter_by(user_id=user1.id).first()

        now = datetime.now(dt_timezone.utc)
        asgn = Assignment(
            title="Домашнее задание: Графы и деревья",
            assignment_type='homework',
            deadline=now + timedelta(hours=12),
            created_by_id=user1.id,
            is_active=True
        )
        db.session.add(asgn)
        db.session.commit()

        sub1 = Submission(
            assignment_id=asgn.assignment_id,
            student_id=st1.student_id,
            status='IN_PROGRESS',
            submitted_at=now
        )
        sub2 = Submission(
            assignment_id=asgn.assignment_id,
            student_id=st1.student_id,
            status='IN_PROGRESS',
            submitted_at=now + timedelta(minutes=5)
        )
        db.session.add(sub1)
        db.session.add(sub2)
        db.session.commit()

        try:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user1.id)
                sess['_fresh'] = True

            resp = client.get('/schedule')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert 'Графы и деревья' in html
            # Проверяем, что в active_homework ровно 1 запись для этого assignment_id (дедуплицировано)
            start_tag = '<script type="application/json" id="schedule-data">'
            end_tag = '</script>'
            json_str = html.split(start_tag)[1].split(end_tag)[0]
            data = json.loads(json_str)
            matching_hw = [h for h in data['active_homework'] if h['id'] == asgn.assignment_id]
            assert len(matching_hw) == 1
        finally:
            db.session.delete(sub1)
            db.session.delete(sub2)
            db.session.delete(asgn)
            db.session.commit()


def test_student_schedule_midnight_timezone_shift(client, app_instance):
    """Проверка конвертации времени урока около полуночи в таймзону пользователя."""
    with app_instance.app_context():
        user1 = User.query.filter_by(username='test_evo_student1').first()
        st1 = Student.query.filter_by(user_id=user1.id).first()

        # Создаем урок в 23:30 Moscow time
        # В Tomsk (UTC+7, MSK+4) это будет 03:30 следующего дня
        now = datetime.now(dt_timezone.utc)
        # Находим текущий вторник 20:30 UTC = 23:30 MSK
        msk_late = datetime(now.year, now.month, now.day, 20, 30, tzinfo=dt_timezone.utc)
        lesson_late = Lesson(
            student_id=st1.student_id,
            topic="Поздний вечерний урок",
            lesson_date=msk_late,
            duration=60,
            status='planned',
            lesson_type='individual'
        )
        db.session.add(lesson_late)
        db.session.commit()

        try:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user1.id)
                sess['_fresh'] = True

            # Запрашиваем с таймзоной Asia/Tomsk
            resp = client.get('/schedule?timezone=Asia/Tomsk')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert 'Поздний вечерний урок' in html
            start_tag = '<script type="application/json" id="schedule-data">'
            end_tag = '</script>'
            json_str = html.split(start_tag)[1].split(end_tag)[0]
            data = json.loads(json_str)
            assert data['timezone'] == 'Asia/Tomsk'
        finally:
            db.session.delete(lesson_late)
            db.session.commit()


def test_student_schedule_concept_d_ribbon_structure(client, app_instance):
    """Sprint 2.0: Проверка 7-дневной ленты Concept D и интерактивных табов."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'id="unified-ribbon-track"' in html
        for i in range(7):
            assert f'id="unified-tab-{i}"' in html
        assert 'unified-day-tab' in html
        assert 'is-active' in html
        assert 'id="unified-week-label"' in html


def test_student_schedule_concept_d_peer_lessons_and_compact_tasks(client, app_instance):
    """Sprint 2.0: Проверка равноправных карточек уроков и компактных полос ДЗ."""
    with app_instance.app_context():
        user = User.query.filter_by(username='test_evo_student1').first()
        st = Student.query.filter_by(user_id=user.id).first()

        now = datetime.now(dt_timezone.utc)
        test_lesson = Lesson(
            student_id=st.student_id,
            topic="Интеграционный урок Concept D",
            lesson_date=now,
            duration=60,
            status='planned',
            lesson_type='individual'
        )
        asgn = Assignment(
            title="Интеграционное ДЗ Concept D",
            assignment_type='homework',
            deadline=now + timedelta(hours=8),
            created_by_id=user.id,
            is_active=True
        )
        db.session.add(test_lesson)
        db.session.add(asgn)
        db.session.commit()

        sub = Submission(
            assignment_id=asgn.assignment_id,
            student_id=st.student_id,
            status='IN_PROGRESS',
            submitted_at=now
        )
        db.session.add(sub)
        db.session.commit()

        try:
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
                sess['_fresh'] = True

            resp = client.get('/schedule')
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            assert 'peer-event-card' in html
            assert 'btn-3d-primary' in html
            assert 'btn-3d-amber' in html
            assert 'Интеграционный урок Concept D' in html
            assert 'Интеграционное ДЗ Concept D' in html
            assert 'Войти в урок →' in html
            assert 'Сдать работу →' in html
        finally:
            db.session.delete(sub)
            db.session.delete(asgn)
            db.session.delete(test_lesson)
            db.session.commit()


def test_student_schedule_concept_d_empty_day_boo(client, app_instance):
    """Sprint 2.0: Проверка органического Empty State с маскотом Бу на пустой неделе."""
    with app_instance.app_context():
        student_user = User.query.filter_by(username='test_evo_student1').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule?week=50')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'hero_mascot_3d.png' in html
        assert 'Свободный учебный день' in html
        assert 'Перейти в банк задач' in html
        assert 'База знаний и теория' in html



