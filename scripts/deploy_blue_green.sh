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
STOP_OLD_AFTER_DRAIN="${STOP_OLD_AFTER_DRAIN:-0}"
PRUNE_IMAGES_AFTER_DEPLOY="${PRUNE_IMAGES_AFTER_DEPLOY:-0}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
#
MIGRATION_RECOVERY_ANCHOR="${MIGRATION_RECOVERY_ANCHOR:-f2b3c4d5e6f7}"
# Celery belongs to the primary compose stack. Rebuilding it through the
# blue-green file could create duplicate workers and duplicate scheduled jobs.
UPDATE_CELERY="${UPDATE_CELERY:-0}"

cd "$APP_DIR"
mkdir -p "$STATE_DIR"

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

ensure_clean_worktree() {
    if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
        echo "Deployment stopped: the server checkout contains local changes or untracked files." >&2
        echo "Commit them to the release branch or move them outside $APP_DIR, then run deploy again." >&2
        return 1
    fi
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
    local response_file="/tmp/boostudy-ready-${color}.json"
    echo "Waiting for $color readiness at $url"
    for attempt in $(seq 1 60); do
        local code
        code="$(curl -sS -o "$response_file" -w '%{http_code}' --max-time 5 "$url" || true)"
        if [[ "$code" == "200" ]]; then
            echo "$color is ready"
            return 0
        fi
        echo "Readiness attempt $attempt failed with HTTP $code"
        if [[ -s "$response_file" ]]; then
            sed -n '1,8p' "$response_file"
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
    local migration_log
    if [[ "$RUN_MIGRATIONS" != "1" ]]; then
        echo "Skipping migrations because RUN_MIGRATIONS=$RUN_MIGRATIONS"
        return 0
    fi
    echo "Running expand-only migrations on $color"
    migration_log="$(mktemp /tmp/boostudy-migrations-${color}.XXXXXX)"
    if ! compose run --rm "$(service_for_color "$color")" flask db upgrade -d /app/migrations >"$migration_log" 2>&1; then
        cat "$migration_log" >&2
        if ! grep -q "Can't locate revision identified" "$migration_log"; then
            rm -f "$migration_log"
            echo "Migration failed. Traffic was not switched." >&2
            return 1
        fi

        echo "Recovering an orphaned legacy Alembic revision from $MIGRATION_RECOVERY_ANCHOR"
        if ! compose run --rm "$(service_for_color "$color")" flask db stamp "$MIGRATION_RECOVERY_ANCHOR" --purge -d /app/migrations; then
            rm -f "$migration_log"
            echo "Legacy migration recovery failed. Traffic was not switched." >&2
            return 1
        fi
        if ! compose run --rm "$(service_for_color "$color")" flask db upgrade -d /app/migrations; then
            rm -f "$migration_log"
            echo "Migration failed after legacy recovery. Traffic was not switched." >&2
            return 1
        fi
    else
        cat "$migration_log"
    fi
    rm -f "$migration_log"

    if ! compose run --rm "$(service_for_color "$color")" flask db current -d /app/migrations; then
        echo "Migration state cannot be read after upgrade. Traffic was not switched." >&2
        return 1
    fi
    if ! compose run --rm "$(service_for_color "$color")" flask schema-audit; then
        echo "Schema audit failed after migrations. Traffic was not switched." >&2
        return 1
    fi
}

deploy() {
    local current target current_service target_service
    current="$(active_color)"
    target="$(opposite_color "$current")"
    current_service="$(service_for_color "$current")"
    target_service="$(service_for_color "$target")"

    echo "Current: $current, target: $target"
    ensure_clean_worktree
    git fetch origin "$BRANCH"
    git pull --ff-only origin "$BRANCH"

    if [[ ! -f "$COMPOSE_FILE" ]]; then
        echo "Missing $APP_DIR/$COMPOSE_FILE. Deploy is stopped before any traffic switch." >&2
        exit 2
    fi

    if [[ -f "docker-compose.yml" ]]; then
        echo "Ensuring primary infrastructure (redis, db) is running..."
        docker compose up -d db redis || true
    fi

    compose build "$target_service"
    run_expand_only_migrations "$target"
    compose up -d "$target_service"
    wait_ready "$target"
    write_nginx_upstream "$target"

    if [[ "$UPDATE_CELERY" == "1" ]]; then
        echo "Celery update is intentionally managed by the primary compose stack." >&2
        echo "Use its dedicated release procedure after this web deployment." >&2
    fi

    echo "Letting old $current connections drain/reconnect for ${DRAIN_SECONDS}s"
    sleep "$DRAIN_SECONDS"
    if [[ "$STOP_OLD_AFTER_DRAIN" == "1" ]]; then
        compose stop "$current_service" || true
        echo "Stopped old $current service"
    else
        echo "Keeping old $current service running for fast rollback"
    fi
    if [[ "$PRUNE_IMAGES_AFTER_DEPLOY" == "1" ]]; then
        docker image prune -f || true
    else
        echo "Skipping image prune; keep old images for rollback"
    fi
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

# Legacy installations created before Alembic can contain a revision from an
# abandoned migration history.  A normal upgrade cannot start from an unknown
# revision, so recover it from the last schema-repair anchor and then apply the
# current forward-only chain.  This never deletes application data.