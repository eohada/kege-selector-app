# Переменные окружения

Этот файл не заменяет `.env.example`, а систематизирует переменные по зонам ответственности.

## 1. Базовое окружение

| Переменная | Назначение |
|------------|------------|
| `ENVIRONMENT` | Текущая среда: `local`, `development`, `sandbox`, `production` |
| `IS_SANDBOX` | Флаг песочницы |
| `PORT` | Порт web-приложения |

## 2. Безопасность и сессии

| Переменная | Назначение |
|------------|------------|
| `SECRET_KEY` | Ключ Flask-сессий и CSRF. Обязателен вне local/dev |
| `CROSS_ENV_LOGIN_SECRET` | Секрет для кросс-средового signed autologin |

## 3. База данных

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | Основной DSN базы |
| `DATABASE_EXTERNAL_URL` | Приоритетный внешний DSN, если нужен отдельный endpoint |
| `POSTGRES_URL` | Альтернативный внешний DSN |
| `DEMO_DATABASE_URL` | Отдельная БД для demo-site сценария |

## 4. Demo и multi-environment сценарии

| Переменная | Назначение |
|------------|------------|
| `DEMO_SITE` | Включение demo-режима |
| `DEMO_BASE_URL` | Базовый URL demo-сайта |
| `DEMO_HOST` | Домен demo-инстанса |
| `DEMO_CREATOR_AVATAR_URL` | Demo asset override |
| `DEMO_CREATOR_COVER_URL` | Demo asset override |
| `PROD_URL` | URL production для internal switching |
| `SANDBOX_URL` | URL sandbox для internal switching |
| `PRODUCTION_URL` | URL production для sandbox maintenance checks |
| `ADMIN_URL` | URL admin-сервера или remote admin контура |

## 5. Trainer

| Переменная | Назначение |
|------------|------------|
| `TRAINER_URL` | Адрес Streamlit trainer-сервиса для iframe/web integration |
| `TRAINER_SHARED_SECRET` | Shared secret для доверенного обмена между платформой и trainer |
| `PLATFORM_BASE_URL` | Базовый адрес платформы со стороны `trainer_app` |
| `TRAINER_PLATFORM_URL` | Альтернативное имя для base URL платформы |
| `TRAINER_ENABLE_RUNNER` | Включение code runner в trainer |
| `TRAINER_LLM_TIMEOUT_SECONDS` | Таймаут LLM-запросов |
| `TRAINER_LLM_MAX_ATTEMPTS` | Количество retry для trainer LLM |

## 6. LLM и AI

| Переменная | Назначение |
|------------|------------|
| `GIGACHAT_CREDENTIALS` | Credentials для GigaChat |
| `GIGACHAT_MODEL` | Выбор модели |
| `GIGACHAT_SCOPE` | Scope/режим доступа |
| `GIGACHAT_VERIFY_SSL_CERTS` | SSL-поведение |
| `GIGACHAT_CA_BUNDLE_FILE` | Пользовательский CA bundle |

## 7. Telegram

### Production webhook контур

| Переменная | Назначение |
|------------|------------|
| `BOT_TOKEN` | Основной токен production Telegram-бота |
| `UREP_BOT_TOKEN` | Альтернативное имя токена для `urep_bot` |
| `BOT_INTERNAL_TOKEN` | Внутренний токен для API связи с ботом |
| `APP_URL` | Базовый URL приложения для Telegram-ссылок |
| `APP_OPEN_URL` | Публичный open URL, если нужен отдельный адрес |
| `BOT_LOG_LEVEL` | Уровень логирования Telegram-контура |
| `BOT_INSTANCE_LOCK_KEY` | Coordination/lock key для bot runtime |

### Standalone tester-report bot

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` | Токен отдельного бота-трекера репортов |
| `TELEGRAM_ADMIN_ID` | Telegram ID администратора |
| `TELEGRAM_GROUP_ID` | ID группы тестировщиков |
| `TELEGRAM_TOPIC_ID` | Topic/thread ID |
| `TELEGRAM_MAIN_TESTER_ID` | Дополнительный ID тестировщика |
| `TELEGRAM_MAIN_TESTER_ID_2` | Дополнительный ID тестировщика |
| `REPORTS_DB_PATH` | Путь к SQLite базе репортов |
| `TELEGRAM_BOT_LOG_LEVEL` | Уровень логирования standalone-бота |

## 8. Miro и внешние инструменты

| Переменная | Назначение |
|------------|------------|
| `MIRO_ACCESS_TOKEN` | Токен Miro API |
| `MIRO_CLIENT_ID` | OAuth client id |
| `MIRO_CLIENT_SECRET` | OAuth client secret |
| `MIRO_REDIRECT_URI` | Redirect URI для OAuth callback |
| `DAILY_API_KEY` | Ключ Daily.co |

## 9. Хранилище и uploads

| Переменная | Назначение |
|------------|------------|
| `AVATAR_UPLOAD_ROOT` | Корень аватаров |
| `COVER_UPLOAD_ROOT` | Корень обложек |
| `THEORY_UPLOAD_ROOT` | Корень файлов теории |
| `TASK_ATTACHMENTS_ROOT` | Корень вложений заданий |
| `ANSWER_ATTACHMENTS_ROOT` | Корень вложений ответов |

## 10. S3 / MinIO

| Переменная | Назначение |
|------------|------------|
| `S3_ENDPOINT_URL` | Endpoint S3-compatible storage |
| `S3_ACCESS_KEY` | Access key |
| `S3_SECRET_KEY` | Secret key |
| `S3_BUCKET` | Имя bucket |

## 11. Административные токены

| Переменная | Назначение |
|------------|------------|
| `PRODUCTION_ADMIN_TOKEN` | Токен remote admin API для production |
| `SANDBOX_ADMIN_TOKEN` | Токен remote admin API для sandbox |
| `ADMIN_ADMIN_TOKEN` | Токен admin-сервера |

## 12. Background and maintenance

| Переменная | Назначение |
|------------|------------|
| `ASSIGNMENT_NOTIFY_POLL_SECONDS` | Интервал polling worker уведомлений |
| `ASSIGNMENT_NOTIFY_DEBOUNCE_SECONDS` | Debounce для уведомлений |
| `LESSON_AUTO_COMPLETE_POLL_SECONDS` | Интервал worker автозавершения уроков |
| `MAINTENANCE_ENABLED` | Принудительное включение режима техработ |
| `RATELIMIT_ENABLED` | Включение/выключение limiter |
| `AUTO_DB_SCHEMA_SYNC` | Legacy auto-sync схемы, только для одиночного процесса |

## 13. Практические договорённости

- В production запрещено стартовать без `SECRET_KEY`.
- Для новой интеграции сначала зафиксируйте её env vars в `.env.example`, затем отразите их в этом документе.
- Не смешивайте переменные встроенного production Telegram webhook и standalone `telegram_bot`.
- Перед запуском scripts всегда проверяйте, к какой БД и к какой среде привязаны переменные.
