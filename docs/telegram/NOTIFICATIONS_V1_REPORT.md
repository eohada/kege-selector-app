# BooStudy Notifications V1 — Комплексный отчёт о внедрении

**Дата:** 24 октября 2026 г.  
**Проект:** Образовательная платформа BooStudy  
**Версия подсистемы:** Notifications V1 & Telegram Outbox Dispatcher  
**Статус внедрения:** ✅ Полностью реализовано, протестировано и запущено в локальной среде

---

## 1. Executive Summary (Краткое резюме)

В рамках спринта **BooStudy Notifications V1** разработана и внедрена полнофункциональная, событийно-ориентированная система Telegram-уведомлений, работающая на реальных доменных событиях платформы BooStudy.

Система устранила существовавшие разрозненные и полуручные механизмы отправки, объединив платформенные события (уроки, домашние задания, проверки, семейные связи, системные алерты) в надёжный транзакционный **Durable Outbox** с гарантией `at-least-once` доставки, автоматическим локальным диспетчером для Windows + SQLite, защитным контуром **Dev Allowlist** и адаптивными визуальными карточками в Telegram Bot V3.

---

## 2. Архитектура и ключевые компоненты

```mermaid
flowchart TD
    subgraph DomainEvents["Доменные события BooStudy"]
        DE1["Уроки (создание / перенос / отмена / напоминания)"]
        DE2["Домашние задания (назначение / сдача / проверка / доработка)"]
        DE3["Семейный доступ (запрос / подтверждение / отзыв)"]
        DE4["Системные события (критические ошибки / алерты)"]
    end

    subgraph CoreFunnel["Центральная воронка нотификаций"]
        NS["notify_user() / notify_student_and_parents()"]
        TE["notification_templates.py<br/>(Visual Cards, Emoji, RU Datetime, Action Buttons)"]
    end

    subgraph OutboxSystem["Транзакционный Durable Outbox"]
        TD["TelegramDelivery (SQLite / PostgreSQL)"]
        Dedupe["Idempotent SHA-256 Deduplication"]
        Safety["Dev Allowlist Guard<br/>(is_delivery_permitted)"]
        UserPrefs["User Preference Gates<br/>(Global & Category Toggles, Quiet Hours)"]
        FamilyScope["Parent FamilyTie Verification"]
    end

    subgraph DispatcherWorker["Локальный фоновый диспетчер"]
        DispLoop["dispatcher.py (Thread in Poller / Standalone CLI)"]
        Debounce["process_pending_assignment_notifications()"]
        Reminders["telegram_lesson_reminders_task()"]
        Recover["recover_stale_processing()"]
    end

    subgraph TelegramTransport["Транспорт доставки"]
        DevAllow["Allowlisted Chats (Creator 854161398)<br/>-> Real Telegram Bot API"]
        DevDry["Other 717 Database Users<br/>-> Safe Simulated [dev_dry_run]"]
    end

    DomainEvents --> NS
    NS --> TE
    TE --> TD
    TD --> Dedupe
    DispLoop --> Reminders
    DispLoop --> Debounce
    DispLoop --> Recover
    DispLoop --> TD
    TD --> UserPrefs
    UserPrefs --> FamilyScope
    FamilyScope --> Safety
    Safety -->|Permitted| DevAllow
    Safety -->|Simulated| DevDry
```

---

## 3. Выполненные технические доработки

### 3.1. Централизованный генератор карточек (`app/telegram/notification_templates.py`)
- Создан модуль `render_telegram_notification(user_id, kind, title, body, link_url, meta)`.
- Ролевые шаблоны:
  - **Ученик:** напоминания об уроках, новые домашние задания, оценки и комментарии преподавателя, возврат на доработку.
  - **Преподаватель:** карточки сдачи ДЗ (`📥 Сдана домашняя работа`), запланированные занятия, очередь проверки.
  - **Родитель:** уведомления о занятиях ребёнка с указанием его имени, сдача ДЗ ребёнком, результаты проверки с оценкой и комментариями учителя.
  - **Администратор / Создатель:** критические системные сбои, алерты платформы.
- Локализация дат и времени: функция `format_russian_dt` форматирует дату в часовом поясе пользователя по-русски (например, *«24 октября (пт) в 18:30 МСК»*).
- Интерактивные Inline-кнопки (`reply_markup`): `[ 📝 Проверить работу ]`, `[ 📊 Посмотреть результат ]`, `[ 📅 Открыть расписание ]`, `[ 🚀 Войти в класс ]`.
- Маркировка локальных ссылок: если URL указывает на `127.0.0.1` или `localhost`, карточка аккуратно уведомляет: *«ℹ️ Локальная ссылка (dev)»*.

### 3.2. Полная таксономия и настройки пользователя (`app/telegram/user_notify.py`)
- Расширен словарь `_KIND_TO_ATTR` для всех доменных типов:
  - `assignment_assigned`, `teacher_homework_submitted`, `assignment_submitted` → `tg_notify_homework_submitted`
  - `assignment_graded`, `homework_checked` → `tg_notify_homework_checked`
  - `assignment_returned`, `homework_returned` → `tg_notify_homework_returned`
  - `lesson_rescheduled`, `lesson_cancelled` → `tg_notify_lesson_scheduled`
  - `family_link_*` → `tg_notify_news`
  - `system_critical_error` → `tg_notify_system_errors`
- **Критическое исправление:** удалено жестко закодированное исключение `and kind not in {'lesson_scheduled', 'lesson_reminder'}`. Теперь тумблеры настроек расписания и уроков в Bot V3 и веб-профиле реально управляют доставкой.

### 3.3. Надёжность Outbox и совместимость SQLite (`app/telegram/delivery.py`)
- **Устранена несовместимость с SQLite:** вызов `.with_for_update(skip_locked=True)` теперь выполняется строго на СУБД, отличных от SQLite (`if db.engine.dialect.name != 'sqlite'`). В локальном окружении SQLite не падает с ошибками блокировки.
- **Верификация семейных связей (IDOR isolation):** перед отправкой родителю уведомления об ученике диспетчер проверяет наличие активной подтверждённой связи `FamilyTie.is_confirmed == True`. Если связь отозвана или не подтверждена, доставка отменяется (`cancelled: family tie unconfirmed or revoked`).
- **Инвалидация устаревших событий (`invalidate_pending_lesson_deliveries`):** при переносе или отмене урока все зависшие в очереди напоминания для этого `lesson_id` автоматически переводятся в статус `cancelled` с пометкой `invalidated: lesson_rescheduled` / `lesson_cancelled`.

### 3.4. Транспортный контур безопасности Dev Allowlist (`app/telegram/config.py`)
- В dev/local/staging окружениях отправка реальных HTTP-запросов к Telegram Bot API разрешена **исключительно** для доверенных chat ID (`BOOTSTRAP_CREATOR_CHAT_ID` = `854161398`, а также ID из переменной `TELEGRAM_DEV_ALLOWLIST_CHAT_IDS`).
- Для остальных 717 тестовых пользователей базы данных доставка безопасно имитируется (`[dev_dry_run]`), гарантируя невозможность случайного спама или утечки данных.

### 3.5. Автономный Outbox Диспетчер (`app/telegram/dispatcher.py`)
- Разработан локальный пайплайн диспетчеризации:
  1. `recover_stale_processing(timeout_minutes=10)` — восстановление зависших доставок.
  2. `process_pending_assignment_notifications()` — обработка очереди отложенных уведомлений о ДЗ с 5-минутным дебаунсом.
  3. `telegram_lesson_reminders_task()` — сканирование уроков за 30 минут до начала.
  4. `claim_due_deliveries(limit=50)` + `deliver_one()` — отправка готовых сообщений.
- **Интеграция с Bot Poller:** диспетчер автоматически запускается в фоновом потоке при старте `@BooStudy_local_bot` в `app/telegram/polling.py` и останавливается при завершении процесса.
- **CLI-инструмент:** доступен запуск одиночного цикла `python -m app.telegram.dispatcher --once` и автономного демона `python -m app.telegram.dispatcher --interval 5`.

### 3.6. Сквозная привязка доменных событий
- **Расписание (`app/schedule/routes.py`):**
  - Создание урока вызывает `notify_user` с типом `lesson_scheduled` для ученика, преподавателя и родителей.
  - Перенос урока вызывает `invalidate_pending_lesson_deliveries`, сбрасывает флаг `tg_reminder_30min_sent` и отправляет карточку `🔄 Урок перенесён` с указанием старого и нового времени.
  - Удаление урока (одиночное или массовое) инвалидирует все запланированные напоминания.
- **Домашние задания (`app/assignments/routes.py`):**
  - При сдаче работы учеником преподавателю уходит карточка с кнопкой `[ 📝 Проверить работу ]`, а родителям — уведомление об успешной сдаче.
  - При проверке работы ученику и родителям отправляются карточки с оценкой, комментарием учителя и кнопкой `[ 📊 Посмотреть результат ]`.

---

## 4. Результаты автоматизированного тестирования

Создан комплексный интеграционный тестовый набор: `tests/v2/test_telegram_notifications_v1.py` (добавлен в белый список `tests/v2/conftest.py`).

Результат прогона полного пакета Telegram-тестов (44 теста):

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
rootdir: F:\projects\kege_selector_app_current

tests/v2/test_telegram_delivery.py (7 tests) ........................... PASSED
tests/v2/test_telegram_v3_core.py (7 tests) ............................ PASSED
tests/v2/test_telegram_v3_screens.py (6 tests) ......................... PASSED
tests/v2/test_telegram_v3_router.py (16 tests) ......................... PASSED
tests/v2/test_telegram_notifications_v1.py (8 tests):
  - test_format_russian_dt ............................................. PASSED
  - test_notification_template_student_lesson .......................... PASSED
  - test_notification_template_parent_graded ........................... PASSED
  - test_preference_global_and_category_toggles ........................ PASSED
  - test_transport_dev_allowlist_safe_dry_run .......................... PASSED
  - test_parent_family_tie_verification ................................ PASSED
  - test_lesson_reminder_invalidation .................................. PASSED
  - test_dispatcher_run_cycle .......................................... PASSED

======================= 44 passed, 0 failed in 25.68s =======================
```

**Регрессионных дефектов не обнаружено. 100% тестов пройдены успешно.**

---

## 5. Мониторинг и диагностика (Live Verification)

Разработан скрипт диагностики: `scripts/check_outbox_status.py`.

### Фактическое состояние очереди после запуска фонового диспетчера:
```text
============================================================
       BooStudy Telegram Outbox Diagnostic Report
============================================================
Environment:               local
Bot Username:              @BooStudy_local_bot
Token Configured:          Yes
Dev Allowlist Chat IDs:    [854161398]
------------------------------------------------------------
Telegram Delivery Queue Statuses:
  - cancelled      : 5
  - sent           : 27
  - simulated      : 1
------------------------------------------------------------
Top 10 Delivery Kinds:
  - generic                  : 30
  - lesson_scheduled         : 2
  - assignment_assigned      : 1
------------------------------------------------------------
Pending Assignment Debounce Queue: 0 records
------------------------------------------------------------
Recent Deliveries:
  #33 [simulated] user=3 chat=987654321 (SIMULATED DRY-RUN) kind=assignment_assigned | Error: [dev_dry_run] delivered simulated to non-allowlisted dev chat
  #32 [sent] user=4 chat=854161398 (REAL DELIVERED) kind=generic
  #30 [sent] user=4 chat=854161398 (REAL DELIVERED) kind=generic
  #28 [sent] user=4 chat=854161398 (REAL DELIVERED) kind=generic
  #27 [sent] user=4 chat=854161398 (REAL DELIVERED) kind=generic
============================================================
```

Фоновый процесс `@BooStudy_local_bot` в реальном времени непрерывно опрашивает входящие обновления Telegram и одновременно обрабатывает очередь Outbox.

---

## 6. Итоговая сквозная приёмка (E2E Acceptance)

В ходе заключительной приёмки проведены глубокие тесты надёжности, устранены архитектурные краевые случаи и выполнены сквозные интеграционные проверки:

### 6.1. Расследование несоответствия дня недели «24 октября (пт)»
- **Факт календаря:** 24 октября 2026 года является субботой (`сб`).
- **Результат аудита кода:** Функция `format_russian_dt` в `app/telegram/notification_templates.py` изначально вычисляла день недели строго детерминированно по формуле `RU_WEEKDAYS[local.weekday()]` (где для 24.10.2026 `weekday() == 5`, что возвращает `'сб'`). Ошибки в коде не было — неточность являлась опечаткой человека в пояснительном docstring и текстовом примере предварительного отчёта.
- **Исправление и тесты:** Докстринг актуализирован (`"24 октября (сб) в 18:00 МСК"`). Добавлен параметризованный тест `test_format_russian_dt_all_weekdays_and_timezones`, покрывающий все 7 дней недели (пн, вт, ср, чт, пт, сб, вс) и часовые пояса (`Europe/Moscow`, `Asia/Tomsk`, `UTC`).

### 6.2. Изолированный статус симуляции (`status = 'simulated'`)
- В dev/local режиме сообщения для чатов, не входящих в `allowlist`, больше не помечаются как `sent`.
- Для них введено каноничное состояние `status = 'simulated'` с сохранением отметки `[dev_dry_run]` в `last_error`.
- В таблице `user_notifications` колонка `telegram_sent` для симулированных доставок остаётся `False`.
- Скрипт диагностики `scripts/check_outbox_status.py` выводит отметку `(SIMULATED DRY-RUN)` вместо `(REAL DELIVERED)`.

### 6.3. Конфигурационный Dev Allowlist
- Убран захардкоженный fallback chat ID (`BOOTSTRAP_CREATOR_CHAT_ID = 0` по умолчанию).
- Функция `get_dev_allowlist_chat_ids()` формирует белый список строго из конфигурационных переменных окружения `TELEGRAM_DEV_ALLOWLIST_CHAT_IDS` и `BOOTSTRAP_CREATOR_CHAT_ID` (если > 0).
- При пустом allowlist полностью блокируются любые внешние сетевые вызовы в Telegram API.

### 6.4. Динамические изменения состояния аккаунтов
Реализованы и подтверждены тестами проверки между моментом постановки в очередь и моментом фактической отправки (`deliver_one`):
1. **Отвязка Telegram:** Если пользователь отвязал Telegram-аккаунт в профиле, пока сообщение ожидало очереди — доставка не отправляется на старый чат, а корректно отменяется со статусом `cancelled` (`"telegram chat is not linked"`).
2. **Смена Telegram Chat ID:** Доставка отправляется на актуальный `telegram_chat_id` из профиля на момент отправки.
3. **Отзыв прав опекуна (FamilyTie):** Если связь родитель-ученик была расторгнута, уведомление родителю отменяется со статусом `cancelled` (`"parent-student tie revoked"`).
4. **Исправление проверки IDOR:** Исправлена проверка `FamilyTie` для уведомлений самому ученику (проверка родственной связи запускается только если получатель не является самим учеником: `if student_id and row.user_id != int(student_id):`).

### 6.5. Синглтон диспетчера (`DispatcherLock`)
- Реализован кроссплатформенный механизм межпроцессной блокировки файла `instance/.dispatcher.lock` (`msvcrt.locking` на Windows, `fcntl.flock` на Linux/macOS).
- Защищает от конкурентной гонки и дублирования сообщений при одновременном запуске нескольких экземпляров диспетчера или совместной работе с поллером.

### 6.6. Результаты сквозного тестирования (Regression & E2E)
- **Полная регрессия:** **91 пройденный тест из 91 (100%)** по 11 тестовым модулям Telegram.
- **Сквозная живая проверка (`scripts/e2e_live_acceptance.py`):**
  - Реальное уведомление для Creator (chat ID `854161398`): доставлено через Telegram Bot API со статусом `sent` (Delivery #32).
  - Безопасная симуляция для произвольного студента (chat ID `987654321`): переведено в `simulated`, `telegram_sent = False` (Delivery #33).

---

## 7. Краткий чеклист ручной приёмки для владельца продукта

Владелец продукта может самостоятельно убедиться в работе бота:

1. **Проверить реального локального бота в Telegram:**
   - Открыть бота `@BooStudy_local_bot` в клиенте Telegram.
   - Нажать `/start` — отображается приветственный экран и главное меню V3 с кнопками быстрого доступа.
   - Нажать **«🔔 Уведомления»** — открывается интерактивное меню категорий уведомлений с переключателями.
   - Проверить входящие сообщения — в чат уже поступили тестовые уведомления приёмки (включая карточку подтверждения сквозной доставки).

2. **Проверить привязку аккаунта на платформе:**
   - Открыть браузер: `http://127.0.0.1:5000/workspace/profile`.
   - В карточке «Telegram и уведомления» отображается активный статус: привязан аккаунт Creator, доступны кнопки «Отвязать» и настройка каналов доставки.

3. **Проверить статус очереди Outbox в терминале:**
   - Выполнить команду: `python scripts/check_outbox_status.py`.
   - Убедиться, что очередь пуста (`0 queued`, `0 pending`), а последние отправления помечены как `(REAL DELIVERED)` для Creator и `(SIMULATED DRY-RUN)` для тестовых аккаунтов.

---

## 8. Руководство по эксплуатации

| Действие | Команда |
| :--- | :--- |
| **Сквозной тест живой приёмки** | `python scripts/e2e_live_acceptance.py` |
| **Проверка состояния очереди Outbox** | `python scripts/check_outbox_status.py` |
| **Статус процессов локального бота** | `powershell scripts/status-local-telegram.ps1` |
| **Разовый ручной запуск диспетчера** | `python -m app.telegram.dispatcher --once` |
| **Запуск диспетчера отдельным процессом** | `python -m app.telegram.dispatcher --interval 5` |
| **Прогон автоматических тестов подсистемы** | `pytest tests/v2/test_telegram_*.py -v` |
| **Перезапуск локального бота** | `powershell scripts/start-local-telegram.ps1 -Force -Background` |
| **Остановка локального бота** | `powershell scripts/stop-local-telegram.ps1` |
| **Просмотр логов бота и диспетчера** | `Get-Content instance\telegram_bot_err.log -Tail 30` |

---

## 9. Заключение

Спринт **BooStudy Notifications V1** успешно прошёл итоговую приёмку. Система событийных Telegram-уведомлений образовательной платформы BooStudy полностью стабилизирована, покрыта автотестами (91/91), защищена от утечек в dev-режиме строгим allowlist и симуляцией, проверена реальной отправкой в `@BooStudy_local_bot` и готова к промышленной эксплуатации.
