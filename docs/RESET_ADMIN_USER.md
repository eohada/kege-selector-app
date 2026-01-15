# Как создать или сбросить пароль пользователя в admin окружении

## Вариант 1: Через Railway Shell (РЕКОМЕНДУЕТСЯ)

Этот способ работает даже если пользователь уже существует.

### Шаги:

1. **Откройте Railway Dashboard:**
   - Перейдите в ваш проект
   - Выберите admin сервис
   - Откройте вкладку "Deployments" или "Settings"

2. **Запустите скрипт через Railway Shell:**
   ```bash
   railway run python scripts/reset_admin_user.py admin ваш_пароль creator
   ```
   
   Или через Railway CLI:
   ```bash
   railway link  # если еще не привязан
   railway run python scripts/reset_admin_user.py admin ваш_пароль creator
   ```

3. **Параметры:**
   - `admin` - имя пользователя
   - `ваш_пароль` - новый пароль (минимум 8 символов)
   - `creator` - роль (можно не указывать, по умолчанию creator)

### Примеры:

```bash
# Создать/обновить пользователя admin с паролем MyPass123
railway run python scripts/reset_admin_user.py admin MyPass123 creator

# Создать другого пользователя
railway run python scripts/reset_admin_user.py manager SecurePass456 admin
```

## Вариант 2: Через API (только если пользователя еще нет)

Этот способ работает **только если в базе нет пользователей**.

### Шаги:

1. **Обновите URL в скрипте:**
   Откройте `scripts/create_user.py` и измените URL на ваш admin сервис:
   ```python
   url = 'https://ваш-admin.up.railway.app/setup/first-user'
   ```

2. **Запустите скрипт:**
   ```bash
   python scripts/create_user.py admin ваш_пароль creator
   ```

   Или укажите URL через аргумент:
   ```bash
   python scripts/create_user.py admin ваш_пароль creator admin@example.com https://ваш-admin.up.railway.app/setup/first-user
   ```

## Вариант 3: Через веб-интерфейс (только если пользователя еще нет)

1. Откройте в браузере:
   ```
   https://ваш-admin.up.railway.app/setup/first-user
   ```

2. Отправьте POST запрос с JSON:
   ```json
   {
     "username": "admin",
     "password": "ваш_пароль",
     "role": "creator",
     "email": "admin@example.com"
   }
   ```

## Какой вариант выбрать?

- **Если пользователь уже существует** → Используйте Вариант 1 (Railway Shell)
- **Если база пустая** → Можно использовать любой вариант
- **Если нет доступа к Railway CLI** → Используйте Вариант 2 (API) или Вариант 3 (веб)

## Проверка

После создания/сброса пароля:

1. Откройте: `https://ваш-admin.up.railway.app/login`
2. Войдите с новыми учетными данными
3. Должны попасть на dashboard или `/remote-admin`

## Безопасность

⚠️ **Важно:**
- После создания пользователя endpoint `/setup/first-user` автоматически отключается
- Используйте надежные пароли (минимум 8 символов, лучше 12+)
- Не храните пароли в открытом виде
- Удалите файл `admin_tokens.txt` после использования (если создавали токены)
