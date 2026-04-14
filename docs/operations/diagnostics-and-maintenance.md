# Диагностика и обслуживание

## 1. Основные источники operational signal

- HTTP health endpoint `/health`
- application logs
- audit logs
- diagnostic/admin screens
- state базы данных
- состояние batch и Telegram-контуров

Дополнительные специализированные документы:

- `docs/LOGGING.md`
- `docs/DIAGNOSTICS_ACCESS.md`
- `docs/HOW_TO_USE_DIAGNOSTICS.md`
- `docs/QUICK_DIAGNOSTICS.md`
- `docs/DEBUG_GUIDE.md`

## 2. Что проверять при инциденте

### Web-приложение

- запускается ли `wsgi.py`/gunicorn процесс;
- доступен ли `/health`;
- есть ли ошибки в логах;
- отвечает ли база данных;
- не включён ли режим техработ;
- не ломают ли запросы error handlers из `app/__init__.py`.

### Database

- корректен ли `DATABASE_URL`;
- применены ли миграции;
- не произошёл ли drift схемы;
- не попал ли runtime в SQLite fallback вместо production PostgreSQL.

### Integrations

- Telegram webhook;
- trainer iframe и internal trainer API;
- storage/S3;
- Miro/Daily;
- Celery/Redis, если затронуты background flows.

## 3. Бэкапы и восстановление

В репозитории есть отдельные каталоги и скрипты, связанные с бэкапами:

- `backups/`
- `scripts/restore_from_backup.py`

Важно:

- наличие backup-скрипта не означает, что путь восстановления универсален;
- часть скриптов выглядит incident-specific и жёстко привязанной к локальным путям;
- восстановление БД нельзя выполнять без проверки среды, target path и актуальности файла backup.

## 4. Maintenance и административные операции

### Что считается штатным обслуживанием

- применение миграций;
- проверка DB readiness;
- контроль логов и health;
- поддержка storage/upload путей;
- проверка Telegram и trainer интеграций;
- точечные административные операции через `admin`/`remote_admin`.

### Что уже требует повышенного внимания

- любые sync-операции между production и sandbox;
- create/fix/delete scripts в `scripts/`;
- генерация административных токенов;
- ручное восстановление из backup;
- массовые data-fix скрипты.

## 5. Скрипты повышенного риска

Особенно осторожно относитесь к таким типам сценариев:

- удаление данных;
- запись в production БД;
- sandbox-to-prod sync;
- schema/data backfills;
- токены и доступы;
- массовые трансформации репозитория и комментариев.

Примеры high-risk операций перечислены в `docs/modules/scripts-and-tools.md` и `docs/audit/cleanup-register.md`.

## 6. Практический triage чек-лист

### Если упал web flow

1. Проверить `/health`.
2. Проверить конфигурацию окружения.
3. Проверить доступность БД.
4. Проверить свежие логи и трассировки.
5. Понять, локальна ли проблема для конкретного blueprint или системная.

### Если проблема в данных

1. Проверить последние миграции.
2. Проверить, не запускался ли data-fix script.
3. Сравнить sandbox/production при необходимости.
4. Только потом думать о backfill/restore.

### Если проблема в интеграциях

1. Проверить env vars.
2. Проверить сетевую доступность внешнего сервиса.
3. Проверить target endpoint или webhook registration.
4. Проверить, не относится ли проблема к legacy/dormant контуру.

## 7. Cleanup-подход для эксплуатации

В рамках текущего документационного цикла удаление файлов не выполнялось. Вместо этого:

- зафиксированы кандидаты на перенос/архивацию/удаление;
- сохранены legacy-зоны как объекты аудита;
- выстроена каноническая docs-навигация без рискованной агрессивной чистки.

Это безопаснее для живого production-репозитория.

## 8. Рекомендации по дальнейшему operational усилению

- добавить test/lint шаги в CI;
- формализовать post-deploy smoke checklist;
- version-control для server-side deploy scripts;
- пометить prod-sensitive scripts единым шаблоном предупреждений;
- выделить отдельный runbook для recovery/rollback.
