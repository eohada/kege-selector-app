# Быстрая настройка удаленной админки в Railway

## Шаг 1: Создание сервиса

1. В Railway создайте **новый сервис** (Empty Service или через GitHub Repo)
2. Назовите его, например: `remote-admin` или `admin-panel`

## Шаг 2: Подключение репозитория

### Вариант A: Если создали Empty Service
1. В сервисе перейдите в **Settings** → **Source**
2. Нажмите **"Connect GitHub Repo"**
3. Выберите ваш репозиторий `kege-selector-app`
4. Railway автоматически начнет деплой

### Вариант B: Если создали через GitHub Repo
- Репозиторий уже подключен, деплой начнется автоматически

## Шаг 3: Создание базы данных

1. В Railway в вашем сервисе нажмите **"+ New"** → **"Database"** → **"Add PostgreSQL"**
2. Railway автоматически создаст переменную `DATABASE_URL`
3. БД будет создана автоматически при первом деплое

## Шаг 4: Настройка переменных окружения

В **Settings** → **Variables** добавьте:

### Обязательные переменные для работы приложения:

```bash
# База данных (создана автоматически, но можно проверить)
DATABASE_URL=<автоматически_из_Railway>

# Секретный ключ (сгенерируйте новый уникальный)
SECRET_KEY=<сгенерируйте_новый_уникальный_ключ>

# Окружение
ENVIRONMENT=admin
RAILWAY_ENVIRONMENT=admin
```

### Переменные для подключения к другим окружениям:

```bash
# Production окружение
PRODUCTION_URL=https://ваш-production.up.railway.app
PRODUCTION_ADMIN_TOKEN=<сгенерируйте_токен_1>

# Sandbox окружение  
SANDBOX_URL=https://ваш-sandbox.up.railway.app
SANDBOX_ADMIN_TOKEN=<сгенерируйте_токен_2>

# Admin окружение (само себя)
ADMIN_URL=https://ваш-admin.up.railway.app
ADMIN_ADMIN_TOKEN=<сгенерируйте_токен_3>
```

## Шаг 5: Создание пользователя для входа

После деплоя нужно создать пользователя с ролью "creator":

### Через Railway Shell (самый простой способ):

1. В Railway откройте ваш сервис
2. Перейдите в **Settings** → **Shell**
3. Выполните:
```bash
python scripts/create_tester_user.py admin <ваш_пароль> creator
```

**Пример:**
```bash
python scripts/create_tester_user.py admin MySecurePass123 creator
```

**Результат:**
- ✅ Логин: `admin`
- ✅ Пароль: `MySecurePass123`
- ✅ Роль: `creator`

### Альтернатива: через Railway CLI

```bash
railway run python scripts/create_tester_user.py admin <ваш_пароль> creator
```

## Шаг 6: Настройка токенов в других окружениях

### В Production окружении добавьте:
```bash
PRODUCTION_ADMIN_TOKEN=<тот_же_токен_1>
```

### В Sandbox окружении добавьте:
```bash
SANDBOX_ADMIN_TOKEN=<тот_же_токен_2>
```

## Шаг 7: Проверка работы

1. Дождитесь завершения деплоя (проверьте вкладку **Deployments**)
2. Откройте URL вашего сервиса: `https://ваш-admin.up.railway.app`
3. Перейдите на `/login`
4. Войдите с созданными учетными данными:
   - Логин: `admin` (или тот, что вы указали)
   - Пароль: тот, что вы указали при создании
5. После входа перейдите на `/remote-admin`
6. Выберите окружение (production/sandbox) и проверьте статус

## Генерация токенов

Используйте любой из способов:

### Онлайн:
- https://www.random.org/strings/
- Длина: 32+ символов
- Тип: буквы и цифры

### В терминале (Linux/Mac):
```bash
openssl rand -hex 32
```

### В PowerShell (Windows):
```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | % {[char]$_})
```

## Важно!

⚠️ **Токены должны совпадать:**
- `PRODUCTION_ADMIN_TOKEN` в admin сервисе = `PRODUCTION_ADMIN_TOKEN` в production сервисе
- `SANDBOX_ADMIN_TOKEN` в admin сервисе = `SANDBOX_ADMIN_TOKEN` в sandbox сервисе

⚠️ **База данных:**
- **Обязательно создайте отдельную БД** для admin сервиса
- Это нужно для хранения пользователей админки и сессий
- Не используйте БД из production/sandbox

⚠️ **Пользователь для входа:**
- **Обязательно создайте пользователя** с ролью "creator" после деплоя
- Без этого вы не сможете войти в удаленную админку
- Используйте скрипт `create_tester_user.py` (см. Шаг 5)

⚠️ **SECRET_KEY:**
- Должен быть уникальным для каждого сервиса
- Не используйте один и тот же ключ в разных сервисах

## Структура после настройки

```
Railway Project
├── Production Environment
│   ├── Web Service (production)
│   ├── PostgreSQL DB
│   └── Variables: PRODUCTION_ADMIN_TOKEN=abc123...
│
├── Sandbox Environment  
│   ├── Web Service (sandbox)
│   ├── PostgreSQL DB
│   └── Variables: SANDBOX_ADMIN_TOKEN=def456...
│
└── Admin Environment (или отдельный проект)
    ├── Web Service (admin) ← ваш новый сервис
    ├── PostgreSQL DB (опционально)
    └── Variables:
        ├── PRODUCTION_URL=...
        ├── PRODUCTION_ADMIN_TOKEN=abc123...
        ├── SANDBOX_URL=...
        ├── SANDBOX_ADMIN_TOKEN=def456...
        └── ADMIN_ADMIN_TOKEN=ghi789...
```

## Устранение проблем

### Сервис не деплоится
- Проверьте логи в **Deployments**
- Убедитесь, что репозиторий подключен
- Проверьте, что `requirements.txt` существует

### Ошибка подключения к БД
- Создайте PostgreSQL в Railway
- Скопируйте `DATABASE_URL` в переменные окружения

### Окружения показывают "Не настроено"
- Проверьте, что все `*_URL` и `*_ADMIN_TOKEN` установлены
- Убедитесь, что URL правильные (без слеша в конце)

### Окружения показывают "Недоступно"
- Проверьте, что токены совпадают в обоих сервисах
- Проверьте, что внутренние API работают: `https://your-app.up.railway.app/internal/remote-admin/status`
