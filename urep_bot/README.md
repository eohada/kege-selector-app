# URep Telegram Bot

Telegram бот для уведомлений учеников платформы URep.

## Функционал

### Команды
- `/start` — Приветствие и инструкция по привязке
- `/link КОД` — Привязать аккаунт по коду из личного кабинета
- `/unlink` — Отвязать Telegram
- `/me` — Мой профиль (тариф, уроки)
- `/lessons` — Ближайшие уроки
- `/stats` — Статистика
- `/settings` — Настройки уведомлений
- `/help` — Справка

### Автоматические уведомления
- Напоминания об уроках (за 1 час и за 15 минут)
- Результаты проверки ДЗ
- Сообщения от преподавателя
- Предупреждение о заканчивающихся уроках

## Установка

### Локальный запуск

1. Установите зависимости:
```bash
pip install -r urep_bot/requirements.txt
```

2. Создайте файл `.env` в корне проекта:
```env
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:password@host:port/database
APP_URL=https://boostudy.ru/
APP_OPEN_URL=https://boostudy.ru/login
BOT_INTERNAL_TOKEN=your_internal_token
```

3. Запустите бота:
```bash
python urep_bot/run_bot.py
```

### Деплой на Railway

1. Создайте новый сервис в Railway
2. Подключите репозиторий
3. Установите переменные окружения:
   - `BOT_TOKEN` — токен от @BotFather
   - `DATABASE_URL` — URL базы данных (та же что у Flask)
   - `APP_URL` — URL веб-приложения
   - `APP_OPEN_URL` — ссылка для кнопки "Открыть сайт" в боте
   - `BOT_INTERNAL_TOKEN` — токен для привязки аккаунтов через API

4. Установите Start Command:
```
python urep_bot/run_bot.py
```

## Привязка аккаунта

1. Пользователь заходит в личный кабинет на сайте
2. Открывает профиль → "Привязать Telegram"
3. Получает 6-значный код (действителен 10 минут)
4. Отправляет боту команду `/link КОД`
5. Бот подтверждает привязку

## Архитектура

```
urep_bot/
├── __init__.py         # Инициализация модуля
├── bot.py              # Обработчики команд и callback
├── config.py           # Конфигурация
├── db.py               # Подключение к PostgreSQL
├── keyboards.py        # Inline-клавиатуры
├── messages.py         # Тексты сообщений
├── notifications.py    # Фоновые задачи
├── run_bot.py          # Точка входа
├── requirements.txt    # Зависимости
├── Procfile            # Для Railway
└── README.md           # Документация
```

## Конфигурация

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `BOT_TOKEN` | Токен Telegram бота | — |
| `DATABASE_URL` | URL PostgreSQL | — |
| `APP_URL` | URL веб-приложения | https://boostudy.ru/ |
| `APP_OPEN_URL` | Ссылка для кнопки "Открыть сайт" | https://boostudy.ru/login |
| `BOT_INTERNAL_TOKEN` | Токен для привязки аккаунтов | — |
| `BOT_LOG_LEVEL` | Уровень логирования | INFO |

## Получение токена бота

1. Откройте @BotFather в Telegram
2. Отправьте `/newbot`
3. Введите имя бота (например: URep Notifications)
4. Введите username (например: urep_notify_bot)
5. Скопируйте токен

## Лицензия

Проприетарное ПО. Все права защищены.
