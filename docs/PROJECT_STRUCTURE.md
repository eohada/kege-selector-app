# Структура проекта

Краткая и актуальная карта репозитория. Для подробного описания модулей см. `PROJECT_STRUCTURE_FULL.md`.

## Общая схема

Проект состоит из одного основного Flask-приложения, нескольких связанных подсистем и большого числа служебных скриптов.

```text
kege_selector_app_current/
├── app/                   # Основное Flask-приложение
├── core/                  # Доменные модели и общее ядро
├── templates/             # Jinja-шаблоны
├── static/                # JS/CSS/изображения/сторонние ассеты
├── scripts/               # Административные, миграционные, диагностические скрипты
├── scraper/               # Логика парсинга и синхронизации банка заданий
├── trainer_app/           # Отдельный Streamlit-тренажёр
├── urep_bot/              # Shared utilities для production Telegram webhook
├── telegram_bot/          # Отдельный бот-трекер репортов
├── data/                  # Локальные данные, прототипы, экспортируемые артефакты
├── docs/                  # Каноническая документация проекта
├── migrations/            # Alembic / Flask-Migrate
├── wsgi.py                # Основная точка входа web-приложения
├── celery_app.py          # Точка входа Celery
├── requirements.txt       # Основные Python-зависимости
├── .env.example           # Шаблон переменных окружения
└── docker-compose.example.yml
```

## Главные части системы

### `app/`

Основное Flask-приложение. Здесь находятся:

- фабрика приложения в `app/__init__.py`;
- зарегистрированные blueprints;
- cross-cutting части: analytics, storage, tasks, utils, logging, limiter;
- обработчики ошибок, интеграции, фоновые thread-workers.

Ключевые группы blueprints:

- базовый UX: `auth`, `main`;
- учебный контур: `students`, `lessons`, `assignments`, `schedule`, `theory`, `task_generator`;
- организационный контур: `courses`, `groups`, `parents`, `billing`, `library`;
- операционный контур: `admin`, `remote_admin`, `api`, `qa`, `chief_tester`;
- интеграции: `trainer`, `uploads`, `storage`, `telegram`.

### `core/`

Единое ядро доменной модели и общей бизнес-логики.

- `db_models.py` — SQLAlchemy-модели;
- `selector_logic.py` — логика подбора заданий;
- `audit_logger.py`, `audit_decorators.py` — аудит действий.

### `trainer_app/`

Отдельный Streamlit-интерфейс тренажёра, который встраивается в платформу через iframe и вызывает внутренние `/internal/trainer/*` API основного приложения.

### `urep_bot/`

Shared utilities для production Telegram-интеграции. В production бот работает не отдельным long-polling сервисом, а внутри Flask через webhook `POST /webhook/telegram`.

### `telegram_bot/`

Независимый Telegram-бот для трекинга репортов тестировщиков. Использует собственную SQLite-базу и не является частью основного request-cycle платформы.

### `scripts/`

Большая коллекция служебных скриптов:

- bootstrap и настройка окружения;
- миграции и data-fixes;
- диагностика и сравнение сред;
- скрапинг и импорт контента;
- тестовые harness-скрипты;
- опасные одноразовые операции.

### `scraper/`

Парсинг и синхронизация банка заданий, в том числе работа с `kompege.ru`, whitelist-политикой и upsert-логикой в основной task bank.

## Корневые точки входа

- `wsgi.py` — web entrypoint для локального запуска.
- `celery_app.py` — Celery entrypoint.
- `Procfile` — production-style запуск через gunicorn.
- `scripts/run_local.py` — локальный helper.

Важно: канонической web-точкой входа является `wsgi.py`, а не исторический `app.py`.

## Runtime и служебные каталоги

- `data/` — прототипы, reference-данные, локальные БД, экспортные артефакты;
- `backups/` — бэкапы БД;
- `logs/` — логи;
- `exports/` — генерируемые выгрузки;
- `tools/` — локальные tool-бинарники, например Tailwind CLI.

## Legacy и шум

В репозитории есть зоны, которые не являются канонической частью текущего приложения, но важны для аудита:

- `legacy_backup/` — старые шаблоны и куски логики;
- `boostudy2.0_examples/` — макеты/демо-экраны;
- `qa_testing_files_md/` — markdown-слепки для QA;
- разрозненные markdown-файлы в корне.

Подробности и рекомендации по ним вынесены в `docs/audit/cleanup-register.md`.

