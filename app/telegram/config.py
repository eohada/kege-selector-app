"""Telegram runtime config used inside the main app package."""
from __future__ import annotations

import os

BOT_TOKEN = os.environ.get('BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN') or ''
BOT_INTERNAL_TOKEN = os.environ.get('BOT_INTERNAL_TOKEN', '').strip()
APP_URL = (os.environ.get('APP_URL') or 'https://boostudy.ru/').strip()
APP_OPEN_URL = (os.environ.get('APP_OPEN_URL') or 'https://boostudy.ru/login').strip()
