---
status: untouched
domain: Администрирование и QA
type: action
---
# QA Тестирование и Баг Репорты

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Админ_Панель_и_Пользователи]]

## 💻 Текущий бэкенд
- **Роуты:** `/qa/testcases`, `/chief_tester/reports` (Файл: `app/qa/routes.py`, `app/chief_tester/routes.py`)
- **Таблицы БД:** `qa_test_cases`, `qa_reports`, `qa_tasks`, `qa_comments`, `platform_bug_reports`
- **Связанные макеты:** `templates/chief_tester/reports.html`

## 📝 План интеграции
Панель для тестировщиков: выполнение тест-кейсов, логирование багов платформы и прикрепление скриншотов.
