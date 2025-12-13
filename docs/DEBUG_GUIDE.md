# Руководство по использованию Debug режима в Cursor

## Что такое Debug режим?

Debug в Cursor - это специальный режим для поиска и исправления ошибок в коде. В отличие от Agent (который пишет новый код) или Plan (который планирует), Debug фокусируется на **диагностике проблем**.

## Как использовать Debug

### 1. Открытие Debug режима

- Нажмите на **"Debug"** в боковой панели Cursor
- Или в чате напишите: `Debug: [ваш вопрос]`

### 2. Типичные запросы для поиска багов

#### Поиск ошибок в конкретном файле:
```
Debug: Find all bugs in app/lessons/routes.py
Debug: Check for errors in app/api/routes.py
Debug: Analyze app/students/routes.py for potential issues
```

#### Поиск типичных проблем:
```
Debug: Find all places where database sessions are not properly closed
Debug: Check for SQL injection vulnerabilities
Debug: Find unused imports in the project
Debug: Check for missing error handling in database operations
Debug: Find potential NoneType errors
Debug: Check for memory leaks
```

#### Поиск проблем безопасности:
```
Debug: Find all places where user input is not validated
Debug: Check for CSRF protection issues
Debug: Find SQL injection vulnerabilities
Debug: Check authentication bypass possibilities
```

#### Поиск проблем производительности:
```
Debug: Find N+1 query problems
Debug: Check for inefficient database queries
Debug: Find missing database indexes
Debug: Check for unnecessary loops
```

## Типичные баги в Flask приложениях

### 1. Проблемы с базой данных

**Проблема:** Незакрытые сессии, отсутствие rollback при ошибках

**Как найти:**
```
Debug: Find all database operations without proper error handling
Debug: Check for missing db.session.rollback() in exception handlers
```

**Пример проблемы:**
```python
# ❌ Плохо
try:
    db.session.add(user)
    db.session.commit()
except Exception as e:
    # Нет rollback!
    return error

# ✅ Хорошо
try:
    db.session.add(user)
    db.session.commit()
except Exception as e:
    db.session.rollback()  # Важно!
    return error
```

### 2. N+1 запросы

**Проблема:** Множественные запросы к БД в циклах

**Как найти:**
```
Debug: Find N+1 query problems in app/lessons/routes.py
Debug: Check for loops that query database
```

**Пример:**
```python
# ❌ Плохо - N+1 запрос
lessons = Lesson.query.all()
for lesson in lessons:
    print(lesson.student.name)  # Новый запрос для каждого урока!

# ✅ Хорошо - один запрос
lessons = Lesson.query.options(joinedload(Lesson.student)).all()
for lesson in lessons:
    print(lesson.student.name)  # Данные уже загружены
```

### 3. Отсутствие проверок на None

**Проблема:** Обращение к атрибутам без проверки существования

**Как найти:**
```
Debug: Find all places where .attribute is accessed without None check
Debug: Check for potential AttributeError in app/students/routes.py
```

**Пример:**
```python
# ❌ Плохо
student_name = lesson.student.name  # Может быть None!

# ✅ Хорошо
student_name = lesson.student.name if lesson.student else None
```

### 4. Проблемы с импортами

**Как найти:**
```
Debug: Find unused imports in app/
Debug: Check for circular imports
Debug: Find missing imports
```

### 5. Проблемы с обработкой форм

**Как найти:**
```
Debug: Check form validation in app/students/forms.py
Debug: Find missing CSRF protection
```

## Практические примеры для вашего проекта

### Пример 1: Проверка обработки ошибок в API

**Запрос:**
```
Debug: Check all API routes in app/api/routes.py for proper error handling and database rollback
```

**Что искать:**
- Все ли `try/except` блоки имеют `db.session.rollback()`?
- Правильно ли обрабатываются исключения?
- Возвращаются ли корректные HTTP статусы?

### Пример 2: Проверка безопасности

**Запрос:**
```
Debug: Find all places where user input is used in database queries without proper validation
```

**Что искать:**
- Прямое использование `request.form.get()` в запросах
- Отсутствие валидации данных
- Потенциальные SQL инъекции

### Пример 3: Проверка производительности

**Запрос:**
```
Debug: Find all database queries in loops that could cause N+1 problems
```

**Что искать:**
- Циклы с запросами к БД внутри
- Отсутствие `joinedload()` или `selectinload()`

### Пример 4: Проверка логики

**Запрос:**
```
Debug: Check app/lessons/utils.py for logical errors in perform_auto_check function
```

**Что искать:**
- Ошибки в логике сравнения ответов
- Проблемы с обработкой граничных случаев
- Неправильные вычисления

## Чеклист для Debug проверки

Перед коммитом проверьте:

- [ ] Все ли ошибки БД обрабатываются с rollback?
- [ ] Нет ли N+1 запросов?
- [ ] Все ли проверки на None присутствуют?
- [ ] Валидируются ли все пользовательские данные?
- [ ] Нет ли утечек памяти?
- [ ] Правильно ли обрабатываются исключения?
- [ ] Нет ли неиспользуемого кода?
- [ ] Все ли импорты используются?

## Автоматизация проверок

### Использование линтеров

Cursor может автоматически находить некоторые проблемы:

```
Debug: Run pylint on app/ directory
Debug: Check for flake8 errors
Debug: Find all type hints issues
```

### Использование статического анализа

```
Debug: Use mypy to check type errors
Debug: Find all potential runtime errors using static analysis
```

## Советы по эффективному использованию Debug

1. **Будьте конкретны:** Вместо "Find bugs" пишите "Find database connection leaks in app/api/"

2. **Проверяйте по модулям:** Разбивайте проверку на части:
   - Сначала проверьте один blueprint
   - Потом другой
   - И так далее

3. **Используйте контекст:** Указывайте, что именно вас беспокоит:
   ```
   Debug: I'm getting database connection errors. Check app/lessons/routes.py for proper session management
   ```

4. **Проверяйте после изменений:** После больших изменений всегда запускайте:
   ```
   Debug: Check for regressions after recent changes
   ```

## Примеры реальных проблем в вашем проекте

### Проблема 1: Отсутствие rollback в некоторых местах

**Найдено в:** `app/api/routes.py` - в целом хорошо, но стоит проверить все места

**Как исправить:**
```python
try:
    # операции с БД
    db.session.commit()
except Exception as e:
    db.session.rollback()  # Всегда добавляйте!
    logger.error(f'Error: {e}')
    return error_response
```

### Проблема 2: Потенциальные N+1 запросы

**Проверьте:**
- `app/lessons/routes.py` - загрузка заданий
- `app/students/routes.py` - загрузка уроков студента

**Исправление:**
```python
# Используйте joinedload
lessons = Lesson.query.options(
    joinedload(Lesson.student),
    joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
).all()
```

## Заключение

Debug режим в Cursor - мощный инструмент для поддержания качества кода. Используйте его регулярно, особенно:

- Перед коммитом изменений
- После больших рефакторингов
- При появлении странных ошибок
- Перед релизом

Помните: лучше найти баг до продакшена, чем после!

