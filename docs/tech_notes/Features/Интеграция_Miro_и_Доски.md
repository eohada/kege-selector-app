---
status: untouched
domain: Уроки и Вебинары
type: action
---
# Интеграция Miro и Доски

**Статус интеграции:** #status/untouched (Серый - заглушка)

## 🔗 Зависимости (Что должно быть готово ДО интеграции этой фичи)
- [[Комната_Урока]]

## 💻 Текущий бэкенд
- **Роуты:** `/lessons/miro/token`, `/lessons/whiteboard/<int:id>` (Файл: `app/lessons/miro_service.py`)
- **Таблицы БД:** `miro_user_tokens`, `lesson_whiteboards`
- **Связанные макеты:** `templates/sandbox/lesson_room.html`

## 📝 План интеграции
Интеграция фрейма интерактивной доски Miro или собственного canvas-хоста в UI вебинарной комнаты.
