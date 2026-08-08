---
status: untouched
domain: Telegram Интеграция
type: action
---
# Telegram Уведомления и Бот

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Telegram_Mini_App]]
- [[Центр_Уведомлений]]

## 💻 Текущий бэкенд
- **Роуты:** `/telegram/webhook`, `/telegram/link` (Файл: `app/telegram/webhook.py`, `app/telegram/link_api.py`)
- **Таблицы БД:** `telegram_broadcasts`, `bot_admins`, `bot_error_reports`
- **Связанные макеты:** `templates/telegram/status.html`

## 📝 План интеграции
Отправка дублирующих алертов в Telegram-бот при появлении новых проверок и оценок.
