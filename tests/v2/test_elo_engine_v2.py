import pytest
from app.analytics.engine import AnalyticsEngine
from app.analytics.mmr_config import get_mmr_config
from core.db_models import User, Tasks, KnowledgeNode, Subject, UserMastery, UserTaskMMR, AnalyticsEvent
from app.models import db


def test_elo_logistic_properties(app):
    """Проверка математических свойств формулы логистического матожидания и дельт."""
    with app.app_context():
        cfg = get_mmr_config()
        k_base = float(cfg.get("k_factor", 36.0))
        divisor = float(cfg.get("scale_divisor", 400.0))

        # 1. Равные рейтинги (1400 vs 1400): E = 0.5
        exp_even = (1400.0 - 1400.0) / divisor
        e_even = 1.0 / (1.0 + (10.0 ** exp_even))
        assert abs(e_even - 0.5) < 1e-4

        # Дельта при победе: K * (1 - 0.5) = +18
        delta_win_even = k_base * (1.0 - e_even)
        assert abs(delta_win_even - 18.0) < 1e-4

        # 2. Сильный ученик (1800) решает простую задачу (800)
        # E > 0.99
        exp_easy = (800.0 - 1800.0) / divisor
        e_easy = 1.0 / (1.0 + (10.0 ** exp_easy))
        assert e_easy > 0.99

        # При успехе: минимальный прирост (< 0.2 MMR), фармить нельзя
        delta_win_easy = k_base * (1.0 - e_easy)
        assert delta_win_easy < 0.2

        # При ошибке: жестокий штраф (> 35 MMR)
        delta_loss_easy = k_base * (0.0 - e_easy)
        assert delta_loss_easy < -35.0

        # 3. Слабый ученик (900) пытается решить олимпиадную задачу (2500)
        # E < 0.001
        exp_hard = (2500.0 - 900.0) / divisor
        e_hard = 1.0 / (1.0 + (10.0 ** exp_hard))
        assert e_hard < 0.001

        # При ошибке: микро-штраф (> -0.1 MMR), ученик не демотивируется
        delta_loss_hard = k_base * (0.0 - e_hard)
        assert delta_loss_hard > -0.1

        # При успехе: максимальный прирост (~ +36 MMR)
        delta_win_hard = k_base * (1.0 - e_hard)
        assert delta_win_hard > 35.0


def test_process_submission_elo_flow(app, role_users):
    """Проверка полного цикла process_submission с сохранением в БД."""
    with app.app_context():
        student_user_id = role_users['student_user_id']
        task = Tasks.query.filter_by(task_number=1).first()
        if not task:
            task = Tasks(task_number=1, content_html='<p>Графы</p>', difficulty_level=1)
            db.session.add(task)
            db.session.commit()

        # Решение задачи через движок
        res = AnalyticsEngine.process_submission_details(
            user_id=student_user_id,
            task_id=task.task_id,
            is_correct=True,
            time_spent_sec=120,
            attempt_no=1,
            mode='trainer',
        )

        assert res is not None
        assert 'new_rating' in res
        assert 'expected_score' in res
        assert 'task_elo' in res
        assert res['mmr_delta'] > 0


def test_anti_cheat_spiral_success(app, role_users):
    """Проверка анти-чита: быстрое угадывание (spiral_success) даёт 0 MMR."""
    with app.app_context():
        student_user_id = role_users['student_user_id']
        task = Tasks.query.filter_by(task_number=27).first()
        if not task:
            task = Tasks(task_number=27, content_html='<p>Сложная ДП</p>', difficulty_level=3)
            db.session.add(task)
            db.session.commit()

        # Задача №27 норматив 2100 сек. Решение за 5 сек (< 0.15 T_ref)
        res = AnalyticsEngine.process_submission_details(
            user_id=student_user_id,
            task_id=task.task_id,
            is_correct=True,
            time_spent_sec=5,
            attempt_no=1,
            mode='trainer',
        )

        assert res is not None
        assert res['time_band'] == 'spiral_success'
        assert res['mmr_delta'] == 0.0
