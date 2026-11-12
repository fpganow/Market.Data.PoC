# FPGA Now - Run on Hardware (`fpganow-hwrun`)

WordPress plugin behind the "Run on hardware" page: a visitor picks one of the pre-canned CBOE
PITCH test pcaps, the parser implementation (LabVIEW FPGA netlist or the Verilog `poc_v/`
parser) and the board (KR260), the pcap is replayed over the 10G cable against the live board,
and the page shows every parsed message with its recv->parse latency as a table, a CSV
download and a scatter chart.

## Pieces

| Where | What |
|-------|------|
| `Market.Data.PoC/tools/hwrun/hwrun_server.py` | The run service on the PC cabled to the board: loads the requested bitstream (`xmutil loadapp mktdata_poc_labview` / `mktdata_poc_rtl`), brings the host side of the 10G link up, captures with `poc_server poll`, replays the pcap, scores with `eval_sim.py`. Bearer-token HTTP API on port 8300. |
| this plugin | Settings page (service URL, token, per-IP cooldown), REST proxy `fpganow-hwrun/v1/{catalog,runs,runs/<id>,runs/<id>/csv}`, shortcode `[fpganow_hwrun]` with the form, log, summary cards, Chart.js chart (bundled `vendor/chart.umd.js` 4.4.1), per-frame and per-message tables. |

The browser only ever talks to WordPress; the token stays server-side. Starting a run needs
the custom header `X-FPGANOW-HWRUN: 1` (blocks cross-site requests) and is rate-limited per IP.

## Setup

1. On the service PC: `python3 tools/hwrun/hwrun_server.py --bind <addr> --port 8300`
   (token in `tools/hwrun/token`). For the local Docker dev stack bind to the Docker bridge
   address (`172.17.0.1`), which the container reaches as `host.docker.internal`
   (`extra_hosts` in `docker-compose.yaml`).
2. Activate the plugin, fill in Settings -> Run on Hardware (URL + token). The page shows
   whether the service answers.
3. Put `[fpganow_hwrun]` on a page.

For the production site the service must be reachable from the web server: an SSH reverse
tunnel, Tailscale or a Cloudflare tunnel from the lab PC to the server (the service is only
ever bound to a private address and still needs the token).

## Sign-in (v1.2.0, 2026-11-12)

Starting a run needs a signed-in account (Settings -> Run on Hardware -> "Require sign-in").
Visitors sign in with Google on the page: Google Identity Services hands the browser an ID token,
`POST fpganow-hwrun/v1/google-login` checks it with `https://oauth2.googleapis.com/tokeninfo`
(audience = our client ID, verified e-mail) and logs in the subscriber account for that address,
creating it on first use (user meta `fpganow_google_sub`). Only a Google OAuth **client ID** is
needed (type "Web application", authorised JavaScript origin `https://fpganow.com`); no secret, no
redirect URI. Accounts registered by e-mail through wp-login.php can run only if "Also allow e-mail
accounts" is ticked; editors and administrators always can, and never sign in through Google here.
Viewing the catalog and finished runs stays public.
