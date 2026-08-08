---
status: untouched
domain: Telegram Интеграция
type: read-only
---
# Telegram Mini App

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Авторизация_и_Вход]]
- [[Дашборд_Ученика]]

## 💻 Текущий бэкенд
- **Роуты:** `/telegram/webapp`, `/telegram/auth` (Файл: `app/telegram/mini_app.py`)
- **Таблицы БД:** `telegram_start_leads`, `users`
- **Связанные макеты:** `templates/telegram/mini_app.html`

## 📝 План интеграции
Адаптированный веб-интерфейс платформы для запуска внутри Telegram WebApp.
