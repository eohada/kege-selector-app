# 🔍 Быстрая диагностика уведомлений о рефералах

## Выполните эти SQL запросы на вашем сервере:

### 1. Проверьте BotAdmin'ов
```sql
SELECT
  ba.admin_id,
  ba.user_id,
  u.username,
  up.telegram_chat_id,
  up.telegram_notifications_enabled,
  up.tg_notify_referral_used
FROM "BotAdmins" ba
JOIN "Users" u ON u.id = ba.user_id
LEFT JOIN "UserProfiles" up ON up.user_id = ba.user_id
WHERE ba.is_active = TRUE;
```

**Ожидаемый результат:**
- `telegram_chat_id`: число (не NULL)
- `telegram_notifications_enabled`: TRUE
- `tg_notify_referral_used`: TRUE

### 2. Проверьте последние уведомления
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
LIMIT 5;
```

**Ожидаемый результат:**
- Должны быть строки с `telegram_sent = FALSE`
- Если все `telegram_sent = TRUE`, значит urep_bot их обработал

### 3. Проверьте, что urep_bot может прочитать
```sql
SELECT
  un.notification_id,
  un.user_id,
  un.kind,
  un.title,
  up.telegram_chat_id,
  up.tg_notify_referral_used
FROM "UserNotifications" un
JOIN "UserProfiles" up ON up.user_id = un.user_id
WHERE un.telegram_sent = FALSE
  AND un.kind = 'referral_used'
  AND up.telegram_chat_id IS NOT NULL
  AND (up.telegram_notifications_enabled = TRUE OR up.telegram_notifications_enabled IS NULL)
  AND un.created_at > NOW() - INTERVAL '24 hours';
```

**Ожидаемый результат:**
- Должны быть строки, которые urep_bot должен обработать

### 4. Проверьте логи urep_bot
Посмотрите логи urep_bot:
```bash
# Найдите процесс
ps aux | grep urep_bot

# Посмотрите логи (если логируются в файл)
tail -f /path/to/urep_bot.log
```

Ищите сообщения вроде:
- "Sent X notifications to Telegram"
- "Failed to send notification to chat_id=..."

### 5. Ручная отправка тестового уведомления
```python
from app import create_app
from app.models import db, UserNotification

app = create_app()
with app.app_context():
    # Создайте тестовое уведомление для себя
    notif = UserNotification(
        user_id=YOUR_USER_ID,  # Замените на ваш user_id
        kind='referral_used',
        title='Тестовое уведомление',
        body='Это тест',
        telegram_sent=False
    )
    db.session.add(notif)
    db.session.commit()
    print(f"Created notification ID: {notif.notification_id}")
```

Затем подождите 30 секунд и проверьте, пришло ли в Telegram.

---

## Возможные проблемы:

### ❌ Urep_bot не запущен
**Симптомы:** Уведомления остаются с `telegram_sent = FALSE`
**Решение:** Запустите urep_bot

### ❌ Urep_bot использует другую БД
**Симптомы:** Urep_bot не видит уведомления
**Решение:** Проверьте `DATABASE_URL` в `.env` для urep_bot

### ❌ Настройки уведомлений выключены
**Симптомы:** `tg_notify_referral_used = FALSE`
**Решение:** Включите в профиле пользователя

### ❌ Ошибка отправки в Telegram
**Симптомы:** В логах urep_bot ошибки "blocked by the user" или "chat not found"
**Решение:** Перепривяжите Telegram: `/unlink` затем `/link КОД`

---

## Что делать, если ничего не помогает:

1. **Остановите urep_bot**
2. **Запустите в режиме отладки:**
   ```bash
   python urep_bot/run_bot.py  # Добавьте логирование
   ```
3. **Создайте тестовое уведомление** (см. шаг 5)
4. **Посмотрите логи** — должно быть видно, пытается ли бот отправить

Сообщите результаты диагностики! 🔍