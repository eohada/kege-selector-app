# BooStudy Telegram Mini App V2 — Архитектура прямого HTTPS без VPN и Cloudflare

## 1. Резюме и статус

В ходе приёмки BooStudy Telegram Mini App V2 при запуске через Cloudflare Quick Tunnel была выявлена критическая нестабильность: в нативном Telegram WebView на мобильных устройствах и десктопе возникала ошибка **`502 Bad Gateway — Host Error`**, не исчезающая даже при включённом VPN.

Для обеспечения стабильного запуска для пользователей из РФ спроектирована и подготовлена **независимая архитектура прямого HTTPS без внешних CDN и без Cloudflare**.

---

## 2. Технический диагноз ошибки 502 (Cloudflare Quick Tunnel)

### 2.1. Фактические логи и воспроизведение

1. **Локальный бэкенд Flask (`127.0.0.1:5000`):**
   - Эндпоинты `/ready` и `/tg-app/` отвечали с кодом **HTTP 200 (OK)** за ~10 мс. Размер HTML — 70 556 байт.
2. **Локальный шлюз безопасности (`127.0.0.1:5050`):**
   - Эндпоинт `/healthz` и проксирование `/tg-app/` работали штатно со статусом **HTTP 200**.
3. **Логи шлюза (`instance/mini_app_gateway.log`):**
   - В моменты появления 502 в браузере/Telegram на локальный шлюз **не поступило ни одного байта**.
4. **Логи Cloudflare Tunnel (`instance/cloudflared.log`):**
   ```text
   ERR error="Incoming request ended abruptly: context canceled" connIndex=0 event=1 ingressRule=0 originService=http://127.0.0.1:5050
   Failed to proxy HTTP: Incoming request ended abruptly: context canceled
   ```

### 2.2. Причины сбоя quick-tunnel (`trycloudflare.com`)

1. **Сброс контекста на Edge Cloudflare:**
   - Сервис Quick Tunnel (`trycloudflare.com`) является бесплатным временным пулом без SLA. Подключения туннеля направляются через случайные пограничные узлы Cloudflare (в нашем случае `location=dme06`, Москва). При возрастании нагрузки или неполном handshake edge-сервер разрывает контекст стрима HTTP/2 (`context canceled`), возвращая клиенту `502 Host Error`.
2. **Сетевые блокировки и DPI/ТСПУ в РФ:**
   - Диапазоны IP-адресов Anycast Cloudflare и домены третьего уровня `*.trycloudflare.com` систематически подвергаются замедлению и TCP RST со стороны российских ТСПУ.
3. **Непригодность для Telegram WebView:**
   - Встроенный WebView в клиентах Telegram строго относится к тайм-аутам TLS и TLS-first байтам. Любая задержка в Cloudflare edge вызывает падение шторки WebApp.

---

## 3. Целевая архитектура прямого HTTPS

```
[ Telegram Client (RU Mobile / Desktop) ]
                   │  (Прямой HTTPS, без VPN, без Cloudflare)
                   ▼
       [ dev-tg.boostudy.ru (A-запись на RU VPS IP) ]
                   │
                   ▼
       [ Dev-VPS Edge Proxy (Caddy / Nginx) ]
                   │  (Терминация TLS: Let's Encrypt / ZeroSSL)
                   │  (Проксирование на 127.0.0.1:5055)
                   ▼
  [ Reverse SSH Tunnel (ssh -NT -R 5055:127.0.0.1:5050) ]
                   │
                   │  (Зашифрованный SSH канал от ПК разработчика к VPS)
                   ▼
[ Local Gateway mini_app_gateway.py (127.0.0.1:5050) ]
  • Валидация подписи initData (HMAC-SHA256)
  • Проверка белого списка ролей и Chat ID (854161398)
  • Защита от Path Traversal, блокировка сессионных cookie
  • Whitelist маршрутов (/tg-app, /api/tg/..., /static/...)
                   │
                   ▼
       [ Local BooStudy Flask (127.0.0.1:5000) ]
```

### 3.1. Преимущества схемы

1. **100% доступность в РФ:** Трафик идёт напрямую в российский дата-центр (Selectel, Timeweb, RuVDS) без посредников.
2. **Нулевой риск для Production:** Отдельный поддомен `dev-tg.boostudy.ru` и изолированный порт `5055` на dev-сервере. Боевой сервер `boostudy.ru` не затрагивается.
3. **Минимальные требования к инфраструктуре:** На ПК разработчика используется встроенный Windows OpenSSH (`ssh.exe`), не требующий сторонних утилит.
4. **Многоуровневая безопасность:**
   - Порт `5055` слушает исключительно `127.0.0.1` на VPS (`GatewayPorts no`).
   - Доступ по SSH ограничен пользователем `boostudy-tunnel` без интерактивного шелла (`/usr/sbin/nologin`).
   - Локальный шлюз `5050` отсекает любые несанкционированные запросы к основному приложению.

---

## 4. Оптимизация Frontend для работы в РФ (Zero-CDN)

Для устранения задержек при загрузке страницы внутри России были внесены изменения в шаблоны:

1. **Google Fonts изолированы:**
   - В `templates/base_minimal.html` теги `fonts.googleapis.com` и `fonts.gstatic.com` вынесены в переопределяемый блок `{% block head_fonts %}`.
   - В `templates/telegram/mini_app.html` этот блок переопределён пустым. Это исключило подвисания рендеринга из-за блокировок и замедления шрифтовых CDN.
2. **Telegram WebApp SDK вендоризован локально:**
   - Скрипт `telegram-web-app.js` (119 КБ) скачан локально в `static/js/vendor/telegram-web-app.js`.
   - В `mini_app.html` реализована первичная локальная загрузка с мягким fallback на `telegram.org`:
   ```html
   <script src="/static/js/vendor/telegram-web-app.js"></script>
   <script>
     if (!window.Telegram || !window.Telegram.WebApp) {
       document.write('<script src="https://telegram.org/js/telegram-web-app.js"><\/script>');
     }
   </script>
   ```

---

## 5. Подготовленные конфигурационные файлы и скрипты

Все необходимые файлы размещены в репозитории:

| Файл | Назначение |
|---|---|
| `deploy/dev-vps/Caddyfile` | Конфигурация Caddy с автоматическим получением Let's Encrypt сертификата и проксированием на `127.0.0.1:5055`. |
| `deploy/dev-vps/nginx-dev-tg.conf` | Альтернативная конфигурация Nginx + Certbot с HTTP/2 и строгими заголовками безопасности. |
| `deploy/dev-vps/setup-tunnel-user.sh` | Bash-скрипт для создания ограниченного пользователя `boostudy-tunnel` на VPS (`/usr/sbin/nologin`, `ForceCommand /bin/false`). |
| `scripts/tunnel-ssh-dev.ps1` | PowerShell-скрипт автоматизации запуска/мониторинга/остановки SSH-туннеля с ПК разработчика. |

---

## 6. Пошаговая инструкция по запуску

### Шаг 1. Настройка DNS (Владелец)
1. В панели управления DNS домена `boostudy.ru` добавить A-запись:
   - **Хост:** `dev-tg`
   - **Тип:** `A`
   - **Значение:** `<IP_АДРЕС_DEV_VPS>`
   - **Cloudflare Proxy:** **OFF** (только DNS / серое облако, если DNS обслуживается Cloudflare).

### Шаг 2. Первоначальная настройка Dev-VPS (1 минута)
На dev-VPS выполнить скрипт настройки:
```bash
# 1. Скачать и запустить скрипт создания пользователя
sudo bash deploy/dev-vps/setup-tunnel-user.sh

# 2. Добавить публичный SSH-ключ разработчика
sudo nano /home/boostudy-tunnel/.ssh/authorized_keys
# Вставить строку:
# restrict,port-forwarding,permitopen="127.0.0.1:5055" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... (ключ ПК разработчика)

# 3. Запустить веб-сервер (Caddy или Nginx)
sudo caddy run --config /etc/caddy/Caddyfile
# или
sudo cp deploy/dev-vps/nginx-dev-tg.conf /etc/nginx/sites-available/dev-tg.boostudy.ru
sudo certbot --nginx -d dev-tg.boostudy.ru
```

### Шаг 3. Запуск туннеля с локального ПК
В PowerShell выполнить:
```powershell
.\scripts\tunnel-ssh-dev.ps1 -Start -RemoteHost "<IP_DEV_VPS>" -PublicDomain "dev-tg.boostudy.ru"
```
Скрипт:
1. Проверит работу локального шлюза `127.0.0.1:5050`.
2. Поднимет SSH-сессию с пробросом `5055 -> 127.0.0.1:5050`.
3. Запишет рабочий URL `https://dev-tg.boostudy.ru` в `instance/mini_app_tunnel_env.json`.
4. Бот `@BooStudy_local_bot` автоматически подхватит новый URL для кнопки WebApp.

---

## 7. План приёмки без VPN

После поднятия туннеля:
1. Открыть `@BooStudy_local_bot` в мобильном Telegram (подключённом через мобильный интернет РФ: МТС / Мегафон / Билайн / Т-Мобайл без VPN).
2. Нажать `/menu` -> **«📱 Открыть Mini App»**.
3. Убедиться в мгновенном открытии WebApp шторки:
   - Зелёная точка Online.
   - Профиль `creator` (Создатель).
   - Быстрый переход между вкладками Кабинета Преподавателя (Очередь проверки, Расписание, Настройки).
   - Haptic Feedback (виброотклик).
