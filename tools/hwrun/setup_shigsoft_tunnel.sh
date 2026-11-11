#!/bin/bash
# shigsoft side (run as john, no sudo needed): a key for the tunnel and a cron-kept
#   ssh -L 172.17.0.1:8301 -> (home) 172.17.0.1:8300   via bayside.stratoudakis.com:2222
# Run it once BEFORE setup_home_ssh.sh (it prints the public key that script needs); the cron
# job simply retries every minute until the home side accepts the key.
set -e
KEY=~/.ssh/id_ed25519_bayside; HOST=bayside.stratoudakis.com; PORT=2222
[ -f $KEY ] || ssh-keygen -q -t ed25519 -N "" -C "shigsoft->bayside hwrun tunnel" -f $KEY
mkdir -p ~/bin
cat > ~/bin/hwrun_tunnel.sh <<SH
#!/bin/bash
# keeps the hwrun tunnel up; started by cron every minute, flock makes it a singleton
exec flock -n /tmp/hwrun_tunnel.lock ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \\
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new \\
    -i $KEY -p $PORT -L 172.17.0.1:8301:172.17.0.1:8300 john@$HOST
SH
chmod +x ~/bin/hwrun_tunnel.sh
( { crontab -l 2>/dev/null || true; } | grep -v hwrun_tunnel || true; echo "* * * * * $HOME/bin/hwrun_tunnel.sh >/dev/null 2>&1" ) | crontab -
echo "cron installed; public key to pass to setup_home_ssh.sh:"
cat $KEY.pub
