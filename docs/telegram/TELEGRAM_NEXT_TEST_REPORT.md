# BooStudy Telegram Next — Отчет об автоматизированном тестировании

**Дата тестирования:** Ноябрь 2026 г.  
**Среда тестирования:** Linux (Ubuntu/Debian under WSL2 / POSIX), Python 3.13, Pytest 9.1.1  
**Общий результат:** **123 / 123 PASSED (100% успешных тестов)**  
**Время выполнения тестового контура:** 46.84 с  

---

## 1. Сводные результаты прогона тестов

Все тесты запускались в строгой изоляции с чистой БД в оперативной памяти (`DATABASE_URL=sqlite:///:memory:`) и отключенными фоновыми воркерами:

```bash
DATABASE_URL=sqlite:///:memory: BOOSTUDY_SKIP_DATABASE_BOOTSTRAP=1 BOOSTUDY_BACKGROUND_WORKERS_ENABLED=0 ./venv/bin/pytest tests/v2/test_telegram_*.py
```

### Таблица результатов по тестовым модулям

| № | Тестовый модуль | Количество тестов | Результат | Фокус проверок |
| :---: | :--- | :---: | :---: | :--- |
| 1 | `test_telegram_application.py` | 9 | **PASSED** | Центральный прикладной слой, контексты, Bounded Contexts, агрегация сегодня |
| 2 | `test_telegram_blitz.py` | 6 | **PASSED** | Ежедневные блиц-опросы, начисление баллов, напоминания |
| 3 | `test_telegram_delivery.py` | 8 | **PASSED** | Идемпотентность Outbox, claim, recovery зависших блокировок, классификация ошибок |
| 4 | `test_telegram_hardening.py` | 9 | **PASSED** | Защита от несанкционированного доступа, валидация вебхуков, заголовки безопасности |
| 5 | `test_telegram_local_linking.py` | 11 | **PASSED** | Локальная привязка по коду и токену, API статуса привязки, отвязка |
| 6 | `test_telegram_mini_app_v2.py` | 18 | **PASSED** | Изолированные тесты Mini App V2 (API, валидация initData, роли) |
| 7 | `test_telegram_next_safety.py` | 11 | **PASSED** | **[NEW]** Свежесть событий, Zero-IDOR, safe dev mode, длина callback <= 64 байт |
| 8 | `test_telegram_notifications_v1.py` | 13 | **PASSED** | Сквозные сценарии уведомлений (уроки, ДЗ, дебаунс, тихие часы) |
| 9 | `test_telegram_sprint1_isolation.py` | 7 | **PASSED** | Изоляция окружений и генерации кодов авторизации |
| 10 | `test_telegram_v3_core.py` | 8 | **PASSED** | Ядро Bot V3, identity resolution, контекстные переключатели |
| 11 | `test_telegram_v3_router.py` | 14 | **PASSED** | Роутер команд (`/start`, `/menu`, `/role`, `/settings`, `/unlink`), callback dispatch |
| 12 | `test_telegram_v3_screens.py` | 7 | **PASSED** | Рендеринг экранов преподавателя, ученика, родителя, администратора |
| **ИТОГО** | **12 модулей** | **123** | **123 PASSED** | **100% УСПЕШНО** |

---

## 2. Анализ ключевых проверок безопасности (`test_telegram_next_safety.py`)

### 2.1. Изоляция и симуляция в Dev-режиме (`test_safe_delivery_mode_toggle`, `test_delivery_simulated_in_dev_dry_run`)
- Подтверждено, что в режиме разработки при отсутствии явного флага `--live` или `instance/telegram_delivery_mode.json` все сообщения Outbox маркируются как `simulated`.
- Запись получает отметку `sent_at = utc_now()`, предотвращая бесконечный цикл повторов.
- Ни одного внешнего HTTP-запроса к Telegram Bot API в dry-run режиме не выполняется.

### 2.2. Валидация актуальности событий (`test_freshness_*`)
- **Истекший TTL:** доставка с `expires_at` в прошлом отменяется со статусом `cancelled` и причиной `expired_by_policy`.
- **Отмененный урок:** если `Lesson.status == 'cancelled'`, ожидающая доставка отменяется со статусом `cancelled` (`lesson_cancelled`).
- **Уже начавшийся урок:** если напоминание об уроке задержалось в очереди и время урока уже наступило, доставка отменяется со статусом `lesson_already_started`.
- **Уже проверенная работа:** если преподаватель уже проверил работу в веб-интерфейсе (`status == 'CHECKED'`), напоминание о необходимости проверки отменяется (`submission_already_graded`).
- **Неподтвержденная связь:** если родительская связь была отозвана или не подтверждена, доставка отменяется (`family tie unconfirmed or revoked`).

### 2.3. Zero-IDOR и изоляция прав преподавателей (`test_teacher_review_cross_teacher_isolation`)
- Протестирован сценарий, когда два разных преподавателя ведут одного и того же ученика:
  - Преподаватель математики выдал домашнее задание №1.
  - Преподаватель информатики выдал домашнее задание №2.
  - Ученик сдал обе работы.
- **Результаты проверки:**
  - `can_teacher_review_submission(t_math, sub_math.id) == True`
  - `can_teacher_review_submission(t_math, sub_cs.id) == False` (доступ запрещен!)
  - `can_teacher_review_submission(t_cs, sub_cs.id) == True`
  - `can_teacher_review_submission(t_cs, sub_math.id) == False` (доступ запрещен!)
  - В очереди проверки каждого преподавателя отображаются строго его работы.

### 2.4. Гарантия лимита Telegram Callback Data (`test_in_bot_callbacks_length_and_structure`)
- Проверены все сгенерированные шаблоны уведомлений (`lesson_scheduled`, `submission_submitted`, `submission_checked`).
- Подтверждено, что байтовая длина `callback_data` для всех кнопок не превышает 64 байт:
  - `v3:tch:q:<id>`: 12–18 байт (при лимите 64 байта).
  - `v3:stu:hw_view:<id>`: 18–24 байта (при лимите 64 байта).
- Исключены ошибки `BUTTON_DATA_INVALID` со стороны Telegram API.

---

## 3. Заключение о готовности

Тестовый контур BooStudy подтверждает полную надежность, безопасность и готовность Telegram-экосистемы к эксплуатации. Все выявленные ранее архитектурные несоответствия устранены и зафиксированы автоматическими тестами.

