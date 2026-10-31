"""Admin operational panel screens for BooStudy Bot V3."""
from __future__ import annotations

import math
from typing import Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.models import db, User, UserProfile
from app.telegram.application import (
    build_operational_summary,
    build_operational_problems,
)
from app.telegram.v3.constants import (
    CB_PREFIX,
    DOMAIN_ADMIN,
    DOMAIN_NAV,
    DOMAIN_SETTINGS,
    PAGE_SIZE_USERS,
    ROLE_EMOJIS,
    ROLE_TITLES,
)
from app.telegram.v3.identity import get_display_name
from app.telegram.v3.ui import (
    card_header,
    empty_state,
    escape,
    format_dt,
    is_localhost_url,
    localhost_hint,
    build_nav_row,
    build_pagination_row,
    render_screen,
)


def _can_access_admin(user: User) -> bool:
    return bool(user.is_admin() or user.is_creator() or getattr(user, "role", "") in {"admin", "chief_admin", "creator"})


async def show_admin_home(update: Update, user: User) -> None:
    """Render the Admin Operational Home dashboard."""
    if not _can_access_admin(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только администраторам платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    name = escape(get_display_name(user))
    summary = build_operational_summary(user)

    text = f"{card_header(f'⚙️ Управление · {name}', 'Панель администратора')}\n"

    if summary:
        text += (
            f"📊 <b>Сводка платформы:</b>\n"
            f"• Пользователей: <b>{summary.users}</b> (учеников: {summary.active_students}, учителей: {summary.active_teachers})\n"
            f"• Работ ждут проверки: <b>{summary.pending_reviews}</b>\n"
            f"• Открытых обращений: <b>{summary.open_bug_reports}</b>\n"
        )
        if summary.failed_deliveries:
            text += f"• ⚠️ Ошибок Telegram Outbox: <b>{summary.failed_deliveries}</b>\n"
        text += "\n"

    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("👥 Пользователи платформы", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:all")],
        [InlineKeyboardButton("📊 Полная статистика", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:metrics")],
        [InlineKeyboardButton("⚠️ Обращения и проблемы", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:probs")],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home"),
            InlineKeyboardButton("🔄 Обновить", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
        ],
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_metrics(update: Update, user: User) -> None:
    """Render detailed platform operational metrics."""
    if not _can_access_admin(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только администраторам платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    summary = build_operational_summary(user)
    text = f"{card_header('📊 Сводные метрики', 'Операционные показатели BooStudy')}\n"

    if not summary:
        text += empty_state("📊", "Нет данных", "Сводная статистика временно недоступна.")
    else:
        text += (
            f"👥 <b>Пользователи:</b>\n"
            f"• Активных аккаунтов: <b>{summary.users}</b>\n"
            f"• Активных учеников: <b>{summary.active_students}</b>\n"
            f"• Преподавателей и тьюторов: <b>{summary.active_teachers}</b>\n\n"
            f"📝 <b>Учебный процесс:</b>\n"
            f"• Сдач в очереди на проверку: <b>{summary.pending_reviews}</b>\n"
            f"• Открытых баг-репортов: <b>{summary.open_bug_reports}</b>\n\n"
            f"📬 <b>Telegram Outbox (очереди отправки):</b>\n"
            f"• В ожидании (pending): <b>{summary.pending_deliveries}</b>\n"
            f"• Повторные попытки (retry): <b>{summary.retry_deliveries}</b>\n"
            f"• Ошибки доставки (failed): <b>{summary.failed_deliveries}</b>\n"
        )

    keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:home")]
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_users_list(update: Update, user: User, page: int = 1, role_filter: str = "all") -> None:
    """Render paginated, filterable user list without monstrous dumps."""
    if not _can_access_admin(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только администраторам платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    query = User.query.filter(User.is_active.is_(True))
    if role_filter == "student":
        query = query.filter(User.role == "student")
    elif role_filter == "teacher":
        query = query.filter(User.role.in_(("teacher", "tutor")))
    elif role_filter == "parent":
        query = query.filter(User.role == "parent")
    elif role_filter == "admin":
        query = query.filter(User.role.in_(("admin", "chief_admin", "creator")))

    total_count = query.count()
    total_pages = max(1, math.ceil(total_count / PAGE_SIZE_USERS))
    page = max(1, min(page, total_pages))

    users = query.order_by(User.id.asc()).offset((page - 1) * PAGE_SIZE_USERS).limit(PAGE_SIZE_USERS).all()

    filter_titles = {
        "all": "Все",
        "student": "Ученики",
        "teacher": "Учителя",
        "parent": "Родители",
        "admin": "Админы",
    }
    cur_filter_title = filter_titles.get(role_filter, "Все")

    text = f"{card_header('👥 Пользователи', f'Фильтр: {cur_filter_title} (Всего: {total_count})')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    # Filter buttons row
    f_rows = [
        InlineKeyboardButton("Все" if role_filter != "all" else "• Все •", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:all"),
        InlineKeyboardButton("Ученики" if role_filter != "student" else "• Ученики •", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:student"),
        InlineKeyboardButton("Учителя" if role_filter != "teacher" else "• Учителя •", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:teacher"),
        InlineKeyboardButton("Админы" if role_filter != "admin" else "• Админы •", callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:1:admin"),
    ]
    keyboard.append(f_rows)

    if not users:
        text += empty_state("👤", "Пользователи не найдены", "По данному фильтру пользователей нет.")
    else:
        for u in users:
            uname = escape(u.username or f"user_{u.id}")
            urole = ROLE_TITLES.get(u.role, u.role)
            emoji = ROLE_EMOJIS.get(u.role, "👤")
            tg_status = "✅" if (getattr(u.profile, "telegram_chat_id", None) or u.telegram_chat_id) else "❌"

            text += f"• <b>#{u.id} {uname}</b> ({emoji} {urole}) [TG: {tg_status}]\n"

            btn_label = f"#{u.id} {uname[:20]}"
            keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u_item:{u.id}:{page}:{role_filter}")])

        text += "\n"

    # Pagination row
    pag_row = build_pagination_row(DOMAIN_ADMIN, f"u", page, total_pages, extra=role_filter)
    if pag_row:
        keyboard.append(pag_row)

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_user_card(
    update: Update,
    user: User,
    target_user_id: int,
    return_page: int = 1,
    return_role: str = "all",
) -> None:
    """Render single user details for administrator."""
    if not _can_access_admin(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только администраторам платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    target = db.session.get(User, target_user_id)
    if not target:
        text = f"{card_header('Пользователь не найден')}\n<i>Запрошенный аккаунт не существует.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:{return_page}:{return_role}")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    uname = escape(target.username)
    email = escape(target.email or "Не указан")
    role_title = ROLE_TITLES.get(target.role, target.role)
    emoji = ROLE_EMOJIS.get(target.role, "👤")

    prof = target.profile
    full_name = escape(f"{prof.first_name or ''} {prof.last_name or ''}".strip()) if prof else ""
    tg_chat = prof.telegram_chat_id if prof else target.telegram_chat_id
    tg_status = f"<code>{tg_chat}</code>" if tg_chat else "Не привязан"

    reg_date = format_dt(target.created_at, relative=False) if target.created_at else "Не указана"

    text = (
        f"{card_header('👤 Карточка пользователя', f'ID: {target.id}')}\n"
        f"<b>Логин:</b> {uname}\n"
        f"<b>Имя:</b> {full_name or 'Не заполнено'}\n"
        f"<b>Роль:</b> {emoji} {role_title}\n"
        f"<b>Email:</b> {email}\n"
        f"<b>Telegram Chat ID:</b> {tg_status}\n"
        f"<b>Дата регистрации:</b> {reg_date}\n\n"
    )

    from app.telegram import deep_links
    web_url = deep_links.user(target.id)

    if web_url and is_localhost_url(web_url):
        text += f"{localhost_hint()}"

    keyboard: list[list[InlineKeyboardButton]] = []
    if web_url:
        keyboard.append([InlineKeyboardButton("💻 Открыть в веб-админке", url=web_url)])
    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:u:{return_page}:{return_role}"))

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))


async def show_admin_problems(update: Update, user: User) -> None:
    """Render open operational bug reports and problems."""
    if not _can_access_admin(user):
        text = f"{card_header('Доступ ограничен')}\n<i>Раздел доступен только администраторам платформы.</i>"
        keyboard = [build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_NAV}:home")]
        await render_screen(update, text, InlineKeyboardMarkup(keyboard))
        return

    problems = build_operational_problems(user, limit=10)
    text = f"{card_header('⚠️ Проблемы и обращения', f'Открытых проблем: {len(problems)}')}\n"
    keyboard: list[list[InlineKeyboardButton]] = []

    if not problems:
        text += empty_state("🎉", "Нет открытых проблем", "Все обращения обработаны, сбоев доставки в очереди нет.")
    else:
        text += "Список инцидентов:\n\n"
        for idx, p in enumerate(problems, 1):
            title = escape(p.get("title") or "Обращение")
            sev = escape(p.get("severity") or "normal")
            text += f"<b>{idx}. #{p.get('id')}</b> {title} <i>(Важность: {sev})</i>\n"
            if p.get("deep_link") and idx <= 3:
                keyboard.append([InlineKeyboardButton(f"🔗 #{p.get('id')} на сайте", url=p["deep_link"])])
            text += "\n"

    keyboard.append(build_nav_row(back_cb=f"{CB_PREFIX}:{DOMAIN_ADMIN}:home"))
    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
