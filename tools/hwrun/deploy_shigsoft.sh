#!/bin/bash
# Run ON shigsoft as john:   bash ~/deploy_hwrun.sh
# Expects, delivered by scp from the lab PC: ~/fpganow-hwrun (the plugin dir) and ~/hwrun.token.
# Installs the plugin into the production site's plugins dir (sudo: the dir belongs to www-data),
# installs and starts the cron-kept tunnel to the lab PC, activates the plugin, creates the page.
set -e
P=~/websites/fpganow/wp-content/plugins
[ -d ~/fpganow-hwrun ] || { echo "~/fpganow-hwrun missing (scp it first)"; exit 1; }
[ -f ~/hwrun.token ]   || { echo "~/hwrun.token missing (scp it first)"; exit 1; }
TOKEN=$(tr -d '\n' < ~/hwrun.token)

echo "== plugin files -> $P/fpganow-hwrun (sudo)"
sudo rm -rf "$P/fpganow-hwrun"
sudo mv ~/fpganow-hwrun "$P/"
sudo chown -R www-data:www-data "$P/fpganow-hwrun"

echo "== tunnel"
bash "$P/fpganow-hwrun/setup_shigsoft_tunnel.sh"
pgrep -f hwrun_tunnel.sh >/dev/null || { nohup ~/bin/hwrun_tunnel.sh >/dev/null 2>&1 & }
sleep 6
ss -ltn | grep -q 8301 && echo "tunnel listening on 172.17.0.1:8301" || echo "tunnel NOT listening yet (cron retries every minute)"

echo "== site"
cd ~/websites/fpganow
bash "$P/fpganow-hwrun/setup_shigsoft_site.sh" "$TOKEN"
rm -f ~/hwrun.token
echo "== done: https://fpganow.com/run-on-hardware/"
