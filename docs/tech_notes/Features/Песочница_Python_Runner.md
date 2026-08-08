---
status: untouched
domain: Интерактивный Workspace
type: action
---
# Песочница Python Runner

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Профиль_Пользователя]]

## 💻 Текущий бэкенд
- **Роуты:** `/sandbox/run`, `/api/v1/sandbox/execute` (Файл: `app/sandbox/python_runner.py`, `app/task_workspace/routes.py`)
- **Таблицы БД:** `student_workspace_files`
- **Связанные макеты:** `templates/sandbox/python_runner.html`

## 📝 План интеграции
Онлайн IDE для исполнения кода Python в изоляции. Проверить таймауты выполнения, вывод stdout/stderr и подгрузку датасетов.
