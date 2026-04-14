# Единый handbook проекта

Этот файл — единая обзорная точка входа для всех ролей сразу:

- владельца или менеджера проекта;
- пользователя платформы;
- разработчика;
- администратора и оператора;
- человека, который просто пытается быстро понять, что здесь происходит.

Если нужен один файл “обо всём сразу”, начинать нужно с него.

## 1. Что это за проект

Это платформа подготовки к ЕГЭ по информатике, построенная вокруг Flask-приложения с дополнительными подсистемами:

- управление учениками, уроками, заданиями и теорией;
- расписание, аналитика, уведомления и billing;
- Telegram webhook и Telegram Mini App;
- отдельный Streamlit-тренажёр;
- большой набор служебных скриптов и operational tooling.

## 2. Из чего состоит система

### Основное приложение

- `app/` — Flask blueprints и web-логика;
- `core/` — модели и общая доменная логика;
- `templates/` и `static/` — интерфейс и front-end assets;
- `wsgi.py` — основная web-точка входа;
- `celery_app.py` — фоновый runtime для Celery-сценариев.

### Дополнительные подсистемы

- `trainer_app/` — отдельный Streamlit-тренажёр;
- `app/telegram/` + `urep_bot/` — production Telegram integration;
- `telegram_bot/` — отдельный бот-трекер репортов;
- `scraper/` + `scripts/` — импорт, синхронизация, миграции, диагностика и one-off операции.

## 3. Для пользователя платформы

### Что умеет платформа

- вести учеников и группы;
- планировать и проводить уроки;
- выдавать задания и проверять работы;
- хранить и открывать теорию;
- показывать статистику и аналитику;
- работать с Telegram-сценариями и уведомлениями;
- открывать встраиваемый trainer.

### Какие основные роли есть в системе

- `creator`
- `admin`
- `tutor`
- `student`
- `parent`
- `tester`
- `chief_tester`
- `designer`

### Что обычно открывают пользователи

- dashboard;
- страницы учеников и уроков;
- assignments/submissions;
- theory;
- billing/plans;
- parent dashboard;
- Telegram Mini App.

Если нужен более прикладной пользовательский контекст, смотреть:

- `docs/PLATFORM_USER_GUIDE.md`
- `docs/USER_SCENARIOS.md`
- `docs/PLATFORM_AUDIT_STUDENT_PARENT.md`

## 4. Для разработчика

### С чего начать чтение кода

1. `README.md`
2. `docs/README.md`
3. `docs/PROJECT_STRUCTURE.md`
4. `docs/PROJECT_STRUCTURE_FULL.md`
5. `app/__init__.py`
6. `core/db_models.py`
7. профильный модуль из `docs/modules/`

### Главные технические факты

- основное приложение — Flask монолит на blueprints;
- основная модель данных живёт в `core/db_models.py`;
- основной web entrypoint — `wsgi.py`, не исторический `app.py`;
- PostgreSQL используется как production target, SQLite возможен локально;
- часть background-сценариев живёт через Celery, часть — прямо в Flask runtime;
- trainer — отдельный Streamlit-процесс, но не полностью изолированный сервис.

### Куда смотреть по крупным темам

- архитектура: `docs/architecture/system-overview.md`
- устройство модулей: `docs/modules/platform-modules.md`
- side-services: `docs/modules/side-services.md`
- scripts: `docs/modules/scripts-and-tools.md`
- данные и runtime-артефакты: `docs/modules/data-and-runtime-artifacts.md`

## 5. Для локального запуска

### Базовый поток

1. Установить зависимости:

```bash
pip install -r requirements.txt
```

2. Создать `.env` на основе `.env.example`.

3. Запустить web-приложение:

```bash
python wsgi.py
```

4. При необходимости собрать CSS:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1
```

### Trainer локально

```bash
pip install -r trainer_app/requirements.txt
streamlit run trainer_app/app.py
```

Подробный setup:

- `docs/setup/local-development.md`
- `docs/setup/environment-variables.md`

## 6. Для администратора и оператора

### Что важно знать об окружениях

Проект различает:

- `local`
- `development`
- `sandbox`
- `production`

Основные deploy-источники:

- `.github/workflows/deploy.yml`
- `.github/workflows/deploy_sandbox.yml`
- `.env.example`
- `docker-compose.example.yml`

### Важные operational особенности

- production deploy запускается вручную через GitHub Actions;
- sandbox deploy может запускаться автоматически;
- `docker-compose.example.yml` иллюстративный, а не полноценный self-contained production truth;
- в репозитории нет полноценного канонического `Dockerfile`;
- production Telegram webhook встроен в web runtime, а не обязан жить как отдельный контейнер.

Подробности:

- `docs/operations/deploy-and-environments.md`
- `docs/operations/diagnostics-and-maintenance.md`
- `DEPLOY_TELEGRAM_WEBHOOK.md`

## 7. Переменные окружения

Ключевые группы env vars:

- базовая среда и безопасность;
- DB connection;
- trainer;
- Telegram;
- Miro / Daily;
- uploads и storage;
- admin tokens;
- maintenance и background настройки.

Полный справочник:

- `docs/setup/environment-variables.md`
- `.env.example`

## 8. Скрипты и опасные зоны

`scripts/` нельзя считать просто набором “полезных файлов”. Там рядом лежат:

- bootstrap-утилиты;
- диагностика;
- миграции и data-fixes;
- scraping;
- тестовые harness-скрипты;
- потенциально опасные destructive или prod-writing one-off операции.

Если нужен script, сначала смотреть:

- `docs/modules/scripts-and-tools.md`

Особенно осторожно относиться к:

- delete/fix/sync скриптам;
- production-write сценариям;
- underscore one-off утилитам;
- recovery/backup операциям;
- токен- и доступо-связанным скриптам.

## 9. Что уже признано legacy или шумом

Во время аудита зафиксированы зоны, которые не стоит считать канонической частью текущего продукта без перепроверки:

- `legacy_backup/`
- `boostudy2.0_examples/`
- `qa_testing_files_md/`
- ряд root-level markdown-файлов;
- старые plan/spec документы в `docs/`

Реестр и рекомендации:

- `docs/audit/cleanup-register.md`
- `docs/audit/docs-health.md`

## 10. Как теперь устроена документация

Чтобы docs масштабировалась, она разделена на слои:

- `docs/architecture/` — обзор системы;
- `docs/setup/` — запуск и конфигурация;
- `docs/operations/` — эксплуатация и поддержка;
- `docs/modules/` — крупные подсистемы;
- `docs/audit/` — состояние документации и cleanup-кандидаты.

Но если нужен именно один файл, использовать следует этот handbook.

## 11. Самые важные ссылки

- главный индекс docs: `docs/README.md`
- краткая структура: `docs/PROJECT_STRUCTURE.md`
- полная структура: `docs/PROJECT_STRUCTURE_FULL.md`
- системный обзор: `docs/architecture/system-overview.md`
- локальная разработка: `docs/setup/local-development.md`
- переменные окружения: `docs/setup/environment-variables.md`
- деплой и среды: `docs/operations/deploy-and-environments.md`
- диагностика: `docs/operations/diagnostics-and-maintenance.md`
- модули платформы: `docs/modules/platform-modules.md`
- side-services: `docs/modules/side-services.md`
- scripts: `docs/modules/scripts-and-tools.md`
- cleanup audit: `docs/audit/cleanup-register.md`

## 12. Короткий вывод

Если нужно быстро понять проект:

- как продукт — читайте разделы 1, 3 и 6;
- как разработчик — разделы 2, 4, 5 и 8;
- как оператор — разделы 6, 7 и 8;
- как человек, разгребающий хаос — разделы 9 и 10.
