# Быстрый старт: Проверка и перенос данных

## ✅ Что уже сделано

Вы уже:
- ✅ Создали проект "Databases" в Railway
- ✅ Создали 3 базы данных (production-db, sandbox-db, admin-db)
- ✅ Добавили переменные `DATABASE_URL` в сервисы

## 🔍 Шаг 1: Проверка подключений

### Способ 1: Через Railway Shell (самый простой)

1. **Откройте Railway Shell в Production сервисе:**
   - Production сервис → Settings → Shell → Open Shell

2. **Запустите проверку:**
   ```bash
   python scripts/verify_railway_databases.py
   ```

3. **Что должно быть:**
   ```
   ✅ Production DB: Подключение успешно
   ✅ Sandbox DB: Подключение успешно  
   ✅ Admin DB: Подключение успешно
   ```

### Способ 2: Через веб-интерфейс

1. Откройте приложение в браузере:
   - Production: `https://ваш-production.up.railway.app`
   - Sandbox: `https://ваш-sandbox.up.railway.app`

2. Если страница загружается без ошибок 500 - все хорошо!

## 📦 Шаг 2: Перенос данных (если нужно)

⚠️ **Этот шаг нужен только если у вас уже есть данные в старых базах!**

### Для Production:

1. **Найдите старую Production базу:**
   - Найдите старый Production сервис в Railway
   - Скопируйте `DATABASE_URL` из Variables

2. **Найдите новую Production базу:**
   - Проект "Databases" → "production-db" → Variables → `DATABASE_URL`

3. **Откройте Railway Shell в Production сервисе**

4. **Запустите миграцию:**
   ```bash
   export OLD_PRODUCTION_DATABASE_URL="postgresql://старая_база"
   export NEW_PRODUCTION_DATABASE_URL="postgresql://новая_база_production-db"
   python scripts/migrate_to_centralized_db.py production
   ```

### Для Sandbox:

1. **Найдите старую Sandbox базу:**
   - Найдите старый Sandbox сервис в Railway
   - Скопируйте `DATABASE_URL` из Variables

2. **Найдите новую Sandbox базу:**
   - Проект "Databases" → "sandbox-db" → Variables → `DATABASE_URL`

3. **Откройте Railway Shell в Sandbox сервисе**

4. **Запустите миграцию:**
   ```bash
   export OLD_SANDBOX_DATABASE_URL="postgresql://старая_база"
   export NEW_SANDBOX_DATABASE_URL="postgresql://новая_база_sandbox-db"
   python scripts/migrate_to_centralized_db.py sandbox
   ```

## 🎯 Шаг 3: Проверка результата

1. **Проверьте логи миграции:**
   - Должно быть: `✅ Перенос завершен! Всего записей: X`

2. **Проверьте приложение:**
   - Откройте Production/Sandbox в браузере
   - Убедитесь, что данные отображаются

3. **Проверьте подключения еще раз:**
   ```bash
   python scripts/verify_railway_databases.py
   ```

## ❓ Частые вопросы

### Базы пустые - это нормально?

**Да!** Новые базы пустые по умолчанию. Приложение автоматически создаст таблицы при первом запуске.

### Как проверить, что таблицы созданы?

```bash
python scripts/verify_railway_databases.py
```

Должно показать: `✅ Найдено таблиц: X`

### Ошибка "URL не установлен"

Проверьте, что в каждом сервисе установлена переменная `DATABASE_URL`:
- Production сервис → Variables → `DATABASE_URL` = (из production-db)
- Sandbox сервис → Variables → `DATABASE_URL` = (из sandbox-db)
- Admin сервис → Variables → `DATABASE_URL` = (из admin-db)

### Ошибка подключения

1. Проверьте, что БД работает (зеленый индикатор в Railway)
2. Проверьте, что `DATABASE_URL` правильный (скопируйте заново)
3. Убедитесь, что используете правильный URL (не внутренний Railway URL)

## 🔄 Миграции схемы (колонки, таблицы)

**Отдельный скрипт для синхронизации запускать не нужно.** Миграции схемы (новые колонки вроде `Users.numeric_id`, таблица `UserRoles`, бэкфилл ролей и т.п.) выполняются **автоматически при старте приложения**: при подключении к БД вызывается `ensure_schema_columns(app)`. Достаточно задеплоить новую версию и перезапустить сервис — после первого запуска схема будет обновлена.

## 📚 Дополнительная документация

- **Полная инструкция:** `docs/RAILWAY_DATABASE_SETUP_STEP_BY_STEP.md`
- **Быстрая проверка:** `docs/QUICK_DATABASE_CHECK.md`
- **Устранение проблем:** см. раздел "Устранение проблем" в основной документации
