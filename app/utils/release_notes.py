"""Lightweight release notes surfaced in the product and Telegram bot."""
from __future__ import annotations

RELEASE_VERSION = '2026.06.06'

RELEASE_TITLE = 'Обновление BooStudy'

RELEASE_BULLETS = [
    'Компактный личный кабинет ученика: собрали всё самое важное (ближайший урок, долги по домашке, текущий тариф и панель быстрых действий) на одном главном экране.',
    'Улучшенная панель администратора: добавили общую сводную статистику, быстрый поиск по ученикам и сделали карточки более информативными.',
    'Интерактивные команды в Telegram-боте: теперь /help и /status не просто присылают текст, а сразу предлагают кнопки для перехода к нужным действиям.',
]


def build_release_notes_text() -> str:
    lines = [
        f'🆕 <b>{RELEASE_TITLE}</b>',
        f'Версия: <code>{RELEASE_VERSION}</code>',
        '',
    ]
    for bullet in RELEASE_BULLETS:
        lines.append(f'• {bullet}')
    lines += [
        '',
        'Мы постарались сократить лишние клики и добавить больше контекста на ключевых экранах, чтобы работать с платформой было проще и приятнее.',
    ]
    return '\n'.join(lines)

