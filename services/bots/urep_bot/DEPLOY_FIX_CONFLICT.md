# Исправление Conflict: "only one bot instance running"

## Проблема
```
telegram.error.Conflict: Conflict: terminated by other getUpdates request; 
make sure that only one bot instance is running
```

Telegram разрешает только **одно** long-polling соединение на один BOT_TOKEN. Если запущено 2+ экземпляра — они конфликтуют.

## Решение

### 1. Одна реплика бота в docker-compose

Открой `/opt/boostudy/docker-compose.yml` и для сервиса бота добавь/проверь:

```yaml
services:
  bot_prod:   # или как у тебя назван сервис бота
    # ...
    deploy:
      replicas: 1
```

Если используется `docker-compose scale` — не масштабируй бота.

### 2. Убрать устаревший version (предупреждение)

В начале docker-compose.yml удали строку:
```yaml
version: "3.8"   # <-- удалить
```

Docker Compose v2+ игнорирует version, он устарел.

### 3. Перезапуск с одним экземпляром

```bash
cd /opt/boostudy
docker compose down
docker compose up -d --build
```

Проверь, что контейнер бота один:
```bash
docker compose ps
# Должен быть один bot_prod-1 (или аналогично)
```

### 4. Если конфликт сохраняется

- Убедись, что бот не запущен вручную (ssh + `python urep_bot/run_bot.py`) одновременно с Docker.
- Проверь другие среды: staging/prod не должны использовать один и тот же BOT_TOKEN.
- Advisory lock (в run_bot.py) блокирует второй экземпляр, если они оба подключаются к **одной** PostgreSQL. Если боты используют разные БД — lock не сработает.
