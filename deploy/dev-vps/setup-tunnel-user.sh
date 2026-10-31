#!/usr/bin/env bash
# deploy/dev-vps/setup-tunnel-user.sh
# One-time setup script for Linux dev-VPS to provision a locked-down SSH tunnel user.

set -euo pipefail

TUNNEL_USER="boostudy-tunnel"
TUNNEL_HOME="/home/${TUNNEL_USER}"
PORT="5055"

echo "=== Provisioning Restricted SSH Tunnel User: ${TUNNEL_USER} ==="

# Ensure /bin/false is recognized as a valid shell in /etc/shells for PAM
if [ -f /etc/shells ] && ! grep -q "^/bin/false$" /etc/shells; then
    echo "/bin/false" >> /etc/shells
fi

if id "${TUNNEL_USER}" &>/dev/null; then
    echo "[INFO] User ${TUNNEL_USER} already exists."
    usermod -s /bin/false "${TUNNEL_USER}"
else
    useradd -m -d "${TUNNEL_HOME}" -s /bin/false -c "BooStudy Reverse Tunnel" "${TUNNEL_USER}"
    echo "[OK] Created system user ${TUNNEL_USER} with shell /bin/false."
fi

# Ensure SSH directory
mkdir -p "${TUNNEL_HOME}/.ssh"
chmod 700 "${TUNNEL_HOME}/.ssh"
touch "${TUNNEL_HOME}/.ssh/authorized_keys"
chmod 600 "${TUNNEL_HOME}/.ssh/authorized_keys"
chown -R "${TUNNEL_USER}:${TUNNEL_USER}" "${TUNNEL_HOME}/.ssh"

# Configure sshd to allow reverse port forwarding exclusively to loopback port 5055
SSHD_CONFIG_FILE="/etc/ssh/sshd_config.d/boostudy-tunnel.conf"
mkdir -p /etc/ssh/sshd_config.d

cat <<EOF > "${SSHD_CONFIG_FILE}"
# BooStudy Reverse SSH Tunnel Security Policy
Match User ${TUNNEL_USER}
    AllowTcpForwarding yes
    PermitListen 127.0.0.1:${PORT}
    PermitOpen none
    GatewayPorts no
    X11Forwarding no
    AllowAgentForwarding no
    PermitTTY no
    ForceCommand /bin/false
EOF

chmod 644 "${SSHD_CONFIG_FILE}"
systemctl reload ssh || systemctl reload sshd

echo "=== Setup Complete ==="
echo "1. Add your developer public key (from local PC) to: ${TUNNEL_HOME}/.ssh/authorized_keys"
echo "   Recommended authorized_keys prefix:"
echo '   restrict,port-forwarding,permitlisten="127.0.0.1:'"${PORT}"'" ssh-ed25519 ...'
echo "2. Reverse SSH forwarding is strictly locked to 127.0.0.1:${PORT} on this VPS."
echo "3. Arbitrary forwarding, outbound tunneling, and interactive shell are completely forbidden."
