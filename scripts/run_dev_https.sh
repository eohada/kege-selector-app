#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-5443}"
TARGET="${2:-127.0.0.1:5000}"
BIND_IP="${3:-192.168.1.3}"
CERTS_DIR="certs"

if [ ! -f "$CERTS_DIR/dev_server_bundle.pem" ]; then
    echo "Certificate bundle not found. Generating..."
    ./scripts/setup_dev_ca.sh "$BIND_IP"
fi

echo "Starting Local Trusted HTTPS Proxy on https://$BIND_IP:$PORT -> $TARGET"
echo "Press Ctrl+C to stop."
exec socat OPENSSL-LISTEN:$PORT,bind=$BIND_IP,reuseaddr,fork,cert=$CERTS_DIR/dev_server_bundle.pem,verify=0 TCP:$TARGET
