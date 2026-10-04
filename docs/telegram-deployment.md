# Telegram: deployment checklist

- применить `alembic -c migrations/alembic.ini upgrade head`;
- проверить `/ready`, PostgreSQL и Redis;
- запустить web, Celery worker и Celery beat;
- запустить `telegram-poller` для основного бота и `telegram-qa-poller` для QA-бота;
- убедиться, что beat запускает `telegram-delivery-dispatch` и `telegram-delivery-recovery`;
- выполнить `docs/telegram-manual-qa.md`;
- контролировать `TelegramDeliveries` по статусам и `last_error`.

Production configuration must set `ENVIRONMENT=production` for `web_prod`,
`celery-worker`, `celery-beat`, and the Telegram pollers. `APP_URL` and
`BASE_URL` must be `https://boostudy.ru`; do not inherit a local `.env` value.
The main token is read from `MAIN_BOT_TOKEN` (or the compatibility aliases
`BOT_TOKEN`/`TELEGRAM_BOT_TOKEN`), the optional QA token from
`QA_BOT_TOKEN`/`TELEGRAM_TESTERS_BOT_TOKEN`, and `TELEGRAM_BOT_USERNAME` must
match the verified main bot username. `BOT_INTERNAL_TOKEN` is mandatory.

The polling services are the canonical Telegram consumers. Keep
`TELEGRAM_POLLING_DROP_PENDING_UPDATES=false`; set it to `true` only for an
explicit recovery operation. Do not run webhook and polling consumers for the
same bot token at the same time.

The legacy `/api/webhooks/main-bot` and `/api/webhooks/qa-bot` routes are
disabled unless their per-bot secret (`TELEGRAM_MAIN_WEBHOOK_SECRET` or
`TELEGRAM_QA_WEBHOOK_SECRET`) is explicitly configured. They process updates
synchronously and return an error on handler failure.

Webhook mode is an alternative, not the default. It requires
`TELEGRAM_WEBHOOK_SECRET`, Telegram's `X-Telegram-Bot-Api-Secret-Token`, and
the protected `/webhook/telegram/set` operation. `/webhook/telegram/status`
shows configuration, Redis reachability and outbox counts without exposing
tokens or calling Telegram on every readiness request.

If a token was ever present in source, shell history, or an artifact, rotate it
through BotFather before production rollout. Rotation is intentionally manual:
create a new token, update the secret store, restart only after the new token
has been validated, then revoke the old token.

`TELEGRAM_DELIVERY_DISABLED=1` временно отключает dispatcher и recovery; частоты задаются `TELEGRAM_DELIVERY_BEAT_SECONDS` и `TELEGRAM_DELIVERY_RECOVERY_SECONDS`. Outbox вручную не удалять.
