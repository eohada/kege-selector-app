# Исправление ошибки: "can't compare offset-naive and offset-aware datetime"

## 🔴 Ошибка
```
can't compare offset-naive and offset-aware datetime
```

**Причина:** Python не может сравнивать datetime объекты разных типов:
- `moscow_now()` возвращает **timezone-aware** datetime (с `Europe/Moscow`)
- `assignment.deadline` в БД может быть **timezone-naive** (без timezone)
- Сравнение `aware > naive` → ошибка

## ✅ Решение

### 1. Helper функция для нормализации (app/assignments/routes.py)
Добавлена функция `_ensure_aware_datetime(dt)`:
```python
def _ensure_aware_datetime(dt):
    """Конвертирует naive datetime в aware (Moscow timezone)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MOSCOW_TZ)
    return dt
```

### 2. Исправлены функции в routes.py

#### `submission_start()` (строка 1605)
- ДО: `if now > submission.assignment.deadline and submission.assignment.hard_deadline:`
- ПОСЛЕ:
  ```python
  deadline = _ensure_aware_datetime(submission.assignment.deadline)
  if deadline and now > deadline and submission.assignment.hard_deadline:
  ```

#### `submission_submit()` (строка 1745)
- ДО: `is_late = now > assignment.deadline`
- ПОСЛЕ:
  ```python
  deadline = _ensure_aware_datetime(assignment.deadline)
  is_late = deadline and now > deadline
  ```

#### `submission_view()` (строка 1566)
- ДО: `deadline_naive = assignment.deadline.replace(tzinfo=None) if assignment.deadline.tzinfo else assignment.deadline`
- ПОСЛЕ: `deadline = _ensure_aware_datetime(assignment.deadline)`

#### `_derive_flags()` (строка 720)
- Добавлена нормализация deadline перед сравнением

#### Список сравнений (строка 809)
- Добавлена нормализация deadline для сравнений

### 3. Импорты
Добавлен импорт `MOSCOW_TZ`:
```python
from core.db_models import SubmissionComment, MOSCOW_TZ
```

## 🧪 Результат

Теперь при нажатии на "Начать выполнение":
- Все datetime сравниваются корректно
- Сервер возвращает JSON `{"success": true}` вместо HTTP 500
- Страница обновляется и работа переходит в статус `IN_PROGRESS`

## 📝 Общий подход

**Правило:** Всегда используй `_ensure_aware_datetime()` перед сравнением с `moscow_now()`.

Вместо:
```python
if now > assignment.deadline:  # ОШИБКА!
```

Пиши:
```python
deadline = _ensure_aware_datetime(assignment.deadline)
if deadline and now > deadline:  # OK
```
