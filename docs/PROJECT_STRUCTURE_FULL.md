# Полная структура проекта

Подробная архитектурная карта репозитория. Этот документ описывает текущее устройство системы, а не исторические планы по рефакторингу.

## 1. Назначение системы

Проект решает несколько связанных задач в рамках одной платформы:

- ведение учеников, уроков, домашних и проверочных работ;
- управление учебным контентом, теорией и банком заданий;
- генерация и подбор заданий КЕГЭ;
- аналитика прогресса;
- Telegram-интеграции и Mini App;
- отдельный тренажёр на Streamlit;
- эксплуатационные и администраторские сценарии.

Предметный фокус текущего README и основного кода: ЕГЭ по информатике. Упоминания математики в части старых документов относятся к legacy-контексту и не должны считаться каноническим описанием продукта.

## 2. Точки входа и процессы

### Web

- `wsgi.py` — основная точка входа Flask-приложения.
- `app/__init__.py` — фабрика `create_app()`, где инициализируются конфиг, DB, CSRF, login manager, rate limiter, storage, audit, blueprints, SocketIO и часть фоновых workers.
- `Procfile` — production-style команда через gunicorn.

### Background

- `celery_app.py` — точка входа Celery.
- В `app/__init__.py` также поднимаются thread-based workers для уведомлений и автозавершения уроков.

### Дополнительные сервисы

- `trainer_app/app.py` — Streamlit-тренажёр.
- `app/telegram/webhook.py` — Telegram webhook внутри основного Flask-приложения.
- `telegram_bot/bot.py` — отдельный бот-трекер репортов.

## 3. Корневая структура репозитория

| Путь | Назначение |
|------|------------|
| `app/` | Основное Flask-приложение и все HTTP-модули |
| `core/` | Ядро доменной модели и общей бизнес-логики |
| `templates/` | Jinja2-шаблоны |
| `static/` | CSS, JS, изображения, сторонние front-end ассеты |
| `scripts/` | Служебные скрипты разного уровня риска |
| `scraper/` | Логика парсинга и синхронизации task bank |
| `trainer_app/` | Отдельный Streamlit-тренажёр |
| `urep_bot/` | Shared utilities для production Telegram webhook |
| `telegram_bot/` | Отдельный Telegram-бот для репортов тестировщиков |
| `data/` | Данные, reference-материалы, локальные БД, JSON-артефакты |
| `backups/` | Бэкапы БД |
| `logs/` | Логи |
| `exports/` | Экспортные файлы и выгрузки |
| `docs/` | Каноническая документация |
| `migrations/` | Alembic / Flask-Migrate |
| `.github/workflows/` | CI/CD workflow-файлы |

## 4. Устройство основного Flask-приложения

### 4.1 Shell приложения

`app/__init__.py` выполняет роль orchestration-слоя:

- собирает `Flask(...)` с root-level `templates/` и `static/`;
- конфигурирует DB URL, `SECRET_KEY`, upload roots, S3, Miro, Daily, sandbox/demo flags;
- инициализирует `db`, `migrate`, `csrf`, `login_manager`, `limiter`, `audit_logger`, storage;
- регистрирует blueprints;
- подключает SocketIO для lesson room и presence;
- настраивает глобальные Jinja filters и error handlers;
- запускает встроенные фоновые workers.

Связанные cross-cutting файлы:

- `app/logging_core.py`
- `app/limiter.py`
- `app/constants.py`
- `app/utils/hooks.py`
- `app/utils/jinja_filters.py`

### 4.2 Data layer

Основная схема данных живёт в `core/db_models.py`.

Пакет `app/models/` не содержит отдельного слоя моделей, а переэкспортирует `db` и доменные сущности из `core`.

Это важно для документации и онбординга: `app/models` — convenience layer, а не источник истины.

### 4.3 Cross-cutting подсистемы

| Путь | Роль |
|------|------|
| `app/utils/` | Хуки, миграционные helper-функции, Jinja filters, trainer tokens, cross-env login и прочие shared utilities |
| `app/analytics/` | Analytics engine и related config |
| `app/storage/` | Абстракция файлового хранилища и S3/MinIO-интеграция |
| `app/tasks/` | Именованные background/job entrypoints для уведомлений, Telegram-рассылок, код-чека и пр. |

## 5. Blueprints основного приложения

Ниже перечислены blueprints, реально регистрируемые в `create_app()`.

### 5.1 Базовый UX и доступ

| Blueprint | Назначение |
|-----------|------------|
| `auth` | Логин, logout, профиль, RBAC-вспомогательные сценарии |
| `main` | Главная, dashboard, health, presence, часть общих экранов |

### 5.2 Учебный контур

| Blueprint | Назначение |
|-----------|------------|
| `students` | Ученики, профили, статистика, аналитика |
| `lessons` | Жизненный цикл урока, classroom, classwork, homework, review |
| `assignments` | Работы, submissions, grading, autosave |
| `schedule` | Календарь, повторяемые слоты, ICS |
| `task_generator` | Генерация и подбор заданий для уроков |
| `templates_manager` | Шаблоны уроков/работ |
| `theory` | Теория, учебные материалы, управление блоками теории |

### 5.3 Организационный контур

| Blueprint | Назначение |
|-----------|------------|
| `courses` | Курсы и модули курсов |
| `groups` | Группы учеников и массовые операции |
| `parents` | Кабинет и API для родителей |
| `library` | Библиотека материалов и шаблонов |
| `billing` | Тарифы, подписки, планы |
| `reminders` | Пользовательские напоминания |
| `notifications` | In-app уведомления |

### 5.4 Операционный и административный контур

| Blueprint | Назначение |
|-----------|------------|
| `admin` | Админка, аудит, maintenance, управление пользователями и тестерами |
| `remote_admin` | Отдельный remote-admin UI и API |
| `api` | JSON API, глобальный поиск, аналитика, Telegram-link flows |
| `qa` | QA god mode, манипуляции средами, impersonation |
| `chief_tester` | Кабинет главного тестировщика |

### 5.5 Интеграции и вспомогательные каналы

| Blueprint | Назначение |
|-----------|------------|
| `trainer` | UI `/trainer` и внутренние `/internal/trainer/*` endpoints |
| `uploads` | Публичная/внутренняя отдача файлов и upload-сценарии |
| `storage` | HTTP-точки поверх storage layer |
| `telegram` | Webhook для production Telegram-бота |
| `tg_app` | Telegram Mini App HTML + JSON API |

## 6. Незарегистрированные или dormant HTTP-пакеты

Внутри `app/` есть пакеты, которые выглядят как blueprints, но не регистрируются в `create_app()`:

- `app/kege_generator/`
- `app/designer/`
- `app/onboarding/`
- `app/rubrics/`

Это не обязательно мёртвый код, но эти зоны нужно считать потенциально частично отключёнными, историческими или зависящими от других entrypoints. При изменениях стоит отдельно проверять, используются ли они реально.

## 7. Side-сервисы и интеграции

### `trainer_app/`

Отдельный Streamlit UI, который:

- встраивается через iframe в `/trainer`;
- ходит в основной Flask по `/internal/trainer/*`;
- зависит от `PLATFORM_BASE_URL`, `TRAINER_URL`, `TRAINER_SHARED_SECRET`, `GIGACHAT_*`;
- не является полностью изолированным микросервисом, так как импортирует части основного репозитория.

### `urep_bot/`

Production Telegram integration utilities:

- webhook живёт внутри Flask;
- shared DB/session helpers используются основным приложением;
- `run_bot.py` — legacy shim, а не основной production entrypoint.

### `telegram_bot/`

Отдельный бот для репортов тестировщиков:

- запускается независимо;
- использует собственную SQLite-базу;
- не является частью основного учебного request/response потока.

### `scraper/`

Слой синхронизации банка заданий:

- Playwright/API ingestion;
- whitelist-логика;
- upsert в основную таблицу задач;
- используется из `scripts/`, а не как отдельное веб-приложение.

## 8. Скрипты и операционные утилиты

`scripts/` содержит большой объём операций разного класса:

- bootstrap и setup;
- миграции и schema/data fixes;
- диагностику и сравнение сред;
- scraping и import/export;
- ручные тестовые harness-скрипты;
- опасные одноразовые операции.

Для безопасной работы с ними важно разделять:

- повторяемые runbook-сценарии;
- скрипты, которые можно запускать локально;
- prod-sensitive скрипты;
- одноразовые incident-driven инструменты.

См. `modules/scripts-and-tools.md`.

## 9. Данные и runtime-артефакты

### Постоянные и reference-данные

- `data/reference_prototypes/`
- `data/reference_solutions/`
- `trainer_knowledge/`

### Runtime и генерируемые артефакты

- локальные `.db` в `data/`;
- `backups/*.db`;
- `logs/`;
- `exports/*.jsonl`, `exports/*.csv`;
- `data/rag_hints/`;
- `debug_out/`;
- `tools/tailwindcss/tailwindcss.exe`.

Часть этих путей должна существовать только локально или в окружении сервера и не является исходным кодом продукта.

## 10. CI/CD и окружения

Репозиторий содержит два workflow-файла:

- `.github/workflows/deploy.yml` — ручной production deploy по SSH;
- `.github/workflows/deploy_sandbox.yml` — auto/manual sandbox deploy по SSH.

При этом:

- в репозитории нет полноценного test/lint CI;
- `docker-compose.example.yml` является иллюстративным и не запускается как production truth out of the box;
- в дереве репозитория не найден канонический `Dockerfile`.

## 11. Legacy и документационный долг

Отдельно нужно держать в фокусе следующие зоны:

- `legacy_backup/` — старые шаблоны и части модульной логики;
- `boostudy2.0_examples/` — примеры/макеты экранов;
- `qa_testing_files_md/` — markdown-слепки для QA-анализа;
- root-level markdown-файлы вне `docs/`.

Эти области не должны считаться актуальной архитектурой без дополнительной проверки.

## 12. Архитектурные выводы

1. Это не набор независимых сервисов, а один крупный Flask-монолит с несколькими тесно связанными спутниками.
2. Самые чувствительные зоны для сопровождения: `app/__init__.py`, `core/db_models.py`, `app/lessons/routes.py`, `app/api/routes.py`, `app/admin/routes.py`, `app/trainer/routes.py`, Telegram-контур и `scripts/`.
3. Документация должна разделять:
   - каноническое текущее устройство;
   - специализированные runbooks;
   - исторические планы и legacy-материалы.
