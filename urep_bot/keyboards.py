"""
Inline-клавиатуры бота.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_keyboard():
    """Основная клавиатура."""
    keyboard = [
        [
            InlineKeyboardButton("📅 Уроки", callback_data="lessons"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard(notifications_enabled: bool):
    """Клавиатура настроек."""
    toggle_text = "🔕 Выключить" if notifications_enabled else "✅ Включить"
    toggle_data = "toggle_notifications"
    
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton("« Назад", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_unlink_confirm_keyboard():
    """Клавиатура подтверждения отвязки."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, отвязать", callback_data="confirm_unlink"),
            InlineKeyboardButton("❌ Отмена", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
    """Клавиатура с кнопкой назад."""
    keyboard = [
        [InlineKeyboardButton("« Назад", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_open_link_keyboard(url: str, text: str = "Открыть"):
    """Клавиатура со ссылкой."""
    keyboard = [
        [InlineKeyboardButton(text, url=url)],
    ]
    return InlineKeyboardMarkup(keyboard)
