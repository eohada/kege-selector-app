# urep_bot — Shared Utilities

This package provides shared utilities for the BooStudy Telegram integration (webhook mode via Flask).

## Files

- `**bot.py**` — DB query helpers used by `app/telegram/handlers.py`: `get_user_by_chat_id`, `get_student_by_email`, `get_lessons`, `build_lessons_text`, `build_stats_text`, etc.
- `**config.py**` — Bot configuration: `APP_URL`, `APP_OPEN_URL`, `BOT_TOKEN`, etc.
- `**db.py**` — SQLAlchemy session factory (`get_session`, `close_session`) for the bot's background asyncio thread.

## Architecture

The bot runs in webhook mode as part of the main Flask application:

- Webhook endpoint: `POST /webhook/telegram`
- Handlers: `app/telegram/handlers.py`
- Notifications: `app/telegram/notifications.py`
- Mini App API: `app/telegram/mini_app.py`

The standalone polling runner (`run_bot.py`) has been removed — use the Flask webhook instead.