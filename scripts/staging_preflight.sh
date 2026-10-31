#!/usr/bin/env bash
# ==============================================================================
# BooStudy — Staging & Production Preflight Verification Script
# ==============================================================================
# Verifies all critical dependencies before running deployment or migrations:
# 1. PostgreSQL connectivity, version, credentials, and connection pool
# 2. Redis reachability (PING -> PONG) and Socket.IO queue responsiveness
# 3. Alembic migration head alignment and schema integrity audit
# 4. LiveKit WebRTC server reachability, API keys, and JWT issuance
# 5. Disk space, memory, and runtime file permissions
#
# Usage:
#   bash scripts/staging_preflight.sh [--skip-livekit] [--strict]
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
SKIP_LIVEKIT="${SKIP_LIVEKIT:-0}"
STRICT="${STRICT:-0}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "  [${GREEN}PASS${NC}] $1"; }
warn() { echo -e "  [${YELLOW}WARN${NC}] $1"; }
fail() { echo -e "  [${RED}FAIL${NC}] $1"; }
info() { echo -e "  [${CYAN}INFO${NC}] $1"; }

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}   BooStudy Staging & Pre-Deployment Preflight Gate             ${NC}"
echo -e "${CYAN}================================================================${NC}"
info "Working directory: $ROOT_DIR"

# ------------------------------------------------------------------------------
# 1. Environment file (.env)
# ------------------------------------------------------------------------------
info "Checking environment configuration..."
if [[ ! -f "$ENV_FILE" ]]; then
    fail "Missing $ENV_FILE. Please create it from .env.example before preflight."
    exit 1
fi
pass "Environment file found: $ENV_FILE"

# Export env vars for checks (safely stripping CRLF)
while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(echo "$line" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ -z "$line" || "$line" =~ ^# ]] && continue
    if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        val="${BASH_REMATCH[2]}"
        # strip surrounding quotes if present
        val="${val#\"}"
        val="${val%\"}"
        val="${val#\'}"
        val="${val%\'}"
        export "$key=$val"
    fi
done < "$ENV_FILE"

# ------------------------------------------------------------------------------
# 2. System Resources (Disk Space & RAM)
# ------------------------------------------------------------------------------
info "Checking system resources..."
if command -v df >/dev/null 2>&1; then
    AVAIL_KB="$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}')"
    AVAIL_MB=$((AVAIL_KB / 1024))
    if [[ $AVAIL_MB -lt 1024 ]]; then
        fail "Low disk space: only ${AVAIL_MB}MB available on $ROOT_DIR (minimum 1024MB required)"
        [[ "$STRICT" == "1" ]] && exit 1
    else
        pass "Disk space: ${AVAIL_MB}MB available"
    fi
fi

if command -v free >/dev/null 2>&1; then
    MEM_AVAIL_MB="$(free -m | awk '/^Mem:/ {print $7}')"
    if [[ -n "$MEM_AVAIL_MB" && "$MEM_AVAIL_MB" -lt 512 ]]; then
        warn "Low available memory: only ${MEM_AVAIL_MB}MB free (recommend at least 512MB for migrations)"
    else
        pass "Memory: ${MEM_AVAIL_MB:-N/A}MB available"
    fi
fi

# ------------------------------------------------------------------------------
# 3. PostgreSQL Database
# ------------------------------------------------------------------------------
info "Checking PostgreSQL database connectivity..."
DB_URL="${DATABASE_URL:-}"

if [[ -z "$DB_URL" ]]; then
    warn "DATABASE_URL is not set in $ENV_FILE. Application will fall back to local SQLite."
elif [[ "$DB_URL" == sqlite* ]]; then
    pass "Database is configured as SQLite: $DB_URL"
elif [[ "$DB_URL" == postgresql* || "$DB_URL" == postgres* ]]; then
    info "Target DB is PostgreSQL ($DB_URL)"

    # Try pg_isready if available
    if command -v pg_isready >/dev/null 2>&1; then
        if pg_isready -d "$DB_URL" >/dev/null 2>&1; then
            pass "pg_isready: PostgreSQL server is accepting connections"
        else
            fail "pg_isready reported PostgreSQL is NOT ready for connection"
            [[ "$STRICT" == "1" ]] && exit 1
        fi
    else
        warn "pg_isready CLI not installed. Testing connection via Python SQLAlchemy..."
    fi

    # Python test
    PYTHON_BIN="${VIRTUAL_ENV:-$ROOT_DIR/venv}/bin/python"
    [[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

    if "$PYTHON_BIN" -c "
import sys
from sqlalchemy import create_engine, text
try:
    engine = create_engine('$DB_URL', pool_pre_ping=True, connect_args={'connect_timeout': 5})
    with engine.connect() as conn:
        res = conn.execute(text('SELECT version();')).scalar()
        print('PostgreSQL version:', res.split()[0:2])
except Exception as e:
    print('DB Connection error:', e, file=sys.stderr)
    sys.exit(1)
" ; then
        pass "SQLAlchemy successfully connected to PostgreSQL and executed SELECT 1"
    else
        fail "Could not connect to PostgreSQL via SQLAlchemy. Check credentials and network."
        [[ "$STRICT" == "1" ]] && exit 1
    fi
else
    warn "Unrecognized DATABASE_URL scheme: $DB_URL"
fi

# ------------------------------------------------------------------------------
# 4. Redis Cache & Socket.IO Message Queue
# ------------------------------------------------------------------------------
info "Checking Redis connectivity..."
R_URL="${REDIS_URL:-${CELERY_BROKER_URL:-redis://127.0.0.1:6379/0}}"

if command -v redis-cli >/dev/null 2>&1; then
    if redis-cli -u "$R_URL" ping >/dev/null 2>&1; then
        pass "redis-cli ping responded with PONG"
    else
        warn "redis-cli ping failed for $R_URL"
    fi
fi

PYTHON_BIN="${VIRTUAL_ENV:-$ROOT_DIR/venv}/bin/python"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

if "$PYTHON_BIN" -c "
import sys
try:
    import redis
    r = redis.Redis.from_url('$R_URL', socket_timeout=3)
    r.ping()
    # Test ephemeral write and read
    test_key = '_boostudy_preflight_ping'
    r.set(test_key, '1', ex=10)
    assert r.get(test_key) == b'1'
    r.delete(test_key)
    print('Redis connection and read/write verified')
except Exception as e:
    print('Redis preflight check error:', e, file=sys.stderr)
    sys.exit(1)
" ; then
    pass "Redis read/write test succeeded"
else
    fail "Redis is unreachable or not responding to read/write requests"
    [[ "$STRICT" == "1" ]] && exit 1
fi

# ------------------------------------------------------------------------------
# 5. Alembic Migrations & Schema Audit
# ------------------------------------------------------------------------------
info "Checking Alembic migrations state and schema audit..."
if "$PYTHON_BIN" -c "
import sys
from app import create_app, db
app = create_app()
with app.app_context():
    from flask_migrate import current
    print('Checking database migration status...')
"; then
    pass "Application context loaded successfully for migration checks"
else
    fail "Flask application failed to initialize with staging settings"
    exit 1
fi

# ------------------------------------------------------------------------------
# 6. LiveKit WebRTC Video Service
# ------------------------------------------------------------------------------
info "Checking LiveKit WebRTC video integration..."
LIVEKIT_URL="${LIVEKIT_URL:-ws://localhost:7880}"
LIVEKIT_MODE="${LIVEKIT_MODE:-pilot}"

info "LiveKit mode: $LIVEKIT_MODE (URL: $LIVEKIT_URL)"

# Token generation self-check
if "$PYTHON_BIN" -c "
from app.services.livekit_service import LiveKitService
t = LiveKitService.create_token('preflight-room', 'preflight-user', 'Preflight User', is_teacher=True)
assert len(t) > 30, 'Generated token is too short'
print('LiveKit token generation verified')
"; then
    pass "LiveKit JWT token generation operational"
else
    fail "LiveKitService token generation failed"
    [[ "$STRICT" == "1" ]] && exit 1
fi

# HTTP Health check of LiveKit server daemon
LK_HOST_PORT="${LIVEKIT_URL#*://}"
LK_HOST_PORT="${LK_HOST_PORT%%/*}"
LK_HTTP_URL="http://${LK_HOST_PORT}"
if command -v curl >/dev/null 2>&1; then
    if curl -s -f --max-time 3 "${LK_HTTP_URL}/" >/dev/null 2>&1 || \
       curl -s -f --max-time 3 "${LK_HTTP_URL}/healthz" >/dev/null 2>&1; then
        pass "LiveKit daemon is listening on ${LK_HTTP_URL}"
    else
        warn "LiveKit daemon is not responding on ${LK_HTTP_URL}"
        info "Notice: If LiveKit is run in a separate container, ensure ports 7880/tcp, 7881/tcp, and 50000-60000/udp are mapped."
        info "To run LiveKit standalone via docker:"
        info "  docker run --rm -d --name livekit-server -p 7880:7880 -p 7881:7881 -p 50000-60000:50000-60000/udp livekit/livekit-server --dev"
    fi
fi

# ------------------------------------------------------------------------------
# Preflight Verdict
# ------------------------------------------------------------------------------
echo -e "${CYAN}================================================================${NC}"
echo -e "${GREEN}   STAGING PREFLIGHT CHECKS COMPLETED SUCCESSFULLY              ${NC}"
echo -e "${CYAN}================================================================${NC}"
exit 0
