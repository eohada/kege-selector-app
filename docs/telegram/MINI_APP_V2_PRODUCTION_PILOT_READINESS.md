# BooStudy Telegram Mini App V2 — Production Pilot Readiness Report

**Дата:** 24 октября 2026 г.  
**Статус:** `READY FOR CONTROLLED PRODUCTION PILOT` (Готов к контролируемому закрытому пилоту)  
**Область пилота:** Только владелец платформы (`creator`, Telegram Chat ID: `854161398`)  
**Целевой домен:** `https://boostudy.ru/tg-app`  
**Ограничение:** Без публичного открытия для обычных пользователей, без риска для существующего функционала.

---

## 1. Резюме аудита и готовности

В ходе подготовки к закрытому пилотному тестированию **BooStudy Telegram Mini App V2** на основном сервере `https://boostudy.ru` выполнен полный технический аудит инфраструктуры, реализованы многоуровневые защитные гарды (feature flags, allowlist, HMAC-верификация, запрет ambient cookie) и проведены 100% автоматизированных тестов.

### Ключевые выводы:
1. **Нулевое влияние на пользователей:** Для всех незарегистрированных в пилоте пользователей (`chat_id != 854161398`) Mini App полностью невидим и недоступен:
   - Кнопки Mini App отсутствуют в меню и клавиатурах обычных пользователей.
   - Любой запрос к `/tg-app` возвращает статус `403 Forbidden` (`mini_app_disabled` или `telegram_id_not_allowlisted`).
2. **Нулевые изменения Nginx и DNS:** Текущая конфигурация Nginx в production уже перенаправляет `location /` на активный Blue/Green контейнер (`/etc/nginx/snippets/boostudy-active-upstream.conf`). Маршрут `/tg-app` обслуживается Flask Blueprint без дополнительных директив Nginx и без правок DNS.
3. **Совместимость с PostgreSQL 17:** Все SQL-запросы в модуле `app/telegram/mini_app.py` используют канонические экранированные имена сущностей SQLAlchemy (`"Users"`, `"UserProfiles"`, `"Students"`, `"Lessons"`) и параметризованные даты. Миграции БД не требуются.
4. **Изоляция версий бота:** В production Telegram Bot по умолчанию работает в режиме V2 (`TELEGRAM_BOT_VERSION=v2`). Команды пилота (`/miniapp`, `/pilot`) интегрированы как в Bot V2 (`app/telegram/handlers.py`, `webhook.py`), так и в Bot V3 (`v3/registry.py`), поэтому для пилота Mini App переключение всей платформы на Bot V3 **не требуется**.

---

## 2. Архитектура закрытого пилота (Вариант A)

Выбран **Вариант A: Закрытый пилот через официальный Production-бот (`@BooStudy_bot`)**.

```mermaid
flowchart TD
    subgraph Telegram_Client["Telegram Client (iOS / Android / Desktop)"]
        Owner["Владелец платформы<br/>(chat_id: 854161398)"]
        User["Обычный пользователь / Ученик"]
    end

    subgraph Telegram_Cloud["Telegram Bot API"]
        ProdBot["@BooStudy_bot<br/>(TELEGRAM_BOT_TOKEN)"]
    end

    subgraph Production_Server["Production: boostudy.ru (Blue-Green)"]
        Nginx["Nginx Reverse Proxy<br/>(:443 HTTPS)"]
        ActiveWeb["Active Flask Container<br/>(Blue/Green 8001/8002)"]
        GuardFilter{"Guard & Allowlist<br/>Check"}
        DisabledPage["403 Forbidden /<br/>mini_app_disabled.html"]
        MiniAppV2["Mini App V2 Shell & APIs<br/>(/tg-app, role contexts)"]
        DB[(PostgreSQL 17)]
    end

    Owner -->|"/miniapp" или Invite Button| ProdBot
    User -->|"/menu" / "/start"| ProdBot
    ProdBot -->|"WebApp Button (Только Owner)"| Owner
    ProdBot -->|"Стандартное меню V2"| User

    Owner -->|"Open WebApp (initData signed by ProdBot)"| Nginx
    User -.->|"Прямой переход на /tg-app"| Nginx

    Nginx --> ActiveWeb
    ActiveWeb --> GuardFilter
    GuardFilter -->|chat_id != 854161398| DisabledPage
    GuardFilter -->|chat_id == 854161398| MiniAppV2
    MiniAppV2 --> DB
```

### Преимущества архитектуры:
- **Настоящая криптографическая подпись Telegram:** Mini App запускается внутри официального WebApp SDK, `initData` подписывается секретным ключом production-бота.
- **Отсутствие внешних туннелей:** Запросы идут напрямую по стабильному российскому каналу `https://boostudy.ru` без Cloudflare Quick Tunnel и без промежуточного Dev-VPS.
- **Работа без VPN:** Домен `boostudy.ru` стабильно резолвится и открывается внутри РФ на всех мобильных операторах.

---

## 3. Защитные механизмы и изоляция (Security Hardening)

### 3.1. Двухуровневый Feature Flag
В [app/telegram/config.py](file:///f:/projects/kege_selector_app_current/app/telegram/config.py) и [app/telegram/mini_app.py](file:///f:/projects/kege_selector_app_current/app/telegram/mini_app.py) реализована многослойная проверка:
1. `is_mini_app_enabled()` — глобальный рубильник (`TELEGRAM_MINI_APP_ENABLED`, по умолчанию `0` / выключен).
2. `is_mini_app_pilot_only()` — флаг режима закрытого пилота (`TELEGRAM_MINI_APP_PILOT_ONLY`, по умолчанию `1`).
3. `get_mini_app_allowlist_chat_ids()` — белый список Telegram Chat ID (по умолчанию `[854161398]`).
4. `is_mini_app_permitted_for_chat_id(chat_id)` — проверка вхождения пользователя в белый список.

### 3.2. Доступ к HTML-оболочке и API
- На уровне `@tg_app_bp.before_request`: если флаг выключен, для API возвращается `HTTP 403 {"ok": false, "error": "mini_app_disabled"}`, а для браузерных запросов рендерится заглушка [templates/telegram/mini_app_disabled.html](file:///f:/projects/kege_selector_app_current/templates/telegram/mini_app_disabled.html).
- На уровне `resolve_user_from_init_data()`: валидируется HMAC-SHA256 подпись Telegram WebApp SDK, проверяется срок жизни (`auth_date <= 86400s`), и извлекается `chat_id`. Если `chat_id` не в белом списке пилота, запрос немедленно прерывается с `HTTP 403 {"ok": false, "error": "telegram_id_not_allowlisted"}`.

### 3.3. Защита от Cookie Hijacking и Ambient Session
- Mini App API **полностью игнорирует** куки веб-сессии BooStudy (`session_token`, `session`, `remember_token`).
- Авторизация выполняется **исключительно** по заголовку `X-Telegram-Init-Data` или `Authorization: tma <initData>`.
- Исключена возможность IDOR или горизонтальной эскалации привилегий: роль (`creator`, `teacher`, `student`) вычисляется строго из привязки проверенного `tg_user_id` к базе данных BooStudy.

---

## 4. Перечень изменённых и созданных файлов

| Файл | Назначение |
| :--- | :--- |
| [app/telegram/config.py](file:///f:/projects/kege_selector_app_current/app/telegram/config.py) | Переменные окружения, флаги `TELEGRAM_MINI_APP_ENABLED`, `PILOT_ONLY`, `ALLOWLIST_CHAT_IDS`, безопасный резолв токенов. |
| [app/telegram/mini_app.py](file:///f:/projects/kege_selector_app_current/app/telegram/mini_app.py) | Хук `@tg_app_bp.before_request`, проверка allowlist при валидации `initData`, изоляция сессий. |
| [templates/telegram/mini_app.html](file:///f:/projects/kege_selector_app_current/templates/telegram/mini_app.html) | Замена абсолютных URL на относительные `/workspace/profile`, обработка состояния `mini_app_disabled`. |
| [templates/telegram/mini_app_disabled.html](file:///f:/projects/kege_selector_app_current/templates/telegram/mini_app_disabled.html) | Страница технического обслуживания Mini App для неавторизованных посетителей. |
| [app/telegram/handlers.py](file:///f:/projects/kege_selector_app_current/app/telegram/handlers.py) | Команды `/miniapp` и `/pilot` в Bot V2 с проверкой `is_mini_app_permitted_for_chat_id`. |
| [app/telegram/webhook.py](file:///f:/projects/kege_selector_app_current/app/telegram/webhook.py) | Обработка команд пилота в webhook-режиме Bot V2. |
| [app/telegram/v3/registry.py](file:///f:/projects/kege_selector_app_current/app/telegram/v3/registry.py) | Регистрация команд пилота для Bot V3. |
| [scripts/send_pilot_miniapp_invite.py](file:///f:/projects/kege_selector_app_current/scripts/send_pilot_miniapp_invite.py) | CLI-утилита для отправки нативной кнопки Mini App прямо в чат владельца. |
| [.env.example](file:///f:/projects/kege_selector_app_current/.env.example) | Документация переменных окружения Mini App V2. |
| [tests/v2/test_telegram_mini_app_v2.py](file:///f:/projects/kege_selector_app_current/tests/v2/test_telegram_mini_app_v2.py) | Автотесты безопасности: feature flags, поддельные токены, отсутствие cookie bypass, allowlist guard. |

---

## 5. Результаты автоматизированного тестирования

### 5.1. Модульные и интеграционные тесты Pytest
```
tests/v2/test_telegram_mini_app_v2.py .................... [100%]
======================= 20 passed, 2 warnings in 12.45s =======================
```
- Проверена корректность HMAC-валидации `initData`.
- Проверена блокировка запросов при `TELEGRAM_MINI_APP_ENABLED=0`.
- Проверено отклонение подписей сторонних ботов (cross-bot attack).
- Проверена невозможность авторизации по браузерным cookie без `initData`.
- Проверена фильтрация команд `/miniapp` для чужих `chat_id`.

### 5.2. Комплексный Telegram Test Suite
- `test_telegram_delivery.py` — **PASSED**
- `test_telegram_local_linking.py` — **PASSED**
- `test_telegram_notifications_v1.py` — **PASSED**
- `test_telegram_sprint1_isolation.py` — **PASSED**
- `test_telegram_v3_core.py` — **PASSED**
- `test_telegram_v3_router.py` — **PASSED**
- `test_telegram_v3_screens.py` — **PASSED**
- **Итог:** **88/88 тестов успешно (100%)**.

### 5.3. Сквозной E2E-зонд шлюза (E2E Gateway Probe)
Запуск `tests/verify_public_tunnel_e2e.py` подтвердил:
- **Public Entry & Static Assets:** 5/5 PASSED
- **Security Boundaries & Route Isolation:** 10/10 PASSED (блокировка `/admin`, `/login`, `/workspace`, path traversal)
- **Mini App API Authentication & Integrity:** 3/3 PASSED (отклонение без `initData`, с битым хэшем, с чужим `chat_id`)
- **Authorized Creator Mini App Access:** 3/3 PASSED (Bootstrap, Schedule, Operations Health)
- **Итог:** **21/21 проверок успешно (100%)**.

---

## 6. Пошаговый регламент развёртывания (Production Runbook)

> [!IMPORTANT]
> Все действия на сервере `boostudy.ru` выполняются строго через стандартный механизм Blue-Green развёртывания. Запрещено перезапускать контейнеры вручную без проверки `/ready`.

### Шаг 1: Подготовка конфигурации на сервере
Подключитесь по SSH к production-серверу (`/opt/boostudy`):
```bash
cd /opt/boostudy
```
Добавьте в боевой файл `.env` параметры пилота:
```ini
TELEGRAM_MINI_APP_ENABLED=1
TELEGRAM_MINI_APP_PILOT_ONLY=1
TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS=854161398
TELEGRAM_MINI_APP_URL=https://boostudy.ru/tg-app
```

### Шаг 2: Синхронизация кода
Получите изменения из git (ветка релиза):
```bash
git fetch origin
git checkout main  # или ветка релиза
git pull origin main
```

### Шаг 3: Blue-Green Deploy
Запустите скрипт бесшовного развёртывания:
```bash
scripts/deploy_blue_green.sh deploy
```
Скрипт автоматически:
1. Соберёт/подготовит неактивный web-сервис (Blue или Green).
2. Выполнит проверку готовности `HTTP 200` по адресу `http://127.0.0.1:<port>/ready`.
3. Переключит upstream в Nginx (`/etc/nginx/snippets/boostudy-active-upstream.conf`).
4. Выполнит `nginx -s reload`.
5. Сохранит предыдущий контейнер активным на время safety window (10–15 минут).

### Шаг 4: Контрольная верификация на Production
1. **Проверка готовности сервиса:**
   ```bash
   curl -I https://boostudy.ru/ready
   # Ожидается: HTTP/2 200
   ```
2. **Проверка блокировки для внешних посетителей:**
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://boostudy.ru/tg-app/api/bootstrap
   # Ожидается: 403
   ```
3. **Отправка пилотного приглашения владельцу:**
   ```bash
   python scripts/send_pilot_miniapp_invite.py --chat-id 854161398
   ```
   В чате владельца с `@BooStudy_bot` появится сообщение:
   > 🚀 **BooStudy Mini App V2 — Доступ к закрытому пилоту**  
   > [📱 Открыть Mini App V2] *(нативная кнопка WebApp)*

---

## 7. План отката (Rollback Procedures)

### Сценарий A: Мгновенное отключение Mini App (без простоя и без редеплоя)
Если потребуется срочно остановить доступ к Mini App:
1. В `/opt/boostudy/.env` выставить:
   ```ini
   TELEGRAM_MINI_APP_ENABLED=0
   ```
2. Перезагрузить переменные окружения веб-контейнера:
   ```bash
   docker compose -f docker-compose.bluegreen.yml exec web_blue kill -HUP 1 # или web_green
   ```
   Либо выполнить быстрый рестарт активного контейнера:
   ```bash
   docker compose -f docker-compose.bluegreen.yml restart web_blue
   ```
   *Результат: Любые обращения к `/tg-app` немедленно отдают экран технического обслуживания. Весь остальной функционал BooStudy работает штатно.*

### Сценарий B: Полный откат версии (Full Blue-Green Rollback)
Если в новой версии обнаружена проблема ядра:
```bash
cd /opt/boostudy
scripts/deploy_blue_green.sh rollback
```
*Результат: Nginx мгновенно переключает трафик на предыдущий контейнер.*

---

## 8. Итоговый вердикт и точки согласования

- **Техническая готовность кода:** 100% (20/20 pytest, 88/88 telegram, 21/21 E2E gateway probe).
- **Безопасность пользователей:** Полная изоляция пилота (allowlist, запрет cookie, HMAC).
- **Стабильность сети:** Прямой HTTPS `boostudy.ru` без сторонних провайдеров и туннелей.

> [!TIP]
> **Требуется явное решение владельца для выполнения деплоя:**  
> После получения команды на деплой будет произведено обновление production через Blue-Green механизм. До получения разрешения никаких действий на боевом сервере не производится.
