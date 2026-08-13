"""Single entry point for real learning rewards.

Rewards are emitted only after a learner performs a persisted educational
action. Page views and dashboard pings must never change XP or a streak.
"""

from __future__ import annotations

import logging

from app.models import db
from app.utils.achievement_service import check_and_grant_dynamic_achievements, grant_achievement
from app.utils.streak_service import update_student_streak
from app.utils.xp_service import add_xp_to_student

logger = logging.getLogger(__name__)

SUBMISSION_BASE_XP = 15
CORRECT_ANSWER_XP = 5


def reward_submission(student, correct_answers: int) -> int:
    """Reward a persisted learning submission exactly once per transition."""
    if not student:
        return 0

    awarded_xp = SUBMISSION_BASE_XP + max(0, int(correct_answers or 0)) * CORRECT_ANSWER_XP
    try:
        add_xp_to_student(student, awarded_xp, commit=False)
        update_student_streak(student, commit=False)
        grant_achievement(student, "first_step", award_xp=False, commit=False)
        check_and_grant_dynamic_achievements(student, commit=False)
        db.session.commit()
        return awarded_xp
    except Exception:
        db.session.rollback()
        logger.exception("Could not apply gamification reward for student_id=%s", student.student_id)
        return 0


def reward_lesson_completion(student) -> int:
    """Reward a student when completing a live/studio lesson (+30 XP + streak)."""
    if not student:
        return 0
    awarded_xp = 30
    try:
        add_xp_to_student(student, awarded_xp, commit=False)
        update_student_streak(student, commit=False)
        check_and_grant_dynamic_achievements(student, commit=False)
        db.session.commit()
        return awarded_xp
    except Exception:
        db.session.rollback()
        logger.exception("Could not apply lesson completion reward for student_id=%s", getattr(student, 'student_id', None))
        return 0


def reward_theory_reading(student) -> int:
    """Reward a student when completing a theory block reading (+10 XP + streak)."""
    if not student:
        return 0
    awarded_xp = 10
    try:
        add_xp_to_student(student, awarded_xp, commit=False)
        update_student_streak(student, commit=False)
        check_and_grant_dynamic_achievements(student, commit=False)
        db.session.commit()
        return awarded_xp
    except Exception:
        db.session.rollback()
        logger.exception("Could not apply theory reading reward for student_id=%s", getattr(student, 'student_id', None))
        return 0


def reward_single_task_correct(student) -> int:
    """Reward a student when solving an individual task correctly (+10 XP + streak)."""
    if not student:
        return 0
    awarded_xp = 10
    try:
        add_xp_to_student(student, awarded_xp, commit=False)
        update_student_streak(student, commit=False)
        grant_achievement(student, "first_step", award_xp=False, commit=False)
        check_and_grant_dynamic_achievements(student, commit=False)
        db.session.commit()
        return awarded_xp
    except Exception:
        db.session.rollback()
        logger.exception("Could not apply single task reward for student_id=%s", getattr(student, 'student_id', None))
        return 0
