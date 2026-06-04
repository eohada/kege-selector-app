"""DB helpers for Telegram runtime inside the main Flask app."""
from __future__ import annotations

from app.models import db


def get_session():
    return db.session


def close_session(session=None):
    try:
        db.session.remove()
    except Exception:
        pass
