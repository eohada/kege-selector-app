"""
Модуль формирования клавиатур Telegram-бота BooStudy.
Поддерживает роль-ориентированные клавиатуры и 1-click переключение режима Создателя.
"""
from __future__ import annotations

import os
from typing import Optional
from telegram import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from app.telegram.config import APP_URL


def get_webapp_info(url_path: str = '/tg-app/') -> WebAppInfo:
    base = (APP_URL or os.environ.get('APP_URL') or os.environ.get('BASE_URL') or '').strip().rstrip('/')
    if not base or base.startswith('http://'):
        base = 'https://boostudy.ru'
    full_url = f"{base}/{url_path.lstrip('/')}"
    return WebAppInfo(url=full_url)


def get_main_keyboard(user_role: str, creator_mode: str = 'creator') -> ReplyKeyboardMarkup:
    role = (user_role or '').lower()
    webapp_info = get_webapp_info()

    # 👑 СОЗДАТЕЛЬ
    if role == 'creator':
        if creator_mode == 'teacher':
            # Режим Преподавателя для Создателя
            keyboard = [
                [KeyboardButton(text="🚀 Панель Преподавателя", web_app=webapp_info), KeyboardButton(text="📅 Уроки на сегодня")],
                [KeyboardButton(text="📥 На проверку"), KeyboardButton(text="👥 Мои ученики")],
                [KeyboardButton(text="🔄 Режим: 👑 Создатель"), KeyboardButton(text="🚪 Отвязать аккаунт")]
            ]
        else:
            # Режим Создателя по умолчанию
            keyboard = [
                [KeyboardButton(text="📊 Сводка"), KeyboardButton(text="👥 Пользователи")],
                [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📝 Ученики")],
                [KeyboardButton(text="🔄 Режим: 👨‍🏫 Преподаватель"), KeyboardButton(text="🚪 Отвязать аккаунт")]
            ]

    # 🛡️ АДМИНИСТРАТОР
    elif role in ['admin', 'chief_admin']:
        keyboard = [
            [KeyboardButton(text="📊 Сводка"), KeyboardButton(text="👥 Пользователи")],
            [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📝 Ученики")],
            [KeyboardButton(text="🚪 Отвязать аккаунт")]
        ]

    # 👨‍🏫 ПРЕПОДАВАТЕЛЬ / ТЬЮТОР
    elif role in ['teacher', 'tutor', 'content_maker']:
        keyboard = [
            [KeyboardButton(text="🚀 Панель Преподавателя", web_app=webapp_info), KeyboardButton(text="📅 Уроки на сегодня")],
            [KeyboardButton(text="📥 На проверку"), KeyboardButton(text="👥 Мои ученики")],
            [KeyboardButton(text="🚪 Отвязать аккаунт")]
        ]

    # 👨‍👩‍👧 РОДИТЕЛЬ
    elif role == 'parent':
        keyboard = [
            [KeyboardButton(text="🚀 Кабинет Родителя", web_app=webapp_info), KeyboardButton(text="👨‍👩‍👧 Мои дети")],
            [KeyboardButton(text="💳 Семейный баланс"), KeyboardButton(text="🔔 Настройки отчетов")],
            [KeyboardButton(text="🚪 Отвязать аккаунт")]
        ]

    # 🎓 УЧЕНИК
    else:
        keyboard = [
            [KeyboardButton(text="🚀 Открыть BooStudy", web_app=webapp_info), KeyboardButton(text="📅 Мое расписание")],
            [KeyboardButton(text="📝 Очередь ДЗ"), KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="⚙️ Профиль"), KeyboardButton(text="🚪 Отвязать аккаунт")]
        ]

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
