"""Central request and callback router for BooStudy Bot V3.

Dispatches commands, text inputs (including link codes), and inline callback queries
to appropriate domain screens with strict server-side RBAC validation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Tuple

from sqlalchemy import func, or_
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.models import db, User, UserProfile
from app.telegram.config import APP_URL
from app.telegram.link_api import call_link_bot_api
from app.telegram.linking import TelegramLinkConflict, link_telegram_identity
from app.telegram.v3.constants import (
    CB_PREFIX,
    CMD_CANCEL,
    CMD_HELP,
    CMD_MENU,
    CMD_ROLE,
    CMD_SETTINGS,
    CMD_START,
    CMD_UNLINK,
    DOMAIN_ADMIN,
    DOMAIN_CONTEXT,
    DOMAIN_CREATOR,
    DOMAIN_NAV,
    DOMAIN_PARENT,
    DOMAIN_SETTINGS,
    DOMAIN_STUDENT,
    DOMAIN_TEACHER,
)
from app.telegram.v3.context import (
    available_contexts,
    get_active_context,
    switch_context,
    toggle_creator_mode,
)
from app.telegram.v3.identity import (
    get_display_name,
    record_start_lead,
    resolve_user_identity,
    touch_interaction,
)
from app.telegram.v3.screens.admin import (
    show_admin_home,
    show_admin_metrics,
    show_admin_problems,
    show_admin_user_card,
    show_admin_users_list,
)
from app.telegram.v3.screens.creator import show_creator_home
from app.telegram.v3.screens.parent import (
    show_parent_child_digest,
    show_parent_child_schedule,
    show_parent_child_view,
    show_parent_home,
)
from app.telegram.v3.screens.settings import (
    execute_unlink,
    show_help_screen,
    show_notifications_menu,
    show_role_switcher_menu,
    show_settings_home,
    show_unlink_confirmation,
    toggle_notification_setting,
)
from app.telegram.v3.screens.student import (
    show_student_hw_item,
    show_student_hw_list,
    show_student_home,
    show_student_progress,
    show_student_schedule,
)
from app.telegram.v3.screens.teacher import (
    show_teacher_home,
    show_teacher_review_queue,
    show_teacher_schedule,
    show_teacher_student_card,
    show_teacher_students_list,
    show_teacher_submission_item,
)
from app.telegram.v3.screens.unlinked import get_profile_connect_url, show_unlinked_screen
from app.telegram.v3.ui import card_header, escape, render_screen

logger = logging.getLogger(__name__)


def check_domain_access(user: User, domain: str) -> bool:
    """Validate server-side whether user has rights to access domain actions."""
    actual_roles = {str(r).lower() for r in (user.roles() if hasattr(user, "roles") else [user.role])}
    allowed = available_contexts(user)

    if domain == DOMAIN_STUDENT:
        return "student" in allowed or "student" in actual_roles or "creator" in actual_roles
    if domain == DOMAIN_TEACHER:
        return "teacher" in allowed or "tutor" in allowed or bool(actual_roles & {"teacher", "tutor", "creator"})
    if domain == DOMAIN_PARENT:
        return "parent" in allowed or "parent" in actual_roles or "creator" in actual_roles
    if domain == DOMAIN_ADMIN:
        return "admin" in allowed or "chief_admin" in allowed or bool(actual_roles & {"admin", "chief_admin", "creator"})
    if domain == DOMAIN_CREATOR:
        return "creator" in actual_roles
    return True


async def dispatch_active_home(
    update: Update,
    user: User,
    active_context: str | None = None,
    user_data: dict | None = None,
) -> None:
    """Route user to the dashboard corresponding to their current active context."""
    if not active_context:
        active_context = get_active_context(user, user_data)

    if active_context == "creator":
        await show_creator_home(update, user)
    elif active_context in ("teacher", "tutor"):
        await show_teacher_home(update, user)
    elif active_context == "student":
        await show_student_home(update, user)
    elif active_context == "parent":
        await show_parent_home(update, user)
    elif active_context in ("admin", "chief_admin"):
        await show_admin_home(update, user)
    else:
        role = str(getattr(user, "role", "student")).lower()
        if role == "creator":
            await show_creator_home(update, user)
        elif role in ("teacher", "tutor"):
            await show_teacher_home(update, user)
        elif role == "parent":
            await show_parent_home(update, user)
        elif role in ("admin", "chief_admin"):
            await show_admin_home(update, user)
        else:
            await show_student_home(update, user)


def attempt_link_by_code_or_token(
    chat_id: int,
    tg_user: Any,
    token_str: str,
) -> Tuple[bool, str, User | None]:
    """Attempt account linking using 6-char code (BS-XXXXXX) or deep link hex token.

    Returns (success, message, linked_user).
    """
    token = (token_str or "").strip()
    if not token:
        return False, "Код не указан.", None

    tg_username = getattr(tg_user, "username", None) if tg_user else None
    tg_user_id = getattr(tg_user, "id", None) if tg_user else chat_id

    # 1. Check QA key
    qa_user = User.query.filter_by(tg_auth_key=token).first()
    if qa_user:
        qa_user.tg_id = chat_id
        db.session.commit()
        return True, "Аккаунт QA успешно привязан.", qa_user

    # 2. Check 6-char linking code (BS-XXXXXX)
    if token.upper().startswith("BS-") or (len(token) == 6 and token.isalnum()):
        raw_code = token.upper()
        alt_code = raw_code if raw_code.startswith("BS-") else f"BS-{raw_code}"
        profile = UserProfile.query.filter(
            or_(
                func.upper(UserProfile.telegram_link_code) == raw_code,
                func.upper(UserProfile.telegram_link_code) == alt_code,
            )
        ).first()

        if not profile or not profile.user:
            return False, "Код привязки не найден или неверен. Сгенерируйте новый в карточке профиля на сайте.", None

        expires_at = getattr(profile, "telegram_link_code_expires", None)
        if expires_at:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                return False, "Срок действия кода истек. Сгенерируйте новый код в профиле.", None

        try:
            link_telegram_identity(
                db.session,
                user=profile.user,
                profile=profile,
                chat_id=chat_id,
                telegram_username=tg_username,
                telegram_user_id=tg_user_id,
            )
            db.session.commit()
            return True, "Аккаунт успешно привязан!", profile.user
        except TelegramLinkConflict:
            db.session.rollback()
            return False, "Этот Telegram уже привязан к другому активному аккаунту BooStudy.", None
        except Exception as e:
            db.session.rollback()
            logger.error("Error linking by code %s: %s", token, e, exc_info=True)
            return False, f"Ошибка привязки: {e}", None

    # 3. Check 16+ hex token from deep link
    if len(token) >= 16:
        profile = UserProfile.query.filter_by(telegram_link_token=token).first()
        if profile and profile.user:
            expires_at = getattr(profile, "telegram_link_token_expires", None)
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at < datetime.now(timezone.utc):
                    return False, "Срок действия ссылки истек. Откройте профиль и нажмите кнопку снова.", None

            try:
                link_telegram_identity(
                    db.session,
                    user=profile.user,
                    profile=profile,
                    chat_id=chat_id,
                    telegram_username=tg_username,
                    telegram_user_id=tg_user_id,
                )
                db.session.commit()
                return True, "Аккаунт успешно привязан!", profile.user
            except TelegramLinkConflict:
                db.session.rollback()
                return False, "Этот Telegram уже привязан к другому активному аккаунту BooStudy.", None
            except Exception as e:
                db.session.rollback()
                logger.error("Error linking by token %s: %s", token, e, exc_info=True)
                return False, f"Ошибка привязки: {e}", None

        # Fallback to call_link_bot_api if DB lookup yielded nothing
        if APP_URL:
            try:
                res = call_link_bot_api(
                    chat_id=chat_id,
                    telegram_id=f"@{tg_username}" if tg_username else None,
                    link_token=token,
                    app_url=APP_URL,
                )
                if res and res.get("status") == 200 and (res.get("data") or {}).get("success"):
                    u, _ = resolve_user_identity(chat_id)
                    return True, "Аккаунт успешно привязан!", u
            except Exception as e:
                logger.warning("call_link_bot_api fallback failed: %s", e)

        return False, "Ссылка привязки недействительна или устарела.", None

    return False, "Неизвестный формат кода привязки.", None


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

async def handle_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start [token_or_code]."""
    chat_id = update.effective_chat.id
    tg_user = update.effective_user

    touch_interaction(chat_id)
    record_start_lead(
        chat_id,
        username=getattr(tg_user, "username", None),
        first_name=getattr(tg_user, "first_name", None),
        last_name=getattr(tg_user, "last_name", None),
    )

    token = (context.args[0] if context.args else "").strip()
    if token:
        success, msg, linked_user = attempt_link_by_code_or_token(chat_id, tg_user, token)
        if success and linked_user:
            name = get_display_name(linked_user)
            welcome_text = (
                f"{card_header('🎉 BooStudy · Аккаунт привязан', 'Связь успешно установлена')}\n"
                f"Здравствуйте, <b>{escape(name)}</b>!\n"
                "Ваш Telegram-аккаунт успешно подключен к платформе BooStudy.\n\n"
                "Ниже открыта ваша главная страница."
            )
            await update.message.reply_text(welcome_text, parse_mode="HTML")
            await dispatch_active_home(update, linked_user, user_data=context.user_data)
            return
        else:
            err_text = (
                f"{card_header('⚠️ BooStudy · Ошибка привязки', 'Не удалось связать аккаунт')}\n"
                f"{escape(msg)}\n\n"
                "Откройте ваш профиль на сайте и попробуйте подключить Telegram снова."
            )
            keyboard = [[InlineKeyboardButton("🔗 Открыть профиль BooStudy", url=get_profile_connect_url())]]
            await update.message.reply_text(err_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

    # No token provided: check if already linked
    user, _ = resolve_user_identity(chat_id)
    if user:
        await dispatch_active_home(update, user, user_data=context.user_data)
    else:
        await show_unlinked_screen(update)


async def handle_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /menu."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    if user:
        await dispatch_active_home(update, user, user_data=context.user_data)
    else:
        await show_unlinked_screen(update)


async def handle_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)
    await show_help_screen(update, user)


async def handle_settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    if user:
        active_ctx = get_active_context(user, context.user_data)
        await show_settings_home(update, user, active_context=active_ctx)
    else:
        await show_unlinked_screen(update)


async def handle_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /role."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    if user:
        active_ctx = get_active_context(user, context.user_data)
        await show_role_switcher_menu(update, user, current_context=active_ctx)
    else:
        await show_unlinked_screen(update)


async def handle_unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unlink."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    if user:
        await show_unlink_confirmation(update, user)
    else:
        await show_unlinked_screen(update)


async def handle_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel."""
    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    if user:
        await dispatch_active_home(update, user, user_data=context.user_data)
    else:
        await show_unlinked_screen(update)


# ---------------------------------------------------------------------------
# Text Message Handler (Link codes and general messages)
# ---------------------------------------------------------------------------

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming plain text: check for link codes (BS-XXXXXX) or prompt."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    tg_user = update.effective_user

    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    # If code entered while unlinked or explicitly sending code
    is_code_like = text.upper().startswith("BS-") or (len(text) == 6 and text.isalnum())
    if is_code_like:
        success, msg, linked_user = attempt_link_by_code_or_token(chat_id, tg_user, text)
        if success and linked_user:
            name = get_display_name(linked_user)
            welcome_text = (
                f"{card_header('🎉 BooStudy · Аккаунт привязан', 'Связь успешно установлена')}\n"
                f"Здравствуйте, <b>{escape(name)}</b>!\n"
                "Ваш Telegram-аккаунт успешно подключен к платформе BooStudy.\n\n"
                "Ниже открыта ваша главная страница."
            )
            await update.message.reply_text(welcome_text, parse_mode="HTML")
            await dispatch_active_home(update, linked_user, user_data=context.user_data)
            return
        else:
            err_text = (
                f"{card_header('⚠️ BooStudy · Ошибка привязки', 'Код не подошел')}\n"
                f"{escape(msg)}"
            )
            keyboard = [[InlineKeyboardButton("🔗 Открыть профиль BooStudy", url=get_profile_connect_url())]]
            await update.message.reply_text(err_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

    # If user is not linked and sends general text
    if not user:
        await show_unlinked_screen(update)
        return

    # User is linked and sent general text: offer quick jump to /menu
    prompt_text = (
        "💡 Используйте встроенные кнопки и меню для навигации по платформе."
    )
    keyboard = [
        [InlineKeyboardButton("🏠 Открыть главное меню", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:home")],
    ]
    await update.message.reply_text(
        prompt_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------------------------------------------------------------------
# Callback Query Dispatcher (v3:*)
# ---------------------------------------------------------------------------

async def handle_v3_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse and dispatch all inline button callbacks with prefix 'v3:'."""
    query = update.callback_query
    if not query or not query.data:
        return

    chat_id = update.effective_chat.id
    touch_interaction(chat_id)
    user, _ = resolve_user_identity(chat_id)

    raw_data = query.data
    parts = raw_data.split(":")
    if len(parts) < 3 or parts[0] != CB_PREFIX:
        logger.warning("Unrecognized callback format: %s", raw_data)
        await query.answer("Действие не распознано", show_alert=False)
        return

    domain = parts[1]
    action = parts[2]
    params = parts[3:]

    # Public/Unlinked actions that don't require an active linked account:
    if not user:
        if domain == DOMAIN_SETTINGS and action == "help":
            await show_help_screen(update, user=None)
            return
        # Any other action from an unlinked chat redirects to unlinked screen
        await query.answer("Сначала привяжите аккаунт", show_alert=True)
        await show_unlinked_screen(update)
        return

    # Server-side RBAC authorization check
    if not check_domain_access(user, domain):
        logger.warning(
            "User %s attempted unauthorized access to domain '%s' (action=%s)",
            user.id, domain, action,
        )
        await query.answer("⚠️ Недостаточно прав для этого раздела", show_alert=True)
        await dispatch_active_home(update, user, user_data=context.user_data)
        return

    # ------------------ DOMAIN: NAV ------------------
    if domain == DOMAIN_NAV:
        if action == "home":
            await dispatch_active_home(update, user, user_data=context.user_data)
            return

    # ------------------ DOMAIN: CONTEXT ------------------
    elif domain == DOMAIN_CONTEXT:
        if action == "menu":
            active_ctx = get_active_context(user, context.user_data)
            await show_role_switcher_menu(update, user, current_context=active_ctx)
            return
        elif action == "set" and params:
            target_role = params[0]
            new_ctx = switch_context(user, target_role, context.user_data)
            await dispatch_active_home(update, user, active_context=new_ctx, user_data=context.user_data)
            return

    # ------------------ DOMAIN: STUDENT ------------------
    elif domain == DOMAIN_STUDENT:
        if action == "home":
            await show_student_home(update, user)
            return
        elif action == "sch":
            await show_student_schedule(update, user)
            return
        elif action == "hw":
            page = int(params[0]) if params else 1
            await show_student_hw_list(update, user, page=page)
            return
        elif action == "hw_item" and params:
            assignment_id = int(params[0])
            page = int(params[1]) if len(params) > 1 else 1
            await show_student_hw_item(update, user, assignment_id=assignment_id, return_page=page)
            return
        elif action == "prog":
            await show_student_progress(update, user)
            return

    # ------------------ DOMAIN: TEACHER ------------------
    elif domain == DOMAIN_TEACHER:
        if action == "home":
            await show_teacher_home(update, user)
            return
        elif action == "sch":
            await show_teacher_schedule(update, user)
            return
        elif action == "queue":
            page = int(params[0]) if params else 1
            await show_teacher_review_queue(update, user, page=page)
            return
        elif action == "q_item" and params:
            submission_id = int(params[0])
            page = int(params[1]) if len(params) > 1 else 1
            await show_teacher_submission_item(update, user, submission_id=submission_id, return_page=page)
            return
        elif action == "st":
            page = int(params[0]) if params else 1
            await show_teacher_students_list(update, user, page=page)
            return
        elif action == "st_item" and params:
            student_id = int(params[0])
            page = int(params[1]) if len(params) > 1 else 1
            await show_teacher_student_card(update, user, student_id=student_id, return_page=page)
            return

    # ------------------ DOMAIN: PARENT ------------------
    elif domain == DOMAIN_PARENT:
        if action == "home":
            await show_parent_home(update, user)
            return
        elif action == "ch" and params:
            student_id = int(params[0])
            await show_parent_child_view(update, user, student_id=student_id)
            return
        elif action == "sch" and params:
            student_id = int(params[0])
            await show_parent_child_schedule(update, user, student_id=student_id)
            return
        elif action == "dig" and params:
            student_id = int(params[0])
            await show_parent_child_digest(update, user, student_id=student_id)
            return

    # ------------------ DOMAIN: ADMIN ------------------
    elif domain == DOMAIN_ADMIN:
        if action == "home":
            await show_admin_home(update, user)
            return
        elif action == "metrics":
            await show_admin_metrics(update, user)
            return
        elif action == "probs":
            await show_admin_problems(update, user)
            return
        elif action == "u":
            page = int(params[0]) if params else 1
            role_filter = params[1] if len(params) > 1 else "all"
            await show_admin_users_list(update, user, page=page, role_filter=role_filter)
            return
        elif action == "u_item" and params:
            user_id = int(params[0])
            page = int(params[1]) if len(params) > 1 else 1
            role_filter = params[2] if len(params) > 2 else "all"
            await show_admin_user_card(update, user, target_user_id=user_id, return_page=page, return_role=role_filter)
            return

    # ------------------ DOMAIN: CREATOR ------------------
    elif domain == DOMAIN_CREATOR:
        if action == "home":
            await show_creator_home(update, user)
            return
        elif action == "toggle_mode":
            new_ctx = toggle_creator_mode(user, context.user_data)
            await dispatch_active_home(update, user, active_context=new_ctx, user_data=context.user_data)
            return

    # ------------------ DOMAIN: SETTINGS ------------------
    elif domain == DOMAIN_SETTINGS:
        if action == "home":
            active_ctx = get_active_context(user, context.user_data)
            await show_settings_home(update, user, active_context=active_ctx)
            return
        elif action == "help":
            await show_help_screen(update, user)
            return
        elif action == "notif":
            if params and params[0] == "toggle" and len(params) > 1:
                category = params[1]
                await toggle_notification_setting(update, user, category=category)
                return
            else:
                await show_notifications_menu(update, user)
                return
        elif action == "unlink":
            if params and params[0] == "do":
                await execute_unlink(update, user)
                return
            else:
                await show_unlink_confirmation(update, user)
                return

    # Fallback for unhandled action
    logger.warning("Unhandled V3 callback action: domain=%s, action=%s, params=%s", domain, action, params)
    await query.answer("Действие выполнено", show_alert=False)
