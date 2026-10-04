"""Canonical BooStudy web links used by Telegram read models."""
from __future__ import annotations

from flask import url_for
from werkzeug.routing import BuildError


def _build(endpoint: str, **values) -> str | None:
    try:
        return url_for(endpoint, _external=True, **values)
    except BuildError:
        return None


def lesson(lesson_id: int) -> str | None:
    return _build("lessons.lesson_interactive_room", lesson_id=int(lesson_id))


def assignment(assignment_id: int) -> str | None:
    return _build("assignments.assignment_view", assignment_id=int(assignment_id))


def submission(submission_id: int) -> str | None:
    return _build("assignments.submission_view", submission_id=int(submission_id))


def student(student_id: int) -> str | None:
    return _build("students.student_profile", student_id=int(student_id))


def user(user_id: int) -> str | None:
    return _build("admin.user_detail", user_id=int(user_id))


def bug_report(report_id: int) -> str | None:
    return _build("admin.bug_report_detail", report_id=int(report_id))


def schedule() -> str | None:
    return _build("schedule.schedule") or _build("main.schedule")
