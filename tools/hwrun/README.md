# tools/hwrun - run a test pcap on the live board from a web page

`hwrun_server.py` is the backend of the fpganow.com page "Run on Hardware" (WordPress plugin
`fpganow-hwrun` in the websites repo). It is what a visitor's click turns into:

1. **load the implementation** - `xmutil loadapp mktdata_poc_labview` or `mktdata_poc_rtl`
   (skipped when already loaded; clears a stale factory overlay and restarts dfx-mgr if
   `loadapp` refuses). The two apps are the saved builds under `builds/*/kria_build/`
   packaged with `make -C kria_app package-variant NAME=... BIT_BIN=...` and installed with
   `make -C kria_app deploy-variant NAME=...`.
2. **bring the host side of the 10G link up** - wait for `eth1` UP (the link only rises once
   the PL transmits), add `10.0.1.10/24` if missing, re-add the static ARP entry for
   10.0.1.14 (it vanishes on every link flap).
3. **capture** - `poc_server poll` in the background on the board, `poc_server reset`,
   `scripts/send_pcap_udp.py <pcap> --gap-ms 5` from this PC, stop the poll, fetch the text.
4. **score** - the capture is parsed with `ip_export/netlist_sim/eval_sim.py` (same code,
   `--short-price-scale 100`): one row per CMD record with the pcap's expected fields, the
   match verdict, recv.time / parse.time and the latency `(parse - recv) * 6.4 ns`. Records
   with recv.time 0 (the LabVIEW build's todo item 19) get no latency.

Everything of a run is kept in `runs/<id>.{json,csv,capture.txt}` (gitignored).

```bash
make hwrun                       # = python3 tools/hwrun/hwrun_server.py --bind 172.17.0.1 --port 8300
python3 tools/hwrun/hwrun_server.py --bind 127.0.0.1 --port 8300    # local only
```

The bearer token is read from `tools/hwrun/token` (gitignored; generate one with
`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`), `--token` or `$HWRUN_TOKEN`.
The default bind is localhost; `172.17.0.1` (the Docker bridge) is what the local WordPress
dev container reaches as `host.docker.internal`. Never bind it to a public address - the
production web server should reach it through a tunnel (SSH reverse tunnel, Tailscale or
a Cloudflare tunnel from this PC).

API (JSON, `Authorization: Bearer <token>`):

| Call | Returns |
|------|---------|
| `GET /api/catalog` | pcaps (with frame/message counts), implementations, boards (+ loaded app), busy/queued, recent runs |
| `POST /api/runs` `{"pcap","implementation","board"}` | `202 {"id","position"}`; 429 when 4 runs are already waiting |
| `GET /api/runs/<id>` | status `queued/running/done/failed`, step log, summary (`latency_ns` and `since_frame_start_ns` each give count/min/mean/median/p95/p99/max over matched, stamped messages; percentiles interpolate linearly, position p·(n−1)), per-message `rows`, the eval_sim report text |
| `GET /api/runs/<id>/csv` | the rows as CSV |

Runs execute one at a time (one board, one FIFO consumer). A run takes ~10 s, ~20 s when the
bitstream has to be switched. Measured 2026-10-21 through the page: LabVIEW build
203/203 on frame_boundary_repro (median 701 ns), RTL build 659/659 on the 20-frame pcap
(median 326 ns), identical to the hand runs of 2026-10-20.

Pitfalls met while writing it: `pkill -f hwrun_server` from a shell whose command line
contains that text kills the shell itself - stop the service with `fuser -k 8300/tcp`.

## Production link (shigsoft -> this PC), set up 2026-10-26

The router forwards TCP 2222 to this PC's port 22. Three scripts, in this order:

1. on shigsoft as john: `bash setup_shigsoft_tunnel.sh` (copied into the plugin dir in the
   websites repo) - makes the key, installs the cron-kept tunnel, prints the public key;
2. here: `sudo bash tools/hwrun/setup_home_ssh.sh '<that public key>'` - OpenSSH server
   (key-only, john only), the key restricted to forwarding to 172.17.0.1:8300, and a systemd
   unit `hwrun.service` that keeps the run service up;
3. on shigsoft in `~/websites/fpganow` after `git pull`: `bash wp-content/plugins/fpganow-hwrun/setup_shigsoft_site.sh <token>`
   - activates the plugin, points it at `http://172.17.0.1:8301` (the tunnel end on shigsoft's
   Docker bridge), creates the page, and curls the service from inside the container.
