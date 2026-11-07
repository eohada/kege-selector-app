# BooStudy Telegram Next — Матрица событий и регламент уведомлений

**Версия:** 2.0 (Telegram Next)  
**Подсистема:** BooStudy Outbox & Notifications Engine  
**Статус:** Утверждено  

---

## 1. Общие принципы доставки уведомлений

Каждое уведомление в BooStudy проходит многоуровневый конвейер надежности:
1. **Транзакционная запись в БД:** создание записи `UserNotification` и связанной `TelegramDelivery` (Outbox) в единой ACID-транзакции.
2. **Идемпотентная дедупликация:** вычисление SHA-256 ключа по кортежу `[user_id, kind, text, notification_id]`, предотвращающее дублирование при повторных вызовах.
3. **Учет пользовательских настроек:** проверка персонального рубильника категории (`tg_notify_lessons`, `tg_notify_homework`, `tg_notify_marketing`, `tg_notify_news`).
4. **Учет тихих часов:** откладывание несрочных сообщений на время сна пользователя (с учетом его часового пояса).
5. **Валидация свежести перед отправкой (Event Freshness Guard):** повторная проверка статуса реальных бизнес-объектов (урок, ДЗ, семейная связь) непосредственно перед вызовом Telegram Bot API.
6. **Интерактивные In-Bot действия:** снабжение сообщений кнопками с компактными callback-данными (строго $\le 64$ байт), позволяющими перейти к деталям в боте в один клик.

---

## 2. Полная матрица образовательных событий

| Тип события (`kind`) | Триггер в платформе | Получатели | Приоритет / TTL | Тихие часы | Предварительная валидация свежести | Кнопки действия (Action Buttons) |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- |
| **`lesson_scheduled`** | Назначение урока в расписании (`LessonStudio`, календарь) | Ученик, Преподаватель, Родитель | **Normal**<br>TTL: до даты урока | Откладывается | 1. Урок существует в БД.<br>2. Статус урока не `cancelled`. | `🌐 Открыть расписание` (URL) |
| **`lesson_rescheduled`** | Изменение даты/времени урока | Ученик, Преподаватель, Родитель | **High**<br>TTL: до новой даты | Обход тихих часов | 1. Урок существует.<br>2. Статус урока не `cancelled`. | `🌐 Новое расписание` (URL) |
| **`lesson_cancelled`** | Отмена урока преподавателем или учеником | Ученик, Преподаватель, Родитель | **High**<br>TTL: 24 часа | Обход тихих часов | 1. Урок существует.<br>2. Статус урока строго `cancelled`. | `🌐 Расписание` (URL) |
| **`lesson_reminder`** | Фоновый воркер за 2 часа и за 15 минут до начала | Ученик, Преподаватель | **High**<br>TTL: до времени старта | Обход тихих часов | 1. Урок не отменен.<br>2. Текущее время strictly < времени старта урока. | `🌐 Войти в урок` (URL) |
| **`assignment_assigned`** | Преподаватель опубликовал домашнее задание | Ученик | **Normal**<br>TTL: до дедлайна | Откладывается | 1. Задание активно (`is_active == True`).<br>2. Дедлайн в будущем. | `📝 Посмотреть ДЗ` (In-bot: `v3:stu:hw_view:<id>`)<br>`🌐 Открыть на платформе` (URL) |
| **`submission_submitted`** / `teacher_homework_submitted` | Ученик отправил решение ДЗ на проверку | Преподаватель | **Normal**<br>TTL: 7 дней | Откладывается | 1. Работа существует.<br>2. Статус работы: `SUBMITTED` или `IN_REVIEW`.<br>3. Работа еще не проверена (`graded_at is None`). | `📋 Проверить в боте` (In-bot: `v3:tch:q:<id>`)<br>`🌐 Веб-студия проверки` (URL) |
| **`submission_checked`** / `homework_checked` | Преподаватель выставил оценку и комментарий | Ученик, Родитель | **Normal**<br>TTL: 14 дней | Откладывается | 1. Работа существует.<br>2. Статус работы: `CHECKED`.<br>3. Для родителя: связь `FamilyTie` подтверждена. | `📊 Результат ДЗ` (In-bot: `v3:stu:hw_view:<id>`)<br>`🌐 Разбор на платформе` (URL) |
| **`daily_digest`** | Утренний планировщик (08:30 МСК) | Преподаватель, Ученик, Родитель | **Low**<br>TTL: 12 часов | Учитываются | Наличие актуальных уроков или дедлайнов на текущий день. | `📋 Мой день` (In-bot: `v3:nav:home`) |
| **`family_tie_confirmed`** | Ученик подтвердил привязку родительского аккаунта | Родитель | **High**<br>TTL: 48 часов | Обход тихих часов | Связь `FamilyTie.is_confirmed == True`. | `👶 Профиль ребенка` (In-bot: `v3:par:child:<id>`) |
| **`system_announcement`** | Информационная рассылка платформы | Все привязанные пользователи | **Low**<br>TTL: 72 часа | Откладывается | Проверка рубильника `tg_notify_news == True`. | `ℹ️ Подробнее` (URL) |

---

## 3. Регламент валидации свежести (Freshness Guard)

Функция `validate_delivery_freshness(row: TelegramDelivery)` в `app/telegram/delivery.py` гарантирует, что пользователь никогда не получит неактуальное сообщение:

```python
def validate_delivery_freshness(row: TelegramDelivery) -> tuple[bool, str | None]:
    # 1. Проверка срока жизни TTL (expires_at)
    if is_expired_by_policy(row):
        return False, 'expired_by_policy'

    # 2. Повторная валидация урока
    if lesson_id:
        lesson = Lesson.query.get(lesson_id)
        if not lesson:
            return False, 'lesson_not_found'
        if lesson.status == 'cancelled' and row.kind in ('lesson_reminder', 'lesson_scheduled'):
            return False, 'lesson_cancelled'
        if row.kind == 'lesson_reminder' and now > lesson.lesson_date:
            return False, 'lesson_already_started'

    # 3. Повторная валидация сдачи ДЗ
    if submission_id:
        sub = Submission.query.get(submission_id)
        if not sub:
            return False, 'submission_not_found'
        if row.kind in ('review_queue', 'submission_submitted') and sub.status in ('CHECKED', 'GRADED'):
            return False, 'submission_already_graded'

    # 4. Повторная валидация семейной связи
    if parent_recipient and student_id:
        tie = FamilyTie.query.filter_by(parent_id=row.user_id, student_id=student_id, is_confirmed=True).first()
        if not tie:
            return False, 'family tie unconfirmed or revoked'

    return True, None
```

При обнаружении неактуальности доставка помечается как `cancelled` с точным указанием причины в `last_error`, не засоряя чат пользователя и не тратя квоты Telegram API.

---

## 4. Защита от переполнения Callback Data (64 байта)

Все inline-кнопки в шаблонах уведомлений генерируются через функцию `_add_in_bot_action` с обязательным сжатием идентификаторов:
- Преподавательская карточка работы: `v3:tch:q:<id>` (длина от 12 до 18 байт при ID до 999999).
- Очередь проверки: `v3:tch:queue` (12 байт).
- Ученическая карточка ДЗ: `v3:stu:hw_view:<id>` (длина от 18 до 24 байт).
- Домашний экран: `v3:nav:home` (11 байт).

Все значения строго укладываются в лимит 64 байт и покрыты автоматическим тестом `test_in_bot_callbacks_length_and_structure`.

