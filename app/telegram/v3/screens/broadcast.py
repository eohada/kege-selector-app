"""Broadcast Center wizard for BooStudy Bot V3 with strict RBAC, recipient calculation, and dev safety."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, UserProfile
from core.db_models import TelegramBroadcast, TelegramDelivery
from app.utils.relationship_scope import get_student_user_ids_for_tutor
from app.telegram.config import ALLOWLIST_CHAT_IDS, is_delivery_permitted
from app.telegram.delivery import enqueue_delivery
from app.telegram.notification_templates import render_telegram_notification
from app.telegram.user_notify import is_notification_enabled_for_user
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_BROADCAST, DOMAIN_NAV
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import build_nav_row, card_header, escape, render_screen

logger = logging.getLogger(__name__)

AUDIENCE_LABELS: dict[str, str] = {
    "all": "🌐 Все пользователи платформы",
    "students": "🎓 Все ученики",
    "teachers": "👨‍🏫 Все преподаватели",
    "parents": "👨‍👩‍👧 Все родители",
    "my_students": "👥 Мои прикреплённые ученики",
}

CATEGORY_LABELS: dict[str, str] = {
    "broadcast": "📢 Общее объявление",
    "announcement": "🔔 Важное уведомление",
    "news": "📰 Новости и материалы",
}

SAMPLE_BROADCAST_TEMPLATES = [
    {
        "id": "tpl_exam",
        "title": "Подготовка к пробному КЕГЭ",
        "category": "broadcast",
        "text": "В субботу в 12:00 МСК пишем полный пробный вариант КЕГЭ по информатике. Проверьте готовность установленного ПО.",
    },
    {
        "id": "tpl_maintenance",
        "title": "Плановое обновление сервера",
        "category": "announcement",
        "text": "В ночь со среды на четверг с 03:00 до 04:30 МСК будут проводиться технические работы по обновлению серверов LiveKit.",
    },
    {
        "id": "tpl_update",
        "title": "Новые материалы по заданиям 26 и 27",
        "category": "news",
        "text": "В базу платформы добавлены новые разборы прототипов динамического программирования и эффективной сортировки.",
    },
]


@dataclass
class BroadcastDraft:
    user_id: int
    step: str = "audience"  # audience, category, title, text, button, preview, prompt_title, prompt_text, prompt_btn_label, prompt_btn_url
    audience: str = "my_students"
    category: str = "broadcast"
    title: str = "Объявление"
    text: str = ""
    button_label: str | None = None
    button_url: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    is_sending: bool = False


# Temporary in-memory wizard state: user_id -> BroadcastDraft
_DRAFTS: dict[int, BroadcastDraft] = {}
DRAFT_TTL_SECONDS = 3600  # 1 hour TTL


def get_or_create_draft(user_id: int) -> BroadcastDraft:
    now = time.time()
    raw = _DRAFTS.get(user_id)
    if isinstance(raw, dict):
        draft = BroadcastDraft(
            user_id=user_id,
            audience=raw.get("audience", "students"),
            category=raw.get("category", "broadcast"),
            title=raw.get("title", ""),
            text=raw.get("text", ""),
            button_label=raw.get("button_label"),
            button_url=raw.get("button_url"),
            created_at=now,
            updated_at=now,
        )
        _DRAFTS[user_id] = draft
        return draft
    draft = raw
    if not draft or (now - draft.updated_at) > DRAFT_TTL_SECONDS:
        draft = BroadcastDraft(user_id=user_id, created_at=now, updated_at=now)
        _DRAFTS[user_id] = draft
    return draft


def clear_draft(user_id: int) -> None:
    _DRAFTS.pop(user_id, None)


def _get_permitted_audiences(user: User) -> list[tuple[str, str]]:
    role = (getattr(user, "role", "") or "").lower()
    if role in ("creator", "chief_admin"):
        return [
            ("all", AUDIENCE_LABELS["all"]),
            ("students", AUDIENCE_LABELS["students"]),
            ("teachers", AUDIENCE_LABELS["teachers"]),
            ("parents", AUDIENCE_LABELS["parents"]),
        ]
    elif role == "admin":
        return [
            ("students", AUDIENCE_LABELS["students"]),
            ("parents", AUDIENCE_LABELS["parents"]),
        ]
    elif role in ("teacher", "tutor"):
        return [
            ("my_students", AUDIENCE_LABELS["my_students"]),
        ]
    return []


def analyze_broadcast_recipients(sender: User, audience: str, category: str) -> dict[str, Any]:
    """Resolve and filter actual recipient users based on active link and notification preference.

    Strict Dev Safety:
    - Never injects test users or Creator unless Creator is naturally part of the target audience.
    - Accurately itemizes live recipients (chat in ALLOWLIST_CHAT_IDS) vs simulated recipients (dry-run).
    """
    role = (getattr(sender, "role", "") or "").lower()

    if audience == "my_students":
        if role in ("teacher", "tutor"):
            st_uids = get_student_user_ids_for_tutor(sender.id)
            users = User.query.filter(User.id.in_(st_uids)).all() if st_uids else []
        else:
            users = User.query.filter(User.role == "student").all()
    elif audience == "students":
        users = User.query.filter(User.role == "student").all()
    elif audience == "teachers":
        users = User.query.filter(User.role.in_(("teacher", "tutor"))).all()
    elif audience == "parents":
        users = User.query.filter(User.role == "parent").all()
    else:  # all
        users = User.query.filter(User.is_active.is_(True)).all()

    total_audience = len(users)
    linked_telegram = 0
    opted_out = 0
    eligible_users: list[User] = []
    live_users: list[User] = []
    simulated_users: list[User] = []

    for u in users:
        prof = getattr(u, "profile", None)
        chat_id = getattr(prof, "telegram_chat_id", None) or getattr(u, "telegram_chat_id", None)
        if not chat_id:
            continue
        linked_telegram += 1

        u_role = str(u.role or "student").lower()
        if not is_notification_enabled_for_user(u.id, u_role, category):
            opted_out += 1
            continue

        eligible_users.append(u)
        if int(chat_id) in ALLOWLIST_CHAT_IDS:
            live_users.append(u)
        else:
            simulated_users.append(u)

    return {
        "total_audience": total_audience,
        "linked_telegram": linked_telegram,
        "opted_out": opted_out,
        "eligible_users": eligible_users,
        "eligible_count": len(eligible_users),
        "live_count": len(live_users),
        "simulated_count": len(simulated_users),
    }


def calculate_target_recipients(sender: User, audience: str, category: str) -> list[User]:
    """Backward-compatible helper returning the list of eligible users."""
    return analyze_broadcast_recipients(sender, audience, category)["eligible_users"]


# ---------------------------------------------------------------------------
# Wizard Steps
# ---------------------------------------------------------------------------

async def show_broadcast_center_start(update: Update, user: User) -> None:
    """Step 1: Choose Audience."""
    audiences = _get_permitted_audiences(user)
    if not audiences:
        await render_screen(
            update,
            "🚫 <b>Доступ ограничен</b>\n\nУ вас нет прав на отправку массовых рассылок.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]]),
        )
        return

    clear_draft(user.id)
    draft = get_or_create_draft(user.id)
    draft.step = "audience"

    text = (
        f"{card_header('📢 Центр рассылок BooStudy', 'Шаг 1 из 5: Выбор аудитории')}\n"
        "Выберите целевую группу пользователей для отправки сообщения:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for aud_code, aud_label in audiences:
        keyboard.append([
            InlineKeyboardButton(
                aud_label,
                callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:aud:{aud_code}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("📋 История рассылок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:hist")
    ])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def set_broadcast_audience(update: Update, user: User, audience: str) -> None:
    """Step 2: Choose Category / Message Type."""
    draft = get_or_create_draft(user.id)
    draft.audience = audience
    draft.step = "category"
    draft.updated_at = time.time()

    aud_title = AUDIENCE_LABELS.get(audience, audience)

    text = (
        f"{card_header('📢 Центр рассылок: Тип сообщения', 'Шаг 2 из 5: Категория')}\n"
        f"<b>Аудитория:</b> {aud_title}\n\n"
        "Выберите категорию рассылки (соответствует настройкам приватности получателей):\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("📢 Общее объявление", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:cat:broadcast")],
        [InlineKeyboardButton("🔔 Важное оповещение", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:cat:announcement")],
        [InlineKeyboardButton("📰 Новости и материалы", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:cat:news")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start"),
    ]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def set_broadcast_category(update: Update, user: User, category: str) -> None:
    """Step 3: Choose or Enter Title."""
    draft = get_or_create_draft(user.id)
    draft.category = category
    draft.step = "title"
    draft.updated_at = time.time()

    aud_title = AUDIENCE_LABELS.get(draft.audience, draft.audience)
    cat_title = CATEGORY_LABELS.get(category, category)

    text = (
        f"{card_header('📢 Центр рассылок: Заголовок', 'Шаг 3 из 5: Тема сообщения')}\n"
        f"<b>Аудитория:</b> {aud_title}\n"
        f"<b>Категория:</b> {cat_title}\n\n"
        "Выберите готовый заголовок из шаблона или напишите свой:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for tpl in SAMPLE_BROADCAST_TEMPLATES:
        keyboard.append([
            InlineKeyboardButton(
                f"📝 {tpl['title']}",
                callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:tpl:{tpl['id']}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("✏️ Ввести свой заголовок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:prompt_title")
    ])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:aud:{draft.audience}"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def prompt_broadcast_custom_title(update: Update, user: User) -> None:
    """Prompt user to type custom title in chat."""
    draft = get_or_create_draft(user.id)
    draft.step = "prompt_title"
    draft.updated_at = time.time()

    text = (
        f"{card_header('📢 Центр рассылок: Ввод заголовка', 'Шаг 3 из 5')}\n"
        "Отправьте в чат заголовок рассылки (до 100 символов).\n\n"
        "<i>Для отмены отправьте /cancel или нажмите кнопку ниже:</i>"
    )
    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:cat:{draft.category}")]]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def set_broadcast_template(update: Update, user: User, tpl_id: str) -> None:
    """Set template and proceed to text step."""
    draft = get_or_create_draft(user.id)
    found = next((t for t in SAMPLE_BROADCAST_TEMPLATES if t["id"] == tpl_id), SAMPLE_BROADCAST_TEMPLATES[0])
    draft.title = found["title"]
    draft.category = found.get("category", draft.category)
    draft.text = found["text"]
    draft.step = "text"
    draft.updated_at = time.time()

    await show_broadcast_step_text(update, user)


async def show_broadcast_step_text(update: Update, user: User) -> None:
    """Step 4: Choose or Edit Text."""
    draft = get_or_create_draft(user.id)
    draft.step = "text"
    draft.updated_at = time.time()

    title_esc = escape(draft.title)
    text_preview = escape(draft.text[:150] + "..." if len(draft.text) > 150 else draft.text) if draft.text else "<i>(текст ещё не введён)</i>"

    text = (
        f"{card_header('📢 Центр рассылок: Текст сообщения', 'Шаг 4 из 5')}\n"
        f"<b>Заголовок:</b> {title_esc}\n\n"
        f"<b>Текущий текст:</b>\n{text_preview}\n\n"
        "Вы можете использовать предложенный текст или отправить свой вариант сообщения:\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    if draft.text:
        keyboard.append([
            InlineKeyboardButton("✅ Использовать этот текст", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:btn_step")
        ])
    keyboard.append([
        InlineKeyboardButton("✏️ Написать свой текст", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:prompt_text")
    ])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:cat:{draft.category}"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def prompt_broadcast_custom_text(update: Update, user: User) -> None:
    """Prompt user to type broadcast text in chat."""
    draft = get_or_create_draft(user.id)
    draft.step = "prompt_text"
    draft.updated_at = time.time()

    text = (
        f"{card_header('📢 Центр рассылок: Ввод текста', 'Шаг 4 из 5')}\n"
        "Отправьте в чат полный текст рассылки (до 2000 символов).\n"
        "Поддерживается форматирование Telegram (жирный текст, курсив, списки).\n\n"
        "<i>Для отмены отправьте /cancel или нажмите кнопку ниже:</i>"
    )
    keyboard = [[InlineKeyboardButton("◀️ Отмена", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:text_step")]]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_broadcast_step_button(update: Update, user: User) -> None:
    """Step 5: Optional Button / URL."""
    draft = get_or_create_draft(user.id)
    draft.step = "button"
    draft.updated_at = time.time()

    btn_info = f"<b>Кнопка:</b> {escape(draft.button_label)} ({escape(draft.button_url)})\n\n" if draft.button_url else ""

    text = (
        f"{card_header('📢 Центр рассылок: Кнопка действия', 'Шаг 5 из 5: Ссылка (опционально)')}\n"
        f"{btn_info}"
        "Хотите прикрепить к сообщению интерактивную кнопку со ссылкой на платформу или вебинар?\n"
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("⏩ Пропустить (без кнопки)", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:preview")],
        [InlineKeyboardButton("🔗 Прикрепить кнопку со ссылкой", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:prompt_btn_lbl")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:text_step"),
    ]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def prompt_broadcast_button_label(update: Update, user: User) -> None:
    """Prompt user to type button title."""
    draft = get_or_create_draft(user.id)
    draft.step = "prompt_btn_label"
    draft.updated_at = time.time()

    text = (
        f"{card_header('📢 Кнопка рассылки: Текст кнопки', 'Шаг 5 из 5')}\n"
        "Отправьте текст для кнопки (например: <code>Перейти к уроку</code> или <code>Открыть материалы</code>, до 40 символов):\n\n"
        "<i>Для отмены отправьте /cancel или нажмите кнопку:</i>"
    )
    keyboard = [[InlineKeyboardButton("◀️ Пропустить кнопку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:preview")]]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def prompt_broadcast_button_url(update: Update, user: User) -> None:
    """Prompt user to type button URL."""
    draft = get_or_create_draft(user.id)
    draft.step = "prompt_btn_url"
    draft.updated_at = time.time()

    text = (
        f"{card_header('📢 Кнопка рассылки: Ссылка (URL)', 'Шаг 5 из 5')}\n"
        f"<b>Текст кнопки:</b> {escape(draft.button_label or 'Открыть')}\n\n"
        "Отправьте безопасную веб-ссылку (начинается с <code>https://</code> или <code>http://</code>):\n\n"
        "<i>Для отмены отправьте /cancel или нажмите кнопку:</i>"
    )
    keyboard = [[InlineKeyboardButton("◀️ Пропустить кнопку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:preview")]]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_broadcast_preview(update: Update, user: User) -> None:
    """Step 6: Synthetic Preview and Itemized Recipient Breakdown."""
    draft = get_or_create_draft(user.id)
    draft.step = "preview"
    draft.updated_at = time.time()

    aud = draft.audience
    cat = draft.category
    title = draft.title or "Объявление"
    text_body = draft.text or ""

    analysis = analyze_broadcast_recipients(user, aud, cat)

    sender_name = escape(get_display_name(user))
    sample_meta = {
        "sender_name": sender_name,
        "title": title,
        "body": text_body,
        "recipient_role": "student",
    }
    card_html, _ = render_telegram_notification(
        user_id=user.id,
        kind=cat,
        title=title,
        body=text_body,
        meta=sample_meta,
    )

    aud_title = AUDIENCE_LABELS.get(aud, aud)
    cat_title = CATEGORY_LABELS.get(cat, cat)

    btn_line = f"🔘 <b>Кнопка:</b> [{escape(draft.button_label)}] → <code>{escape(draft.button_url)}</code>\n" if draft.button_url else ""

    summary = (
        f"{card_header('📢 Подтверждение рассылки', 'Предпросмотр кампании')}\n"
        f"👥 <b>Целевая аудитория:</b> {aud_title}\n"
        f"🏷 <b>Категория:</b> {cat_title}\n"
        f"{btn_line}"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Расчёт получателей:</b>\n"
        f"• Всего пользователей в группе: <b>{analysis['total_audience']}</b>\n"
        f"• Подключён Telegram: <b>{analysis['linked_telegram']}</b>\n"
        f"• Отключили эту категорию: <b>{analysis['opted_out']}</b>\n"
        f"• <b>Будет создано доставок Outbox:</b> <b>{analysis['eligible_count']}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Режим доставки (Safe Dev Mode):</b>\n"
        f"• Реальная отправка (Allowlist): <b>{analysis['live_count']}</b> (Создатель)\n"
        f"• Безопасная симуляция (Dry-run): <b>{analysis['simulated_count']}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Образец сообщения для получателя:</b>\n\n"
        f"{card_html}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>ℹ️ В dev-окружении реальная отправка производится строго в чат Создателя. "
        "Для остальных адресатов регистрируется безопасная симуляция (dry-run).</i>"
    )

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🚀 Подтвердить и запустить рассылку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:send")],
        [
            InlineKeyboardButton("✏️ Изменить текст", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:prompt_text"),
            InlineKeyboardButton("✏️ Изменить заголовок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:prompt_title"),
        ],
        [InlineKeyboardButton("🔗 Настроить кнопку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:btn_step")],
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start"),
    ]

    await render_screen(update, summary, InlineKeyboardMarkup(keyboard))


async def execute_broadcast_send(update: Update, user: User) -> None:
    """Step 7: Execute send with idempotency guard and recipient stability check."""
    draft = get_or_create_draft(user.id) if user.id in _DRAFTS else None
    if not draft or not draft.text:
        await render_screen(
            update,
            "⚠️ <b>Черновик рассылки устарел.</b> Пожалуйста, начните заново.",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В центр рассылок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start")]]),
        )
        return

    # Idempotency lock
    if draft.is_sending:
        logger.warning("Duplicate broadcast execution prevented for user_id=%s", user.id)
        return
    draft.is_sending = True

    aud = draft.audience
    cat = draft.category
    title = draft.title
    text_body = draft.text
    btn_label = draft.button_label
    btn_url = draft.button_url

    # Re-verify recipients stability
    analysis = analyze_broadcast_recipients(user, aud, cat)
    recipients = analysis["eligible_users"]

    # 1. Create TelegramBroadcast database record
    broadcast_record = TelegramBroadcast(
        created_by_user_id=user.id,
        sender_role=getattr(user, "role", "teacher"),
        title=title,
        category=cat,
        message_text=text_body,
        recipient_scope=aud,
        total_planned=len(recipients),
        is_dry_run=False,
    )
    db.session.add(broadcast_record)
    db.session.flush()

    sender_name = get_display_name(user)
    enqueued_count = 0

    # 2. Enqueue into Outbox
    for r_user in recipients:
        r_meta = {
            "broadcast_id": broadcast_record.broadcast_id,
            "sender_name": sender_name,
            "title": title,
            "body": text_body,
            "recipient_role": getattr(r_user, "role", "student"),
        }
        if btn_url:
            r_meta["action_url"] = btn_url
            r_meta["action_label"] = btn_label or "Открыть"

        r_text, r_markup = render_telegram_notification(
            user_id=r_user.id,
            kind=cat,
            title=title,
            body=text_body,
            link_url=btn_url,
            meta=r_meta,
        )
        dedupe_key = f"telegram:broadcast:{broadcast_record.broadcast_id}:{r_user.id}"
        enqueue_delivery(
            user_id=r_user.id,
            text=r_text,
            kind=cat,
            reply_markup=r_markup,
            meta=r_meta,
            dedupe_key=dedupe_key,
            priority="normal",
        )
        enqueued_count += 1

    broadcast_record.status = "completed"
    broadcast_record.sent_ok = enqueued_count
    db.session.commit()

    # Clear draft on successful send
    clear_draft(user.id)

    aud_title = AUDIENCE_LABELS.get(aud, aud)

    success_text = (
        f"{card_header('✅ Рассылка запущена', f'Кампания #{broadcast_record.broadcast_id}')}\n"
        f"<b>Тема:</b> {escape(title)}\n"
        f"<b>Аудитория:</b> {aud_title}\n"
        f"<b>Поставлено в Outbox:</b> {enqueued_count} сообщений\n\n"
        f"• Реальная доставка (Allowlist): <b>{analysis['live_count']}</b>\n"
        f"• Безопасная симуляция (Dry-run): <b>{analysis['simulated_count']}</b>\n\n"
        "Сообщения переданы диспетчеру очереди Outbox для надёжной фоновой отправки."
    )

    keyboard = [
        [InlineKeyboardButton("📢 Создать ещё рассылку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start")],
        [InlineKeyboardButton("📋 История рассылок", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:hist")],
        build_nav_row(back_cb=None, home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
    ]

    await render_screen(update, success_text, InlineKeyboardMarkup(keyboard))


async def show_broadcast_history(update: Update, user: User) -> None:
    """Step 8: Show list of past broadcasts with clickable inspection."""
    role = (getattr(user, "role", "") or "").lower()
    query = TelegramBroadcast.query
    if role not in ("creator", "chief_admin"):
        query = query.filter_by(created_by_user_id=user.id)
    broadcasts = query.order_by(TelegramBroadcast.created_at.desc()).limit(10).all()

    if not broadcasts:
        text = (
            f"{card_header('📋 История рассылок', 'Нет записей')}\n"
            "Ранее отправленных рассылок не найдено.\n"
        )
        keyboard = [
            [InlineKeyboardButton("📢 Создать рассылку", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start")],
            build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start", home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    text_parts = [
        f"{card_header('📋 История рассылок', f'Последние {len(broadcasts)} кампаний')}\n"
        "Нажмите на кампанию, чтобы открыть детальную карточку доставки:\n"
    ]
    keyboard: list[list[InlineKeyboardButton]] = []

    for b in broadcasts:
        deliveries = TelegramDelivery.query.filter(
            TelegramDelivery.dedupe_key.like(f"telegram:broadcast:{b.broadcast_id}:%")
        ).all()
        sent_cnt = sum(1 for d in deliveries if d.status == 'sent')
        sim_cnt = sum(1 for d in deliveries if d.status == 'simulated')
        pending_cnt = sum(1 for d in deliveries if d.status == 'pending')
        failed_cnt = sum(1 for d in deliveries if d.status == 'failed')

        status_line = []
        if sent_cnt:
            status_line.append(f"✅ {sent_cnt} отпр.")
        if sim_cnt:
            status_line.append(f"🧪 {sim_cnt} симул.")
        if pending_cnt:
            status_line.append(f"⏳ {pending_cnt} очередь")
        if failed_cnt:
            status_line.append(f"❌ {failed_cnt} сбой")
        if not status_line:
            status_line.append(f"Всего: {b.total_planned or b.sent_ok or 0}")

        dt_str = b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "—"
        aud_label = AUDIENCE_LABELS.get(b.recipient_scope, b.recipient_scope or 'all')

        text_parts.append(
            f"<b>#{b.broadcast_id} — {escape(b.title or 'Без темы')}</b>\n"
            f"📅 <i>{dt_str}</i> | {aud_label}\n"
            f"📊 {', '.join(status_line)}\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"🔍 #{b.broadcast_id} {escape(b.title or 'Детали')[:22]}",
                callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:detail:{b.broadcast_id}",
            )
        ])

    keyboard.append([InlineKeyboardButton("📢 Новая рассылка", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start")])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:start", home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home"))
    await render_screen(update, "\n".join(text_parts), InlineKeyboardMarkup(keyboard))


async def show_broadcast_campaign_details(update: Update, user: User, broadcast_id: int) -> None:
    """Step 9: Inspect single past broadcast campaign with Outbox details."""
    b = db.session.get(TelegramBroadcast, broadcast_id)
    if not b:
        await render_screen(
            update,
            "❌ <b>Кампания рассылки не найдена</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К истории", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:hist")]]),
        )
        return

    # Check permission
    role = (getattr(user, "role", "") or "").lower()
    if role not in ("creator", "chief_admin") and b.created_by_user_id != user.id:
        await render_screen(
            update,
            "🚫 <b>Доступ ограничен</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К истории", callback_data=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:hist")]]),
        )
        return

    deliveries = TelegramDelivery.query.filter(
        TelegramDelivery.dedupe_key.like(f"telegram:broadcast:{b.broadcast_id}:%")
    ).all()

    sent_cnt = sum(1 for d in deliveries if d.status == 'sent')
    sim_cnt = sum(1 for d in deliveries if d.status == 'simulated')
    pending_cnt = sum(1 for d in deliveries if d.status == 'pending')
    failed_cnt = sum(1 for d in deliveries if d.status == 'failed')

    aud_title = AUDIENCE_LABELS.get(b.recipient_scope, b.recipient_scope)
    cat_title = CATEGORY_LABELS.get(b.category, b.category)
    dt_str = b.created_at.strftime("%d.%m.%Y %H:%M МСК") if b.created_at else "—"

    creator_user = db.session.get(User, b.created_by_user_id) if b.created_by_user_id else None
    creator_name = escape(get_display_name(creator_user)) if creator_user else "Система"

    text = (
        f"{card_header(f'📋 Кампания #{b.broadcast_id}', escape(b.title or 'Без темы'))}\n"
        f"<b>Тема:</b> {escape(b.title or 'Без темы')}\n"
        f"<b>Категория:</b> {cat_title}\n"
        f"<b>Аудитория:</b> {aud_title}\n"
        f"<b>Автор:</b> {creator_name}\n"
        f"<b>Время создания:</b> {dt_str}\n\n"
        f"<b>Текст сообщения:</b>\n"
        f"<i>{escape(b.message_text or '')}</i>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Статус доставки Outbox:</b>\n"
        f"• Всего запланировано: <b>{b.total_planned or len(deliveries)}</b>\n"
        f"• Доставлено (live): <b>{sent_cnt}</b>\n"
        f"• Безопасная симуляция (dry-run): <b>{sim_cnt}</b>\n"
        f"• Ожидает в очереди: <b>{pending_cnt}</b>\n"
        f"• Ошибок отправки: <b>{failed_cnt}</b>\n"
    )

    if failed_cnt:
        failed_sample = next((d for d in deliveries if d.status == 'failed'), None)
        if failed_sample and failed_sample.last_error:
            text += f"\n⚠️ <i>Пример ошибки: {escape(failed_sample.last_error[:120])}</i>\n"

    keyboard = [
        build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_BROADCAST}:hist", home_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")
    ]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


# ---------------------------------------------------------------------------
# Interactive Text Message Input Handler
# ---------------------------------------------------------------------------

async def handle_broadcast_text_input(update: Update, user: User, text: str) -> bool:
    """Catch plain text messages during wizard prompt steps. Returns True if handled."""
    draft = _DRAFTS.get(user.id)
    if not draft or (time.time() - draft.updated_at) > DRAFT_TTL_SECONDS:
        return False

    clean_text = text.strip()

    if clean_text.lower() in ("/cancel", "отмена"):
        clear_draft(user.id)
        if update.message:
            await update.message.reply_text("Рассылка отменена.", parse_mode="HTML")
        await show_broadcast_center_start(update, user)
        return True

    if draft.step == "prompt_title":
        draft.title = clean_text[:100]
        draft.step = "text"
        draft.updated_at = time.time()
        await show_broadcast_step_text(update, user)
        return True

    elif draft.step == "prompt_text":
        draft.text = clean_text[:2000]
        draft.step = "button"
        draft.updated_at = time.time()
        await show_broadcast_step_button(update, user)
        return True

    elif draft.step == "prompt_btn_label":
        draft.button_label = clean_text[:40]
        draft.step = "prompt_btn_url"
        draft.updated_at = time.time()
        await prompt_broadcast_button_url(update, user)
        return True

    elif draft.step == "prompt_btn_url":
        parsed = urlparse(clean_text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            if update.message:
                await update.message.reply_text(
                    "⚠️ Некорректная ссылка. URL должен начинаться с <code>https://</code> или <code>http://</code>. Попробуйте ещё раз:",
                    parse_mode="HTML",
                )
            return True
        draft.button_url = clean_text
        draft.step = "preview"
        draft.updated_at = time.time()
        await show_broadcast_preview(update, user)
        return True

    return False

