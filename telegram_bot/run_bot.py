#!/usr/bin/env python3
"""
Скрипт для запуска Telegram-бота

Использование:
    python telegram_bot/run_bot.py

Или через модуль:
    python -m telegram_bot.bot
"""
import sys
import os

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_bot.bot import main

if __name__ == '__main__':
    main()