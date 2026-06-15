# Blue-Green деплой BooStudy

Цель: новая версия поднимается рядом со старой, проходит `/ready`, после этого Nginx переключает новые запросы на новую версию. Пользовательское состояние воркспейса живёт вне процесса приложения: PostgreSQL остаётся источником истины, Redis хранит быстрый live snapshot.

## Что уже должно быть готово

- `/health` отвечает, что приложение живо.
- `/ready` проверяет PostgreSQL, Redis, миграции и Socket.IO.
- Workspace autosave пишет live snapshot в Redis и финальное состояние в PostgreSQL.
- Миграции перед переключением только expand-only: добавлять поля/таблицы можно, удалять и переименовывать — отдельным релизом после того, как старая версия уже не используется.

## Файлы

- `docker-compose.bluegreen.example.yml` — пример двух web-сервисов: `web_blue` и `web_green`.
- `deploy/nginx/boostudy-bluegreen.conf` — пример Nginx-конфига с переключаемым upstream.
- `scripts/deploy_blue_green.sh` — deploy/rollback/status helper.

## Подготовка сервера

1. Скопировать пример compose:

```bash
cd /opt/boostudy
cp docker-compose.bluegreen.example.yml docker-compose.bluegreen.yml
```

2. Проверить `.env`: `DATABASE_URL`, `SECRET_KEY`, `BOT_TOKEN`, `REDIS_URL`/`CELERY_BROKER_URL`, upload roots.

3. Подключить Nginx-конфиг.

Пример активного upstream-файла:

```bash
mkdir -p /etc/nginx/snippets
printf 'proxy_pass http://127.0.0.1:8001;\n' > /etc/nginx/snippets/boostudy-active-upstream.conf
nginx -t && nginx -s reload
```

4. Сделать скрипт исполняемым:

```bash
chmod +x scripts/deploy_blue_green.sh
```

## Обычный деплой

```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh deploy
```

Что делает скрипт:

1. Определяет активный цвет.
2. Обновляет код из `main`.
3. Собирает неактивный web-сервис.
4. Запускает `flask db upgrade` как expand-only migrations.
5. Поднимает неактивный web-сервис.
6. Ждёт успешный `/ready`.
7. Переключает Nginx на новый порт.
8. Обновляет Celery worker/beat одним экземпляром после переключения web.
9. Даёт старой версии время на drain.
10. Останавливает старый web-сервис.

## Rollback

```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh rollback
```

Rollback переключает Nginx на предыдущий цвет без rebuild.

Важно: после `DRAIN_SECONDS` старый web-сервис останавливается. Поэтому rollback остаётся быстрым, но уже не мгновенным: скрипт заново поднимает предыдущий web через `docker compose up -d`, ждёт `/ready`, и только потом переключает Nginx.

В первые 10-15 минут после релиза не делайте cleanup старого образа/контейнера вручную. Это сохраняет быстрый rollback без пересборки.

## Проверка статуса

```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh status
```

## Важные правила

- Redis не является источником истины. Если Redis упал, workspace должен продолжать сохраняться в PostgreSQL, но reconnect станет менее удобным.
- Beat нельзя держать в двух активных копиях: это создаст дубли фоновых задач и уведомлений.
- Celery payload должен оставаться совместимым между старой и новой версией, потому что задачи могли быть поставлены старым кодом, а выполниться новым.
- Socket.IO события нужно менять совместимо: новый backend не должен ломать старый frontend во время короткого переходного окна.
- Rollback после drain требует повторного запуска предыдущего web-сервиса, но не требует rebuild.
