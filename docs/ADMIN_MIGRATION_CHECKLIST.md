# Чеклист для переноса админки в отдельное окружение

## Что нужно проверить/настроить в Railway

### 1. Admin сервис в Railway

**Проверьте:**
- [ ] Создан отдельный сервис для admin окружения
- [ ] Сервис задеплоен и работает
- [ ] Есть доступ к сервису по URL (например: `https://ваш-admin.up.railway.app`)

**Где проверить:**
1. Railway Dashboard → ваш проект
2. Проверьте, есть ли отдельное окружение "Admin" или отдельный сервис
3. Скопируйте URL сервиса

### 2. База данных для Admin

**Проверьте:**
- [ ] В проекте "Databases" создана база "admin-db"
- [ ] В admin сервисе установлена переменная `DATABASE_URL` = (из admin-db)
- [ ] База данных подключена и работает

**Где проверить:**
1. Проект "Databases" → "admin-db" → Variables → скопируйте `DATABASE_URL`
2. Admin сервис → Variables → проверьте `DATABASE_URL`

### 3. Переменные окружения в Admin сервисе

**Обязательные переменные:**
- [ ] `DATABASE_URL` = (из admin-db)
- [ ] `ENVIRONMENT` = `admin`
- [ ] `SECRET_KEY` = (уникальный ключ для admin)

**Переменные для подключения к другим окружениям:**
- [ ] `PRODUCTION_URL` = `https://ваш-production.up.railway.app`
- [ ] `PRODUCTION_ADMIN_TOKEN` = (сгенерируйте токен - см. ниже)
- [ ] `SANDBOX_URL` = `https://ваш-sandbox.up.railway.app`
- [ ] `SANDBOX_ADMIN_TOKEN` = (сгенерируйте токен - см. ниже)
- [ ] `ADMIN_URL` = `https://ваш-admin.up.railway.app`
- [ ] `ADMIN_ADMIN_TOKEN` = (сгенерируйте токен - см. ниже)

**Как сгенерировать токены:**
1. Запустите скрипт: `python scripts/generate_admin_tokens.py`
2. Скрипт выведет все токены и сохранит их в `admin_tokens.txt`
3. **ВАЖНО:** Токены должны быть ОДИНАКОВЫМИ в двух местах:
   - `PRODUCTION_ADMIN_TOKEN` в admin сервисе = `PRODUCTION_ADMIN_TOKEN` в production сервисе
   - `SANDBOX_ADMIN_TOKEN` в admin сервисе = `SANDBOX_ADMIN_TOKEN` в sandbox сервисе
   - `ADMIN_ADMIN_TOKEN` в admin сервисе = `ADMIN_ADMIN_TOKEN` в admin сервисе (если нужно управлять самим собой)

**Где проверить:**
1. Admin сервис → Variables
2. Проверьте все переменные выше

### 4. Создание пользователя в Admin

**Проверьте:**
- [ ] Создан пользователь с ролью `creator` в admin базе
- [ ] Можете войти в admin сервис

**Как создать:**
1. Откройте: `https://ваш-admin.up.railway.app/setup/first-user`
2. Или используйте скрипт: `python scripts/create_user.py admin <пароль> creator`
   (но нужно указать правильный URL в скрипте)

### 5. Проверка работы Remote Admin

**Проверьте:**
- [ ] Можете открыть: `https://ваш-admin.up.railway.app/remote-admin`
- [ ] Видите dashboard с выбором окружений
- [ ] Можете переключаться между окружениями
- [ ] Видите список пользователей из выбранного окружения

## Что нужно сообщить мне

Чтобы я мог продолжить работу, мне нужно знать:

1. **URL admin сервиса:**
   - Например: `https://kege-selector-admin.up.railway.app`

2. **Какие переменные окружения уже установлены:**
   - `DATABASE_URL` установлен?
   - `ENVIRONMENT` установлен?
   - `PRODUCTION_URL`, `SANDBOX_URL`, `ADMIN_URL` установлены?
   - Токены (`PRODUCTION_ADMIN_TOKEN`, `SANDBOX_ADMIN_TOKEN`, `ADMIN_ADMIN_TOKEN`) установлены?

3. **Создан ли пользователь:**
   - Можете ли вы войти в admin сервис?

4. **Что работает, что нет:**
   - Открывается ли `/remote-admin`?
   - Видите ли вы dashboard?
   - Работает ли переключение окружений?

## Следующие шаги после настройки

После того, как вы настроите все выше, я смогу:
1. Перенести все функции админки в remote_admin
2. Создать UI для всех функций
3. Обновить маршруты для работы через API
4. Удалить старые админские маршруты из production/sandbox
