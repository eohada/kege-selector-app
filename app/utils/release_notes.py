"""Lightweight release notes surfaced in the product and Telegram bot."""
from __future__ import annotations

RELEASE_VERSION = '2026.06.06'

RELEASE_TITLE = 'Релизная версия BooStudy'

RELEASE_BULLETS = [
    'Ученический кабинет стал короче и полезнее: ближайший урок, долги, тариф и быстрые действия собраны вместе.',
    'Админка получила сводку, поиск ученика и более информативные карточки.',
    'Команды /help и /status теперь ведут к следующему действию, а не просто показывают текст.',
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
        'Это уже ближе к полноценному рабочему продукту: меньше кликов, больше контекста, понятнее следующий шаг.',
    ]
    return '\n'.join(lines)

