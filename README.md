# Платформа подбора заданий КЕГЭ

Веб-приложение для подготовки к ЕГЭ по информатике: управление учениками, уроками, генератор заданий КЕГЭ, расписание и аналитика.

**Стек:** Flask (Python), PostgreSQL / SQLite, Jinja2, RBAC.

- Установка и запуск: см. `requirements.txt`, точка входа — фабрика `app.create_app()`. Локально: `python wsgi.py` или `python scripts/run_local.py` — страница тарифов: http://127.0.0.1:5000/billing/plans/public
- Структура проекта: [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).
- Документация: каталог [docs/](docs/).

## Сборка CSS (Tailwind без npm)

CSS собирается в `static/dist/boostudy.css` из `static/src/input.css`.

На Windows используем standalone Tailwind CLI (бинарник скачивается локально, в git не коммитим).

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1
```

