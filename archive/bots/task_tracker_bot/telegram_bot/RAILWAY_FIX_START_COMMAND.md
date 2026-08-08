# Как установить команду запуска для бота в Railway (РАБОЧЕЕ РЕШЕНИЕ)

## Проблема

Railway блокирует поле "Start Command" в UI, потому что находит `railway.json` в корне проекта.

## ✅ РАБОЧЕЕ РЕШЕНИЕ: Использовать Root Directory

Railway позволяет установить `rootDirectory` для каждого сервиса. Это заставит Railway искать конфигурацию в указанной директории.

### Шаг 1: Создайте railway.json в директории telegram_bot/

Файл `telegram_bot/railway.json` уже существует с правильной командой:
```json
{
  "deploy": {
    "startCommand": "python telegram_bot/run_bot.py"
  }
}
```

### Шаг 2: Установите Root Directory для сервиса бота

1. Railway Dashboard → сервис **telegram-bot**
2. Settings → Deploy
3. Найдите поле **"Root Directory"** (или **"Service Root"**)
4. Установите: `telegram_bot`
5. Сохраните

Теперь Railway будет искать `railway.json` в директории `telegram_bot/`, а не в корне проекта.

### Шаг 3: Проверьте логи

1. Railway Dashboard → сервис **telegram-bot** (НЕ веб-сервис!)
2. Deployments → последний деплой → Logs
3. Должна появиться строка: `Бот запущен и готов к работе`

## Альтернативное решение: Удалить railway.json из корня

Если Root Directory не работает:

1. Временно переименуйте `railway.json` в `railway.json.backup`
2. Закоммитьте и запушьте
3. В Railway Dashboard для сервиса бота установите команду через UI:
   - Settings → Deploy → Start Command: `python telegram_bot/run_bot.py`
4. Для веб-сервиса тоже установите команду вручную:
   - Settings → Deploy → Start Command: `gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 2 --timeout 120`
5. Верните `railway.json` обратно (или оставьте команды установленными вручную)

## ⚠️ ВАЖНО: Проверьте, что смотрите логи правильного сервиса!

В Railway Dashboard должно быть **ДВА сервиса**:
- Один для веб-приложения (там будут логи gunicorn)
- Один для бота (там должны быть логи бота)

Убедитесь, что вы смотрите логи сервиса **telegram-bot**, а не веб-сервиса!

## Проверка работы

После установки команды запуска:

1. **Проверьте логи сервиса telegram-bot:**
   - Должна быть строка: `Бот запущен и готов к работе`
   - Должна быть информация: `Бот: @your_bot_username (ID: ...)`
   - НЕ должно быть строк про gunicorn!

2. **Отправьте `/start` боту в личке:**
   - Бот должен ответить

3. **Отправьте тестовое сообщение с `#BUG` в группу:**
   - Репорт должен прийти в личку