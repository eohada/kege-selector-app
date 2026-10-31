"""Telegram UI Engine for BooStudy Bot V3.

Provides component-based cards, responsive keyboards, pagination,
Russian date/time formatting with user timezone support, and resilient screen rendering.
"""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.error import BadRequest

from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV, ROLE_EMOJIS, ROLE_TITLES

logger = logging.getLogger(__name__)

MONTHS_RU = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
)
DAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def escape(text: Any) -> str:
    """Safe HTML escaping for user inputs in message templates."""
    if text is None:
        return ""
    return html.escape(str(text))


def is_localhost_url(url: str | None) -> bool:
    """Check if URL points to a local development server."""
    if not url:
        return False
    return "127.0.0.1" in url or "localhost" in url


def localhost_hint() -> str:
    """Notice for testers that URL opens on local development machine."""
    return "💡 <i>(Веб-ссылка ведёт на локальный сервер разработки 127.0.0.1)</i>\n"


def get_mini_app_url() -> str:
    """Resolve full Mini App URL based on environment or configuration."""
    explicit = (os.environ.get("TELEGRAM_MINI_APP_URL") or "").strip()
    if not explicit and not os.environ.get("BOOSTUDY_SKIP_DATABASE_BOOTSTRAP"):
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            tunnel_json_path = os.path.join(root_dir, "instance", "mini_app_tunnel_env.json")
            if os.path.exists(tunnel_json_path):
                with open(tunnel_json_path, "r", encoding="utf-8-sig") as f:
                    tcfg = json.load(f)
                    explicit = (tcfg.get("public_url") or "").strip()
        except Exception:
            pass

    if explicit:
        normalized = explicit.rstrip("/")
        if not normalized.endswith("/tg-app"):
            normalized = f"{normalized}/tg-app"
        return normalized
    base = (os.environ.get("APP_URL") or os.environ.get("BASE_URL") or "").strip().rstrip("/")
    if not base:
        from app.telegram.config import APP_URL
        base = APP_URL
    if base:
        return f"{base.rstrip('/')}/tg-app"
    return ""


def build_mini_app_button(label: str = "📱 Открыть Mini App") -> InlineKeyboardButton | None:
    """Build a WebAppInfo or browser button for Telegram Mini App."""
    url = get_mini_app_url()
    if not url:
        return None
    if url.startswith("https://"):
        return InlineKeyboardButton(label, web_app=WebAppInfo(url=url))
    elif url.startswith("http://"):
        return InlineKeyboardButton(f"{label} (браузер)", url=url)
    return None


def format_dt(dt: datetime | None, tz_name: str = "Europe/Moscow", relative: bool = True) -> str:
    """Format datetime into a readable Russian string with relative hint."""
    if not dt:
        return "Не указано"

    try:
        user_tz = ZoneInfo(tz_name or "Europe/Moscow")
    except Exception:
        user_tz = ZoneInfo("Europe/Moscow")

    if dt.tzinfo is None:
        # Assume UTC if naive, as stored in BooStudy DB
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = dt.astimezone(user_tz)
    now_local = datetime.now(user_tz)

    date_str = f"{local_dt.day} {MONTHS_RU[local_dt.month]}"
    time_str = local_dt.strftime("%H:%M")

    # Relative day comparison
    delta_days = (local_dt.date() - now_local.date()).days
    if delta_days == 0:
        day_label = "Сегодня"
    elif delta_days == 1:
        day_label = "Завтра"
    elif delta_days == -1:
        day_label = "Вчера"
    else:
        day_label = f"{DAYS_RU[local_dt.weekday()]}, {date_str}"

    base_str = f"{day_label} в {time_str}"

    if not relative:
        return base_str

    delta_seconds = int((local_dt - now_local).total_seconds())
    if 0 < delta_seconds < 86400:
        hours = delta_seconds // 3600
        mins = (delta_seconds % 3600) // 60
        if hours > 0:
            hint = f"через {hours} ч {mins} мин" if mins else f"через {hours} ч"
        else:
            hint = f"через {max(1, mins)} мин"
        return f"{base_str} <i>({hint})</i>"

    return base_str


def build_pagination_row(
    domain: str,
    action: str,
    page: int,
    total_pages: int,
    extra: str = "",
) -> list[InlineKeyboardButton]:
    """Build a standard compact pagination bar: [◀ Пред.] [ 1 / 3 ] [След. ▶]."""
    if total_pages <= 1:
        return []

    row: list[InlineKeyboardButton] = []
    suffix = f":{extra}" if extra else ""

    if page > 1:
        prev_cb = f"{CB_PREFIX}:{domain}:{action}:{page - 1}{suffix}"
        row.append(InlineKeyboardButton("◀", callback_data=prev_cb))
    else:
        row.append(InlineKeyboardButton("·", callback_data=f"{CB_PREFIX}:noop"))

    row.append(InlineKeyboardButton(f"{page} / {total_pages}", callback_data=f"{CB_PREFIX}:noop"))

    if page < total_pages:
        next_cb = f"{CB_PREFIX}:{domain}:{action}:{page + 1}{suffix}"
        row.append(InlineKeyboardButton("▶", callback_data=next_cb))
    else:
        row.append(InlineKeyboardButton("·", callback_data=f"{CB_PREFIX}:noop"))

    return row


def build_nav_row(
    back_cb: str | None = None,
    home_cb: str = f"{CB_PREFIX}:{DOMAIN_NAV}:home",
    settings_cb: str | None = None,
) -> list[InlineKeyboardButton]:
    """Build a standard navigation control bar."""
    row: list[InlineKeyboardButton] = []
    if back_cb:
        row.append(InlineKeyboardButton("◀ Назад", callback_data=back_cb))
    row.append(InlineKeyboardButton("🏠 Главная", callback_data=home_cb))
    if settings_cb:
        row.append(InlineKeyboardButton("⚙️ Настройки", callback_data=settings_cb))
    return row


def role_badge(role: str) -> str:
    """Return an icon + localized title badge for a role."""
    emoji = ROLE_EMOJIS.get(role, "👤")
    title = ROLE_TITLES.get(role, role.capitalize())
    return f"{emoji} <b>{title}</b>"


def card_header(title: str, subtitle: str | None = None) -> str:
    """Format a consistent visual card header."""
    header = f"<b>{title}</b>\n"
    if subtitle:
        header += f"<i>{subtitle}</i>\n"
    header += "────────────────────\n"
    return header


def empty_state(icon: str, title: str, description: str) -> str:
    """Format a clean empty state card."""
    return (
        f"\n{icon} <b>{title}</b>\n"
        f"<i>{description}</i>\n"
    )


async def render_screen(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    prefer_edit: bool = True,
) -> None:
    """Safely deliver or update a screen in Telegram.

    If callback query exists, edits in-place to avoid clutter.
    Catches MessageNotModified gracefully, and falls back to a new message
    if the original cannot be edited.
    """
    if update.callback_query:
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass

        if prefer_edit and query.message:
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return
            except BadRequest as e:
                err_msg = str(e).lower()
                if "message is not modified" in err_msg:
                    return
                # Message cannot be edited, fall through to sending new message
                logger.debug("Cannot edit message (%s), sending new one", e)
            except Exception as e:
                logger.warning("Error editing message: %s", e)

        # Fallback if cannot edit
        if query.message:
            await query.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

    if update.message:
        await update.message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
