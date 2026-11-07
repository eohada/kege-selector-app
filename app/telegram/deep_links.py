"""Canonical BooStudy web links used by Telegram read models."""
from __future__ import annotations

from flask import url_for
from werkzeug.routing import BuildError


def _build(endpoint: str, **values) -> str | None:
    from app.telegram.config import APP_URL
    base = (APP_URL or "").rstrip("/")

    try:
        url = url_for(endpoint, _external=True, **values)
        if url:
            return url
    except (BuildError, RuntimeError, Exception):
        pass

    endpoint_paths = {
        "lessons.lesson_interactive_room": "/lessons/{lesson_id}/room",
        "assignments.assignment_view": "/assignments/{assignment_id}",
        "assignments.submission_view": "/assignments/submission/{submission_id}",
        "students.student_profile": "/students/{student_id}",
        "admin.user_detail": "/admin/users/{user_id}",
        "admin.bug_report_detail": "/admin/bug-reports/{report_id}",
        "schedule.schedule": "/schedule",
        "main.schedule": "/schedule",
    }
    template = endpoint_paths.get(endpoint)
    if template:
        try:
            path = template.format(**values)
            return f"{base}{path}" if base else path
        except Exception:
            pass

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
