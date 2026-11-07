# BooStudy Telegram Next — Отчет о реализации и рефакторинге

**Дата:** Ноябрь 2026 г.  
**Инициатива:** Telegram Next (Full Product Overhaul)  
**Репозиторий:** `F:\projects\kege_selector_app_current`  
**Статус:** Все этапы реализованы, протестированы и верифицированы

---

## 1. Сводка выполненных работ

В ходе масштабной переработки Telegram-экосистемы BooStudy были устранены архитектурные и логические расхождения между существующим Bot V3 и современной архитектурой платформы. Проект реализован с нулевым воздействием на production-окружение и без изменения Tutor Core.

Ключевые результаты:
1. **Безопасная доставка в Dev-режиме:** по умолчанию все уведомления в локальном окружении переводятся в терминальный статус `simulated` (dry-run). Живая отправка в Telegram возможна только при изолированном opt-in (`--live`) и строго в разрешенные чаты (`854161398`).
2. **Валидация актуальности событий (Event Freshness):** реализована функция `validate_delivery_freshness`, предотвращающая доставку сообщений по отмененным урокам, проверенным работам и истекшим дедлайнам.
3. **Многопользовательская модель преподавателей (Multi-Teacher RBAC):** бот теперь видит всех закрепленных учеников преподавателя через `app.utils.relationship_scope` (`TeacherStudent`, курсовые записи `Enrollment`, кураторство `Student.mentor_id`).
4. **Защита от межпреподавательских утечек (Zero-IDOR):** изолированы очереди и карточки проверки (`can_teacher_review_submission`), исключая доступ одного преподавателя к домашним работам другого преподавателя для общих учеников.
5. **Интерактивные уведомления с In-Bot действиями:** шаблоны уведомлений оснащены кнопками перехода к экранам бота с контролем длины `callback_data` ($\le 64$ байт).
6. **Устранение legacy-рудиментов:** удалены устаревшие кнопки подтверждения («Уведомление пришло?...») и сопутствующие отчеты создателю.
7. **Инструменты обратимого тестирования с манифестом:** созданы скрипты `seed_telegram_v3_acceptance_data.py` (с фиксацией ID в `telegram_acceptance_seed_manifest.json`), `unseed_telegram_v3_acceptance_data.py` (полная очистка) и `trigger_test_notification.py` (безопасный запуск уведомлений).
8. **Полный зеленый тестовый контур:** успешно пройдено 123 автоматизированных теста Telegram-пакета (включая 11 новых тестов безопасности).

---

## 2. Детальный реестр измененных и созданных файлов

### 2.1. Конфигурация и безопасность доставки
- `app/telegram/config.py`:
  - Добавлены функции `is_live_delivery_active()` и `set_live_delivery_active(active: bool)`.
  - Введена поддержка файла динамического управления `instance/telegram_delivery_mode.json`.
  - Добавлена переменная `_CONTROL_FILE` для изоляции в юнит-тестах.
  - В `is_delivery_permitted` добавлена обязательная проверка `is_live_delivery_active()` для локальных окружений.
- `app/telegram/delivery.py`:
  - Добавлена функция `validate_delivery_freshness(row: TelegramDelivery) -> tuple[bool, str | None]`:
    - Проверка срока жизни TTL (`expires_at`).
    - Проверка состояния урока (существование, статус `cancelled`, время старта для `lesson_reminder`).
    - Проверка состояния сдачи ДЗ (существование, статусы `CHECKED`/`GRADED` для `review_queue`).
    - Проверка статуса семейной связи (`FamilyTie.is_confirmed`).
  - В `deliver_one`: вызов `validate_delivery_freshness` перед отправкой.
  - При `is_delivery_permitted == False`: перевод доставки в терминальный статус `simulated` с сохранением `sent_at = utc_now()`, что предотвращает бесконечные повторные попытки.
- `app/telegram/user_notify.py`:
  - Удален студенческий опросник `_with_student_ack_controls` и текстовый промпт `_STUDENT_ACK_PROMPT`.
  - Нейтрализована вспомогательная функция `send_student_notification_ack_report` (возвращает 0, не рассылает спам создателю).

### 2.2. Прикладной слой и ролевой скоупинг
- `app/telegram/application.py`:
  - В `_student_ids_for_context`: для контекста преподавателя (`teacher`) используется агрегация `get_student_user_ids_for_tutor(user.id)` из `app.utils.relationship_scope` с маппингом на `Student.student_id`.
  - Создана функция `_build_teacher_review_query(user)`:
    - Защита прав: `Assignment.created_by_id == user.id` ИЛИ `Lesson.teacher_id == user.id` (через `Assignment.lesson_id`).
    - Фильтрация по ученикам преподавателя.
  - Создана функция `can_teacher_review_submission(user: User, submission_id: int) -> bool` с проверкой RBAC-прав (`assignment.grade`/`assignment.view`) и области видимости.
  - В `build_today_view`: уроки преподавателя фильтруются по `Lesson.teacher_id == user.id`, исключая отмененные и завершенные; счетчик работ на проверку использует `_build_teacher_review_query`.
  - В `build_teacher_students`: список учеников формируется через полный скоуп преподавателя.

### 2.3. Экраны и маршрутизация Bot V3
- `app/telegram/v3/screens/teacher.py`:
  - В `show_teacher_submission_item`: жесткая проверка `student.mentor_id != user.id` заменена на безопасный вызов `can_teacher_review_submission(user, submission_id)`.
  - В `show_teacher_student_card`: проверка доступа переведена на `student_id in _student_ids_for_context(user, "teacher")`.
- `app/telegram/v3/screens/student.py`:
  - В `show_student_hw_item`: проверка принадлежности работы ученику (`submission.student_id in _student_ids_for_context(user, "student")`).
- `app/telegram/v3/router.py`:
  - Добавлена поддержка компактных алиасов callback-кнопок:
    - `v3:tch:q:<id>` и `v3:tch:q_item:<id>` → вызов `show_teacher_submission_item`.
    - `v3:stu:hw_view:<id>` и `v3:stu:hw_item:<id>` → вызов `show_student_hw_item`.
  - Добавлена грациозная обработка отсутствующих или удаленных объектов (возврат информативного сообщения вместо необработанного исключения).

### 2.4. Шаблоны уведомлений
- `app/telegram/notification_templates.py`:
  - Обновлен конструктор кнопок `_make_button`: добавлена поддержка параметра `callback_data`.
  - Реализована функция `_add_in_bot_action(button, text, callback_data)`: сохраняет существующую веб-ссылку и добавляет компактную кнопку перехода внутрь бота.
  - Подключены действия:
    - Для `lesson_scheduled` / `lesson_reminder`: `🗓️ В расписание` (`v3:tch:lessons` / `v3:stu:schedule`).
    - Для `submission_submitted`: `📋 Проверить в боте` (`v3:tch:q:<id>`).
    - Для `submission_checked`: `📊 Результат ДЗ` (`v3:stu:hw_view:<id>`).
  - Очищен футер сообщений: удалены технические строки сервера, добавлен единый аккуратный маркер `<i>ℹ️ Локальная ссылка (dev)</i>` для локальных URL.

### 2.5. Инструменты тестирования и манифест
- `scripts/seed_telegram_v3_acceptance_data.py`:
  - Фиксирует все сгенерированные сущности (UserRole, Student, Lesson, Assignment, Submission, FamilyTie, BugReport) и сохраняет их в `instance/telegram_acceptance_seed_manifest.json`.
- `scripts/unseed_telegram_v3_acceptance_data.py`:
  - Читает `instance/telegram_acceptance_seed_manifest.json` и выполняет чистое удаление всех тестовых записей в порядке обратных зависимостей, после чего удаляет файл манифеста.
- `scripts/trigger_test_notification.py`:
  - Реализована поддержка аргументов `--user-id`, `--kind` (`lesson_scheduled`, `lesson_reminder`, `submission_submitted`, `submission_checked`, `daily_digest`) и `--live`.
  - В режиме `--live` временно активирует живую отправку, доставляет сообщение и гарантированно возвращает безопасный dry-run режим в блоке `finally:`.

### 2.6. Автоматизированные тесты
- `tests/v2/test_telegram_next_safety.py`:
  - 11 специализированных тестов:
    - `test_safe_delivery_mode_toggle`: динамический переключатель доставки.
    - `test_delivery_simulated_in_dev_dry_run`: эмуляция dry-run доставки в dev-режиме.
    - `test_freshness_expired_ttl`: отсечение сообщений с истекшим сроком жизни.
    - `test_freshness_cancelled_lesson`: отмена уведомления для отмененного урока.
    - `test_freshness_already_started_lesson_reminder`: отмена напоминания для уже начавшегося урока.
    - `test_freshness_already_graded_submission`: отмена требования проверки для проверенной работы.
    - `test_freshness_unconfirmed_family_tie`: отмена родительского уведомления при неподтвержденной связи.
    - `test_multi_teacher_relationship_scope`: проверка охвата учеников по разным типам связей.
    - `test_teacher_review_cross_teacher_isolation`: межпреподавательская изоляция работ (Zero-IDOR).
    - `test_in_bot_callbacks_length_and_structure`: гарантия лимита 64 байт для callback_data.
    - `test_router_handles_missing_item_gracefully`: обработка клика по удаленному или несуществующему объекту.
- `tests/v2/conftest.py`:
  - Добавлен `test_telegram_next_safety.py` в список разрешенных тестов.

