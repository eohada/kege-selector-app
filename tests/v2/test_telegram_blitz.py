import pytest
from datetime import date
from app import create_app, db
from app.models import User, Student
from app.telegram.blitz_service import (
    BLITZ_QUESTIONS,
    get_blitz_by_id,
    get_daily_blitz,
    format_blitz_message,
    build_blitz_inline_keyboard,
    check_blitz_answer,
    send_daily_blitz_to_student
)

@pytest.fixture
def app_ctx():
    app = create_app('testing')
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

def test_blitz_questions_bank_structure():
    """Проверка структуры и целостности банка блиц-задач."""
    assert len(BLITZ_QUESTIONS) >= 10
    for q in BLITZ_QUESTIONS:
        assert 'id' in q and q['id']
        assert 'topic' in q and q['topic']
        assert 'question' in q and q['question']
        assert 'options' in q and len(q['options']) >= 3
        assert 'correct_idx' in q and 0 <= q['correct_idx'] < len(q['options'])
        assert 'explanation' in q and q['explanation']

def test_get_daily_blitz_deterministic():
    """Проверка детерминированного выбора задачи дня по дате."""
    d1 = date(2026, 4, 1)
    d2 = date(2026, 4, 2)
    q1 = get_daily_blitz(d1)
    q1_repeat = get_daily_blitz(d1)
    q2 = get_daily_blitz(d2)

    assert q1['id'] == q1_repeat['id']
    # На следующий день выбирается следующая циклическая задача
    assert q1['id'] != q2['id']

def test_format_blitz_message_and_keyboard():
    """Проверка формирования HTML-сообщения и инлайн-клавиатуры."""
    blitz = BLITZ_QUESTIONS[0]
    msg = format_blitz_message(blitz, streak_days=5)
    assert "Блиц-задача дня" in msg
    assert "5 дней" in msg
    assert blitz['question'] in msg

    kb = build_blitz_inline_keyboard(blitz)
    assert 'inline_keyboard' in kb
    assert len(kb['inline_keyboard']) == len(blitz['options'])
    for idx, row in enumerate(kb['inline_keyboard']):
        btn = row[0]
        assert btn['callback_data'] == f"blitz_ans:{blitz['id']}:{idx}"

def test_check_blitz_answer_incorrect_then_correct(app_ctx):
    """Проверка: неверный ответ даёт подсказку, верный ответ начисляет XP и стрик."""
    from datetime import timedelta
    from app.models import moscow_now

    user = User(email="blitz_user@test.local", username="blitz_user", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()

    yesterday = moscow_now().date() - timedelta(days=1)
    student = Student(user_id=user.id, name="Блиц Ученик", streak_days=3, xp=50, last_activity_date=yesterday)
    db.session.add(student)
    db.session.commit()

    blitz = BLITZ_QUESTIONS[0]
    correct_idx = blitz['correct_idx']
    wrong_idx = (correct_idx + 1) % len(blitz['options'])

    # 1. Неверный ответ:
    res_wrong = check_blitz_answer(user, blitz['id'], wrong_idx)
    assert res_wrong['success'] is True
    assert res_wrong['is_correct'] is False
    assert "Не совсем так" in res_wrong['message']

    # Стрик и опыт не изменились
    db.session.refresh(student)
    assert student.streak_days == 3
    assert student.xp == 50

    # 2. Правильный ответ:
    res_correct = check_blitz_answer(user, blitz['id'], correct_idx)
    assert res_correct['success'] is True
    assert res_correct['is_correct'] is True
    assert res_correct['xp_awarded'] == 10
    assert "ВЕРНО" in res_correct['message']

    db.session.refresh(student)
    assert student.streak_days >= 4
    assert student.xp >= 60

def test_send_daily_blitz_to_student_mock(app_ctx, monkeypatch):
    """Проверка функции отправки задачи дня ученику."""
    user = User(
        email="blitz_mock@test.local",
        username="blitz_mock",
        role="student",
        telegram_id="999888777"
    )
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name="Тест Ученик", streak_days=2)
    db.session.add(student)
    db.session.commit()

    called = []
    def fake_send(chat_id, text_body, **kwargs):
        called.append((chat_id, text_body, kwargs))
        return {'ok': True}

    import app.telegram.notifications
    monkeypatch.setattr(app.telegram.notifications, 'send_telegram_message', fake_send)

    sent = send_daily_blitz_to_student(student, force=True)
    assert sent is True
    assert len(called) == 1
    assert called[0][0] == 999888777
    assert "Блиц-задача дня" in called[0][1]


def test_broadcast_daily_blitz_reminders(app_ctx, monkeypatch):
    """Проверка массовой рассылки блиц-напоминаний."""
    from app.telegram.blitz_service import broadcast_daily_blitz_reminders

    u1 = User(email="st1@test.local", username="st1", role="student", telegram_id="111")
    u1.set_password("p1")
    u2 = User(email="st2@test.local", username="st2", role="student", telegram_id="222")
    u2.set_password("p2")
    db.session.add_all([u1, u2])
    db.session.flush()

    s1 = Student(user_id=u1.id, name="Ученик 1")
    s2 = Student(user_id=u2.id, name="Ученик 2")
    db.session.add_all([s1, s2])
    db.session.commit()

    called = []
    def fake_send(chat_id, text_body, **kwargs):
        called.append(chat_id)
        return {'ok': True}

    import app.telegram.notifications
    monkeypatch.setattr(app.telegram.notifications, 'send_telegram_message', fake_send)

    count = broadcast_daily_blitz_reminders(force=True)
    assert count == 2
    assert set(called) == {111, 222}

