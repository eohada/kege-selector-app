"""Batching engine for mass educational operations in BooStudy Telegram.

Prevents notification flooding by grouping >= 3 lessons created in a single batch
into one compact summary card with preview and a single schedule button.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Optional

from app.telegram.notification_templates import format_russian_dt, _get_user_role_and_tz

logger = logging.getLogger(__name__)

BATCH_THRESHOLD = 3
MAX_PREVIEW_ITEMS = 5


def format_batch_lesson_card(
    recipient_user_id: int,
    teacher_name: str,
    lessons_data: list[dict[str, Any]],
    recipient_role: str = "student",
    schedule_url: str = "https://boostudy.ru/schedule",
    student_name: str | None = None,
) -> tuple[str, dict]:
    """Format single HTML card and keyboard for a batch of scheduled lessons."""
    count = len(lessons_data)
    _, user_tz = _get_user_role_and_tz(recipient_user_id)

    if recipient_role == "parent":
        st_label = f" у {html.escape(str(student_name))}" if student_name else " у ребёнка"
        header = f"🗓️ <b>Назначено {count} занятий{st_label}</b>"
    else:
        header = f"🗓️ <b>Вам назначили {count} занятий</b>"

    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━",
        f"👨‍🏫 <b>Преподаватель:</b> {html.escape(str(teacher_name))}",
        "",
        "<b>Ближайшие уроки:</b>",
    ]

    for item in lessons_data[:MAX_PREVIEW_ITEMS]:
        dt_val = item.get("start_time") or item.get("lesson_date")
        dt_str = format_russian_dt(dt_val, user_tz) if dt_val else "Время согласовывается"
        topic = item.get("topic") or item.get("subject") or "Занятие"
        lines.append(f"• <b>{dt_str}</b> — {html.escape(str(topic))}")

    if count > MAX_PREVIEW_ITEMS:
        lines.append(f"<i>... и ещё {count - MAX_PREVIEW_ITEMS} занятий в расписании</i>")

    lines.append("")
    lines.append("Все занятия уже добавлены в ваш календарь платформы.")

    markup = {
        "inline_keyboard": [
            [{"text": "📅 Моё расписание", "url": schedule_url}]
        ]
    }

    return "\n".join(lines), markup


def process_scheduled_lessons_batch(
    recipient_user_id: int,
    teacher_name: str,
    lessons_data: list[dict[str, Any]],
    batch_id: str,
    recipient_role: str = "student",
    schedule_url: str = "https://boostudy.ru/schedule",
    student_name: str | None = None,
) -> list[dict[str, Any]]:
    """Determine whether to emit a single grouped batch card or individual cards.

    Returns:
        List of dicts ready for Outbox enqueueing.
    """
    if not lessons_data:
        return []

    count = len(lessons_data)

    # If >= 3 lessons for the same recipient in a batch: group into 1 card
    if count >= BATCH_THRESHOLD:
        text, markup = format_batch_lesson_card(
            recipient_user_id=recipient_user_id,
            teacher_name=teacher_name,
            lessons_data=lessons_data,
            recipient_role=recipient_role,
            schedule_url=schedule_url,
            student_name=student_name,
        )
        dedupe_key = f"telegram:batch:lesson_scheduled:{recipient_user_id}:{batch_id}"
        preview_items = []
        _, user_tz = _get_user_role_and_tz(recipient_user_id)
        for item in lessons_data[:MAX_PREVIEW_ITEMS]:
            dt_val = item.get("start_time") or item.get("lesson_date")
            dt_str = format_russian_dt(dt_val, user_tz) if dt_val else ""
            topic = item.get("topic") or item.get("subject") or "Занятие"
            preview_items.append(f"{dt_str} — {topic}")

        return [
            {
                "user_id": recipient_user_id,
                "kind": "lesson_batch_scheduled",
                "text": text,
                "reply_markup": markup,
                "dedupe_key": dedupe_key,
                "priority": "normal",
                "meta": {
                    "batch_id": batch_id,
                    "lessons_count": count,
                    "teacher_name": teacher_name,
                    "recipient_role": recipient_role,
                    "items_preview": preview_items,
                },
            }
        ]

    # Less than 3 lessons: emit individual cards
    individual = []
    from app.telegram.notification_templates import render_telegram_notification
    for l_item in lessons_data:
        l_id = l_item.get("lesson_id") or l_item.get("id") or 0
        topic = l_item.get("topic") or l_item.get("subject") or "Занятие"
        dt_val = l_item.get("start_time") or l_item.get("lesson_date")
        meta = {
            "teacher_name": teacher_name,
            "subject": topic,
            "start_time": dt_val,
            "recipient_role": recipient_role,
            "lesson_id": l_id,
        }
        text, markup = render_telegram_notification(
            user_id=recipient_user_id,
            kind="lesson_scheduled",
            title="Новое занятие",
            meta=meta,
            link_url=schedule_url,
        )
        dedupe_key = f"telegram:lesson_scheduled:{recipient_user_id}:{l_id}"
        individual.append(
            {
                "user_id": recipient_user_id,
                "kind": "lesson_scheduled",
                "text": text,
                "reply_markup": markup,
                "dedupe_key": dedupe_key,
                "priority": "normal",
                "meta": meta,
                "lesson_id": l_id,
            }
        )

    return individual
