# Ошибка 413 при загрузке аватарки (Request Entity Too Large)

Если перед приложением стоит **nginx** (Ubuntu/другой сервер), по умолчанию он ограничивает размер тела запроса (~1 MB). Запрос на обновление профиля с аватаркой (до 5 MB) обрезается, и nginx возвращает **413 Request Entity Too Large** до того, как запрос дойдёт до Flask.

## Решение

В конфигурации nginx нужно увеличить лимит. Варианты:

### 1. Для одного server-блока (рекомендуется)

В блок `server { ... }`, который проксирует запросы к вашему приложению, добавьте:

```nginx
server {
    # ... остальные директивы ...
    client_max_body_size 10M;
    location / {
        proxy_pass http://...;
        # ...
    }
}
```

### 2. Глобально для всех сайтов

В начало файла `/etc/nginx/nginx.conf`, внутри блока `http { ... }`:

```nginx
http {
    client_max_body_size 10M;
    # ...
}
```

### 3. Только для маршрута загрузки (точечно)

Если не хотите поднимать лимит для всего сервера:

```nginx
location /user/profile/update {
    client_max_body_size 10M;
    proxy_pass http://ваш_backend;
    proxy_request_buffering off;  # при необходимости
    # ...
}
```

После правок перезагрузите nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## Ошибка 502 Bad Gateway

502 обычно значит, что nginx не дождался ответа от gunicorn или не может к нему подключиться.

В `location`, который проксирует на приложение, выровняйте таймауты с gunicorn (`--timeout 180` в `Procfile`):

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;  # порт вашего web_prod
    proxy_connect_timeout 10s;
    proxy_read_timeout 180s;
    proxy_send_timeout 180s;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Проверка на сервере:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
docker compose ps
docker compose logs web_prod --tail 80
sudo tail -30 /var/log/nginx/error.log
```

В приложении уже задан лимит 10 MB (`MAX_CONTENT_LENGTH`); аватарка в интерфейсе ограничена 5 MB. Лимит в nginx должен быть не меньше (рекомендуется **10M**).
