# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🇷🇺 Russian Language Rules
- **Always conduct all internal reasoning and console logs in Russian.**
- **Always present all interactive questions, lists of options, and configuration prompts in Russian.**

## Commands
- **Install Python dependencies:** `pip install -r requirements.txt`
- **Install Node dependencies:** `npm install`
- **Run the app locally:** `python wsgi.py` or `python scripts/run_local.py`
- **Run Celery worker:** `celery -A celery_app worker --loglevel=info`
- **Build CSS:** `powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1` (Windows) or use Tailwind CLI directly. CSS is built from `static/src/input.css` to `static/dist/boostudy.css`.
- **Run all E2E tests:** `npm run test:e2e`
- **Run E2E tests with UI:** `npm run test:e2e:headed`
- **Show test report:** `npm run test:e2e:report`
- **Deploy (Production):** `cd /opt/boostudy && scripts/deploy_blue_green.sh deploy`
- **Rollback (Production):** `cd /opt/boostudy && scripts/deploy_blue_green.sh rollback`

## Architecture Overview
This is a comprehensive monolithic platform for EGE Informatics preparation (Flask/Python + Jinja2 + Tailwind + PostgreSQL/SQLite). The backend handles role-based access control, progress tracking, and integration with external APIs via asynchronous tasks (Celery).

- **`app/`**: The core Flask application directory. Uses an application factory (`app/__init__.py`). It is organized by blueprints which span multiple domains:
  - **Learning loop:** `theory/`, `task_generator/`, `assignments/`, `lessons/`.
  - **Business logic:** `billing/`, `courses/`, `groups/`.
  - **Operations:** `admin/`, `api/`, `qa/`, `remote_admin/`, `chief_tester/`.
  - **Integrations:** `telegram/`, `trainer/`.
- **`core/`**: Shared domain models. Contains `db_models.py` for SQLAlchemy ORM models, `selector_logic.py`, and `audit_logger.py` for audit trails.
- **`data/`**: Ignored by git typically, holds local databases (`boostudy.db`), prototypes, exported files.
- **`scripts/`**: Huge assortment of operational scripts for db fixes, diagnostics, temporary patches, and deployments.
- **`scraper/`**: Contains logic and tasks for fetching/syncing tasks from `kompege.ru`.
- **`trainer_app/`**: A standalone Streamlit-based interactive trainer app that embeds in the main site via iframe.
- **`telegram_bot/` / `urep_bot/`**: Telegram integration logic.
- **`templates/` & `static/`**: Standard Jinja templates and static assets (images, CSS, JS).

## Development Guidelines
- **Always read `AGENTS.md` before making changes.** It contains the strict repository rules.
- **Always sync with Obsidian:** Changes, changelog lines, and bugs must be tracked in the associated Obsidian Vault (`/run/media/eohada/Main/projects/obs_bd/boostudy_bd`). Record task changes in `Задачи/Список_задач.md`.
- **Always record changes in `CHANGELOG.md`:** Any code modifications must be documented immediately with date and time.
- **Deployment Strategy:** Blue-green deployment is strictly mandated for production. Ensure migrations are backward-compatible and only switch traffic via the provided `./scripts/deploy_blue_green.sh` script when `/ready` returns 200.
- **Code Quality:** Ensure all files are generated completely without lazy stubs like `// TODO: implement later`. Perform full impact analysis on any changes to schemas, function signatures, or large structural updates across the codebase.