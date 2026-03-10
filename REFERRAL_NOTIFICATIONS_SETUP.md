# 🚀 Настройка уведомлений админам о новых рефералах в Telegram

## 📋 Что было сделано

Добавлена система уведомлений в Telegram для администраторов бота при использовании реферального кода:
- Когда пользователь вводит реферальный код и начинает демо-тур, в личку **админам бота** приходит уведомление
- Уведомление содержит: кто создал код, какой пользователь его использовал, в какое время

## ✅ Требования

Для получения уведомлений администратор должен:

### 1. Быть добавленным в таблицу `BotAdmins`

**Проверка:**
```sql
SELECT * FROM "BotAdmins" WHERE is_active = TRUE;
```

**Если админа нет, создать его:**

Вариант А (через скрипт):
```bash
python scripts/setup_bot_admin.py <user_id>
```

Вариант Б (вручную через Python):
```python
from app import create_app
from app.models import db, BotAdmin

app = create_app()
with app.app_context():
    # user_id — ID пользователя в системе
    admin = BotAdmin(user_id=1, is_active=True)
    db.session.add(admin)
    db.session.commit()
    print("✅ BotAdmin создан!")
```

### 2. Привязать Telegram аккаунт

**Как администратор должен привязать Telegram:**

1. Зайти в личный кабинет на сайте
2. Открыть свой профиль (`/auth/profile`)
3. Найти кнопку **"Generate Telegram Link Code"** (или "Привязать Telegram")
4. Скопировать полученный КОД
5. Отправить боту сообщение: `/link КОД`
6. Получить подтверждение ✅

**Проверка привязки в БД:**
```sql
SELECT 
  ba.admin_id,
  u.username,
  up.telegram_chat_id,
  up.telegram_notifications_enabled,
  up.tg_notify_referral_used
FROM "BotAdmins" ba
JOIN "Users" u ON u.id = ba.user_id
LEFT JOIN "UserProfiles" up ON up.user_id = ba.user_id
WHERE ba.is_active = TRUE;
```

**Должны быть:**
- `telegram_chat_id`: **не NULL** (если NULL → администратор не привязал Telegram)
- `telegram_notifications_enabled`: **TRUE**
- `tg_notify_referral_used`: **TRUE** (или NULL, по умолчанию TRUE)

### 3. Убедиться, что urep_bot работает

Фоновый процесс `urep_bot` должен бежать и отправлять уведомления:

```bash
# Проверить, запущен ли процесс
ps aux | grep urep_bot

# Если не запущен, запустить:
python urep_bot/run_bot.py
```

## 🔧 Отладка

### Проблема: Уведомления не приходят

**Шаг 1: Проверьте, созданы ли уведомления в БД**
```sql
SELECT 
  notification_id,
  user_id,
  kind,
  title,
  telegram_sent,
  created_at
FROM "UserNotifications"
WHERE kind = 'referral_used'
ORDER BY created_at DESC
LIMIT 10;
```

**Результаты:**
- **Нет строк**: Уведомления не создаются
  - Проверьте, что реферальный код используется → должна создаться ReferralUsage запись
  - Проверьте, что создатель кода существует в таблице Users
  
- **telegram_sent = FALSE**: Уведомления ждут отправки
  - Проверьте, запущен ли urep_bot
  - Проверьте логи urep_bot на ошибки
  
- **telegram_sent = TRUE, но сообщение не пришло**: Ошибка доставки Telegram
  - Проверьте логи urep_bot: может быть бот заблокирован или chat_id неверный

**Шаг 2: Проверьте, есть ли активные BotAdmin'ы**
```sql
SELECT COUNT(*) FROM "BotAdmins" WHERE is_active = TRUE;
```

Если результат = 0, не будут отправляться уведомления!

**Шаг 3: Проверьте привязку Telegram**
```sql
SELECT 
  ba.user_id,
  u.username,
  up.telegram_chat_id
FROM "BotAdmins" ba
JOIN "Users" u ON u.id = ba.user_id
LEFT JOIN "UserProfiles" up ON up.user_id = ba.user_id
WHERE ba.is_active = TRUE;
```

Если `telegram_chat_id = NULL`, администратор не привязал Telegram.

**Шаг 4: Проверьте, включены ли уведомления**
```sql
SELECT 
  u.username,
  up.telegram_notifications_enabled,
  up.tg_notify_referral_used
FROM "UserProfiles" up
JOIN "Users" u ON u.id = up.user_id
WHERE u.id IN (SELECT user_id FROM "BotAdmins" WHERE is_active = TRUE);
```

Оба значения должны быть **TRUE**.

## 📝 Где что хранится в коде

- **Добавление уведомления**: [app/auth/routes.py](../app/auth/routes.py#L310) — когда используется реферальный код
- **Модель уведомления**: `UserNotification` в [core/db_models.py](../core/db_models.py)
- **Модель BotAdmin**: `BotAdmin` в [core/db_models.py](../core/db_models.py)
- **Отправка в Telegram**: [urep_bot/notifications.py](../urep_bot/notifications.py) — функция `process_pending_notifications()`
- **Шаблон сообщения**: [urep_bot/messages.py](../urep_bot/messages.py#L77) — `'referral_used'`

## 💡 Советы

### Если нужно тестировать локально:

1. **Создайте тестового BotAdmin:**
   ```python
   python scripts/setup_bot_admin.py <your_user_id>
   ```

2. **Привяжите ваш Telegram** (смотрите профиль → Generate Link Code)

3. **Используйте реферальный код** в демо-версии

4. **Проверьте БД:**
   ```sql
   SELECT * FROM "UserNotifications" 
   WHERE kind = 'referral_used' AND telegram_sent = FALSE;
   ```

5. **Убедитесь, что urep_bot бежит:**
   ```bash
   python urep_bot/run_bot.py
   ```

6. **Проверьте логи:)**
   - Сообщение в Telegram должно прийти в течение 30 секунд (интервал проверки)

### Для production:

- `urep_bot` должен висеть как отдельный сервис (systemd, Docker, Heroku dyno и т.д.)
- Переменная окружения `BOT_TOKEN` должна быть установлена
- DATABASE_URL должен указывать на правильную БД

## 🎯 Итого

Система готова! Просто убедитесь, что:
- ✅ BotAdmin создан
- ✅ Telegram привязан (`/link КОД`)
- ✅ Уведомления включены (по умолчанию они включены)
- ✅ urep_bot запущен и слушает уведомления
