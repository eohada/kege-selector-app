# Платформа подбора заданий КЕГЭ

Платформа для подготовки к ЕГЭ по информатике: управление учениками, уроками, заданиями, теорией, расписанием, аналитикой, Telegram-интеграциями и встраиваемым тренажёром.

## Что находится в этом репозитории

- Основное Flask-приложение с Jinja-интерфейсом и RBAC.
- База данных PostgreSQL в production и SQLite для локальной разработки.
- Встроенные интеграции: Telegram webhook, Mini App, Miro, S3/MinIO, Celery/Redis.
- Отдельный Streamlit-тренажёр в `trainer_app/`.
- Большой набор служебных и миграционных скриптов в `scripts/`.

## Быстрый старт

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Скопировать `.env.example` в `.env` и заполнить ключевые переменные.

3. Запустить приложение:

```bash
python wsgi.py
```

Альтернатива для локального запуска:

```bash
python scripts/run_local.py
```

Основная локальная точка входа: `http://127.0.0.1:5000/`.

## Сборка CSS

CSS собирается в `static/dist/boostudy.css` из `static/src/input.css`.

На Windows используется standalone Tailwind CLI:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1
```

## Карта документации

Верхнеуровневая документация находится в `docs/`.

- Единый handbook: [docs/HANDBOOK.md](docs/HANDBOOK.md)
- Стартовая страница: [docs/README.md](docs/README.md)
- Краткая структура проекта: [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)
- Подробная архитектура: [docs/PROJECT_STRUCTURE_FULL.md](docs/PROJECT_STRUCTURE_FULL.md)
- Архитектурный обзор: [docs/architecture/system-overview.md](docs/architecture/system-overview.md)
- Локальная разработка и запуск: [docs/setup/local-development.md](docs/setup/local-development.md)
- Окружения и деплой: [docs/operations/deploy-and-environments.md](docs/operations/deploy-and-environments.md)
- Аудит документации и cleanup-кандидатов: [docs/audit/README.md](docs/audit/README.md)

## Ключевые точки входа

- Web app: `wsgi.py`
- Flask factory: `app/__init__.py`
- Local helper: `scripts/run_local.py`
- Celery: `celery_app.py`
- Streamlit trainer: `trainer_app/app.py`

## Важное замечание

Репозиторий исторически содержит legacy-артефакты, разрозненные инструкции и экспериментальные каталоги. Каноническая навигация и актуальное описание системы теперь поддерживаются через `docs/README.md`; не стоит использовать случайные markdown-файлы в корне как единственный источник истины без сверки с `docs/`.

