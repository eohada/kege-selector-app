# Исправления url_for после рефакторинга на blueprints

## Проблема
После рефакторинга монолитного `app.py` на blueprints все `url_for` в шаблонах нужно было обновить с префиксами blueprints.

## Исправленные файлы

### 1. templates/login.html
- `url_for('login')` → `url_for('auth.login')`

### 2. templates/user_profile.html
- `url_for('login')` → `url_for('auth.login')`
- `url_for('logout')` → `url_for('auth.logout')`

### 3. templates/_user_menu.html
- `url_for('logout')` → `url_for('auth.logout')`

### 4. templates/student_profile.html
- `url_for("api_templates")` → `url_for("api.api_templates")`
- `url_for('templates_manager.templates_list')` → `url_for('templates.templates_list')`
- `url_for('templates_manager.template_apply', ...)` → `url_for('templates.template_apply', ...)`

### 5. templates/templates_list.html
- Все `templates_manager.*` → `templates.*`

### 6. templates/template_view.html
- Все `templates_manager.*` → `templates.*`

### 7. templates/template_form.html
- Все `templates_manager.*` → `templates.*`

## Соответствие blueprints и префиксов

| Blueprint | Префикс | Пример |
|-----------|---------|--------|
| `auth_bp` | `auth.` | `auth.login`, `auth.logout` |
| `main_bp` | `main.` | `main.dashboard`, `main.index` |
| `students_bp` | `students.` | `students.student_profile` |
| `lessons_bp` | `lessons.` | `lessons.lesson_edit` |
| `admin_bp` | `admin.` | `admin.admin_panel` |
| `kege_generator_bp` | `kege_generator.` | `kege_generator.kege_generator` |
| `api_bp` | `api.` | `api.api_templates` |
| `schedule_bp` | `schedule.` | `schedule.schedule` |
| `templates_bp` | `templates.` | `templates.templates_list` |

## Исключения

- `url_for('static', ...)` - не требует префикса, это встроенный endpoint Flask
- Все остальные endpoints должны иметь префикс blueprint

## Проверка

Используйте скрипт `scripts/check_url_for.py` для проверки всех url_for в шаблонах.

