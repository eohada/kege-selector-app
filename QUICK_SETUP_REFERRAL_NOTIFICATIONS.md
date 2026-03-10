# ✅ БЫСТРЫЙ ЧЕКЛИСТ: Включение уведомлений о рефералах в Telegram

## Что было добавлено:
- ✅ Уведомления админам при использовании реферального кода
- ✅ Логирование для отладки
- ✅ Обработка ошибок

## Как включить (4 шага):

### Шаг 1: Создать BotAdmin для администратора
```bash
python scripts/setup_bot_admin.py <user_id>
```
Или найти админа автоматически:
```bash
python scripts/setup_bot_admin.py
```

### Шаг 2: Администратор привязывает Telegram
1. Зайти на сайт → Профиль
2. Кнопка "Generate Telegram Link Code"
3. Скопировать КОД
4. Отправить боту: `/link КОД`

### Шаг 3: Запустить urep_bot (если не запущен)
```bash
python urep_bot/run_bot.py
```

### Шаг 4: Тестировать
- Использовать реферальный код в демо
- Проверить, пришло ли уведомление в Telegram

---

## Если уведомления не приходят:

### Проверка 1: BotAdmin создан?
```sql
SELECT * FROM "BotAdmins" WHERE is_active = TRUE;
```
❌ Нет → выполните **Шаг 1**
✅ Да → переход к Проверке 2

### Проверка 2: Telegram привязан?
```sql
SELECT u.username, up.telegram_chat_id 
FROM "UserProfiles" up
JOIN "Users" u ON u.id = up.user_id
WHERE u.id IN (SELECT user_id FROM "BotAdmins" WHERE is_active = TRUE);
```
❌ telegram_chat_id = NULL → выполните **Шаг 2**
✅ Есть chat_id → переход к Проверке 3

### Проверка 3: Уведомления включены?
```sql
SELECT u.username, up.telegram_notifications_enabled, up.tg_notify_referral_used
FROM "UserProfiles" up
JOIN "Users" u ON u.id = up.user_id
WHERE u.id IN (SELECT user_id FROM "BotAdmins" WHERE is_active = TRUE);
```
❌ FALSE → включить опцию в профиле администратора
✅ TRUE → переход к Проверке 4

### Проверка 4: urep_bot запущен?
```bash
ps aux | grep urep_bot
```
❌ Не запущен → выполните **Шаг 3**
✅ Запущен → проверьте логи на ошибки

### Проверка 5: Уведомления в БД?
```sql
SELECT * FROM "UserNotifications" 
WHERE kind = 'referral_used' 
ORDER BY created_at DESC 
LIMIT 5;
```
❌ Пусто → реферальный код не используется или есть ошибка в приложении
✅ Есть → проверьте поле `telegram_sent`:
  - FALSE → urep_bot еще не отправил (подождите или перезагрузите)
  - TRUE → отправлено успешно (но может быть ошибка на стороне Telegram)

---

## Логирование для отладки:

Уведомления теперь логируются. Смотрите вывод приложения:
```
📢 Уведомляю 1 админов(ы) о новом реферале: MYCODE123
✅ Уведомление добавлено админу с ID 1 о реферале MYCODE123
```

Если видите ошибки — проверьте шаги выше.

---

## Файлы, которые были изменены:

1. **app/auth/routes.py** — добавлена отправка уведомлений BotAdmin'ам с логированием
2. **scripts/setup_bot_admin.py** — новый скрипт для создания BotAdmin
3. **DEBUG_REFERRAL_NOTIFICATIONS.md** — полная инструкция по отладке
4. **REFERRAL_NOTIFICATIONS_SETUP.md** — подробная документация

---

## 💡 Дополнительно:

Если нужно, чтобы уведомления отправлялись **только админам** (без создателя кода):
```python
# Удалите блок с notify_user для creator_id
# Оставьте только блок с BotAdmin'ами
```

Если нужно, чтобы **и создатель, и админы** получали уведомления (текущее поведение):
```python
# Всё уже настроено как нужно ✅
```
