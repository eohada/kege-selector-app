# Централизованное управление базами данных в Railway

## Проблема

- БД разбросаны по разным окружениям
- Сложно понять, какая БД к какому сервису относится
- Постоянные 500 ошибки из-за неправильных подключений
- Сложно синхронизировать структуру БД между окружениями

## Решение: Централизованная структура БД

### Вариант 1: Отдельный проект для БД (рекомендуется) ✅

Создайте отдельный Railway проект только для баз данных:

```
Railway Project: "Databases"
├── PostgreSQL: production-db
├── PostgreSQL: sandbox-db  
└── PostgreSQL: admin-db
```

**Преимущества:**
- ✅ Все БД в одном месте
- ✅ Легко видеть статус всех БД
- ✅ Простое управление connection strings
- ✅ Можно легко создавать бэкапы
- ✅ Изоляция от приложений

**Как настроить:**

1. Создайте новый проект в Railway: "Databases" или "DB Management"
2. Создайте 3 PostgreSQL сервиса:
   - `production-db`
   - `sandbox-db`
   - `admin-db`
3. Скопируйте `DATABASE_URL` из каждого сервиса
4. В ваших приложениях используйте эти URL как переменные окружения

**В production сервисе:**
```bash
DATABASE_URL=<из production-db>
```

**В sandbox сервисе:**
```bash
DATABASE_URL=<из sandbox-db>
```

**В admin сервисе:**
```bash
DATABASE_URL=<из admin-db>
```

### Вариант 2: Общая БД с префиксами схем (для тестирования) ⚠️

Используйте одну БД, но с разными схемами:

```sql
-- Схема для production
CREATE SCHEMA production;

-- Схема для sandbox
CREATE SCHEMA sandbox;

-- Схема для admin
CREATE SCHEMA admin;
```

**Недостатки:**
- ❌ Нет полной изоляции
- ❌ Риск конфликтов
- ❌ Сложнее управлять

### Вариант 3: Database Service с переменными (гибридный) ✅

Создайте отдельный сервис, который хранит только connection strings:

```
Railway Project: "Main App"
├── Environment: Production
│   ├── Web Service
│   └── PostgreSQL (production-db)
├── Environment: Sandbox
│   ├── Web Service
│   └── PostgreSQL (sandbox-db)
└── Environment: Admin
    ├── Web Service
    └── PostgreSQL (admin-db)
```

Но используйте **Shared Variables** для управления:

1. В Railway создайте **Shared Variables** на уровне проекта
2. Все сервисы будут использовать эти переменные
3. Легко менять connection strings в одном месте

## Рекомендуемая структура (Вариант 1)

### Шаг 1: Создайте проект "Databases"

1. В Railway создайте новый проект: **"Databases"**
2. Создайте 3 PostgreSQL сервиса:
   ```
   production-db
   sandbox-db
   admin-db
   ```

### Шаг 2: Настройте переменные

В каждом сервисе БД Railway автоматически создаст:
- `DATABASE_URL` (внутренний)
- `DATABASE_EXTERNAL_URL` (внешний, если нужен)

### Шаг 3: Используйте в приложениях

**В production сервисе:**
```bash
# Скопируйте из production-db
DATABASE_URL=postgresql://user:pass@host:port/production_db
```

**В sandbox сервисе:**
```bash
# Скопируйте из sandbox-db
DATABASE_URL=postgresql://user:pass@host:port/sandbox_db
```

**В admin сервисе:**
```bash
# Скопируйте из admin-db
DATABASE_URL=postgresql://user:pass@host:port/admin_db
```

## Управление через Railway CLI

Создайте скрипт для управления БД:

```bash
#!/bin/bash
# scripts/manage_databases.sh

# Получить все DATABASE_URL
railway variables --project databases | grep DATABASE_URL

# Обновить DATABASE_URL в production
railway variables set DATABASE_URL=<новый_url> --service production-web

# Проверить подключение
railway run --service production-web python -c "from app import db; db.engine.connect()"
```

## Автоматическая синхронизация структуры

Создайте скрипт для синхронизации схемы БД:

```python
# scripts/sync_db_schema.py
"""
Синхронизирует структуру БД между окружениями
"""
import os
import sys
sys.path.insert(0, os.path.abspath('.'))

from app import app, db

def sync_schema(source_env, target_env):
    """Синхронизирует схему из source в target"""
    # 1. Подключиться к source БД
    # 2. Экспортировать структуру
    # 3. Применить к target БД
    pass
```

## Мониторинг и диагностика

Создайте единый endpoint для проверки всех БД:

```python
# app/admin/db_health.py
@admin_bp.route('/admin/db-health')
def db_health():
    """Проверка состояния всех БД"""
    databases = {
        'production': os.environ.get('PRODUCTION_DB_URL'),
        'sandbox': os.environ.get('SANDBOX_DB_URL'),
        'admin': os.environ.get('DATABASE_URL')
    }
    
    results = {}
    for name, url in databases.items():
        try:
            # Проверка подключения
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            results[name] = {'status': 'ok', 'url': mask_url(url)}
        except Exception as e:
            results[name] = {'status': 'error', 'error': str(e)}
    
    return jsonify(results)
```

## Миграция существующих БД

Если у вас уже есть БД в разных проектах:

1. **Экспортируйте данные:**
```bash
# Production
pg_dump $PRODUCTION_DATABASE_URL > production_backup.sql

# Sandbox
pg_dump $SANDBOX_DATABASE_URL > sandbox_backup.sql
```

2. **Создайте новые БД в централизованном проекте**

3. **Импортируйте данные:**
```bash
# Production
psql $NEW_PRODUCTION_DATABASE_URL < production_backup.sql

# Sandbox
psql $NEW_SANDBOX_DATABASE_URL < sandbox_backup.sql
```

4. **Обновите переменные окружения в сервисах**

5. **Проверьте работу**

6. **Удалите старые БД**

## Преимущества централизованного подхода

✅ **Единое место управления**
- Все БД видны в одном проекте
- Легко найти нужную БД

✅ **Упрощенное резервное копирование**
- Можно настроить автоматические бэкапы для всех БД
- Легко восстановить из бэкапа

✅ **Мониторинг**
- Видно использование ресурсов всех БД
- Легко отследить проблемы

✅ **Безопасность**
- Централизованное управление доступом
- Легче контролировать кто имеет доступ

✅ **Масштабируемость**
- Легко добавить новую БД
- Простое управление ресурсами

## Чеклист миграции

- [ ] Создать новый проект "Databases" в Railway
- [ ] Создать 3 PostgreSQL сервиса (production, sandbox, admin)
- [ ] Экспортировать данные из существующих БД
- [ ] Импортировать данные в новые БД
- [ ] Обновить `DATABASE_URL` в сервисах приложений
- [ ] Проверить работу всех сервисов
- [ ] Настроить автоматические бэкапы
- [ ] Удалить старые БД (после проверки)

## Устранение 500 ошибок

После централизации БД:

1. **Проверьте connection strings:**
   - Убедитесь, что URL правильные
   - Проверьте, что БД доступны

2. **Проверьте миграции:**
   - Убедитесь, что структура БД создана
   - Запустите миграции если нужно

3. **Проверьте логи:**
   - Railway → Service → Logs
   - Ищите ошибки подключения к БД

4. **Используйте диагностику:**
   - `/admin/diagnostics` - проверка состояния БД
   - `/admin/db-health` - проверка всех БД
