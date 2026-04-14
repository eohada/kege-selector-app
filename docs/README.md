# Документация

Единая точка входа в документацию проекта. Этот каталог теперь разделён по типам знаний: архитектура, запуск, эксплуатация, модули и аудит беспорядка.

## С чего начать

- [HANDBOOK.md](HANDBOOK.md) — единый сводный файл для пользователя, разработчика и оператора.
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) — краткая и актуальная структура репозитория.
- [PROJECT_STRUCTURE_FULL.md](PROJECT_STRUCTURE_FULL.md) — подробная архитектурная карта системы.
- [architecture/system-overview.md](architecture/system-overview.md) — системный обзор, контуры подсистем и основные потоки.
- [setup/local-development.md](setup/local-development.md) — локальный запуск, миграции, CSS, trainer.
- [operations/deploy-and-environments.md](operations/deploy-and-environments.md) — окружения, CI/CD, деплой и риски.
- [audit/README.md](audit/README.md) — состояние документации, legacy-зоны и cleanup-кандидаты.

## Разделы

### Архитектура

- [architecture/README.md](architecture/README.md) — карта архитектурного раздела.
- [architecture/system-overview.md](architecture/system-overview.md) — обзор платформы, сервисов и потоков данных.

### Setup

- [setup/README.md](setup/README.md) — навигация по запуску и конфигурации.
- [setup/local-development.md](setup/local-development.md) — установка, локальная разработка, миграции, trainer, CSS.
- [setup/environment-variables.md](setup/environment-variables.md) — справочник переменных окружения.

### Operations

- [operations/README.md](operations/README.md) — навигация по эксплуатации и поддержке.
- [operations/deploy-and-environments.md](operations/deploy-and-environments.md) — production/sandbox, workflow-файлы, compose, ограничения.
- [operations/diagnostics-and-maintenance.md](operations/diagnostics-and-maintenance.md) — диагностика, бэкапы, обслуживание, опасные сценарии.

### Modules

- [modules/README.md](modules/README.md) — карта модульного слоя документации.
- [modules/platform-modules.md](modules/platform-modules.md) — основное Flask-приложение, blueprints и cross-cutting части.
- [modules/side-services.md](modules/side-services.md) — `trainer_app`, `urep_bot`, `telegram_bot`, `scraper`.
- [modules/scripts-and-tools.md](modules/scripts-and-tools.md) — классификация и риски скриптов.
- [modules/data-and-runtime-artifacts.md](modules/data-and-runtime-artifacts.md) — данные, runtime-артефакты, build/output каталоги.

### Audit

- [audit/README.md](audit/README.md) — итоговый аудит документации и структуры.
- [audit/docs-health.md](audit/docs-health.md) — противоречия, устаревшие места и договорённости.
- [audit/cleanup-register.md](audit/cleanup-register.md) — безопасный реестр кандидатов на перенос, архивирование и возможную очистку.

## Специализированные руководства

### База данных и миграции

- [DATABASE_MIGRATION_QUICK_START.md](DATABASE_MIGRATION_QUICK_START.md)
- [DATABASE_CENTRALIZED_MANAGEMENT.md](DATABASE_CENTRALIZED_MANAGEMENT.md)
- [QUICK_DATABASE_CHECK.md](QUICK_DATABASE_CHECK.md)

### Remote admin и доступы

- [REMOTE_ADMIN_SETUP.md](REMOTE_ADMIN_SETUP.md)
- [REMOTE_ADMIN_GUIDE.md](REMOTE_ADMIN_GUIDE.md)
- [REMOTE_ADMIN_QUICK_SETUP.md](REMOTE_ADMIN_QUICK_SETUP.md)
- [REMOTE_ADMIN_DATABASE_SETUP.md](REMOTE_ADMIN_DATABASE_SETUP.md)
- [ADMIN_ENV_VARIABLES.md](ADMIN_ENV_VARIABLES.md)
- [ADMIN_MIGRATION_CHECKLIST.md](ADMIN_MIGRATION_CHECKLIST.md)
- [RESET_ADMIN_USER.md](RESET_ADMIN_USER.md)

### Диагностика, аудит и техподдержка

- [AUDIT_LOG_DESIGN.md](AUDIT_LOG_DESIGN.md)
- [AUDIT_LOG_SETUP.md](AUDIT_LOG_SETUP.md)
- [LOGGING.md](LOGGING.md)
- [DIAGNOSTICS_ACCESS.md](DIAGNOSTICS_ACCESS.md)
- [HOW_TO_USE_DIAGNOSTICS.md](HOW_TO_USE_DIAGNOSTICS.md)
- [QUICK_DIAGNOSTICS.md](QUICK_DIAGNOSTICS.md)
- [DEBUG_GUIDE.md](DEBUG_GUIDE.md)
- [EDGE_NETWORK_DEBUG.md](EDGE_NETWORK_DEBUG.md)

### Расписание, QA и продуктовые сценарии

- [SCHEDULE_IMPLEMENTATION.md](SCHEDULE_IMPLEMENTATION.md)
- [SCHEDULE_TROUBLESHOOTING.md](SCHEDULE_TROUBLESHOOTING.md)
- [SYNC_LESSONS_GUIDE.md](SYNC_LESSONS_GUIDE.md)
- [USER_SCENARIOS.md](USER_SCENARIOS.md)
- [QA_TEST_SCENARIOS.md](QA_TEST_SCENARIOS.md)
- [QA_PRE_RELEASE_PLATFORM_TEST.md](QA_PRE_RELEASE_PLATFORM_TEST.md)
- [STAGING_TEST_CHECKLIST.md](STAGING_TEST_CHECKLIST.md)
- [PLATFORM_USER_GUIDE.md](PLATFORM_USER_GUIDE.md)
- [PLATFORM_AUDIT_STUDENT_PARENT.md](PLATFORM_AUDIT_STUDENT_PARENT.md)

### Плановые и исследовательские документы

Эти файлы полезны как контекст, но не являются каноническим описанием текущего устройства системы:

- `UPDATE_PLANS.md`
- `ONLINE_SCHOOL_ROADMAP.md`
- `ONLINE_SCHOOL_GAPS.md`
- `ASSIGNMENTS_REFACTOR_PLAN.md`
- `TASK_BASE_AND_LLM_PLAN.md`
- `GIGACHAT_FINETUNING_PLAN.md`
- `ANALYTICS_MODULE_SPEC_ADAPTATION.md`
- `KNOWLEDGE_REQUIREMENTS.md`
- `MMR_QA_GUIDE_OBSIDIAN.md`

## Правила использования docs

- Для текущего устройства проекта сначала сверяйтесь с файлами из разделов `architecture`, `setup`, `operations`, `modules`, `audit`.
- Узкоспециализированные инструкции используйте как дополнение, а не как первичный источник истины.
- Если документ описывает старый `app.py`, старые URL или старую предметную область, проверяйте его по `audit/docs-health.md`.
