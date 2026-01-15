# Обязательные переменные окружения для Admin сервиса

## Критически важные (без них приложение не запустится):

```
DATABASE_URL=<URL из admin-db>
ENVIRONMENT=admin
SECRET_KEY=<уникальный ключ для admin>
```

## Для подключения к другим окружениям (опционально, но рекомендуется):

```
PRODUCTION_URL=https://ваш-production.up.railway.app
PRODUCTION_ADMIN_TOKEN=<токен>
SANDBOX_URL=https://ваш-sandbox.up.railway.app
SANDBOX_ADMIN_TOKEN=<токен>
ADMIN_URL=https://ваш-admin.up.railway.app
ADMIN_ADMIN_TOKEN=<токен>
```

## Где проверить:

1. Railway Dashboard → ваш проект → Admin сервис
2. Вкладка "Variables"
3. Убедитесь, что все переменные выше установлены

## Если деплой не проходит:

1. Проверьте логи в Railway → Admin сервис → Deployments → последний деплой
2. Убедитесь, что `DATABASE_URL` указывает на правильную базу данных
3. Убедитесь, что `SECRET_KEY` установлен (не может быть пустым)
4. Проверьте, что база данных `admin-db` создана и работает

## Проверка после деплоя:

1. Откройте: `https://ваш-admin.up.railway.app/health`
2. Должен вернуться JSON с `"status": "OK"`
3. Если ошибка - проверьте логи в Railway
