#!/usr/bin/env bash
set -euo pipefail

CERTS_DIR="certs"
IP_HOST="${1:-192.168.1.3}"

mkdir -p "$CERTS_DIR"

if [ ! -f "$CERTS_DIR/dev_root_ca.crt" ]; then
    echo "=== Generating BooStudy Local Dev Root CA ==="
    openssl req -x509 -new -nodes -keyout "$CERTS_DIR/dev_root_ca.key" \
        -sha256 -days 3650 -out "$CERTS_DIR/dev_root_ca.crt" \
        -subj "/CN=BooStudy Dev Root CA/O=BooStudy Local"
    chmod 600 "$CERTS_DIR/dev_root_ca.key"
    echo "Root CA created at $CERTS_DIR/dev_root_ca.crt"
fi

echo "=== Generating Server Certificate for $IP_HOST ==="
cat << EOF > "$CERTS_DIR/san.cnf"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = $IP_HOST
O = BooStudy Local Dev

[req_ext]
subjectAltName = @alt_names

[alt_names]
IP.1 = $IP_HOST
IP.2 = 127.0.0.1
DNS.1 = localhost
EOF

openssl req -new -nodes -keyout "$CERTS_DIR/dev_server.key" -out "$CERTS_DIR/dev_server.csr" -config "$CERTS_DIR/san.cnf"
openssl x509 -req -in "$CERTS_DIR/dev_server.csr" -CA "$CERTS_DIR/dev_root_ca.crt" -CAkey "$CERTS_DIR/dev_root_ca.key" \
    -CAcreateserial -out "$CERTS_DIR/dev_server.crt" -days 365 -sha256 -extfile "$CERTS_DIR/san.cnf" -extensions req_ext
chmod 600 "$CERTS_DIR/dev_server.key"
cat "$CERTS_DIR/dev_server.crt" "$CERTS_DIR/dev_server.key" > "$CERTS_DIR/dev_server_bundle.pem"
chmod 600 "$CERTS_DIR/dev_server_bundle.pem"

echo "=== Success ==="
echo "Install certs/dev_root_ca.crt on your smartphone (Android / iOS) as a Trusted CA Certificate."
echo "Then start HTTPS proxy with: ./scripts/run_dev_https.sh"
