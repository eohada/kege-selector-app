# Инициализация прав ролей

## Проблема

Права ролей не были инициализированы из `DEFAULT_ROLE_PERMISSIONS` в базе данных на production и sandbox серверах.

## Решение

Используйте скрипт `scripts/init_role_permissions.py` для инициализации прав.

## Запуск скрипта

### На production сервере:

```bash
railway run --service production python scripts/init_role_permissions.py
```

### На sandbox сервере:

```bash
railway run --service sandbox python scripts/init_role_permissions.py
```

## Что делает скрипт

1. Проверяет наличие таблицы `RolePermissions`
2. Для каждой роли из `DEFAULT_ROLE_PERMISSIONS`:
   - Добавляет права, которых еще нет в базе
   - Включает права, которые были отключены (`is_enabled=False`)
   - Пропускает права, которые уже существуют и включены

## Права по умолчанию

Права определяются в `app/auth/permissions.py` в словаре `DEFAULT_ROLE_PERMISSIONS`:

- **creator**: Все права
- **admin**: Все права
- **chief_tester**: `tools.testers`, `task.manage`, `user.view_list`
- **designer**: `assets.manage`
- **tutor**: `lesson.create`, `lesson.edit`, `user.view_list`, `tools.schedule`, `task.manage`, `assignment.create`, `assignment.grade`, `assignment.view`
- **student**: `assignment.view`
- **parent**: `assignment.view`
- **tester**: Нет прав по умолчанию

## После инициализации

После запуска скрипта все роли будут отображаться в админ-панели с правильными правами по умолчанию.
