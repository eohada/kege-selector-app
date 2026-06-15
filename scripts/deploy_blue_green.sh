#!/usr/bin/env bash
set -euo pipefail

# BooStudy blue-green deploy helper.
#
# Expected server layout:
#   /opt/boostudy
#   /opt/boostudy/docker-compose.bluegreen.yml
#   /etc/nginx/snippets/boostudy-active-upstream.conf
#
# Usage:
#   scripts/deploy_blue_green.sh deploy
#   scripts/deploy_blue_green.sh status
#   scripts/deploy_blue_green.sh rollback
#
# Rollback does not rebuild the previous web image. After the drain window the
# old web service may be stopped, so rollback starts it, waits for /ready, then
# switches nginx back.

APP_DIR="${APP_DIR:-/opt/boostudy}"
BRANCH="${BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.bluegreen.yml}"
STATE_DIR="${STATE_DIR:-$APP_DIR/.deploy}"
ACTIVE_FILE="${ACTIVE_FILE:-$STATE_DIR/active_color}"
NGINX_UPSTREAM_FILE="${NGINX_UPSTREAM_FILE:-/etc/nginx/snippets/boostudy-active-upstream.conf}"
NGINX_TEST_CMD="${NGINX_TEST_CMD:-nginx -t}"
NGINX_RELOAD_CMD="${NGINX_RELOAD_CMD:-nginx -s reload}"
BLUE_PORT="${BLUE_PORT:-8001}"
GREEN_PORT="${GREEN_PORT:-8002}"
DRAIN_SECONDS="${DRAIN_SECONDS:-90}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
UPDATE_CELERY="${UPDATE_CELERY:-1}"

cd "$APP_DIR"
mkdir -p "$STATE_DIR"

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

active_color() {
    if [[ -f "$ACTIVE_FILE" ]]; then
        tr -d '[:space:]' < "$ACTIVE_FILE"
    else
        echo "blue"
    fi
}

opposite_color() {
    case "${1:-$(active_color)}" in
        blue) echo "green" ;;
        green) echo "blue" ;;
        *) echo "blue" ;;
    esac
}

port_for_color() {
    case "$1" in
        blue) echo "$BLUE_PORT" ;;
        green) echo "$GREEN_PORT" ;;
        *) echo "Unknown color: $1" >&2; exit 2 ;;
    esac
}

service_for_color() {
    echo "web_$1"
}

wait_ready() {
    local color="$1"
    local port
    port="$(port_for_color "$color")"
    local url="http://127.0.0.1:${port}/ready"
    echo "Waiting for $color readiness at $url"
    for _ in $(seq 1 60); do
        if curl -fsS --max-time 5 "$url" >/dev/null; then
            echo "$color is ready"
            return 0
        fi
        sleep 2
    done
    echo "$color did not become ready" >&2
    return 1
}

write_nginx_upstream() {
    local color="$1"
    local port
    port="$(port_for_color "$color")"
    printf 'proxy_pass http://127.0.0.1:%s;\n' "$port" > "$NGINX_UPSTREAM_FILE"
    $NGINX_TEST_CMD
    $NGINX_RELOAD_CMD
    printf '%s\n' "$color" > "$ACTIVE_FILE"
    echo "Traffic switched to $color on port $port"
}

run_expand_only_migrations() {
    local color="$1"
    if [[ "$RUN_MIGRATIONS" != "1" ]]; then
        echo "Skipping migrations because RUN_MIGRATIONS=$RUN_MIGRATIONS"
        return 0
    fi
    echo "Running expand-only migrations on $color"
    compose run --rm "$(service_for_color "$color")" flask db upgrade
}

deploy() {
    local current target current_service target_service
    current="$(active_color)"
    target="$(opposite_color "$current")"
    current_service="$(service_for_color "$current")"
    target_service="$(service_for_color "$target")"

    echo "Current: $current, target: $target"
    git fetch origin "$BRANCH"
    git pull --ff-only origin "$BRANCH"

    compose build "$target_service"
    run_expand_only_migrations "$target"
    compose up -d "$target_service"
    wait_ready "$target"
    write_nginx_upstream "$target"

    if [[ "$UPDATE_CELERY" == "1" ]]; then
        echo "Updating Celery worker/beat after web switch"
        compose up -d --build celery-worker celery-beat
    fi

    echo "Letting old $current connections drain for ${DRAIN_SECONDS}s"
    sleep "$DRAIN_SECONDS"
    compose stop "$current_service" || true
    docker image prune -f || true
    echo "Deploy complete: $target is active"
}

rollback() {
    local current previous previous_service
    current="$(active_color)"
    previous="$(opposite_color "$current")"
    previous_service="$(service_for_color "$previous")"
    echo "Rollback from $current to $previous"
    compose up -d "$previous_service"
    wait_ready "$previous"
    write_nginx_upstream "$previous"
    echo "Rollback complete: $previous is active"
}

status() {
    local current port
    current="$(active_color)"
    port="$(port_for_color "$current")"
    echo "Active color: $current"
    echo "Active URL: http://127.0.0.1:$port/ready"
    compose ps
}

case "${1:-deploy}" in
    deploy) deploy ;;
    rollback) rollback ;;
    status) status ;;
    switch-blue) write_nginx_upstream blue ;;
    switch-green) write_nginx_upstream green ;;
    *) echo "Usage: $0 [deploy|rollback|status|switch-blue|switch-green]" >&2; exit 2 ;;
esac
