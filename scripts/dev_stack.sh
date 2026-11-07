#!/usr/bin/env bash
# scripts/dev_stack.sh
# Управление локальным окружением BooStudy через systemd user services:
# 1. Платформа (Flask на 0.0.0.0:5000) — доступна локально и с телефона по Wi-Fi
# 2. Туннель платформы (Cloudflare Tunnel -> 5000) — доступ к платформе с телефона из любой сети
# 3. Обычный Telegram-бот (run_bot.py) без Mini App

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

PYTHON="$ROOT_DIR/venv/bin/python"
INSTANCE_DIR="$ROOT_DIR/instance"
mkdir -p "$INSTANCE_DIR"
CF_LOG="$INSTANCE_DIR/cloudflared.log"
CF_BIN="$(which cloudflared 2>/dev/null || echo "$HOME/.local/bin/cloudflared")"

get_lan_ip() {
    ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' || hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1"
}

stop_stack() {
    echo "=== Остановка окружения BooStudy [-] ==="
    systemctl --user stop boostudy-bot.service boostudy-tunnel.service boostudy-backend.service 2>/dev/null || true
    fuser -k 5000/tcp 2>/dev/null || true
    pkill -f "run_bot.py" 2>/dev/null || true
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    pkill -f "scripts/run_local.py" 2>/dev/null || true
    rm -f "$INSTANCE_DIR/mini_app_tunnel_env.json"
    echo "  [OK] Все сервисы остановлены"
}

start_stack() {
    stop_stack > /dev/null 2>&1 || true
    sleep 1

    echo "=== Запуск окружения BooStudy [+] ==="
    LAN_IP=$(get_lan_ip)

    # 1. Backend
    echo "[1/3] Запуск платформы Flask (порт 5000 на всех интерфейсах)..."
    systemd-run --user --unit=boostudy-backend \
      --working-directory="$ROOT_DIR" \
      --setenv=HOST=0.0.0.0 \
      --property=Restart=on-failure \
      "$PYTHON" -u scripts/run_local.py > /dev/null 2>&1

    BACKEND_READY=0
    for _ in {1..15}; do
        sleep 1
        CODE=$(curl --noproxy "*" -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/ || true)
        if [ "$CODE" = "200" ]; then
            BACKEND_READY=1
            break
        fi
    done

    if [ "$BACKEND_READY" -eq 1 ]; then
        echo "  [OK] Платформа запущена (HTTP 200, systemd: boostudy-backend)"
    else
        echo "  [WARN] Платформа запустилась, но ответ еще не 200"
    fi

    # 2. Tunnel
    echo "[2/3] Запуск Cloudflare Tunnel к платформе (для доступа с телефона)..."
    > "$CF_LOG"
    systemd-run --user --unit=boostudy-tunnel \
      --working-directory="$ROOT_DIR" \
      --property=Restart=on-failure \
      /bin/bash -c "exec '$CF_BIN' tunnel --protocol http2 --url http://127.0.0.1:5000 > '$CF_LOG' 2>&1" > /dev/null 2>&1

    PUBLIC_URL=""
    for _ in {1..25}; do
        sleep 1
        if [ -f "$CF_LOG" ]; then
            MATCH=$(grep -oE "https://[a-zA-Z0-9-]+\.trycloudflare\.com" "$CF_LOG" | head -n 1 || true)
            if [ -n "$MATCH" ]; then
                PUBLIC_URL="$MATCH"
                break
            fi
        fi
    done

    if [ -n "$PUBLIC_URL" ]; then
        echo "  [OK] Cloudflare Tunnel активен"
    else
        echo "  [WARN] Cloudflare Tunnel запущен, ссылка появится в instance/cloudflared.log"
    fi

    # 3. Bot
    echo "[3/3] Запуск Telegram-бота..."
    systemd-run --user --unit=boostudy-bot \
      --working-directory="$ROOT_DIR" \
      --property=Restart=on-failure \
      "$PYTHON" -u run_bot.py > /dev/null 2>&1

    sleep 3
    if systemctl --user is-active --quiet boostudy-bot.service; then
        echo "  [OK] Telegram-бот запущен (@BooStudy_local_bot)"
    else
        echo "  [WARN] Проверьте статус бота: journalctl --user -u boostudy-bot -e"
    fi

    echo ""
    echo "=========================================================="
    echo "  * Локальная платформа (ПК):       http://127.0.0.1:5000"
    echo "  * Доступ с телефона (в Wi-Fi):   http://$LAN_IP:5000"
    if [ -n "$PUBLIC_URL" ]; then
        echo "  * Доступ с телефона (Интернет):  $PUBLIC_URL"
    fi
    echo "  * Telegram-бот:                  @BooStudy_local_bot"
    echo "=========================================================="
}

status_stack() {
    LAN_IP=$(get_lan_ip)
    echo "=== Статус окружения BooStudy ==="
    
    if systemctl --user is-active --quiet boostudy-backend.service; then
        echo "  * Платформа (5000):   РАБОТАЕТ (systemd: boostudy-backend)"
        echo "    - ПК:              http://127.0.0.1:5000"
        echo "    - Телефон (Wi-Fi): http://$LAN_IP:5000"
    else
        echo "  * Платформа (5000):   ОСТАНОВЛЕНА"
    fi

    if systemctl --user is-active --quiet boostudy-tunnel.service; then
        MATCH=$(grep -oE "https://[a-zA-Z0-9-]+\.trycloudflare\.com" "$CF_LOG" 2>/dev/null | head -n 1 || echo "не найден")
        echo "  * Туннель с телефона: РАБОТАЕТ ($MATCH)"
    else
        echo "  * Туннель с телефона: ОСТАНОВЛЕН"
    fi

    if systemctl --user is-active --quiet boostudy-bot.service; then
        echo "  * Telegram-бот:       РАБОТАЕТ (@BooStudy_local_bot)"
    else
        echo "  * Telegram-бот:       ОСТАНОВЛЕН"
    fi
}

case "${1:-status}" in
    start)
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    restart)
        stop_stack
        sleep 1
        start_stack
        ;;
    status)
        status_stack
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
