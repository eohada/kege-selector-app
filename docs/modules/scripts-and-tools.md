# Скрипты и инструменты

## 1. Назначение раздела

Каталог `scripts/` слишком большой и разнотипный, чтобы воспринимать его как единый безопасный toolbox. Здесь скрипты разделены по назначению и риску.

## 2. Категории скриптов

### Bootstrap и setup

Назначение:

- начальная настройка окружения;
- подготовка локальной БД;
- seed-данные;
- выдача базовых ролей и пользователей;
- build helpers.

Типичные примеры:

- `run_local.py`
- `setup_local_test_db.py`
- `init_staging_db.py`
- `setup_bot_admin.py`
- `init_role_permissions.py`
- `seed_demo_data.py`
- `seed_demo_db.py`
- `seed_rbac_data.py`
- `create_user.py`
- `build_css.ps1`

### Миграции и data-fixes

Назначение:

- изменения схемы;
- backfill;
- data repair;
- legacy-to-new migrations.

Типичные примеры:

- `migrate_to_centralized_db.py`
- `migrate_data_simple.py`
- `migrate_users.py`
- `migrate_whiteboard.py`
- `add_role_column.py`
- `fix_sequences.py`
- `fix_db_schema_robust.py`
- `recalculate_statistics.py`
- `reparse_with_preservation.py`

### Диагностика и проверки

Назначение:

- read-only проверки;
- health и readiness;
- сравнение сред;
- точечный анализ содержимого данных.

Типичные примеры:

- `check_all_databases.py`
- `check_url_for.py`
- `check_profiles.py`
- `check_system_ready.py`
- `check_schedule_data.py`
- `compare_sandbox_prod.py`
- `validate_prototypes.py`
- `_debug_metrics.py`

### Scraping и content ingestion

Назначение:

- парсинг внешних источников;
- импорт заданий;
- синхронизация task bank;
- скачивание вложений.

Типичные примеры:

- `sync_kege_informatics_bank.py`
- `scrape_ege_math.py`
- `scrape_oge_math.py`
- `scrape_oge_inf.py`
- `download_all_task_attachments.py`
- `extract_answers.py`

### Тестовые и verification harnesses

Назначение:

- ручные или полуавтоматические проверки подсистем;
- локальные regression checks;
- специальные тесты интеграций.

Типичные примеры:

- `test_rbac_api.py`
- `test_rbac_implementation.py`
- `test_remote_admin_connection.py`
- `test_notifications.py`
- `test_referral_notifications.py`
- `test_ocr.py`

### Экспорт, операции и одноразовые сценарии

Назначение:

- перенос данных между средами;
- экспорт контента;
- инцидентные cleanup и one-off операции;
- подготовка review-инструментов и generated artifacts.

Типичные примеры:

- `sync_to_sandbox.py`
- `sync_local_from_production.py`
- `sync_lessons_sandbox_to_prod.py`
- `export_tasks_from_prod.py`
- `export_training_data.py`
- `review_tasks.py`
- `generate_reference_attachments.py`
- `build_hints_rag_index.py`

## 3. Скрипты повышенного риска

Следующие группы должны быть явно помечены как опасные:

### Удаление и необратимые изменения

- `delete_user.py`
- `delete_test_data_from_prod.py`
- `delete_wrong_lessons.py`

### Прямая запись в production или sandbox

- `sync_lessons_sandbox_to_prod.py`
- `create_tables_in_production.py`
- `sync_to_sandbox.py`

### Восстановление и массовые трансформации

- `restore_from_backup.py`
- `strip_all_comments.py`

### Секреты и доступы

- `generate_admin_tokens.py`
- `reset_admin_user.py`

### Инцидентные task-specific one-offs

- `_restore_task3.py`
- `_autofilter_task2.py`
- `_autofilter_task3.py`
- `_autofilter_task3_v2.py`
- `_fix_gen_9_15_16.py`
- `_fix_gen_9_15_v2.py`

## 4. Правило безопасного использования

Перед запуском любого скрипта ответьте на 4 вопроса:

1. Он read-only или меняет данные?
2. С какой БД и средой он работает?
3. Есть ли backup/rollback?
4. Это штатный runbook или одноразовый incident tool?

Если хотя бы на один вопрос нет ясного ответа, скрипт нельзя считать безопасным для запуска.

## 5. Отдельно про `scraper/`

Логика из `scraper/` не существует в вакууме: она используется operational-скриптами и способна массово менять task bank. Всегда документируйте её вместе со связанными sync-скриптами.

## 6. Рекомендация по дальнейшему порядку

В идеале для scripts нужно постепенно ввести единый формат шапки:

- цель;
- target environment;
- read-only / mutating;
- irreversible / reversible;
- prerequisite checks;
- backup requirement.

Пока такого стандарта нет, этот документ служит навигацией и первым защитным уровнем от случайного запуска опасных утилит.
