# Как использовать диагностику для сравнения Production и Sandbox

## ⚠️ Важно: Код должен быть задеплоен

Диагностический endpoint будет доступен только после деплоя изменений на Railway.

## Шаг 1: Проверьте, что код задеплоен

1. Откройте Railway проект
2. Проверьте, что последний коммит задеплоен в оба окружения (production и sandbox)
3. Дождитесь завершения деплоя

## Шаг 2: Проверьте доступность тестового endpoint

Перед использованием полной диагностики, проверьте, что endpoint зарегистрирован:

- **Production**: `https://kege-selector-staging-production.up.railway.app/admin/diagnostics/test`
- **Sandbox**: `https://kege-selector-staging-sandbox.up.railway.app/admin/diagnostics/test`

Должен вернуться JSON:
```json
{
  "status": "OK",
  "message": "Диагностический endpoint доступен",
  "endpoint": "/admin/diagnostics",
  "note": "Для полной диагностики требуется авторизация"
}
```

Если этот endpoint не работает - значит код еще не задеплоен или есть ошибка.

## Шаг 3: Войдите в систему

1. Откройте любой из сайтов:
   - Production: https://kege-selector-staging-production.up.railway.app/
   - Sandbox: https://kege-selector-staging-sandbox.up.railway.app/

2. Войдите в систему (используйте свои учетные данные)

## Шаг 4: Откройте диагностику

После входа откройте в браузере:

- **Production**: `https://kege-selector-staging-production.up.railway.app/admin/diagnostics`
- **Sandbox**: `https://kege-selector-staging-sandbox.up.railway.app/admin/diagnostics`

## Шаг 5: Сравните данные

Откройте диагностику в обоих окружениях и сравните:

### Что проверять:

1. **Окружение**:
   - `ENVIRONMENT` должен быть `production` или `sandbox`
   - `RAILWAY_ENVIRONMENT` должен отличаться

2. **База данных**:
   - **Подключение**: Должно быть "OK" в обоих
   - **Таблиц в БД**: Должно быть одинаковое количество
   - **Данные**: 
     - Production: должно быть много данных
     - Sandbox: может быть пустая БД (0 учеников, 0 уроков) - это нормально для тестового окружения

3. **Приложение**:
   - `SECRET_KEY` должен быть установлен в обоих
   - `CSRF защита` должна быть включена

## Если диагностика не открывается

### Вариант 1: Код не задеплоен

**Симптомы**: 404 ошибка при открытии `/admin/diagnostics`

**Решение**:
1. Убедитесь, что изменения закоммичены в git
2. Проверьте, что Railway автоматически задеплоил изменения
3. Дождитесь завершения деплоя

### Вариант 2: Ошибка при импорте

**Симптомы**: 500 ошибка или ошибки в логах Railway

**Решение**:
1. Откройте Railway → Deployments → последний деплой
2. Просмотрите логи запуска
3. Найдите ошибки импорта или инициализации
4. Исправьте ошибки и задеплойте снова

### Вариант 3: Не авторизованы

**Симптомы**: Редирект на `/login` или 403 ошибка

**Решение**:
1. Войдите в систему через `/login`
2. После входа откройте `/admin/diagnostics`

## Альтернативный способ: Проверка через логи Railway

Если диагностический endpoint недоступен, можно проверить конфигурацию через логи:

1. Откройте Railway проект
2. Переключитесь на окружение (production или sandbox)
3. Откройте Deployments → последний деплой
4. Просмотрите логи запуска

**Что искать в логах:**
```
=== Application Initialization ===
Environment: production (или sandbox)
Database connection: OK (или FAILED)
Using DATABASE_URL (internal Railway connection)
✓ Database connection: OK
SECRET_KEY set: YES
=== Initialization Complete ===
```

## Быстрая проверка через Railway CLI

Если у вас установлен Railway CLI:

```bash
# Проверка переменных окружения
railway variables --environment production
railway variables --environment sandbox

# Проверка подключения к БД
railway run --environment production python -c "from app import create_app; app = create_app(); print('OK')"
railway run --environment sandbox python -c "from app import create_app; app = create_app(); print('OK')"
```

## Что делать дальше

После того, как вы получили диагностическую информацию:

1. **Сравните данные** между окружениями
2. **Найдите различия** (особенно в количестве данных в БД)
3. **Используйте руководство** `docs/RAILWAY_TROUBLESHOOTING.md` для решения проблем

## Типичные проблемы

### Пустая БД в sandbox

Если в sandbox 0 учеников, 0 уроков - это нормально для тестового окружения. Но если функционал не работает из-за этого:

1. Синхронизируйте данные из production
2. Или создайте тестовые данные вручную

### Ошибка подключения к БД

Если в диагностике "Database connection: ERROR":

1. Проверьте, что PostgreSQL сервис запущен в Railway
2. Проверьте переменную `DATABASE_URL` в настройках окружения
3. Проверьте логи Railway на наличие ошибок подключения

