"""MMR analytics engine aligned with product concept."""
from __future__ import annotations

import logging
import random
from datetime import timedelta

from app.analytics.mmr_config import get_mmr_config
from app.models import db, Course
from core.db_models import (
    AnalyticsEvent,
    KnowledgeNode,
    MOSCOW_TZ,
    RematchQueue,
    Subject,
    Tasks,
    UserMastery,
    UserTaskMMR,
    utc_now,
)

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    INITIAL_RATING = 1000.0

    @classmethod
    def _cfg(cls) -> dict[str, object]:
        return get_mmr_config()

    @classmethod
    def _difficulty_weight(cls, difficulty_level: int | None) -> float:
        cfg = cls._cfg()
        weights = cfg.get("difficulty_weight", {})
        if difficulty_level == 1:
            return float(weights.get("base", 800.0))
        if difficulty_level == 3:
            return float(weights.get("hard", 2200.0))
        return float(weights.get("standard", 1500.0))

    @classmethod
    def _get_task_t_ref_sec(cls, task_number: int | None) -> int:
        cfg = cls._cfg()
        ttl = cfg.get("task_time_limits", {})
        groups = ttl.get("groups", [])
        tn = int(task_number or 0)
        for g in groups:
            numbers = set(int(x) for x in (g.get("task_numbers") or []))
            if tn in numbers:
                return int(g.get("t_ref_sec", 420))
        return int(ttl.get("fallback_t_ref_sec", 420))

    @classmethod
    def _time_coeff(cls, is_correct: bool, time_spent_sec: int | None, task_number: int | None) -> tuple[float, dict]:
        meta = {"time_band": "unknown"}
        if time_spent_sec is None:
            return 1.0, meta
        cfg = cls._cfg()
        bands = cfg.get("time_bands", {})
        t_ref = max(1, cls._get_task_t_ref_sec(task_number))
        effective_time = int(time_spent_sec)
        ratio = float(effective_time) / float(t_ref)
        if ratio > float(bands.get("afk_gt_ratio", 3.0)):
            effective_time = int(float(bands.get("afk_gt_ratio", 3.0)) * t_ref)
            ratio = float(effective_time) / float(t_ref)
            meta["afk_clamped"] = True
        meta["t_ref_sec"] = t_ref
        meta["effective_time_sec"] = effective_time
        meta["time_ratio"] = round(ratio, 4)
        spiral_ratio = float(bands.get("spiral_lt_ratio", 0.15))
        fast_ratio = float(bands.get("fast_lt_ratio", 0.8))
        normal_ratio = float(bands.get("normal_lte_ratio", 1.5))
        if ratio < spiral_ratio:
            if is_correct:
                meta["time_band"] = "spiral_success"
                meta["suspicious"] = True
                return 0.0, meta
            meta["time_band"] = "spiral_fail"
            return 1.5, meta
        if ratio < fast_ratio:
            meta["time_band"] = "fast"
            return 1.2, meta
        if ratio <= normal_ratio:
            meta["time_band"] = "normal"
            return 1.0, meta
        meta["time_band"] = "slow"
        return 0.7, meta

    @classmethod
    def _difficulty_label(cls, difficulty_level: int | None) -> str:
        if difficulty_level == 1:
            return "База"
        if difficulty_level == 3:
            return "Хард"
        return "Стандарт"

    @classmethod
    def _attempt_coeff(cls, is_correct: bool, attempt_no: int | None) -> float:
        if attempt_no is None or attempt_no <= 1:
            attempt_no = 1
        if not is_correct:
            return 1.0
        coeffs = cls._cfg().get("attempt_coeff_correct", {})
        if attempt_no == 1:
            return float(coeffs.get("first_try", 1.0))
        if attempt_no == 2:
            return float(coeffs.get("second_try", 0.5))
        return float(coeffs.get("other_try", 0.5))

    @classmethod
    def _calibration_multiplier(cls, solved_count: int) -> float:
        cal = cls._cfg().get("calibration", {})
        first_stage_tasks = int(cal.get("first_stage_tasks", 5))
        second_stage_tasks = int(cal.get("second_stage_tasks", 10))
        if solved_count < first_stage_tasks:
            return float(cal.get("first_stage_multiplier", 3.0))
        if solved_count < second_stage_tasks:
            return float(cal.get("second_stage_multiplier", 2.0))
        return 1.0

    @classmethod
    def _clamp_mmr(cls, value: float) -> float:
        cfg = cls._cfg()
        return max(float(cfg.get("min_mmr", 0.0)), min(float(cfg.get("max_mmr", 2500.0)), value))

    @classmethod
    def _resolve_task_knowledge_node(cls, task: Tasks) -> KnowledgeNode | None:
        """
        Узел знаний: сначала Tasks.knowledge_node_id, иначе номер задания + матрица
        analytics_*_difficulty.json для предмета курса (КЕГЭ/ОГЭ).
        """
        if getattr(task, "knowledge_node_id", None):
            node = getattr(task, "knowledge_node", None)
            if node is not None:
                return node
        from app.utils.reference_import import get_node_code_by_task_number

        tn = int(task.task_number or 0)
        if tn < 1:
            return None
        subject = None
        if getattr(task, "course_id", None):
            subject = cls._subject_from_course(int(task.course_id))
        if subject is None:
            subject = Subject.query.filter_by(slug="kege").first()
        if subject is None:
            return None
        slug = (subject.slug or "kege").strip().lower()
        node_code = get_node_code_by_task_number(tn, subject_slug=slug)
        if not node_code:
            return None
        return KnowledgeNode.query.filter_by(subject_id=subject.id, code=node_code).first()

    @classmethod
    def _create_or_update_rematch(
        cls,
        user_id: int,
        task: Tasks,
        *,
        attempt_no: int,
        time_spent_sec: int | None,
        is_correct: bool,
        etalon_sec: int = 120,
    ) -> None:
        rematch_cfg = cls._cfg().get("rematch", {})
        trigger_attempts = int(rematch_cfg.get("trigger_attempts_gte", 2))
        trigger_time_ratio = float(rematch_cfg.get("trigger_time_ratio_gte", 1.5))
        time_trigger = bool(time_spent_sec is not None and time_spent_sec >= int(etalon_sec * trigger_time_ratio))
        should_queue = (attempt_no >= trigger_attempts) or time_trigger
        if not should_queue:
            return

        existing = RematchQueue.query.filter_by(
            user_id=user_id,
            task_id=task.task_id,
            status='pending',
        ).order_by(RematchQueue.id.desc()).first()
        now = utc_now()
        if is_correct:
            min_days = int(rematch_cfg.get("first_min_days", 3))
            max_days = int(rematch_cfg.get("first_max_days", 4))
            stage = 1
        else:
            min_days = int(rematch_cfg.get("repeat_error_min_days", 10))
            max_days = int(rematch_cfg.get("repeat_error_max_days", 14))
            stage = 2
        due_at = now + timedelta(days=random.randint(min_days, max_days))
        if existing:
            existing.due_at = due_at
            existing.attempt_stage = max(existing.attempt_stage or 1, stage)
            existing.updated_at = now
        else:
            db.session.add(RematchQueue(
                user_id=user_id,
                task_id=task.task_id,
                task_type=task.task_number,
                due_at=due_at,
                attempt_stage=stage,
                status='pending',
            ))

    @classmethod
    def process_submission(
        cls,
        user_id: int,
        task_id: int,
        is_correct: bool,
        time_spent_sec: int | None = None,
        submission_id: int | None = None,
        answer_id: int | None = None,
        difficulty_level_override: int | None = None,
        attempt_no: int | None = None,
        mode: str | None = None,
        manual_low_mmr_mode: bool = False,
        manual_mmr_delta: float | None = None,
        rating_comment: str | None = None,
        grader_user_id: int | None = None,
    ) -> float | None:
        task = Tasks.query.get(task_id)
        if not task:
            return None
        node = cls._resolve_task_knowledge_node(task)

        mastery = None
        if node:
            mastery = UserMastery.query.filter_by(user_id=user_id, node_id=node.id).first()
            if not mastery:
                mastery = UserMastery(
                    user_id=user_id,
                    node_id=node.id,
                    rating=cls.INITIAL_RATING,
                    volatility=350.0,
                    solved_count=0,
                )
                db.session.add(mastery)

        task_type = int(task.task_number or 0)
        mmr_row = UserTaskMMR.query.filter_by(user_id=user_id, task_type=task_type).first()
        if not mmr_row:
            mmr_row = UserTaskMMR(user_id=user_id, task_type=task_type, mmr=cls.INITIAL_RATING, solved_count=0)
            db.session.add(mmr_row)

        difficulty_level = difficulty_level_override if difficulty_level_override is not None else task.difficulty_level
        cfg = cls._cfg()
        cap = cfg.get("delta_cap", {})
        max_gain = float(cap.get("max_gain", 99999.0))
        max_loss = float(cap.get("max_loss", 99999.0))

        effective_manual: float | None = None
        if manual_mmr_delta is not None:
            try:
                raw_m = float(manual_mmr_delta)
            except (TypeError, ValueError):
                raw_m = None
            if raw_m is not None:
                # Не применять ручной «плюс» при неверном ответе и «минус» при засчитанном — иначе путаница с 0/1 балла
                if not is_correct and raw_m > 0:
                    effective_manual = None
                elif is_correct and raw_m < 0:
                    effective_manual = None
                else:
                    effective_manual = raw_m

        if effective_manual is not None:
            delta = float(effective_manual)
            if delta > 0:
                delta = min(delta, max_gain)
            else:
                delta = max(delta, -max_loss)
            calibration = 1.0
            c_time = 1.0
            c_attempt = 1.0
            time_meta: dict = {"time_band": "manual_override"}
            if time_spent_sec is not None:
                time_meta["effective_time_sec"] = time_spent_sec
        else:
            d_value = cls._difficulty_weight(difficulty_level)
            c_time, time_meta = cls._time_coeff(is_correct, time_spent_sec, task_type)
            c_attempt = cls._attempt_coeff(is_correct, attempt_no)
            calibration = cls._calibration_multiplier(int(mmr_row.solved_count or 0))

            delta = d_value * c_time * c_attempt
            if not is_correct:
                delta *= -1.0
            delta *= calibration
            delta *= float(cfg.get("delta_scale", 1.0))
            if delta > 0:
                delta = min(delta, max_gain)
            else:
                delta = max(delta, -max_loss)

            if manual_low_mmr_mode and not is_correct:
                delta = -40.0
            elif manual_low_mmr_mode and is_correct:
                delta = 0.0

        old_rating = float((mastery.rating if mastery else mmr_row.mmr) or cls.INITIAL_RATING)
        new_rating = cls._clamp_mmr(old_rating + delta)
        if mastery:
            mastery.rating = new_rating
            mastery.last_practiced_at = utc_now()
            mastery.solved_count = int(mastery.solved_count or 0) + 1
            mastery.calibration_done = bool((mastery.solved_count or 0) >= int(cls._cfg().get("calibration", {}).get("second_stage_tasks", 10)))
            mastery.streak_days = (mastery.streak_days or 0) + 1 if is_correct else 0

        old_task_mmr = float(mmr_row.mmr or cls.INITIAL_RATING)
        mmr_row.mmr = cls._clamp_mmr(old_task_mmr + delta)
        mmr_row.solved_count = int(mmr_row.solved_count or 0) + 1

        behavior = {
            "calibration_multiplier": calibration,
            "time_coeff": c_time,
            "attempt_coeff": c_attempt,
            "difficulty_label": cls._difficulty_label(difficulty_level),
            **time_meta,
        }
        if effective_manual is not None:
            behavior["teacher_adjusted"] = True
            behavior["applied_manual_mmr_delta"] = float(effective_manual)
            if rating_comment:
                behavior["rating_comment"] = str(rating_comment)[:4000]
            if grader_user_id is not None:
                behavior["grader_user_id"] = int(grader_user_id)
        if node is not None:
            event = AnalyticsEvent(
                user_id=user_id,
                node_id=node.id,
                task_id=task.task_id,
                submission_id=submission_id,
                answer_id=answer_id,
                is_correct=is_correct,
                task_difficulty=difficulty_level,
                old_rating=old_rating,
                new_rating=new_rating,
                mmr_delta=(new_rating - old_rating),
                task_type=task_type,
                attempt_no=attempt_no,
                mode=mode,
                time_spent_sec=time_meta.get("effective_time_sec", time_spent_sec),
                behavior_flags=behavior,
            )
            db.session.add(event)
        else:
            logger.warning(
                "AnalyticsEvent skipped: missing knowledge node for task_id=%s task_type=%s mode=%s",
                task.task_id,
                task_type,
                mode,
            )
        cls._create_or_update_rematch(
            user_id=user_id,
            task=task,
            attempt_no=int(attempt_no or 1),
            time_spent_sec=time_meta.get("effective_time_sec", time_spent_sec),
            is_correct=is_correct,
            etalon_sec=cls._get_task_t_ref_sec(task_type),
        )
        return new_rating

    @classmethod
    def process_submission_details(
        cls,
        user_id: int,
        task_id: int,
        is_correct: bool,
        time_spent_sec: int | None = None,
        submission_id: int | None = None,
        answer_id: int | None = None,
        difficulty_level_override: int | None = None,
        attempt_no: int | None = None,
        mode: str | None = None,
        manual_low_mmr_mode: bool = False,
        manual_mmr_delta: float | None = None,
        rating_comment: str | None = None,
        grader_user_id: int | None = None,
    ) -> dict | None:
        new_rating = cls.process_submission(
            user_id=user_id,
            task_id=task_id,
            is_correct=is_correct,
            time_spent_sec=time_spent_sec,
            submission_id=submission_id,
            answer_id=answer_id,
            difficulty_level_override=difficulty_level_override,
            attempt_no=attempt_no,
            mode=mode,
            manual_low_mmr_mode=manual_low_mmr_mode,
            manual_mmr_delta=manual_mmr_delta,
            rating_comment=rating_comment,
            grader_user_id=grader_user_id,
        )
        if new_rating is None:
            return None
        ev = (
            AnalyticsEvent.query.filter_by(
                user_id=user_id,
                task_id=task_id,
                answer_id=answer_id,
            ).order_by(AnalyticsEvent.id.desc()).first()
        )
        if not ev and answer_id is None:
            ev = (
                AnalyticsEvent.query.filter_by(
                    user_id=user_id,
                    task_id=task_id,
                    submission_id=submission_id,
                ).order_by(AnalyticsEvent.id.desc()).first()
            )
        if not ev:
            return {"new_rating": new_rating}
        flags = ev.behavior_flags or {}
        return {
            "new_rating": float(ev.new_rating or new_rating),
            "mmr_delta": float(ev.mmr_delta or 0.0),
            "difficulty_label": str(flags.get("difficulty_label") or cls._difficulty_label(ev.task_difficulty)),
            "time_coeff": float(flags.get("time_coeff") or 1.0),
            "attempt_coeff": float(flags.get("attempt_coeff") or 1.0),
            "calibration_multiplier": float(flags.get("calibration_multiplier") or 1.0),
            "time_band": flags.get("time_band"),
            "task_type": ev.task_type,
            "effective_time_sec": flags.get("effective_time_sec", ev.time_spent_sec),
            "t_ref_sec": flags.get("t_ref_sec"),
        }

    @classmethod
    def _subject_from_course(cls, course_id: int) -> Subject | None:
        course = Course.query.get(course_id)
        if not course:
            return None
        slug_map = {'ege_informatics': 'kege', 'oge_informatics': 'oge'}
        subject_slug = slug_map.get((course.slug or '').strip(), 'kege')
        return Subject.query.filter_by(slug=subject_slug).first()

    @classmethod
    def predict_exam_score(cls, user_id: int, subject_id: int | None = None, course_id: int | None = None) -> float:
        if subject_id is None:
            if course_id is not None:
                subj = cls._subject_from_course(course_id)
                if subj:
                    subject_id = subj.id
            if subject_id is None:
                subj = Subject.query.filter_by(slug='kege').first()
                if not subj:
                    return 0.0
                subject_id = subj.id
        nodes = KnowledgeNode.query.filter_by(subject_id=subject_id).all()
        if not nodes:
            return 0.0
        user_masteries = {m.node_id: m for m in UserMastery.query.filter_by(user_id=user_id).all()}
        total_expected = 0.0
        for node in nodes:
            mastery = user_masteries.get(node.id)
            rating = float(mastery.rating if mastery else cls.INITIAL_RATING)
            base = float(getattr(node, 'base_rating', 1000))
            p = max(0.0, min(1.0, rating / max(base, 1.0)))
            total_expected += p * float(node.exam_points or 1)
        return round(total_expected, 1)

