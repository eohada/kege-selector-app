# Деплой и окружения

## 1. Окружения

Репозиторий явно различает как минимум четыре режима:

- `local`
- `development`
- `sandbox`
- `production`

Фактическое поведение зависит от комбинации:

- `ENVIRONMENT`
- `IS_SANDBOX`
- DB URL переменных
- наличия секретов и интеграционных токенов

## 2. Production и sandbox модель

### Production

Production deploy описан через ручной GitHub Actions workflow `.github/workflows/deploy.yml`.

Логика:

1. Проверка SSH secrets.
2. SSH на сервер.
3. `cd /opt/boostudy`
4. `git pull origin main`
5. `docker compose up -d --build`
6. `docker image prune -f`

### Sandbox

Sandbox deploy описан в `.github/workflows/deploy_sandbox.yml`.

Логика:

1. Автозапуск на push в `main` или ручной запуск.
2. SSH c retry-механикой.
3. Удалённый вызов `/opt/boostudy/deploy_sandbox.sh`.

Это означает, что часть реального operational knowledge живёт не только в репозитории, но и на сервере.

## 3. Что есть в репозитории

### Источники правды

- `Procfile`
- `.github/workflows/deploy.yml`
- `.github/workflows/deploy_sandbox.yml`
- `.env.example`
- `docker-compose.example.yml`
- `DEPLOY_TELEGRAM_WEBHOOK.md`

### Что важно понимать

- `docker-compose.example.yml` — пример, а не готовая production-конфигурация;
- в репозитории не найден канонический `Dockerfile`;
- часть deploy-логики вынесена во внешние server-side скрипты;
- CI/CD покрывает доставку, но не покрывает качество через test/lint pipeline.

## 4. Инфраструктурные компоненты

По документам и конфигам проект может использовать:

- web runtime на gunicorn;
- PostgreSQL;
- Redis;
- Celery worker;
- MinIO / S3-compatible storage;
- Telegram webhook;
- Streamlit trainer;
- возможно отдельные server-side scripts и volumes.

## 5. Docker compose: текущее состояние

`docker-compose.example.yml` показывает intended topology:

- `web`
- `db`
- `minio`
- `redis`
- `celery-worker`

Но есть ограничения:

- `command: gunicorn ...` в compose-файле placeholder;
- `build: .` не поддержан каноническим `Dockerfile` в репозитории;
- это нельзя считать self-contained production runbook.

## 6. GitHub Actions: операционные риски

### Что уже хорошо

- production deploy отделён в ручной workflow;
- sandbox deploy имеет retry-логику для SSH;
- sandbox workflow документирует сетевые проблемы GitHub-hosted runners.

### Чего не хватает

- автоматических тестов перед деплоем;
- линтинга;
- smoke checks после деплоя;
- централизованного описания rollback-процедуры;
- versioned server-side deploy scripts внутри репозитория.

## 7. Telegram в production

Главный production Telegram-бот не должен жить отдельным контейнером, если использовать webhook-модель, описанную в `DEPLOY_TELEGRAM_WEBHOOK.md`.

Практический вывод:

- основной канал Telegram интеграции обслуживается внутри web runtime;
- отдельный standalone `telegram_bot/` решает другую задачу и не должен смешиваться с production webhook-контуром.

## 8. Рекомендованный operational checklist перед деплоем

### Перед деплоем

- проверить, какие файлы реально менялись;
- убедиться, что нет несогласованных миграций;
- проверить env vars для целевой среды;
- убедиться, что не планируется случайный запуск опасных scripts;
- при изменениях trainer/telegram/storage проверить связанные integration settings.

### После деплоя

- открыть `/health`;
- проверить основные dashboard flows;
- проверить критичные административные и учебные маршруты;
- проверить webhook/integration сценарии, если релиз их затрагивал;
- при необходимости проверить worker/log channels.

## 9. Документационные ограничения текущего состояния

Сегодня реальная эксплуатационная модель распределена между:

- GitHub workflow-файлами;
- `.env.example`;
- специализированными docs;
- внешними server-side script-ами;
- фактическим кодом `app/__init__.py`.

Из-за этого операционные знания нельзя брать из одного старого md-файла в изоляции.

## 10. Что считать каноническим

Для общего понимания деплоя и окружений используйте этот документ как входную точку.

Затем сверяйтесь с:

- `docs/setup/environment-variables.md`
- `docs/operations/diagnostics-and-maintenance.md`
- `docs/operations/blue-green-deploy.md`
- `docs/modules/side-services.md`
- профильным специализированным runbook из `docs/`

## 11. Blue-Green направление

Новая production-схема должна двигаться к модели:

- `web_blue` / `web_green` поднимаются рядом;
- `/ready` проверяет PostgreSQL, Redis, миграции и Socket.IO;
- Nginx переключает новые входящие запросы на готовый цвет;
- старому web дают короткое drain-окно;
- PostgreSQL остаётся source of truth, Redis хранит быстрый workspace snapshot;
- Celery worker/beat обновляются осторожно после web-switch, без запуска двух beat одновременно;
- rollback выполняется переключением Nginx на предыдущий готовый цвет.

Практический runbook: `docs/operations/blue-green-deploy.md`.
