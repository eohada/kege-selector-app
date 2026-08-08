---
status: untouched
domain: Ученики и Статистика
type: read-only
---
# Статистика и MMR

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Дашборд_Ученика]]

## 💻 Текущий бэкенд
- **Роуты:** `/students/stats`, `/analytics/mmr` (Файл: `app/students/routes.py`, `app/analytics/engine.py`)
- **Таблицы БД:** `student_task_statistics`, `user_task_mmr`, `analytics_events`
- **Связанные макеты:** `templates/students/stats.html`

## 📝 План интеграции
Визуализация графиков MMR и точности решения задач по темам. Проверить корректность вычислений рейтинга ученика.
