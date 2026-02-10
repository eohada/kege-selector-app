"""
Движок аналитики: обновление рейтинга по узлам знаний и прогноз балла ЕГЭ.
Основан на модифицированной системе Elo/Glicko.

Фаза 0: используем per-task difficulty_level (1–10) для расчёта Elo-рейтинга задачи:
  - Easy (1–3)   → base_rating − 100
  - Medium (4–7)  → base_rating
  - Hard (8–10)   → base_rating + 150
  Если difficulty_level = NULL → считаем Medium (без смещения).
"""
import math
import logging
from datetime import datetime

from app.models import db
from core.db_models import (
    Tasks,
    KnowledgeNode,
    UserMastery,
    AnalyticsEvent,
    Subject,
    moscow_now,
    MOSCOW_TZ,
)

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    INITIAL_RATING = 1000.0
    VOLATILITY_GROWTH_PER_DAY = 5.0
    MAX_VOLATILITY = 500.0
    MIN_VOLATILITY = 50.0
    BASE_K_FACTOR = 30.0

    # --- Пороги детектора поведения ---
    FAST_FAIL_SEC = 5          # «быстрый фейл» — ответ за < 5 сек и неверно
    FAST_SUCCESS_HARD_SEC = 10 # «быстрый успех на сложном» — ответ за < 10 сек, верно, Hard

    @staticmethod
    def calculate_probability(user_rating: float, task_rating: float) -> float:
        """Вероятность правильного решения: P = 1 / (1 + 10^((Rb - Ra) / 400))."""
        return 1.0 / (1.0 + math.pow(10, (task_rating - user_rating) / 400.0))

    @classmethod
    def _get_node_for_task(cls, task: Tasks):
        """Возвращает KnowledgeNode для задания (после сида у Tasks заполнен knowledge_node_id)."""
        return getattr(task, 'knowledge_node', None) if getattr(task, 'knowledge_node_id', None) else None

    @classmethod
    def _detect_behavior(cls, is_correct: bool, time_spent_sec: int | None, task: Tasks) -> dict:
        """
        Детектор поведенческих аномалий.
        Возвращает dict с флагами (может быть пустым).

        Детектируемые паттерны:
          - fast_fail: ответ за < FAST_FAIL_SEC и неверно → вероятная невнимательность
          - fast_success_hard: ответ за < FAST_SUCCESS_HARD_SEC, верно, задача Hard → подозрение на списывание/заучивание
        """
        flags = {}
        if time_spent_sec is None:
            return flags

        # Fast Fail — молниеносный неверный ответ
        if not is_correct and time_spent_sec < cls.FAST_FAIL_SEC:
            flags['fast_fail'] = True

        # Fast Success на Hard — слишком быстро решил сложную задачу
        if is_correct and time_spent_sec < cls.FAST_SUCCESS_HARD_SEC:
            label = getattr(task, 'difficulty_label', 'medium')
            if label == 'hard':
                flags['fast_success_hard'] = True

        return flags

    @classmethod
    def process_submission(
        cls,
        user_id: int,
        task_id: int,
        is_correct: bool,
        time_spent_sec: int | None = None,
        submission_id: int | None = None,
        answer_id: int | None = None,
    ) -> float | None:
        """
        Вызывается после проверки ответа. Обновляет рейтинг пользователя по узлу знаний.
        Возвращает новый рейтинг или None, если узел не определён.

        Использует task.get_elo_rating() для расчёта, учитывающего difficulty_level.
        """
        task = Tasks.query.get(task_id)
        if not task:
            return None
        node = cls._get_node_for_task(task)
        if not node:
            logger.debug("Analytics: no knowledge node for task_id=%s", task_id)
            return None

        mastery = UserMastery.query.filter_by(user_id=user_id, node_id=node.id).first()
        if not mastery:
            mastery = UserMastery(
                user_id=user_id,
                node_id=node.id,
                rating=cls.INITIAL_RATING,
                volatility=cls.MAX_VOLATILITY,
            )
            db.session.add(mastery)

        # Рост волатильности за дни простоя
        if mastery.last_practiced_at:
            last_at = mastery.last_practiced_at
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=MOSCOW_TZ)
            delta = (moscow_now() - last_at).days
            if delta > 0:
                mastery.volatility = min(
                    cls.MAX_VOLATILITY,
                    mastery.volatility + delta * cls.VOLATILITY_GROWTH_PER_DAY,
                )

        # --- Per-task difficulty Elo rating ---
        task_rating = task.get_elo_rating()
        expected_score = cls.calculate_probability(mastery.rating, task_rating)
        actual_score = 1.0 if is_correct else 0.0

        k_factor = cls.BASE_K_FACTOR * (mastery.volatility / 100.0)

        # --- Детектор поведения ---
        behavior = cls._detect_behavior(is_correct, time_spent_sec, task)

        # Подавление K при подозрительных паттернах
        if behavior.get('fast_success_hard'):
            k_factor *= 0.1   # Почти не даём рейтинг за «быстрый успех на Hard»
            logger.info("Behavior: fast_success_hard for user=%s task=%s (%.1fs)", user_id, task_id, time_spent_sec or 0)
        elif is_correct and time_spent_sec is not None and time_spent_sec < 10:
            k_factor *= 0.1   # Общая защита от быстрых верных ответов

        if behavior.get('fast_fail'):
            k_factor *= 0.5   # Смягчаем потерю рейтинга за невнимательный клик
            logger.info("Behavior: fast_fail for user=%s task=%s (%.1fs)", user_id, task_id, time_spent_sec or 0)

        old_rating = mastery.rating
        new_rating = old_rating + k_factor * (actual_score - expected_score)
        mastery.rating = new_rating
        mastery.volatility = max(cls.MIN_VOLATILITY, mastery.volatility * 0.95)
        mastery.last_practiced_at = moscow_now()
        if is_correct:
            mastery.streak_days = (mastery.streak_days or 0) + 1
        else:
            mastery.streak_days = 0

        event = AnalyticsEvent(
            user_id=user_id,
            node_id=node.id,
            task_id=task_id,
            submission_id=submission_id,
            answer_id=answer_id,
            is_correct=is_correct,
            task_difficulty=task.difficulty_level,
            old_rating=old_rating,
            new_rating=new_rating,
            time_spent_sec=time_spent_sec,
            behavior_flags=behavior if behavior else None,
        )
        db.session.add(event)
        return new_rating

    @classmethod
    def predict_exam_score(cls, user_id: int, subject_id: int | None = None) -> float:
        """
        Предсказывает первичный балл (математическое ожидание) по предмету.
        Если subject_id не передан, берётся предмет kege.
        """
        if subject_id is None:
            subj = Subject.query.filter_by(slug='kege').first()
            if not subj:
                return 0.0
            subject_id = subj.id
        nodes = KnowledgeNode.query.filter_by(subject_id=subject_id).all()
        if not nodes:
            return 0.0

        user_masteries = {
            m.node_id: m
            for m in UserMastery.query.filter_by(user_id=user_id).all()
        }
        total_expected = 0.0
        for node in nodes:
            mastery = user_masteries.get(node.id)
            user_rating = mastery.rating if mastery else cls.INITIAL_RATING
            exam_task_rating = float(getattr(node, 'base_rating', 1000))
            prob = cls.calculate_probability(user_rating, exam_task_rating)
            total_expected += prob * (node.exam_points or 1)
        return round(total_expected, 1)
