"""Screen displayed for users whose Telegram is not yet linked to BooStudy."""
from __future__ import annotations

import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from app.telegram.config import APP_URL
from app.telegram.v3.constants import CB_PREFIX, DOMAIN_NAV, DOMAIN_SETTINGS
from app.telegram.v3.ui import card_header, render_screen


def get_profile_connect_url() -> str:
    base = (APP_URL or "http://127.0.0.1:5000").rstrip("/")
    return f"{base}/workspace/profile?telegram=connect"


async def show_unlinked_screen(update: Update) -> None:
    """Render the polite unlinked welcome screen with direct linking instructions."""
    connect_url = get_profile_connect_url()

    text = (
        f"{card_header('🔒 BooStudy · Вход в систему', 'Telegram не привязан к аккаунту')}\n"
        "Здравствуйте! Ваш Telegram пока не связан с профилем на платформе <b>BooStudy</b>.\n\n"
        "<b>Как подключить аккаунт:</b>\n"
        "1. Нажмите кнопку <b>«Открыть профиль BooStudy»</b> ниже.\n"
        "2. В карточке <i>«Telegram и уведомления»</i> нажмите <b>«Подключить Telegram»</b>.\n"
        "3. Нажмите <b>«Открыть бота»</b> либо скопируйте 6-значный код (например, <code>BS-A1B2C3</code>) и отправьте его сюда в чат.\n\n"
        "<i>После привязки вам сразу станут доступны расписание, домашние задания и уведомления об уроках.</i>"
    )

    keyboard = [
        [InlineKeyboardButton("🔗 Открыть профиль BooStudy", url=connect_url)],
        [
            InlineKeyboardButton("🔄 Проверить привязку", callback_data=f"{CB_PREFIX}:{DOMAIN_NAV}:home"),
            InlineKeyboardButton("ℹ️ Справка", callback_data=f"{CB_PREFIX}:{DOMAIN_SETTINGS}:help"),
        ],
    ]

    await render_screen(update, text, InlineKeyboardMarkup(keyboard))
