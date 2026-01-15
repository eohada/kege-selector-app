# Руководство по работе с Railway CLI

## Быстрый старт

### 1. Проверка, что вы залогинены

```bash
railway whoami
```

Должно показать ваш email или имя пользователя.

### 2. Просмотр всех проектов

```bash
railway list
```

Покажет список всех ваших проектов, например:
```
PROJECT ID    NAME
abc123        kege-selector-app
def456        Databases
```

### 3. Выбор проекта

```bash
railway link
```

Railway покажет список проектов, выберите нужный (например, ваш основной проект с сервисами).

Или напрямую по ID:
```bash
railway link <PROJECT_ID>
```

### 4. Просмотр сервисов в проекте

```bash
railway status
```

Покажет текущий проект и сервисы.

### 5. Выбор сервиса (окружения)

Railway CLI работает с окружениями (environments). Чтобы выбрать конкретный сервис:

```bash
# Просмотр всех окружений
railway environment

# Выбор окружения (production/sandbox/admin)
railway environment production
# или
railway environment sandbox
# или
railway environment admin
```

### 6. Открытие Shell в выбранном сервисе

```bash
railway shell
```

Это откроет интерактивный shell внутри выбранного сервиса.

### 7. Запуск скрипта проверки

После открытия shell:

```bash
python scripts/verify_railway_databases.py
```

## Полный пример работы

### Проверка Production базы:

```bash
# 1. Выберите проект
railway link

# 2. Выберите окружение production
railway environment production

# 3. Откройте shell (ВАЖНО: используйте shell, а не run!)
railway shell

# 4. В открывшемся shell выполните:
python scripts/verify_railway_databases.py
```

⚠️ **Почему `railway shell`, а не `railway run`?**
- `railway shell` открывает интерактивный shell внутри Railway контейнера
- Внутри контейнера доступны внутренние Railway URL (например, `postgres-xxx.railway.internal`)
- `railway run` может выполнять команды локально, где внутренние URL недоступны
```

### Проверка Sandbox базы:

```bash
railway link
railway environment sandbox
railway shell
python scripts/verify_railway_databases.py
```

### Проверка Admin базы:

```bash
railway link
railway environment admin
railway shell
python scripts/verify_railway_databases.py
```

## Альтернатива: Через веб-интерфейс (проще!)

Если CLI кажется сложным, можно использовать веб-интерфейс:

1. **Откройте Railway Dashboard:**
   - https://railway.app/dashboard

2. **Выберите проект:**
   - Кликните на ваш проект (например, "kege-selector-app")

3. **Выберите окружение:**
   - Вверху страницы есть выпадающий список с окружениями
   - Выберите "Production", "Sandbox" или "Admin"

4. **Откройте сервис:**
   - Кликните на ваш web сервис (обычно называется как проект)

5. **Откройте Shell:**
   - Перейдите на вкладку **"Settings"** (вверху)
   - Прокрутите вниз до раздела **"Shell"**
   - Нажмите **"Open Shell"** или **"Launch Shell"**

6. **Запустите скрипт:**
   ```bash
   python scripts/verify_railway_databases.py
   ```

## Полезные команды Railway CLI

### Просмотр переменных окружения

```bash
railway variables
```

### Установка переменной

```bash
railway variables set DATABASE_URL="postgresql://..."
```

### Просмотр логов

```bash
railway logs
```

### Просмотр статуса

```bash
railway status
```

### Выполнение команды без открытия shell

⚠️ **Важно:** `railway run` может не работать правильно для команд, которые требуют доступа к внутренним Railway ресурсам (например, базы данных с внутренними URL).

**Рекомендуется использовать `railway shell`** для интерактивного доступа, где команды выполняются внутри Railway контейнера.

Если все же нужно использовать `railway run`, убедитесь, что:
- Команда не требует доступа к внутренним Railway ресурсам
- Или используйте публичные URL для внешних подключений

## Определение окружений

Если не знаете, какие окружения есть в проекте:

```bash
railway environment
```

Покажет список всех окружений.

Если окружений нет или они называются по-другому, можно работать напрямую с сервисами через веб-интерфейс.

## Частые проблемы

### "No project linked"

**Решение:**
```bash
railway link
```

### "No environment selected"

**Решение:**
```bash
railway environment production
# или
railway environment sandbox
# или
railway environment admin
```

### "Command not found: railway"

**Решение:**
Установите Railway CLI:
```bash
# Windows (через npm)
npm install -g @railway/cli

# Или через установщик
# Скачайте с https://railway.app/cli
```

### Не знаю, какие окружения есть

**Решение:**
1. Откройте Railway Dashboard
2. Откройте ваш проект
3. Посмотрите выпадающий список с окружениями вверху страницы
4. Или используйте веб-интерфейс для открытия Shell (проще!)

## Рекомендация

**Для начала используйте веб-интерфейс** - это проще и нагляднее:
1. Railway Dashboard → Проект → Окружение → Сервис → Settings → Shell → Open Shell

**CLI полезен для:**
- Автоматизации (скрипты)
- Быстрого доступа из терминала
- Массовых операций
