import pytest
from app import create_app, db
from app.models import User, Student
from core.db_models import StudentLearningPlanItem

from core.audit_logger import audit_logger

@pytest.fixture
def app_ctx(monkeypatch):
    monkeypatch.setattr(audit_logger, 'log', lambda *args, **kwargs: None)
    monkeypatch.setattr(audit_logger, 'log_error', lambda *args, **kwargs: None)
    monkeypatch.setattr(audit_logger, 'log_event', lambda *args, **kwargs: None)
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def test_data(app_ctx):
    # Teacher
    teacher = User(
        email="teacher@test.local",
        username="teacher_bob",
        role="teacher",
        full_name="Боб Учителев"
    )
    teacher.set_password("pass123")
    db.session.add(teacher)

    # Student User + Student model
    student_user = User(
        email="student@test.local",
        username="student_alice",
        role="student",
        full_name="Алиса Студентова"
    )
    student_user.set_password("pass123")
    db.session.add(student_user)
    db.session.flush()

    student = Student(
        student_id=student_user.id,
        user_id=student_user.id,
        name="Алиса Студентова",
        mentor_id=teacher.id,
        xp=100,
        level=1,
        streak_days=3,
        streak_weeks=1,
        study_time_seconds=3600
    )
    db.session.add(student)

    # Other student (unauthorized viewer)
    other_student = User(
        email="other@test.local",
        username="student_charlie",
        role="student",
        full_name="Чарли Другой"
    )
    other_student.set_password("pass123")
    db.session.add(other_student)

    db.session.commit()

    return {
        'teacher_id': teacher.id,
        'student_user_id': student_user.id,
        'student_id': student.student_id,
        'other_student_id': other_student.id
    }


def test_staff_view_student_profile(app_ctx, test_data):
    """Преподаватель может открыть профиль ученика и видит панель управления."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['teacher_id'])
        sess['_fresh'] = True

    resp = client.get(f"/workspace/people/{test_data['student_user_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Должен отображаться бейдж управления и кнопки
    assert "Просмотр профиля ученика" in html
    assert "XP / Бонус" in html
    assert "Управление стриком" in html
    assert "Учебное время" in html
    assert "manage-xp-modal" in html
    assert "manage-streak-modal" in html
    assert "manage-study-time-modal" in html


def test_staff_manage_xp_bonus_and_set(app_ctx, test_data):
    """Преподаватель может начислять бонусный XP и задавать точный уровень опыта."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['teacher_id'])
        sess['_fresh'] = True

    # 1. Бонус XP
    resp1 = client.post(
        f"/student/{test_data['student_id']}/xp",
        json={"mode": "bonus", "bonus_xp": 250, "reason": "За активную работу"}
    )
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1['status'] == 'ok'
    assert data1['xp'] >= 350  # 100 + 250 (+ любые заработанные ачивки)

    # 2. Установка точного XP
    resp2 = client.post(
        f"/student/{test_data['student_id']}/xp",
        json={"mode": "set", "new_xp": 1200}
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['status'] == 'ok'
    assert data2['xp'] >= 1200

    # Проверка в базе
    student = Student.query.get(test_data['student_id'])
    assert student.xp >= 1200


def test_staff_manage_streak(app_ctx, test_data):
    """Преподаватель может менять ежедневный и недельный стрик, заморозку и сбрасывать."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['teacher_id'])
        sess['_fresh'] = True

    # 1. Изменение параметров стрика
    resp1 = client.post(
        f"/student/{test_data['student_id']}/streak",
        json={
            "streak_days": 14,
            "streak_frozen": True,
            "streak_weeks": 3,
            "streak_weeks_frozen": True
        }
    )
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1['status'] == 'ok'
    assert data1['streak_days'] == 14
    assert data1['streak_frozen'] is True
    assert data1['streak_weeks'] == 3
    assert data1['streak_weeks_frozen'] is True

    # 2. Сброс стрика
    resp2 = client.post(
        f"/student/{test_data['student_id']}/streak",
        json={"action": "reset"}
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['status'] == 'ok'
    assert data2['streak_days'] == 0
    assert data2['streak_weeks'] == 0


def test_staff_manage_study_time(app_ctx, test_data):
    """Преподаватель может добавлять учебные минуты и устанавливать точные часы/минуты."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['teacher_id'])
        sess['_fresh'] = True

    # Исходное время: 3600 сек (60 мин)
    # 1. Добавление 45 минут (2700 сек)
    resp1 = client.post(
        f"/student/{test_data['student_id']}/study_time",
        json={"mode": "add", "minutes": 45}
    )
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert data1['status'] == 'ok'
    assert data1['total_seconds'] == 3600 + 2700  # 6300 сек (1 ч 45 мин)

    # 2. Установка точного времени: 4 часа 30 минут = 4*3600 + 30*60 = 16200 сек
    resp2 = client.post(
        f"/student/{test_data['student_id']}/study_time",
        json={"mode": "set", "hours": 4, "minutes": 30}
    )
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2['status'] == 'ok'
    assert data2['total_seconds'] == 16200


def test_staff_manage_student_goals(app_ctx, test_data):
    """Преподаватель может добавлять, переключать и удалять цели ученика из его профиля."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['teacher_id'])
        sess['_fresh'] = True

    # 1. Добавление цели для ученика
    resp_add = client.post(
        "/api/profile/goal/add",
        data={"title": "Решить вариант №12 КЕГЭ", "student_id": test_data['student_id']}
    )
    assert resp_add.status_code == 201
    item_id = resp_add.get_json()['item_id']

    # Проверка в базе
    item = StudentLearningPlanItem.query.get(item_id)
    assert item is not None
    assert item.student_id == test_data['student_id']
    assert item.title == "Решить вариант №12 КЕГЭ"
    assert item.status == "planned"

    # 2. Переключение статуса цели
    resp_toggle = client.post(
        f"/api/profile/goal/toggle/{item_id}",
        data={"student_id": test_data['student_id']}
    )
    assert resp_toggle.status_code == 200
    item = StudentLearningPlanItem.query.get(item_id)
    assert item.status == "done"

    # 3. Удаление цели
    resp_del = client.post(
        f"/api/profile/goal/delete/{item_id}",
        data={"student_id": test_data['student_id']}
    )
    assert resp_del.status_code == 200
    assert StudentLearningPlanItem.query.get(item_id) is None


def test_student_cannot_tamper_other_student_data(app_ctx, test_data):
    """Другой ученик не может редактировать XP, стрик или учебное время чужого профиля (403)."""
    client = app_ctx.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_data['other_student_id'])
        sess['_fresh'] = True

    # Попытка начислить себе/другому XP
    resp_xp = client.post(
        f"/student/{test_data['student_id']}/xp",
        json={"mode": "bonus", "bonus_xp": 1000}
    )
    assert resp_xp.status_code in [403, 302]

    # Попытка изменить стрик
    resp_streak = client.post(
        f"/student/{test_data['student_id']}/streak",
        json={"streak_days": 100}
    )
    assert resp_streak.status_code in [403, 302]

    # Попытка изменить учебное время
    resp_time = client.post(
        f"/student/{test_data['student_id']}/study_time",
        json={"mode": "add", "minutes": 1000}
    )
    assert resp_time.status_code in [403, 302]
