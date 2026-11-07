"""Synthetic notification preview generator for BooStudy Bot V3.

Renders exact production notification cards using canonical templates and synthetic sample data,
without writing to Outbox, touching database delivery logs, or sending real Telegram calls.
"""
from __future__ import annotations

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.telegram.notification_templates import render_telegram_notification
from app.telegram.registry import NotificationTypeRegistry, NotificationTypeDefinition
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_SETTINGS, DOMAIN_PREVIEW, ROLE_TITLES, ROLE_EMOJIS
from app.telegram.v3.ui import build_nav_row, render_screen

logger = logging.getLogger(__name__)


async def show_notification_preview(
    update: Update,
    role: str,
    kind: str,
    return_cb: str | None = None,
) -> None:
    """Render a synthetic preview of a notification card."""
    user = update.effective_user
    uid = user.id if user else 0

    role_norm = str(role).lower().strip()
    defn = NotificationTypeRegistry.get(kind)
    if not defn:
        await render_screen(
            update,
            f"❌ <b>Тип уведомления «{kind}» не найден в реестре.</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=return_cb or f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home")]]),
        )
        return

    sample_meta = NotificationTypeRegistry.get_sample_meta(kind, role_norm)
    link_url = sample_meta.get("link_url")

    # Render through canonical engine
    text_card, markup_dict = render_telegram_notification(
        user_id=uid,
        kind=kind,
        title=defn.title,
        body=sample_meta.get("body") or sample_meta.get("text"),
        link_url=link_url,
        meta=sample_meta,
    )

    role_title = ROLE_TITLES.get(role_norm, role_norm.capitalize())
    role_emoji = ROLE_EMOJIS.get(role_norm, "👤")

    banner = (
        f"👁️ <b>[Предпросмотр карточки уведомления]</b>\n"
        f"🔔 <b>Событие:</b> <b>{defn.title}</b>\n"
        f"🎭 <b>Получатель:</b> {role_emoji} <b>{role_title}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{text_card}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>💡 Синтетическое превью на реалистичных данных BooStudy. Доставка в сеть не производилась.</i>"
    )

    # Build keyboard: buttons from the card + back button
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    if markup_dict and isinstance(markup_dict, dict):
        raw_rows = markup_dict.get("inline_keyboard") or []
        for row in raw_rows:
            btn_row = []
            for btn in row:
                t = btn.get("text", "")
                u = btn.get("url")
                # Action buttons in preview are safe inert buttons showing an informative toast
                btn_row.append(InlineKeyboardButton(f"👁️ {t}", callback_data=f"{CB_PREFIX}:{DOMAIN_PREVIEW}:noop"))
            if btn_row:
                keyboard_rows.append(btn_row)

    back_target = return_cb or f"{CB_PREFIX}:{DOMAIN_SETTINGS}:notif:ev:{role_norm}:{defn.category}:{kind}"
    keyboard_rows.append(build_nav_row(back_cb=back_target))

    await render_screen(update, banner, InlineKeyboardMarkup(keyboard_rows))
