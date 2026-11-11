#!/bin/bash
# Home side of the shigsoft -> lab PC link (run once, as root, in this WSL):
#   sudo bash tools/hwrun/setup_home_ssh.sh "<public key line printed by setup_shigsoft_tunnel.sh>"
# 1. installs OpenSSH server, key-only, user john only (the router forwards TCP 2222 -> this PC:22)
# 2. authorizes shigsoft's tunnel key, restricted to forwarding to the hwrun service and nothing else
# 3. installs a systemd unit that keeps hwrun_server.py running on 172.17.0.1:8300
set -e
PUBKEY="$1"; USER_NAME=john; HOME_DIR=$(getent passwd $USER_NAME | cut -d: -f6)
REPO=$(cd "$(dirname "$0")/../.." && pwd)
[ -n "$PUBKEY" ] || { echo "usage: $0 '<ssh-ed25519 AAAA... comment>'"; exit 1; }

apt-get install -y openssh-server >/dev/null
cat > /etc/ssh/sshd_config.d/10-hwrun.conf <<CONF
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers $USER_NAME
X11Forwarding no
ClientAliveInterval 60
ClientAliveCountMax 3
CONF
systemctl enable --now ssh >/dev/null 2>&1; systemctl restart ssh

install -d -m 700 -o $USER_NAME -g $USER_NAME "$HOME_DIR/.ssh"
AK="$HOME_DIR/.ssh/authorized_keys"; touch "$AK"; chown $USER_NAME:$USER_NAME "$AK"; chmod 600 "$AK"
LINE="restrict,port-forwarding,permitopen=\"172.17.0.1:8300\" $PUBKEY"
grep -qF "$PUBKEY" "$AK" || echo "$LINE" >> "$AK"

cat > /etc/systemd/system/hwrun.service <<UNIT
[Unit]
Description=fpganow.com Run-on-Hardware service (Market.Data.PoC/tools/hwrun)
After=network.target docker.service

[Service]
User=$USER_NAME
WorkingDirectory=$REPO
ExecStart=/usr/bin/python3 $REPO/tools/hwrun/hwrun_server.py --bind 172.17.0.1 --port 8300
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
fuser -k 8300/tcp >/dev/null 2>&1 || true
systemctl daemon-reload; systemctl enable --now hwrun; sleep 2
echo "sshd: $(systemctl is-active ssh) on port $(sshd -T | awk '/^port /{print $2}'), password auth $(sshd -T | awk '/^passwordauthentication/{print $2}')"
echo "hwrun: $(systemctl is-active hwrun)  $(ss -ltn | grep -c '172.17.0.1:8300') listener(s) on 172.17.0.1:8300"
echo "authorized key: $(grep -c permitopen "$AK") restricted line(s) in $AK"
