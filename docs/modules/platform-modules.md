# Модули основной платформы

## 1. Что считается основной платформой

Под основной платформой в этом документе понимаются:

- `app/`
- `core/`
- `templates/`
- `static/`
- связанные migration/config/runtime точки входа

## 2. Shell приложения

### `app/__init__.py`

Главный orchestration-файл проекта. Здесь:

- собирается Flask application object;
- выбирается база данных;
- настраиваются security и интеграции;
- подключаются blueprints;
- инициализируются SocketIO и in-process workers;
- задаются global error handlers и filters.

Любое крупное изменение платформы почти всегда касается этого файла прямо или косвенно.

### `app/models/`

Тонкий export-layer поверх `core.db_models`. Не следует документировать его как отдельную модельную подсистему.

## 3. Группы blueprints

### Базовые и навигационные

| Модуль | Роль |
|--------|------|
| `app/auth/` | Вход, выход, профиль, права доступа, RBAC helper-логика |
| `app/main/` | Главная, dashboard, health, presence и ряд общих страниц |

### Учебный и академический контур

| Модуль | Роль |
|--------|------|
| `app/students/` | Ученики, профили, статистика, аналитика |
| `app/lessons/` | Уроки, classroom, task flows, review, auto-complete logic |
| `app/assignments/` | Работы, submissions, grading, autosave |
| `app/schedule/` | Календарь и schedule-инфраструктура |
| `app/task_generator/` | Генерация/подбор заданий для работы с банком |
| `app/templates_manager/` | Шаблоны уроков и related CRUD |
| `app/theory/` | Теория и CMS-подобное управление учебными материалами |

### Организационный и продуктовый контур

| Модуль | Роль |
|--------|------|
| `app/courses/` | Курсы и структура модулей |
| `app/groups/` | Группы учеников и групповые операции |
| `app/library/` | Библиотека материалов |
| `app/parents/` | Кабинет родителей |
| `app/billing/` | Планы, тарифы, подписки |
| `app/reminders/` | Напоминания |
| `app/notifications/` | In-app уведомления и их состояния |

### Административный и сервисный контур

| Модуль | Роль |
|--------|------|
| `app/admin/` | Главная админка, аудит, maintenance, user/tester management |
| `app/remote_admin/` | Remote admin UI и API |
| `app/api/` | JSON API и интеграционные endpoints |
| `app/qa/` | QA/god mode и средовые манипуляции |
| `app/chief_tester/` | Кабинет главного тестировщика |

### Интеграции внутри платформы

| Модуль | Роль |
|--------|------|
| `app/trainer/` | Встраивание trainer и internal trainer API |
| `app/uploads/` | Файловые endpoints и upload flows |
| `app/storage/` | Storage abstraction + upload endpoint |
| `app/telegram/` | Webhook, notifications, handlers, Mini App |

## 4. Cross-cutting пакеты

### `app/utils/`

Shared helpers, которые используются во множестве контуров:

- hooks;
- DB migration helpers;
- Jinja filters;
- trainer tokens;
- subscription access;
- cross-env login;
- вспомогательные ID/formatting helpers.

### `app/analytics/`

Analytics engine и конфигурация аналитики. Формально не оформлен как отдельный blueprint, но логически влияет на `students`, `api`, `trainer`, `assignments`, `lessons`.

### `app/tasks/`

Именованные task entrypoints:

- notifications;
- submissions;
- Telegram deadlines, digests, reminders, broadcasts;
- code checking.

Это operational-cross-cutting слой, а не пользовательский HTTP UI.

## 5. `core/`

### `core/db_models.py`

Единый источник истины по схеме данных. Если меняется структура моделей, документация и миграции должны синхронно обновляться относительно этого файла.

### `core/selector_logic.py`

Логика подбора/селекции заданий и related domain behavior.

### `core/audit_logger.py` и `core/audit_decorators.py`

Основа audit-контура проекта.

## 6. Шаблоны и статика

### `templates/`

Jinja-шаблоны для всех пользовательских и административных интерфейсов. Исторически это одна из самых разросшихся зон проекта.

### `static/`

Содержит:

- JS-модули проекта;
- CSS;
- `dist/` с собранным стилевым артефактом;
- KaTeX и другие сторонние ассеты;
- icons/fonts/media.

## 7. Dormant и неоднозначные модули

Есть HTTP-пакеты, которые выглядят рабочими, но не регистрируются в `create_app()`:

- `app/kege_generator/`
- `app/designer/`
- `app/onboarding/`
- `app/rubrics/`

Перед использованием или удалением этих областей нужно отдельно проверить фактическую связность с остальным проектом.

## 8. Где обычно искать изменения

### Если ломается пользовательский flow

Чаще всего затронуты:

- `app/main/`
- `app/students/`
- `app/lessons/`
- `app/assignments/`
- `templates/`

### Если ломается интеграция

Чаще всего затронуты:

- `app/trainer/`
- `app/telegram/`
- `app/storage/`
- `app/uploads/`
- env vars в `app/__init__.py`

### Если ломаются права или админские сценарии

Смотрите:

- `app/auth/permissions.py`
- `app/auth/rbac_utils.py`
- `app/admin/`
- `app/remote_admin/`
- `app/qa/`
