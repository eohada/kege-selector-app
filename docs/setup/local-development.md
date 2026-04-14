# Локальная разработка

## 1. Что нужно для запуска

Минимальный сценарий локальной разработки:

- Python-окружение с зависимостями из `requirements.txt` или `requirements-local.txt`;
- заполненный `.env`;
- SQLite fallback или PostgreSQL;
- при необходимости Tailwind CLI для сборки CSS;
- отдельно, при работе с тренажёром, зависимости из `trainer_app/requirements.txt`.

## 2. Установка зависимостей

### Базовая установка

```bash
pip install -r requirements.txt
```

### Более лёгкий локальный вариант

Если требуется упростить локальный setup, ориентируйтесь на `requirements-local.txt`.

## 3. Настройка `.env`

Создайте `.env` на основе `.env.example`.

Минимум для локального старта:

```env
ENVIRONMENT=local
SECRET_KEY=dev-secret-key
PORT=5000
```

Если `DATABASE_URL` не задан, приложение использует SQLite-файл в `data/keg_tasks.db`.

## 4. Запуск основного приложения

Канонический локальный запуск:

```bash
python wsgi.py
```

Альтернативный helper:

```bash
python scripts/run_local.py
```

По умолчанию приложение стартует на `127.0.0.1:5000`.

## 5. База данных и миграции

### Поведение по умолчанию

- при наличии `DATABASE_URL` используется PostgreSQL;
- иначе приложение уходит в SQLite fallback;
- автоматическая синхронизация схемы по умолчанию отключена;
- для нормального обновления схемы ожидается `flask db upgrade`.

### Базовые команды

См. также `migrations/README` и `docs/DATABASE_MIGRATION_QUICK_START.md`.

Типовой поток:

```bash
flask db upgrade
```

Для генерации миграции:

```bash
flask db migrate -m "describe change"
```

### Важное ограничение

В `app/__init__.py` поддерживается legacy-механизм `AUTO_DB_SCHEMA_SYNC=1`, но он предназначен только для одиночного процесса и не должен считаться штатной production-практикой.

## 6. CSS и фронтенд-ассеты

Основной pipeline CSS построен без полноценного npm-build:

- исходник: `static/src/input.css`;
- артефакт: `static/dist/boostudy.css`;
- Windows helper: `scripts/build_css.ps1`;
- standalone binary хранится локально в `tools/tailwindcss/` и не коммитится.

Сборка:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_css.ps1
```

## 7. Локальный запуск trainer

`trainer_app/` живёт как отдельный Streamlit-процесс.

Установка:

```bash
pip install -r trainer_app/requirements.txt
```

Запуск:

```bash
streamlit run trainer_app/app.py
```

Ключевые переменные для trainer:

- `PLATFORM_BASE_URL`
- `TRAINER_URL`
- `TRAINER_SHARED_SECRET`
- `GIGACHAT_CREDENTIALS`
- `TRAINER_ENABLE_RUNNER`

Если trainer встраивается в web-интерфейс через `/trainer`, основной Flask должен знать адрес Streamlit-сервиса через `TRAINER_URL`.

## 8. Telegram и интеграции локально

### Production-style Telegram webhook

Основной Telegram-контур встроен в Flask и использует webhook endpoint `POST /webhook/telegram`.

Для локальной отладки потребуется корректная настройка связанных токенов и внешней доступности endpoint, если вы тестируете настоящий webhook.

### Standalone tester bot

`telegram_bot/` запускается отдельно и использует собственные env vars, не зависящие напрямую от основного web-runtime.

## 9. Полезные локальные сценарии

- быстро проверить health: открыть `/health`;
- проверить публичную страницу тарифов: `/billing/plans/public`;
- использовать `docs/modules/scripts-and-tools.md`, если нужен служебный скрипт;
- не запускать prod-sensitive scripts без проверки окружения и целевой БД.

## 10. Частые локальные проблемы

### Приложение стартует, но ломается часть экранов

Проверьте:

- заполнен ли `SECRET_KEY`;
- корректен ли `DATABASE_URL`;
- не требуется ли `flask db upgrade`;
- собран ли `static/dist/boostudy.css`;
- существуют ли локальные directories для upload/storage сценариев.

### Trainer не открывается

Проверьте:

- запущен ли `trainer_app`;
- задан ли `TRAINER_URL`;
- совпадает ли `TRAINER_SHARED_SECRET`;
- доступен ли `PLATFORM_BASE_URL` из trainer-процесса.

### Telegram-функции не работают

Проверьте:

- токены и bot env vars;
- какой именно контур вы запускаете: встроенный webhook или `telegram_bot`;
- не используется ли неверная БД или неинициализированные таблицы.
