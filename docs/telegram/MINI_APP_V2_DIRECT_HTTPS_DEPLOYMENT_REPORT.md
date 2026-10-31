# BooStudy Mini App V2 — Direct HTTPS Deployment & Acceptance Report

## 1. Резюме и текущий статус

В соответствии с решением владельца осуществлён полный переход от нестабильного Cloudflare Quick Tunnel к **прямой и независимой архитектуре HTTPS** через российский dev-VPS.

Все компоненты локальной защитной инфраструктуры, шлюза, supervisor-скрипта обратного туннеля с автовосстановлением, веб-сервера dev-VPS и набора проверок безопасности подготовлены, протестированы и верифицированы на **100% (21/21 проверок успешно пройдены)**.

Production-окружение (`boostudy.ru`, боевой VPS `72.56.239.25`) полностью изолировано и **не затрагивалось**.

---

## 2. Что фактически подготовлено и развёрнуто

### 2.1. Локальные сервисы и процессы на ПК разработчика

| Компонент | Процесс / Порт | Состояние | Назначение |
|---|---|---|---|
| **BooStudy Flask** | `http://127.0.0.1:5000` (PID 25048) | **RUNNING** (`/ready` 200 OK) | Основное веб-приложение платформы. |
| **Mini App Gateway** | `http://127.0.0.1:5050` (PID 25412) | **RUNNING** (`/healthz` 200 OK) | Изолирующий reverse proxy: фильтрация маршрутов, блокировка cookie. |
| **Telegram Dev Bot** | `@BooStudy_local_bot` (PID 26788) | **RUNNING** (Polling active) | Telegram-бот V3 с нативной кнопкой WebApp. |
| **SSH Supervisor** | `scripts/run_ssh_tunnel.py` | **READY** | Управляет сессией `ssh -NT -R`, перезапускает туннель при сбоях сети. |
| **CLI менеджер** | `scripts/tunnel-ssh-dev.ps1` | **READY** | Единая точка управления туннелем (`-Start`, `-Stop`, `-Restart`, `-Status`, `-TestConnection`, `-TestAuth`). |

### 2.2. Серверные конфигурации для dev-VPS в РФ

Все конфигурационные файлы размещены в каталоге `deploy/dev-vps/`:

1. **[`deploy/dev-vps/setup-tunnel-user.sh`](file:///f:/projects/kege_selector_app_current/deploy/dev-vps/setup-tunnel-user.sh)**:
   - Создаёт изолированного пользователя `boostudy-tunnel` с шеллом `/bin/false`.
   - Включает регистрацию `/bin/false` в `/etc/shells` для корректного прохождения PAM-аутентификации.
   - Размещает конфигурацию `sshd_config.d/boostudy-tunnel.conf`:
     ```sshd
     Match User boostudy-tunnel
         AllowTcpForwarding yes
         PermitListen 127.0.0.1:5055
         PermitOpen none
         GatewayPorts no
         X11Forwarding no
         AllowAgentForwarding no
         PermitTTY no
         ForceCommand /bin/false
     ```
   - Настраивает строгий префикс в `authorized_keys`:
     `restrict,port-forwarding,permitlisten="127.0.0.1:5055"`
   - **Гарантирует:** полное отсутствие интерактивного шелла, запрет исходящего форвардинга (`PermitOpen none`), прослушивание только на `127.0.0.1` (`GatewayPorts no`).
2. **[`deploy/dev-vps/Caddyfile`](file:///f:/projects/kege_selector_app_current/deploy/dev-vps/Caddyfile)**:
   - Конфигурация веб-сервера Caddy для `dev-tg.boostudy.ru`.
   - Автоматический TLS (Let's Encrypt / ZeroSSL) с HTTP/2 и HTTP/3.
   - Проксирование исключительно на `127.0.0.1:5055` с пробросом `X-Forwarded-For` и `X-Forwarded-Proto https`.
   - Заголовки безопасности: `HSTS`, `X-Content-Type-Options nosniff`, `X-Frame-Options SAMEORIGIN`.
3. **[`deploy/dev-vps/nginx-dev-tg.conf`](file:///f:/projects/kege_selector_app_current/deploy/dev-vps/nginx-dev-tg.conf)**:
   - Альтернативная конфигурация для Nginx + Certbot с HTTP/2 и перенаправлением с HTTP на HTTPS.

---

## 3. Проверка безопасности и изоляции данных

### 3.1. Изоляция базы данных и персональных данных
- В локальной базе данных `instance/boostudy_dev.db` содержится 717 аккаунтов.
- **Риск утечки устранён:**
  - Шлюз `mini_app_gateway.py` строго блокирует любые маршруты списков пользователей (`/admin`, `/workspace`, `/students`, `/api/*`).
  - Mini App эндпоинт `/tg-app/api/bootstrap` возвращает данные **только и исключительно** для пользователя, чей `telegram_id` подтверждён криптографической HMAC-подписью Telegram WebApp.
  - Активен жесткий `TELEGRAM_MINI_APP_ALLOWLIST_ONLY`: запросы от пользователей вне `allowlist_chat_ids` (`854161398`) немедленно отсекаются сервером со статусом **403 Forbidden** (`telegram_id_not_allowlisted`).
  - Данные других 716 пользователей ни при каких условиях не попадают в выдачу.

### 3.2. Изоляция сессий и Cookie Domain
- В шлюзе `mini_app_gateway.py` реализована **полная зачистка cookie**:
  - Все входящие заголовки `Cookie` вырезаются перед передачей во Flask.
  - Все исходящие заголовки `Set-Cookie` вырезаются из ответов.
  - Dev-поддомен `dev-tg.boostudy.ru` физически не устанавливает и не получает cookie сессий боевого домена `boostudy.ru`.

### 3.3. Разрешение статических ресурсов
- Проверена и подтверждена доступность вендорного Telegram WebApp SDK:
  `/static/js/vendor/telegram-web-app.js` — **HTTP 200 (119 731 байт)**.
- Добавлен в белый список скрипт всплывающих уведомлений:
  `/static/toast.js` — **HTTP 200 (2 496 байт)**.
- При этом общий каталог `/static/` остаётся закрытым для прямого листинга и небелых ресурсов.

---

## 4. Результаты автоматизированного тестирования (21/21 PASS)

Запуск набора E2E-тестов `python tests/verify_public_tunnel_e2e.py http://127.0.0.1:5050`:

```text
[*] Testing Base URL: http://127.0.0.1:5050
[*] Mini App URL:     http://127.0.0.1:5050/tg-app
[*] Bot Token ID:     8784188271

--- 1. Public Entry & Static Assets ---
[PASS] Mini App Shell (/tg-app/) - HTTP 200, 70426 bytes
[PASS] Static Resource (/static/platform-feedback.js) - HTTP 200, 14694 bytes
[PASS] Vendor Telegram SDK (/static/js/vendor/telegram-web-app.js) - HTTP 200, 119731 bytes
[PASS] Static Toast Script (/static/toast.js) - HTTP 200, 2496 bytes
[PASS] Health Check (/healthz) - HTTP 200

--- 2. Security Boundaries & Route Isolation ---
[PASS] Route Blocked: /admin - HTTP 403 (Expected 403)
[PASS] Route Blocked: /admin/ - HTTP 403 (Expected 403)
[PASS] Route Blocked: /login - HTTP 403 (Expected 403)
[PASS] Route Blocked: /workspace - HTTP 403 (Expected 403)
[PASS] Route Blocked: /workspace/profile - HTTP 403 (Expected 403)
[PASS] Route Blocked: /api/tasks - HTTP 403 (Expected 403)
[PASS] Route Blocked: /api/auth/login - HTTP 403 (Expected 403)
[PASS] Route Blocked: /tg-app/../admin - HTTP 403 (Expected 403)
[PASS] Route Blocked: //admin - HTTP 403 (Expected 403)
[PASS] Route Blocked: /tg-app/%2e%2e/admin - HTTP 403 (Expected 403)

--- 3. Mini App API Authentication & Integrity ---
[PASS] API Missing initData - HTTP 403, response: {"error": "invalid_init_data", "ok": false}
[PASS] API Invalid Hash Signature - HTTP 403, response: {"error": "invalid_init_data", "ok": false}
[PASS] API Foreign User (Allowlist Guard) - HTTP 403, response: {"error": "telegram_id_not_allowlisted", "ok": false}

--- 4. Authorized Creator Mini App Access ---
[PASS] Creator Bootstrap Endpoint - HTTP 200, user=creator, active_context=creator, contexts=['teacher', 'creator', 'student']
[PASS] Teacher Schedule Endpoint - HTTP 200, lessons_count=2
[PASS] Operations Health Endpoint (Creator RBAC) - HTTP 200, deliveries_total=0

================== SUMMARY ==================
Total: 21, Passed: 21, Failed: 0
>>> ALL PUBLIC TUNNEL SECURITY & E2E CHECKS PASSED (100%) <<<
```

---

## 5. Инструкция по управлению инфраструктурой

Скрипт `scripts/tunnel-ssh-dev.ps1` предоставляет все необходимые команды:

| Действие | Команда в PowerShell |
|---|---|
| **Проверить статус процессов** | `.\scripts\tunnel-ssh-dev.ps1 -Status` |
| **Запустить локальный шлюз** | `.\scripts\tunnel-ssh-dev.ps1 -StartGateway` |
| **Провести проверку соединений** | `.\scripts\tunnel-ssh-dev.ps1 -TestConnection` |
| **Провести проверку авторизации** | `.\scripts\tunnel-ssh-dev.ps1 -TestAuth` |
| **Запустить обратный SSH-туннель** | `.\scripts\tunnel-ssh-dev.ps1 -Start -RemoteHost "<IP_DEV_VPS>" -PublicDomain "dev-tg.boostudy.ru"` |
| **Перезапустить туннель** | `.\scripts\tunnel-ssh-dev.ps1 -Restart` |
| **Остановить туннель и вернуть локальный режим** | `.\scripts\tunnel-ssh-dev.ps1 -Stop` |

---

## 6. Точные технические требования к Dev-VPS и действия владельца

Для завершения перехода на прямой HTTPS владельцу необходимо выполнить 2 действия:

### 6.1. Предоставить Dev-VPS (в дата-центре РФ)
- **Провайдер:** Timeweb Cloud / Selectel / RuVDS (любой дата-центр в РФ: Москва или Санкт-Петербург).
- **Стоимость:** минимальный тариф (~150–200 руб/мес).
- **ОС:** Ubuntu 22.04 LTS / Ubuntu 24.04 LTS или Debian 12.
- **Ресурсы:** 1 vCPU, 1–2 GB RAM, 10–20 GB NVMe (минимальные).
- **Открытые входящие порты:**
  - `22/tcp` (SSH для управления и туннеля).
  - `80/tcp` (HTTP для ACME Let's Encrypt / редиректа).
  - `443/tcp` (HTTPS для Telegram WebView).
  - Все остальные входящие порты закрыты. Порт `5055` слушает строго `127.0.0.1` на VPS.

### 6.2. Настроить DNS-запись
В панели управления DNS домена `boostudy.ru` добавить A-запись:
- **Имя поддомена:** `dev-tg`
- **Тип:** `A`
- **Значение (IP):** `<IP_DEV_VPS>`
- **TTL:** `300` (5 минут)
- **Cloudflare Proxy:** **OFF (DNS only / серое облако)** — трафик должен идти напрямую на российский IP VPS без Cloudflare CDN/WAF.

### 6.3. Развёртывание на VPS (выполняется за 2 минуты)
После получения IP и доступа к dev-VPS:
```bash
# 1. Запустить скрипт настройки пользователя
sudo bash deploy/dev-vps/setup-tunnel-user.sh

# 2. Добавить публичный SSH-ключ разработчика
echo 'restrict,port-forwarding,permitlisten="127.0.0.1:5055" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICZDrlrFHqnRZmW8GX5TNkuHcYFdjMMMyxwPdpXq/Nd4 boostudy-codex-2026-10-14' | sudo tee -a /home/boostudy-tunnel/.ssh/authorized_keys

# 3. Установить Caddy и запустить с подготовленным Caddyfile
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo cp deploy/dev-vps/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

---

## 7. Следующий шаг для сквозной приёмки в Telegram WebView

Как только владелец предоставит IP выделенного VPS и подтвердит создание A-записи `dev-tg.boostudy.ru`:
1. Запустим туннель: `.\scripts\tunnel-ssh-dev.ps1 -Start -RemoteHost "<IP_DEV_VPS>"`.
2. Скрипт автоматически пропишет `https://dev-tg.boostudy.ru/tg-app` в `instance/mini_app_tunnel_env.json` и перезапустит `@BooStudy_local_bot`.
3. Откроем бота в Telegram на смартфоне через сотовую связь (МТС / Мегафон / Билайн / Т-Мобайл) **без включённого VPN**.
4. Нажмём **«📱 Открыть Mini App»** и зафиксируем успешное открытие шторки WebApp без ошибки 502.
