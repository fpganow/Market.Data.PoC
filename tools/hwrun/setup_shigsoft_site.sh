#!/bin/bash
# shigsoft side, after the plugin files are in ~/websites/fpganow/wp-content/plugins/fpganow-hwrun
# (git pull of the websites repo) and the tunnel is up: activate the plugin on the production
# site, point it at the tunnel and create the page. Run as john in ~/websites/fpganow:
#   bash setup_shigsoft_site.sh <token>      (token = contents of tools/hwrun/token on the lab PC)
set -e
TOKEN="$1"; [ -n "$TOKEN" ] || { echo "usage: $0 <hwrun token>"; exit 1; }
cd ~/websites/fpganow
WP="docker run --rm --env-file .env.prod --volumes-from fpganow_wp --network container:fpganow_wp wordpress:cli wp"
$WP plugin activate fpganow-hwrun
$WP option update fpganow_hwrun_url http://172.17.0.1:8301
$WP option update fpganow_hwrun_token "$TOKEN" >/dev/null && echo "token set"
$WP option update fpganow_hwrun_cooldown 20
$WP post list --post_type=page --name=run-on-hardware --field=ID | grep -q . || \
$WP post create --post_type=page --post_status=publish --post_title='Run on Hardware' --post_name=run-on-hardware \
  --post_content='<!-- wp:paragraph --><p>Pick one of the pre-recorded CBOE PITCH captures, the parser implementation and the board. The capture is replayed over the 10 Gigabit Ethernet cable into the live FPGA, and every message the parser emits comes back with the time it was received and the time it was parsed, in ticks of 6.4 ns of the 156.25 MHz MAC clock.</p><!-- /wp:paragraph --><!-- wp:shortcode -->[fpganow_hwrun]<!-- /wp:shortcode -->'
echo "tunnel check from the WordPress container:"
docker exec fpganow_wp curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" http://172.17.0.1:8301/api/catalog
