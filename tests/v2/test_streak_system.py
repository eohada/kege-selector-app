import pytest
from datetime import date, timedelta
from app import create_app, db
from app.models import User, Student
from app.utils.streak_service import (
    pluralize_days,
    pluralize_days_word,
    update_student_streak,
    get_effective_streak,
    get_student_streak_info,
    freeze_student_streak,
    unfreeze_student_streak,
    set_student_streak,
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

def test_pluralize_days():
    """Проверка правильного склонения слов 'день/дня/дней'."""
    assert pluralize_days(1) == "1 день"
    assert pluralize_days(2) == "2 дня"
    assert pluralize_days(4) == "4 дня"
    assert pluralize_days(5) == "5 дней"
    assert pluralize_days(11) == "11 дней"
    assert pluralize_days(14) == "14 дней"
    assert pluralize_days(21) == "21 день"
    assert pluralize_days(22) == "22 дня"
    assert pluralize_days(25) == "25 дней"
    assert pluralize_days(100) == "100 дней"
    assert pluralize_days(101) == "101 день"
    assert pluralize_days_word(1) == "день"
    assert pluralize_days_word(3) == "дня"
    assert pluralize_days_word(8) == "дней"

def test_streak_progression_and_same_day(app_ctx):
    """Проверка первого дня, повторной активности в тот же день и перехода на следующий день."""
    user = User(email="streak1@test.local", username="streak_user_1", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()
    
    student = Student(user_id=user.id, name="Студент 1", streak_days=0, streak_frozen=False, last_activity_date=None)
    db.session.add(student)
    db.session.commit()

    d1 = date(2026, 4, 1)
    
    # День 1: первая активность
    res1 = update_student_streak(student, today_date=d1)
    assert res1 is True
    assert student.streak_days == 1
    assert student.last_activity_date == d1

    # Тот же день 1: повторная активность не накручивает стрик
    res1_repeat = update_student_streak(student, today_date=d1)
    assert res1_repeat is False
    assert student.streak_days == 1

    # День 2: активность на следующий день увеличивает стрик до 2
    d2 = date(2026, 4, 2)
    res2 = update_student_streak(student, today_date=d2)
    assert res2 is True
    assert student.streak_days == 2
    assert student.last_activity_date == d2

    # День 3: активность увеличивает стрик до 3
    d3 = date(2026, 4, 3)
    res3 = update_student_streak(student, today_date=d3)
    assert res3 is True
    assert student.streak_days == 3

def test_streak_missed_day_resets_without_freeze(app_ctx):
    """Пропуск дня без заморозки сбрасывает стрик до 1 при новой активности."""
    user = User(email="streak2@test.local", username="streak_user_2", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()
    
    d1 = date(2026, 4, 1)
    student = Student(user_id=user.id, name="Студент 2", streak_days=5, streak_frozen=False, last_activity_date=d1)
    db.session.add(student)
    db.session.commit()

    # Активность через 3 дня (4 апреля, пропущены 2 и 3 апреля)
    d4 = date(2026, 4, 4)
    res = update_student_streak(student, today_date=d4)
    assert res is True
    assert student.streak_days == 1
    assert student.last_activity_date == d4

def test_streak_freeze_saves_missed_day(app_ctx):
    """Заморозка спасает серию при пропуске и корректно расходуется."""
    user = User(email="streak3@test.local", username="streak_user_3", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()
    
    d1 = date(2026, 4, 1)
    # Студент имел 7 дней стрика, была включена заморозка
    student = Student(user_id=user.id, name="Студент 3", streak_days=7, streak_frozen=True, last_activity_date=d1)
    db.session.add(student)
    db.session.commit()

    # Студент заходит 3 апреля (пропустил 2 апреля)
    d3 = date(2026, 4, 3)
    res = update_student_streak(student, today_date=d3)
    
    # Стрик не сгорел! Увеличился до 8, заморозка израсходована
    assert res is True
    assert student.streak_days == 8
    assert student.streak_frozen is False
    assert student.last_activity_date == d3

def test_get_effective_streak_and_info(app_ctx):
    """Проверка расчета эффективного стрика (устранение 'призрачных' стриков) и инфо-объекта."""
    user = User(email="streak4@test.local", username="streak_user_4", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()
    
    d_active = date(2026, 4, 1)
    student = Student(user_id=user.id, name="Студент 4", streak_days=10, streak_frozen=False, last_activity_date=d_active)
    db.session.add(student)
    db.session.commit()

    # На день активности (1 апреля)
    assert get_effective_streak(student, today_date=d_active) == 10
    info1 = get_student_streak_info(student, today_date=d_active)
    assert info1["is_active_today"] is True
    assert info1["needs_activity_today"] is False
    assert info1["is_broken"] is False
    assert info1["days_label"] == "10 дней"

    # На следующий день (2 апреля): стрик ещё жив, но требуется активность
    d_next = date(2026, 4, 2)
    assert get_effective_streak(student, today_date=d_next) == 10
    info2 = get_student_streak_info(student, today_date=d_next)
    assert info2["is_active_today"] is False
    assert info2["needs_activity_today"] is True
    assert info2["is_broken"] is False

    # Спустя 3 дня (4 апреля): стрик сгорел, эффективный стрик = 0
    d_late = date(2026, 4, 4)
    assert get_effective_streak(student, today_date=d_late) == 0
    info3 = get_student_streak_info(student, today_date=d_late)
    assert info3["is_broken"] is True
    assert info3["needs_activity_today"] is False
    assert info3["streak_days"] == 0

def test_admin_streak_routes(app_ctx):
    """Проверка сервисных функций и админского эндпоинта управления стриком."""
    admin_user = User(email="admin_s@test.local", username="admin_streak", role="admin")
    admin_user.set_password("pass123")
    
    student_user = User(email="student_s@test.local", username="student_streak", role="student")
    student_user.set_password("pass123")
    
    db.session.add_all([admin_user, student_user])
    db.session.flush()
    
    student = Student(user_id=student_user.id, name="Студент 5", streak_days=2, streak_frozen=False)
    db.session.add(student)
    db.session.commit()

    # Ручная установка стрика и заморозки через сервисные функции
    set_student_streak(student, 15)
    assert student.streak_days == 15
    
    freeze_student_streak(student)
    assert student.streak_frozen is True
    
    unfreeze_student_streak(student)
    assert student.streak_frozen is False

    # Проверка через тестовый клиент Flask
    with app_ctx.test_client() as client:
        # Авторизуемся под администратором
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # Установка стрика 25 и включение заморозки
        resp = client.post(f"/student/{student.student_id}/streak", json={
            "streak_days": 25,
            "streak_frozen": True
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["streak_days"] == 25
        assert data["streak_frozen"] is True
        assert data["days_label"] == "25 дней"

        db.session.refresh(student)
        assert student.streak_days == 25
        assert student.streak_frozen is True

        # Сброс стрика
        resp_reset = client.post(f"/student/{student.student_id}/streak", json={
            "action": "reset"
        })
        assert resp_reset.status_code == 200
        data_reset = resp_reset.get_json()
        assert data_reset["streak_days"] == 0
        assert data_reset["streak_frozen"] is False

        # Проверка защиты: обычный студент не может менять свой стрик
        with client.session_transaction() as sess:
            sess['_user_id'] = str(student_user.id)
            sess['_fresh'] = True

        resp_forbidden = client.post(f"/student/{student.student_id}/streak", json={
            "streak_days": 100
        })
        assert resp_forbidden.status_code == 403

        # Проверка управления недельным стриком админом
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        resp_weeks = client.post(f"/student/{student.student_id}/streak", json={
            "streak_weeks": 8,
            "streak_weeks_frozen": True
        })
        assert resp_weeks.status_code == 200
        data_weeks = resp_weeks.get_json()
        assert data_weeks["streak_weeks"] == 8
        assert data_weeks["streak_weeks_frozen"] is True
        assert data_weeks["weeks_label"] == "8 недель"

        db.session.refresh(student)
        assert student.streak_weeks == 8
        assert student.streak_weeks_frozen is True


def test_pluralize_weeks():
    """Проверка правильного склонения слов 'неделя/недели/недель'."""
    from app.utils.streak_service import pluralize_weeks, pluralize_weeks_word
    assert pluralize_weeks(1) == "1 неделя"
    assert pluralize_weeks(2) == "2 недели"
    assert pluralize_weeks(4) == "4 недели"
    assert pluralize_weeks(5) == "5 недель"
    assert pluralize_weeks(11) == "11 недель"
    assert pluralize_weeks(14) == "14 недель"
    assert pluralize_weeks(21) == "21 неделя"
    assert pluralize_weeks(22) == "22 недели"
    assert pluralize_weeks(25) == "25 недель"
    assert pluralize_weeks_word(1) == "неделя"
    assert pluralize_weeks_word(3) == "недели"
    assert pluralize_weeks_word(8) == "недель"


def test_weekly_streak_evaluation_and_progression(app_ctx):
    """Проверка оценки недели и непрерывного роста недельного стрика."""
    from app.utils.streak_service import (
        evaluate_student_week_status,
        update_student_weekly_streak,
        get_student_weekly_streak_info,
        get_iso_week_key
    )
    from core.db_models import Lesson, Submission, Assignment
    from datetime import datetime

    user = User(email="wstreak@test.local", username="wstreak_user", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()

    student = Student(user_id=user.id, name="Недельный Ученик", streak_weeks=0, streak_weeks_frozen=False)
    db.session.add(student)
    db.session.commit()

    # Неделя 1: Понедельник 2026-03-30 до Воскресенье 2026-04-05 (2026-W14)
    w1_date = date(2026, 4, 1) # Среда W14
    
    # 1. Если активности не было - неделя не завершена
    eval_empty = evaluate_student_week_status(student, week_date=w1_date)
    assert eval_empty["is_successful"] is False
    assert eval_empty["has_activity"] is False

    # Добавляем 2 урока в неделю 1: оба проведены (completed)
    l1 = Lesson(
        student_id=student.student_id,
        lesson_date=datetime(2026, 3, 31, 16, 0), # Вторник
        status='completed'
    )
    l2 = Lesson(
        student_id=student.student_id,
        lesson_date=datetime(2026, 4, 2, 16, 0),  # Четверг
        status='completed'
    )
    db.session.add_all([l1, l2])
    db.session.commit()

    eval_w1 = evaluate_student_week_status(student, week_date=w1_date)
    assert eval_w1["is_successful"] is True
    assert eval_w1["lessons_completed"] == 2
    assert eval_w1["lessons_missed"] == 0

    # Наступает Неделя 2 (например, 2026-04-08, W15)
    w2_date = date(2026, 4, 8)
    res_w1 = update_student_weekly_streak(student, current_date=w2_date)
    assert res_w1["updated"] is True
    assert res_w1["streak_weeks"] == 1
    assert student.streak_weeks == 1
    assert student.last_completed_week == get_iso_week_key(w1_date)

    # Неделя 2: добавляем ещё урок (completed)
    l3 = Lesson(
        student_id=student.student_id,
        lesson_date=datetime(2026, 4, 7, 16, 0),
        status='completed'
    )
    db.session.add(l3)
    db.session.commit()

    # Наступает Неделя 3 (2026-04-15, W16)
    w3_date = date(2026, 4, 15)
    res_w2 = update_student_weekly_streak(student, current_date=w3_date)
    assert res_w2["updated"] is True
    assert res_w2["streak_weeks"] == 2
    assert student.streak_weeks == 2

    # Проверяем, выдалась ли ачивка weekly_streak_2
    from core.db_models import UserAchievement
    ach = UserAchievement.query.filter_by(
        student_id=student.student_id,
        achievement_key='weekly_streak_2'
    ).first()
    assert ach is not None

    # Инфо-объект для UI
    info = get_student_weekly_streak_info(student, current_date=w3_date)
    assert info["streak_weeks"] == 2
    assert info["weeks_label"] == "2 недели"
    assert info["is_frozen"] is False


def test_weekly_streak_freeze_saves_missed_week(app_ctx):
    """Проверка спасения недельного ритма заморозкой при пропуске недели."""
    from app.utils.streak_service import update_student_weekly_streak, get_iso_week_key
    from core.db_models import Lesson
    from datetime import datetime

    user = User(email="wfreeze@test.local", username="wfreeze_user", role="student")
    user.set_password("pass123")
    db.session.add(user)
    db.session.flush()

    # Ученик имел 4 недели непрерывного ритма, завершил 2026-W13, включил заморозку на W14 (пропустил W14)
    student = Student(
        user_id=user.id,
        name="Замороженный Ученик",
        streak_weeks=4,
        last_completed_week="2026-W13",
        streak_weeks_frozen=True
    )
    db.session.add(student)
    db.session.commit()

    # В W15 (2026-04-08) ученик вернулся и провёл урок
    l = Lesson(
        student_id=student.student_id,
        lesson_date=datetime(2026, 4, 8, 16, 0),
        status='completed'
    )
    db.session.add(l)
    db.session.commit()

    # В W16 (2026-04-15) проверяем обновление: неделя W15 успешна, W14 была пропущена, но защищена заморозкой!
    w16_date = date(2026, 4, 15)
    res = update_student_weekly_streak(student, current_date=w16_date)
    assert res["updated"] is True
    # Заморозка спасла серию: стрик вырос до 5, заморозка израсходована
    assert student.streak_weeks == 5
    assert student.streak_weeks_frozen is False


def test_weekly_streak_saturday_lesson_next_week_deadline(app_ctx):
    """
    Проверка сценария: урок в субботу Недели 1, ДЗ выдано с дедлайном на среду Недели 2.
    - В воскресенье Недели 1 серия успешно закрывается (урок проведён, дедлайн ещё не наступил).
    - ДЗ оценивается только на Неделе 2 (по сроку дедлайна).
    """
    from app.utils.streak_service import evaluate_student_week_status, update_student_weekly_streak
    from core.db_models import Lesson, Assignment, Submission
    from datetime import datetime

    teacher = User(email="t_sat@test.local", username="t_sat", role="teacher")
    user = User(email="sat_student@test.local", username="sat_student", role="student")
    db.session.add_all([teacher, user])
    db.session.flush()

    student = Student(user_id=user.id, name="Субботний Ученик", streak_weeks=0)
    db.session.add(student)
    db.session.commit()

    # Неделя 1: 2026-03-30 (Пн) - 2026-04-05 (Вс)
    # Урок в субботу 2026-04-04 18:00
    lesson_sat = Lesson(
        student_id=student.student_id,
        lesson_date=datetime(2026, 4, 4, 18, 0),
        status='completed',
        topic='Сложные графы'
    )
    db.session.add(lesson_sat)
    db.session.flush()

    # ДЗ выдано в субботу, дедлайн — среда следующей недели (2026-04-08 23:59)
    assignment = Assignment(
        title="ДЗ по графам",
        assignment_type="homework",
        deadline=datetime(2026, 4, 8, 23, 59),
        created_by_id=teacher.id,
        lesson_id=lesson_sat.lesson_id
    )
    db.session.add(assignment)
    db.session.flush()

    # Создаётся Submission в статусе ASSIGNED
    submission = Submission(
        assignment_id=assignment.assignment_id,
        student_id=student.student_id,
        status='ASSIGNED'
    )
    db.session.add(submission)
    db.session.commit()

    # 1. Проверяем состояние Недели 1 на момент воскресенья (2026-04-05):
    w1_eval = evaluate_student_week_status(student, week_date=date(2026, 4, 5))
    # Урок субботы проведён, ДЗ не считается просроченным для Недели 1!
    assert w1_eval["is_successful"] is True
    assert w1_eval["is_on_track"] is True
    assert w1_eval["lessons_completed"] == 1
    assert w1_eval["assignments_due"] == 0  # Дедлайн не на этой неделе
    assert w1_eval["assignments_overdue"] == 0

    # Переход на Неделю 2 (2026-04-06): Неделя 1 засчитывается в стрик!
    res_w1 = update_student_weekly_streak(student, current_date=date(2026, 4, 6))
    assert res_w1["updated"] is True
    assert student.streak_weeks == 1

    # 2. Проверяем Неделю 2: теперь это ДЗ относится к Неделе 2!
    w2_eval = evaluate_student_week_status(student, week_date=date(2026, 4, 8))
    assert w2_eval["assignments_due"] == 1
    # До наступления дедлайна ДЗ не просрочено:
    assert w2_eval["assignments_overdue"] == 0

    # Ученик сдаёт ДЗ во вторник (2026-04-07):
    submission.status = 'SUBMITTED'
    submission.submitted_at = datetime(2026, 4, 7, 20, 0)
    db.session.commit()

    # Неделя 2 также завершается успехом!
    w2_eval_done = evaluate_student_week_status(student, week_date=date(2026, 4, 12))
    assert w2_eval_done["is_successful"] is True
    assert w2_eval_done["assignments_overdue"] == 0


