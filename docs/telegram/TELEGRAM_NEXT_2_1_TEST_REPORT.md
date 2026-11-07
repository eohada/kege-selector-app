# BooStudy Telegram Next 2.1 — Test & Quality Assurance Report

## 1. Сводка верификации

В рамках релиза **BooStudy Telegram Next 2.1 — Intelligent Notifications, Granular Preferences & Broadcast Center** проведена комплексная проверка безопасности, отказоустойчивости, ролевого доступа и логики доставки.

- **Среда выполнения тестов:** Python 3.13.15, Pytest 9.1.1, SQLite In-Memory.
- **Флаги безопасности:** `BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1`, `BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0`.
- **Итоговый результат:** **22/22 тестов успешно пройдено (100% PASS)**, 0 ошибок, 0 регрессий.

---

## 2. Результаты тестов новой функциональности (Telegram Next 2.1)

| Тест | Проверяемый компонент | Ожидаемое поведение | Результат |
| :--- | :--- | :--- | :---: |
| `test_self_notification_suppression` | `event_policy.py` | Студент сдаёт работу → студент подавлен, учитель получает. Учитель назначает урок → учитель подавлен, студент получает. Админ меняет урок → оба получают. Системное напоминание (автор неизвестен) → оба получают. | **PASSED** |
| `test_batching_mass_lessons` | `batching.py` | 5 уроков для одного ученика в одном батче → ровно 1 карточка `lesson_batch_scheduled` с превью до 5 уроков и детерминированным ключом. 2 урока → ровно 2 индивидуальные карточки. | **PASSED** |
| `test_granular_preferences_isolation_and_resolution` | `user_notify.py` | Отключение `lesson_scheduled` для роли `student` не влияет на роль `teacher` того же пользователя. Проверка provenance (`user` vs `default`). Сброс к дефолтам восстанавливает статус. | **PASSED** |
| `test_delivery_respects_granular_preference` | `delivery.py` | Outbox-диспетчер `deliver_one` отменяет доставку со статусом `cancelled (disabled_by_preference)`, если у получателя отключен тип оповещения для данной роли. | **PASSED** |
| `test_teacher_student_rbac_and_comparison` | `teacher_student_notifications.py` | Проверка авторизации преподавателя. Подтверждение вывода из эксплуатации `notify_new_gradebook_entry` и `notify_subscription_expiring` (безопасный `False`, отсутствие спама). | **PASSED** |

---

## 3. Результаты тестов безопасности и свежести (Telegram Next Safety)

| Тест | Проверяемый инвариант | Результат |
| :--- | :--- | :---: |
| `test_safe_delivery_mode_toggle` | Изоляция режима боевой отправки (live mode) в локальном окружении | **PASSED** |
| `test_delivery_simulated_in_dev_dry_run` | Симуляция доставки для не-allowlist адресатов (dry-run mode) | **PASSED** |
| `test_freshness_expired_ttl` | Инвалидация устаревших сообщений по истечении TTL (`expired_by_policy`) | **PASSED** |
| `test_freshness_cancelled_lesson` | Предотвращение отправки напоминания по отменённому уроку | **PASSED** |
| `test_freshness_already_started_lesson_reminder` | Предотвращение отправки напоминания о прошедшем уроке | **PASSED** |
| `test_freshness_already_graded_submission` | Предотвращение ложных алертов по уже проверенным работам | **PASSED** |
| `test_freshness_unconfirmed_family_tie` | Блокировка отправки родителю при неподтверждённой семейной связи | **PASSED** |
| `test_multi_teacher_relationship_scope` | Изоляция учеников между несколькими преподавателями | **PASSED** |
| `test_teacher_review_cross_teacher_isolation` | Предотвращение доступа преподавателя к проверке чужих работ (403) | **PASSED** |
| `test_in_bot_callbacks_length_and_structure` | Валидация длины всех inline callback_data ($\le 64$ байт по стандарту Telegram) | **PASSED** |
| `test_router_handles_missing_item_gracefully` | Устойчивость роутера к удалённым или отсутствующим сущностям | **PASSED** |

---

## 4. Результаты тестов викторин и дайджестов (Telegram Blitz)

| Тест | Проверяемый функционал | Результат |
| :--- | :--- | :---: |
| `test_blitz_questions_bank_structure` | Корректность структуры базы вопросов КЕГЭ | **PASSED** |
| `test_get_daily_blitz_deterministic` | Детерминированный выбор вопроса дня по дате | **PASSED** |
| `test_format_blitz_message_and_keyboard` | Форматирование карточки блица и клавиатуры вариантов | **PASSED** |
| `test_check_blitz_answer_incorrect_then_correct` | Проверка ответов и начисление баллов | **PASSED** |
| `test_send_daily_blitz_to_student_mock` | Безопасная отправка в мок-режиме | **PASSED** |
| `test_broadcast_daily_blitz_reminders` | Пакетный планировщик напоминаний блица | **PASSED** |

---

## 5. Выводы

Архитектурный рефакторинг и реализация Telegram Next 2.1 завершены без поломок существующих подсистем, со 100% успешным прохождением тестов и полной изоляцией боевых данных.
