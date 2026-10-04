# Telegram-бот на сервере: polling и защищённый webhook

В production основной runtime — отдельный `telegram-poller`; отдельный legacy
контейнер `bot_prod` с `urep_bot/run_bot.py` не используется. Если в логах было:

`can't open file '/app/urep_bot/run_bot.py'`

— обновите код с репозитория (в репозитории снова есть заглушка `run_bot.py`) **или** лучше сразу уберите лишний сервис.

## Что сделать

1. **Откройте** `docker-compose.yml` на сервере (в каталоге проекта, например `/opt/boostudy`).
2. **Удалите или закомментируйте** весь блок сервиса с именем вроде `bot_prod`, `bot`, у которого в `command` указано `urep_bot/run_bot.py`.
3. **Перезапустите** стек: `docker compose up -d` (или ваш способ).
4. Для polling убедитесь, что запущен только один `telegram-poller` для основного
   токена. Pending updates не удаляйте без явной операции восстановления.
5. Webhook — альтернативная схема: настройте `TELEGRAM_WEBHOOK_SECRET`, задайте
   Telegram secret header и вызывайте `/webhook/telegram/set` только с
   `X-Bot-Token`.

## Редирект на логин (302) для `/webhook/telegram`

Если в логах видно `require_login: redirecting ... from /webhook/telegram to login`,
глобальная проверка авторизации мешала Telegram. В коде пути `/webhook/*` и
`/tg-app/*` исключены из обязательного входа (см. `app/utils/hooks.py`), но
webhook всё равно проверяет `X-Telegram-Bot-Api-Secret-Token`.
