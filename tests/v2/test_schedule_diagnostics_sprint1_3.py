import json
from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from app import create_app, db
from core.db_models import (
    User, Student, Lesson, Assignment, Submission, Course, TrajectoryModule, Enrollment
)
from werkzeug.security import generate_password_hash


@pytest.fixture
def app_instance():
    app = create_app()
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['TESTING'] = True
    with app.app_context():
        db.create_all()
        # Create mentor
        mentor = User.query.filter_by(username='mentor_diag').first()
        if not mentor:
            mentor = User(
                username='mentor_diag',
                email='mentor_diag@example.com',
                password_hash=generate_password_hash('pass123'),
                role='teacher',
                full_name='Виктор Сергеевич'
            )
            db.session.add(mentor)
            db.session.commit()

        # Create student 1: Empty
        st1_u = User.query.filter_by(username='st_empty').first()
        if not st1_u:
            st1_u = User(username='st_empty', email='st_empty@example.com', password_hash=generate_password_hash('p'), role='student', full_name='Пустой Ученик')
            db.session.add(st1_u)
            db.session.commit()
            st1 = Student(user_id=st1_u.id, name='Пустой Ученик', mentor_id=mentor.id, is_active=True)
            db.session.add(st1)
            db.session.commit()

        # Create student 2: Standard (1 teacher)
        st2_u = User.query.filter_by(username='st_standard').first()
        if not st2_u:
            st2_u = User(username='st_standard', email='st_std@example.com', password_hash=generate_password_hash('p'), role='student', full_name='Стандартный Ученик')
            db.session.add(st2_u)
            db.session.commit()
            st2 = Student(user_id=st2_u.id, name='Стандартный Ученик', mentor_id=mentor.id, is_active=True)
            db.session.add(st2)
            db.session.commit()

        # Create student 3: Heavy / Multi-event
        st3_u = User.query.filter_by(username='st_heavy').first()
        if not st3_u:
            st3_u = User(username='st_heavy', email='st_heavy@example.com', password_hash=generate_password_hash('p'), role='student', full_name='Загруженный Ученик')
            db.session.add(st3_u)
            db.session.commit()
            st3 = Student(user_id=st3_u.id, name='Загруженный Ученик', mentor_id=mentor.id, is_active=True)
            db.session.add(st3)
            db.session.commit()

    return app


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def test_persona_empty_student_schedule(client, app_instance):
    """Persona 1: Ученик без занятий и ДЗ. Все дни должны быть free, прогресс 0, is_completed False."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_empty').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        assert 'id="schedule-data"' in html
        json_str = html.split('id="schedule-data">')[1].split('</script>')[0]
        data = json.loads(json_str)

        assert len(data['weekdays']) == 7
        for day in data['weekdays']:
            assert day['is_completed'] is False
            assert day['has_uncompleted_past'] is False
            assert day['events_count'] == 0
            assert day['events'][0]['type'] == 'free'

        assert data['weekly_stats']['conducted'] == 0
        assert data['weekly_stats']['planned'] == 0
        assert data['weekly_stats']['percent'] == 0


def test_persona_homework_lifecycle_and_day_completion(client, app_instance):
    """Persona 5 & Domain Semantics: Проверка жизненного цикла ДЗ и семантики is_completed."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())

        # 1. Assignment due on Tuesday, status ASSIGNED
        tue_deadline = (monday + timedelta(days=1)).replace(hour=18, minute=0, second=0)
        asgn1 = Assignment(title='ДЗ по графам', assignment_type='homework', created_by_id=st.mentor_id, deadline=tue_deadline, is_active=True)
        db.session.add(asgn1)
        db.session.commit()
        sub1 = Submission(assignment_id=asgn1.assignment_id, student_id=st.student_id, status='ASSIGNED')
        db.session.add(sub1)

        # 2. Assignment due on Wednesday, status SUBMITTED
        wed_deadline = (monday + timedelta(days=2)).replace(hour=19, minute=0, second=0)
        asgn2 = Assignment(title='ДЗ по динамике', assignment_type='homework', created_by_id=st.mentor_id, deadline=wed_deadline, is_active=True)
        db.session.add(asgn2)
        db.session.commit()
        sub2 = Submission(assignment_id=asgn2.assignment_id, student_id=st.student_id, status='SUBMITTED')
        db.session.add(sub2)

        # 3. Lesson on Wednesday: COMPLETED
        l_wed = Lesson(
            student_id=st.student_id,
            lesson_date=wed_deadline - timedelta(hours=2),
            duration=60,
            status='completed',
            topic='Разбор динамического программирования'
        )
        db.session.add(l_wed)

        # 4. Assignment due on Thursday, status RETURNED
        thu_deadline = (monday + timedelta(days=3)).replace(hour=20, minute=0, second=0)
        asgn3 = Assignment(title='ДЗ по строкам', assignment_type='homework', created_by_id=st.mentor_id, deadline=thu_deadline, is_active=True)
        db.session.add(asgn3)
        db.session.commit()
        sub3 = Submission(assignment_id=asgn3.assignment_id, student_id=st.student_id, status='RETURNED')
        db.session.add(sub3)

        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        json_str = html.split('id="schedule-data">')[1].split('</script>')[0]
        data = json.loads(json_str)

        # Tuesday: ASSIGNED -> not completed
        tue_day = data['weekdays'][1]
        assert tue_day['events_count'] == 1
        assert tue_day['is_completed'] is False
        assert tue_day['events'][0]['badge'] == 'Домашнее задание'

        # Wednesday: Lesson completed AND Homework submitted -> is_completed MUST be True!
        wed_day = data['weekdays'][2]
        assert wed_day['events_count'] == 2
        assert wed_day['is_completed'] is True
        hw_ev = [e for e in wed_day['events'] if e['type'] == 'homework'][0]
        assert hw_ev['badge'] == 'ДЗ сдано'

        # Thursday: RETURNED -> is_completed MUST be False
        thu_day = data['weekdays'][3]
        assert thu_day['events_count'] == 1
        assert thu_day['is_completed'] is False
        hw_ev3 = thu_day['events'][0]
        assert hw_ev3['badge'] == 'На доработке'


def test_cancelled_lesson_semantics(client, app_instance):
    """Отменённый урок не должен помечать день как завершённый (is_completed: False)."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        fri_date = (monday + timedelta(days=4)).replace(hour=15, minute=0, second=0)

        l_canc = Lesson(
            student_id=st.student_id,
            lesson_date=fri_date,
            duration=60,
            status='cancelled',
            topic='Отмененный урок по графам'
        )
        db.session.add(l_canc)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        json_str = html.split('id="schedule-data">')[1].split('</script>')[0]
        data = json.loads(json_str)

        fri_day = data['weekdays'][4]
        assert fri_day['events_count'] == 1
        assert fri_day['is_completed'] is False
        assert fri_day['events'][0]['badge'] == 'Отменено'


def test_heavy_student_multi_events_and_segmented_tabs(client, app_instance):
    """Persona 4: День с несколькими событиями (урок + 2 ДЗ) должен иметь events_count == 3."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_heavy').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        target_day = (monday + timedelta(days=1)).replace(hour=16, minute=0, second=0)

        # 1 Lesson + 2 Assignments on Tuesday
        l1 = Lesson(student_id=st.student_id, lesson_date=target_day, duration=90, status='planned', topic='Сложная тема')
        a1 = Assignment(title='ДЗ ч.1', assignment_type='homework', created_by_id=st.mentor_id, deadline=target_day + timedelta(hours=3), is_active=True)
        a2 = Assignment(title='ДЗ ч.2', assignment_type='homework', created_by_id=st.mentor_id, deadline=target_day + timedelta(hours=4), is_active=True)
        db.session.add_all([l1, a1, a2])
        db.session.commit()
        s1 = Submission(assignment_id=a1.assignment_id, student_id=st.student_id, status='ASSIGNED')
        s2 = Submission(assignment_id=a2.assignment_id, student_id=st.student_id, status='IN_PROGRESS')
        db.session.add_all([s1, s2])
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        json_str = html.split('id="schedule-data">')[1].split('</script>')[0]
        data = json.loads(json_str)

        day_tue = data['weekdays'][1]
        assert day_tue['events_count'] == 3
        # In HTML, badge "+2" should be rendered
        assert '+2' in html


def test_calendar_boundaries_and_navigation(client, app_instance):
    """Проверка смещения недель (?week=-1, ?week=0, ?week=1, boundaries -104..104)."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_empty').first()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        # Current week
        resp = client.get('/schedule?week=0')
        assert resp.status_code == 200

        # Past week
        resp_past = client.get('/schedule?week=-1')
        assert resp_past.status_code == 200
        data_past = json.loads(resp_past.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        assert data_past['week_offset'] == -1

        # Future week
        resp_fut = client.get('/schedule?week=2')
        assert resp_fut.status_code == 200
        data_fut = json.loads(resp_fut.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        assert data_fut['week_offset'] == 2

        # Boundary clamping (>104 -> 104)
        resp_bound = client.get('/schedule?week=999')
        assert resp_bound.status_code == 200
        data_bound = json.loads(resp_bound.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        assert data_bound['week_offset'] == 104


def test_timezone_conversion(client, app_instance):
    """Проверка смены часового пояса (Europe/Moscow vs Asia/Tomsk +4)."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        # Lesson at 14:00 UTC
        lesson_time_utc = (monday + timedelta(days=1)).replace(hour=14, minute=0, second=0, tzinfo=dt_timezone.utc)
        l = Lesson(student_id=st.student_id, lesson_date=lesson_time_utc, duration=60, status='planned', topic='Тест времени')
        db.session.add(l)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        # In Moscow (UTC+3) -> 17:00
        resp_msk = client.get('/schedule?timezone=Europe/Moscow')
        assert resp_msk.status_code == 200
        data_msk = json.loads(resp_msk.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        tue_msk = data_msk['weekdays'][1]
        ev_msk = tue_msk['events'][0]
        assert '17:00' in ev_msk['time_str']

        # In Tomsk (UTC+7) -> 21:00
        resp_tsk = client.get('/schedule?timezone=Asia/Tomsk')
        assert resp_tsk.status_code == 200
        data_tsk = json.loads(resp_tsk.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        tue_tsk = data_tsk['weekdays'][1]
        ev_tsk = tue_tsk['events'][0]
        assert '21:00' in ev_tsk['time_str']


def test_long_strings_resilience(client, app_instance):
    """Проверка устойчивости интерфейса к длинным строкам (тема, заметки)."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        lesson_time = (monday + timedelta(days=2)).replace(hour=12, minute=0, second=0)

        huge_topic = "Очень длинная тема занятия " * 10
        huge_notes = "Сверхдлинная персональная рекомендация ученику перед экзаменом " * 15

        l = Lesson(student_id=st.student_id, lesson_date=lesson_time, duration=60, status='planned', topic=huge_topic, notes=huge_notes)
        db.session.add(l)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert huge_topic[:30] in html


def test_weekly_progress_formula_and_metrics_transparency(client, app_instance):
    """Аудит формулы расчета еженедельного прогресса:
    completion_base = conducted + planned
    progress_percent = round((conducted / completion_base) * 100) if completion_base > 0 else 0
    """
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())

        # 2 conducted lessons + 2 planned lessons = 4 total, progress must be exactly 50%
        l1 = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=0)).replace(hour=10), duration=60, status='completed', topic='L1')
        l2 = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=1)).replace(hour=10), duration=60, status='completed', topic='L2')
        l3 = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=2)).replace(hour=10), duration=60, status='planned', topic='L3')
        l4 = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=3)).replace(hour=10), duration=60, status='planned', topic='L4')
        db.session.add_all([l1, l2, l3, l4])
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        data = json.loads(resp.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        stats = data['weekly_stats']

        assert stats['conducted'] >= 2
        assert stats['planned'] >= 2
        # Verify base and calculation
        base = stats['conducted'] + stats['planned']
        expected_pct = int(round((stats['conducted'] / base) * 100))
        assert stats['percent'] == expected_pct


def test_midnight_lesson_bounds(client, app_instance):
    """Урок, начинающийся поздно вечером (23:30), не должен вызывать переполнение end_total > 1440."""
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        late_night = (monday + timedelta(days=0)).replace(hour=23, minute=30, second=0)

        l = Lesson(student_id=st.student_id, lesson_date=late_night, duration=60, status='planned', topic='Ночной практикум')
        db.session.add(l)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule?timezone=UTC')
        assert resp.status_code == 200
        data = json.loads(resp.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        mon_events = data['weekdays'][0]['events']
        late_ev = [e for e in mon_events if e.get('title') == 'Ночной практикум']
        assert len(late_ev) == 1
        assert late_ev[0]['time_str'].startswith('23:30')


def test_multi_teacher_schema_constraint_verification(client, app_instance):
    """Верификация схемы данных Multi-Teacher (Sprint 2.2):
    Lesson имеет явное поле teacher_id (FK Users.id) и subject.
    """
    with app_instance.app_context():
        from core.db_models import Lesson, Student
        lesson_cols = [c.name for c in Lesson.__table__.columns]
        assert 'teacher_id' in lesson_cols
        assert 'subject' in lesson_cols
        assert 'student_id' in lesson_cols

        student_cols = [c.name for c in Student.__table__.columns]
        assert 'mentor_id' in student_cols


def test_multi_teacher_isolation_scenario(client, app_instance):
    """Сценарий 1 ученик - 2 преподавателя (Sprint 2.0.1):
    Когда ученик записан к двум разным преподавателям (например, Tutor A и Tutor B),
    система НЕ должна ошибочно приписывать уроки одного преподавателя другому.
    При неоднозначности карточка занятия честно отображает 'Преподаватель курса'.
    """
    with app_instance.app_context():
        from core.db_models import Course, Enrollment

        # Создаем двух преподавателей
        tutor1_user = User.query.filter_by(username='tutor_multi_1').first()
        if not tutor1_user:
            tutor1_user = User(username='tutor_multi_1', role='tutor', full_name='Иван Преподаватель')
            tutor1_user.set_password('pass123')
            db.session.add(tutor1_user)

        tutor2_user = User.query.filter_by(username='tutor_multi_2').first()
        if not tutor2_user:
            tutor2_user = User(username='tutor_multi_2', role='tutor', full_name='Елена Наставник')
            tutor2_user.set_password('pass123')
            db.session.add(tutor2_user)

        # Создаем ученика с двумя enrollment
        st_user = User.query.filter_by(username='st_multi_teacher').first()
        if not st_user:
            st_user = User(username='st_multi_teacher', role='student', full_name='Ученик Двух Преподавателей')
            st_user.set_password('pass123')
            db.session.add(st_user)
            db.session.flush()

        st_obj = Student.query.filter_by(user_id=st_user.id).first()
        if not st_obj:
            st_obj = Student(user_id=st_user.id, name='Ученик Двух Преподавателей', is_active=True, mentor_id=tutor1_user.id)
            db.session.add(st_obj)
            db.session.flush()

        # Привязываем ученика к двум разным тьюторам через Enrollment (с разными предметами)
        e1 = Enrollment.query.filter_by(student_id=st_user.id, tutor_id=tutor1_user.id).first()
        if not e1:
            e1 = Enrollment(student_id=st_user.id, tutor_id=tutor1_user.id, subject='Информатика')
            db.session.add(e1)

        e2 = Enrollment.query.filter_by(student_id=st_user.id, tutor_id=tutor2_user.id).first()
        if not e2:
            e2 = Enrollment(student_id=st_user.id, tutor_id=tutor2_user.id, subject='Математика')
            db.session.add(e2)

        # Урок на этой неделе
        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())
        l = Lesson(student_id=st_obj.student_id, lesson_date=(monday + timedelta(days=1)).replace(hour=14), duration=60, status='planned', topic='Мульти-урок')
        db.session.add(l)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(st_user.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        data = json.loads(html.split('id="schedule-data">')[1].split('</script>')[0])

        # При наличии 2 разных преподавателей глобальный fallback честно нейтрален
        assert data.get('teacher_name') in (None, 'Преподаватель курса')

        tue_events = data['weekdays'][1]['events']
        lesson_ev = [e for e in tue_events if e.get('title') == 'Мульти-урок'][0]
        # Проверяем, что карточка не приписана ложно одному из них как единственный ментор
        assert lesson_ev['teacher']['name'] == 'Преподаватель курса'


def test_materials_and_notes_strict_isolation(client, app_instance):
    """Проверка изоляции материалов и заметок (Sprint 2.0.1):
    Материалы одного урока не должны утекать в карточку другого урока.
    """
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())

        # Lesson A: has materials and notes
        mat_item = [{'title': 'Спецификация КИМ 2026.pdf', 'url': '/files/kim2026.pdf', 'pages': '4 стр'}]
        l_with_mat = Lesson(
            student_id=st.student_id,
            lesson_date=(monday + timedelta(days=0)).replace(hour=11),
            duration=60,
            status='planned',
            topic='Теория с материалами',
            student_notes='Индивидуальный совет только для этого урока',
            materials=mat_item,
        )

        # Lesson B: has NO materials and NO notes
        l_without_mat = Lesson(
            student_id=st.student_id,
            lesson_date=(monday + timedelta(days=0)).replace(hour=15),
            duration=60,
            status='planned',
            topic='Урок без материалов',
            student_notes=None,
            notes=None,
            materials=None,
        )
        db.session.add_all([l_with_mat, l_without_mat])
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        data = json.loads(html.split('id="schedule-data">')[1].split('</script>')[0])

        mon_events = data['weekdays'][0]['events']
        ev_with = [e for e in mon_events if e.get('title') == 'Теория с материалами'][0]
        ev_without = [e for e in mon_events if e.get('title') == 'Урок без материалов'][0]

        # Lesson A has its own material and note
        assert len(ev_with['materials']) == 1
        assert ev_with['materials'][0]['title'] == 'Спецификация КИМ 2026.pdf'
        assert ev_with['notes'] == 'Индивидуальный совет только для этого урока'

        # Lesson B must be EMPTY (no leakage!)
        assert ev_without['materials'] == []
        assert ev_without['notes'] == ''


def test_real_streak_integrity_and_no_fictitious_fallback(client, app_instance):
    """Проверка стрика (Sprint 2.0.1):
    Запрещены фиктивные захардкоженные значения вроде '5 дн.'.
    Стрик должен считываться достоверно из модели студента.
    """
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        # Устанавливаем стрик = 0
        st.streak_days = 0
        st.last_activity_date = None
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        data = json.loads(html.split('id="schedule-data">')[1].split('</script>')[0])

        assert data['weekly_stats']['streak_days'] == 0
        # В HTML не должно быть фиктивного '5 дн. ударный темп'
        assert '5 дн. ударный темп' not in html

        # Устанавливаем реальный стрик 9 дней с активностью сегодня
        st.streak_days = 9
        st.last_activity_date = datetime.now(dt_timezone.utc).date()
        db.session.commit()

        resp2 = client.get('/schedule')
        assert resp2.status_code == 200
        html2 = resp2.get_data(as_text=True)
        data2 = json.loads(html2.split('id="schedule-data">')[1].split('</script>')[0])

        assert data2['weekly_stats']['streak_days'] == 9
        assert '9 дн. ударный темп' in html2


def test_cancelled_lesson_excluded_from_completion_base(client, app_instance):
    """Аудит формулы прогресса (Sprint 2.0.1):
    Отмененные уроки (status='cancelled') не должны штрафовать ученика и не входят в completion_base.
    """
    with app_instance.app_context():
        u = User.query.filter_by(username='st_standard').first()
        st = Student.query.filter_by(user_id=u.id).first()

        # Очистим старые уроки текущей недели для точного подсчета
        now = datetime.now(dt_timezone.utc)
        monday = now - timedelta(days=now.weekday())

        Lesson.query.filter(Lesson.student_id == st.student_id).delete()
        db.session.commit()

        # 1 проведенный + 1 запланированный + 1 отмененный
        l_done = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=0)).replace(hour=10), duration=60, status='completed', topic='Пройденный')
        l_plan = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=1)).replace(hour=10), duration=60, status='planned', topic='Будущий')
        l_canc = Lesson(student_id=st.student_id, lesson_date=(monday + timedelta(days=2)).replace(hour=10), duration=60, status='cancelled', topic='Отмененный')
        db.session.add_all([l_done, l_plan, l_canc])
        db.session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True

        resp = client.get('/schedule')
        assert resp.status_code == 200
        data = json.loads(resp.get_data(as_text=True).split('id="schedule-data">')[1].split('</script>')[0])
        stats = data['weekly_stats']

        assert stats['conducted'] == 1
        assert stats['planned'] == 1
        assert stats['cancelled'] == 1
        # completion_base = 1 + 1 = 2 (отмененный исключен!)
        assert stats['conducted_and_planned'] == 2
        # percent = 1 / 2 = 50%
        assert stats['percent'] == 50


