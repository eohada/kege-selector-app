# BooStudy AI Lab Sprint 10 — безопасность базы данных

## Исходная локальная база

Целевая пользовательская БД:

`F:\projects\kege_selector_app_current\instance\boostudy_dev.db`

До импорта приложения, `create_app`, Alembic и миграций была сделана согласованная копия за пределами workspace через SQLite `Connection.backup()` из соединения `mode=ro` с `query_only`. Личный экспорт строк таблиц не выполнялся.

| Свойство | Значение при snapshot |
|---|---|
| Исходный размер | 46,088,192 байта |
| Исходный SHA-256 | `7f122b4098523f820e76bb5c7e19df54579b21074f3b5ab4833d3c136d582fe1` |
| Source mtime UTC до/после snapshot | `2026-10-20T14:35:31.838056Z` — совпадает |
| WAL/SHM/journal при snapshot | отсутствовали до и после |
| Backup | `C:\Users\eohad\Documents\BooStudy_Sprint10_DB_Safety\boostudy_dev_20261020T152603807Z.sqlite` |
| Backup SHA-256 | `9a89763ab8c6b214ff4d75086e24aa310d00d5f2003d4b535e7e1751bff0e0e0` |
| Backup integrity | `ok`, 11,252 страниц, `user_version=0` |

JSON metadata и read-only диагностика находятся рядом с backup в `C:\Users\eohad\Documents\BooStudy_Sprint10_DB_Safety\`. Снимок зафиксировал 159 строк `foreign_key_check` по шести таблицам: `TheoryCheckpointAttempts` — 99, `GuestTasks` — 48, `TaskCanvasDrawings` — 4, `AuditLog` — 4, `StudentTheoryNotes` — 3, `ReferralCodes` — 1. Это исходные наблюдения; они не исправлялись и не доказывают, что каждое нарушение возникло в конкретном предыдущем запуске.

## Причина побочного изменения при обслуживании

`flask db heads` загружал `wsgi.py`, затем `create_app()`. Фабрика приложения при запуске локальной конфигурации продолжала в startup bootstrap: создавала схему через `db.create_all()` и выполняла ручные bootstrap-хуки. Поэтому команда, которая должна только прочитать Alembic heads, имела побочный доступ к рабочей SQLite-базе до выполнения самой команды.

В `app/__init__.py` добавлена проверка безопасного режима: миграционные CLI-команды, тестовый процесс и явный флаг пропускают startup bootstrap и фоновые задания. Обычный `flask run` сохраняет своё поведение. Проверка фактической команды `flask db heads` использовала отдельный временный путь; файл базы на этом пути не создавался.

## Изолированная проверка миграций

Миграция `ai_lab_sprint10_task_variants` добавляет `AiLabAssignmentVariants`, индексы и ограничения уникальности поверх `ai_lab_sprint9_families_retries`.

Проверка выполнялась в отдельной baseline-базе:

`C:\Users\eohad\Documents\BooStudy_Sprint10_DB_Safety\migration-pre-sprint9-233703199a3e4b7093a7ea8970c9eed7.sqlite`

В ней были применены миграции Sprint 9 и 10. Результат: Alembic head `ai_lab_sprint10_task_variants`, SQLite `integrity_check=ok`, `foreign_key_check=[]`, обе таблицы семейств и вариантов присутствуют.

Попытка запускать всю историческую цепочку на абсолютно пустой SQLite-базе остановилась на миграции `c0f4d9d2b9b1_theory_groups_and_feedback_history.py`: она предполагает существующую baseline-таблицу `TheoryBlocks`, создаваемую проектным `db.create_all()`. Исторические миграции не изменялись. Итоговая проверка использовала отдельную baseline-схему и затем применила целевые миграции.

## Гарантии и границы

- Миграции не запускались на `instance/boostudy_dev.db`.
- Приложение, работавшее на локальном порту 5058, не перезапускалось и не останавливалось агентом.
- Регрессии использовали `tmp_path`, `sqlite:///:memory:` или отдельный `SQLITE_DB_PATH`; live Runner интеграция также сохраняла данные только во временную тестовую БД.
- Snapshot фиксирует состояние источника в момент backup, но без доверенного снимка до предыдущего инцидента нельзя восстановить точные изменения, внесённые тем запуском.
- FK нарушения источника оставлены без ремонта. Для такого ремонта нужно отдельное расследование миграций и данных; Sprint 10 на них не влиял.

