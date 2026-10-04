# Telegram: manual QA

Проверять на тестовом стенде после запуска web, Celery worker, Celery beat,
`telegram-poller` и отдельного `telegram-qa-poller`.

1. `/start` идемпотентен.
2. Mini App принимает только валидный `Telegram.WebApp.initData`.
3. Ученик видит свои задания, родитель — только подтверждённых детей, преподаватель — свою очередь.
4. Creator переключает Teacher/Creator context; обычный пользователь не может повысить контекст.
5. Одно in-app уведомление создаёт одну outbox-запись.
6. Успех даёт `sent` и `UserNotification.telegram_sent=true`; 429/5xx дают retry; постоянная ошибка — failed.
7. Тихие часы откладывают доставку, а не теряют её.
8. Без `X-Telegram-Bot-Api-Secret-Token` webhook отвечает 403, а payload больше
   256 KiB — 413; legacy webhook без настроенного секрета отключён.
9. Повторный запуск poller не удаляет pending updates при
   `TELEGRAM_*_POLLING_DROP_PENDING_UPDATES=false`.
10. `/webhook/telegram/status` с `X-Bot-Token` показывает конфигурацию, Redis и
    статусы outbox, но не возвращает токены.
