#!/usr/bin/env python3
"""Hardware run service for the fpganow.com "Run on hardware" page.

Replays one of the pre-canned test pcaps (tests/data/*.pcap) against the live KR260 over the
10G cable, with either parser implementation loaded (LabVIEW IP Export netlist or the poc_v/
Verilog parser, installed on the board as the xmutil apps mktdata_poc_labview / mktdata_poc_rtl,
see kria_app/Makefile `package-variant`), captures the parser's CMD/DEBUG streams with
`poc_server poll`, scores them with ip_export/netlist_sim/eval_sim.py and reports every
message with its recv->parse latency.

    python3 tools/hwrun/hwrun_server.py [--bind 127.0.0.1] [--port 8300] [--token SECRET]
                                        [--runs-dir tools/hwrun/runs]

HTTP API (JSON; every request needs `Authorization: Bearer <token>` when a token is set):
    GET  /api/catalog            the selectable pcaps / implementations / boards + board state
    POST /api/runs               {"pcap": "...", "implementation": "labview|rtl|rtl156", "board": "kr260", "speed": "gap5|pcap|..." (optional)}
                                 -> 202 {"id": ..., "position": n}
    GET  /api/runs               the most recent runs (summaries)
    GET  /api/runs/<id>          status, step log, and when done: summary + per-message rows
    GET  /api/runs/<id>/csv      the per-message table as CSV
Runs are executed one at a time by a worker thread (one board, one FIFO consumer). The
WordPress plugin fpganow-hwrun (websites repo) proxies these endpoints for the public page.

Needs: ssh access to the board (host alias in the catalog), the 10G interface on this PC
(the QNAP adapter, found by its MAC 24:5e:be:8b:b1:94 since its ethN name changes, 10.0.1.10/24; the service adds the address and the static ARP entry itself with sudo),
and `poc_server` deployed in the board user's home (make server-deploy)."""
import argparse, csv, datetime, io, json, os, queue, re, secrets, statistics, subprocess, sys
import threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ip_export", "netlist_sim"))
sys.path.insert(0, os.path.join(ROOT, "apps", "poc_inject"))
import eval_sim                     # noqa: E402  (records, pcap_frames, expect, s8, TICK)
from decode_capture import MSG_TYPES, CMD_TYPE_NAMES   # noqa: E402

eval_sim.SHORT_PRICE_SCALE = 100    # short-variant prices are x100 in both parsers (todo item 9 / a0)
TICK = eval_sim.TICK                # 6.4 ns

CATALOG = {
    "pcaps": {
        "generated_2025_05_02": {
            "file": "tests/data/generated_2025_05_02.pcap",
            "label": "generated_2025_05_02 - 1 frame, 10 messages",
            "description": "One frame: a Time message and nine AddOrders. The loopback/sim reference frame."},
        "frame_boundary_repro": {
            "file": "tests/data/frame_boundary_repro.pcap",
            "label": "frame_boundary_repro - 6 frames, 203 messages",
            "description": "Frames 3 and 5 end in 7- and 8-byte AXI beats (the 2026-09 frame-boundary bug)."},
        "generated_2026_09_17_multi": {
            "file": "tests/data/generated_2026_09_17_multi.pcap",
            "label": "generated_2026_09_17_multi - 20 frames, 659 messages",
            "description": "14 PITCH message types, ~1000-byte frames, sequence 1..659 continuing across frames."},
        "heartbeat_repro": {
            "file": "tests/data/heartbeat_repro.pcap",
            "label": "heartbeat_repro - 26 frames, 659 messages + 6 heartbeats",
            "description": "The multi pcap with six 8-byte heartbeat frames inserted."},
        "unsupported_repro": {
            "file": "tests/data/unsupported_repro.pcap",
            "label": "unsupported_repro - 20 frames, 662 messages",
            "description": "The multi pcap with three undecoded PITCH types spliced into frame 10 (-> Unsupported records)."},
    },
    # tick_ns: unit of the CMD record's recv.time / parse.time words. The LabVIEW designs and poc_v
    # count the 156.25 MHz RX clock (6.4 ns, todo item 10); vivado_rtl keeps a true 10 ns tick (time10).
    "implementations": {
        "labview": {"label": "LabVIEW FPGA (IP Export netlist, 2026-10-20)", "app": "mktdata_poc_labview", "tick_ns": 6.4,
                    "description": "bats.parser.vi and poc.ip.kria.vi exported from LabVIEW FPGA 2020 as a netlist (export of 2026-10-20), 100 MHz parser loop."},
        "rtl": {"label": "Verilog (poc_v, 2026-10-20)", "app": "mktdata_poc_rtl", "tick_ns": 6.4,
                "description": "Hand-written Verilog parser with the LabVIEW IP's ports and stream formats (poc_v/, build of 2026-10-20), 100 MHz parser clock."},
        "rtl156": {"label": "Pure Verilog, 156.25 MHz (vivado_rtl, 2026-11-08)", "app": "mktdata_rtl", "tick_ns": 10.0,
                   # the page reads records through the slow host FIFO; this build drops records instead of stalling
                   # when that FIFO is full (50 of 659 came back at any faster speed, 2026-11-11), so only the slow
                   # speed is offered here. Its rate results come from the in-fabric counters (scripts/rate_sweep.py --sink).
                   "speeds": ["gap5"],
                   "description": "vivado_rtl/ip/pitch_rtl_top.v: one message per clock in the 10G receive clock, one 1024-bit record beat (bitstream 3). 10G line rate, 0.81 us max latency."},
    },
    "boards": {
        "kr260": {"label": "AMD Kria KR260 Starter Kit", "ssh": "kr260u", "iface": "eno2np1", "host_mac": "38:05:25:38:16:3d",
                  "src": "10.0.1.10", "dst": "10.0.1.14", "mac": "00:0a:35:18:3c:1f", "port": 8000,
                  "description": "Zynq UltraScale+ (K26 SOM), 10G SFP+ via the XXV Ethernet core, 3 m DAC from the lab PC's Intel E810."},
    },
}
GAP_MS = 5.0          # inter-datagram gap of the default speed (the capture path cannot drain line-rate bursts)
# Playback speeds offered by the page: key -> pacing arguments of scripts/send_pcap_udp.py. The first is the default.
SPEEDS = {
    "gap5": {"label": "Slow: one frame every 5 ms", "args": ["--gap-ms", str(GAP_MS)],
             "description": "A fixed 5 ms between frames (the capture's own timing is ignored). Every frame is parsed on an idle board."},
    "pcap": {"label": "As recorded (the capture's own timestamps)", "args": ["--speed", "1"],
             "description": "Frames are sent with the spacing recorded in the pcap file."},
    "pcap10": {"label": "10x faster than recorded", "args": ["--speed", "10"],
               "description": "The capture's own spacing, compressed ten times."},
    "mbps100": {"label": "100 Mbit/s", "args": ["--mbps", "100"],
                "description": "Evenly paced at 100 Mbit/s on the wire."},
    "mbps1000": {"label": "1 Gbit/s", "args": ["--mbps", "1000"],
                 "description": "Evenly paced at 1 Gbit/s on the wire."},
    "top": {"label": "Top speed (back to back)", "args": ["--topspeed"],
            "description": "No pacing: the frames leave back to back, as fast as the sender can go on the 10G link."},
}
DEFAULT_SPEED = "gap5"
QUEUE_MAX = 4
KEEP_RUNS = 200


def sh(cmd, timeout=120, check=True):
    """Run a local command (list or shell string); returns stdout, raises on failure."""
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{cmd if isinstance(cmd, str) else ' '.join(cmd)}\n{r.stdout}{r.stderr}".strip())
    return r.stdout


def ssh(host, script, timeout=120, check=True):
    return sh(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, script], timeout=timeout, check=check)


class Board:
    """The one shared piece of hardware: app switching, link bring-up, capture."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.loaded = None          # xmutil app known to be loaded, None = unknown
        self.last_seen = None

    def loaded_app(self):
        out = ssh(self.cfg["ssh"], "ls /sys/kernel/config/device-tree/overlays/ 2>/dev/null; true")
        apps = [d[:-len("_image_1")] for d in out.split() if d.endswith("_image_1")]
        self.last_seen = time.time()
        self.loaded = apps[0] if apps else None
        return self.loaded

    def select_app(self, app, log):
        host = self.cfg["ssh"]
        cur = self.loaded_app()
        if cur == app:
            log(f"board: {app} already loaded")
        else:
            log(f"board: loading {app} (was {cur or 'nothing'})")
            out = ssh(host, f"sudo xmutil unloadapp >/dev/null 2>&1; sudo xmutil loadapp {app} 2>&1", timeout=90, check=False)
            if "Loaded" not in out:
                # a stale overlay (factory image after a power cycle) blocks dfx-mgr: clear it and retry
                log("board: loadapp refused, clearing the stale overlay and restarting dfx-mgr")
                ssh(host, "for d in /sys/kernel/config/device-tree/overlays/*; do [ -d \"$d\" ] && sudo rmdir \"$d\"; done; "
                          "sudo systemctl restart dfx-mgr; sleep 3; true", timeout=90, check=False)
                out = ssh(host, f"sudo xmutil loadapp {app} 2>&1", timeout=90, check=False)
                if "Loaded" not in out:
                    raise RuntimeError(f"xmutil loadapp {app} failed: {out.strip()}")
            self.loaded = app
            log(f"board: {out.strip().splitlines()[-1]}")
            time.sleep(2)           # let the 10G link settle before touching the host interface
        self.link_up(log)

    def link_up(self, log):
        """The host side of the 10G cable: interface UP (it rises once the PL transmits),
        static address and the static neighbour entry (the FPGA never answers ARP)."""
        c = dict(self.cfg)
        # WSL renumbers ethN when adapters re-enumerate (the QNAP Thunderbolt adapter was eth1
        # on 2026-10-21 and eth1 was gone on 10-27), so find it by MAC and fall back to the name
        if c.get("host_mac"):
            for l in sh(["ip", "-br", "link"], check=False).splitlines():
                f = l.split()
                if len(f) >= 3 and f[2].lower() == c["host_mac"].lower():
                    c["iface"] = f[0].split("@")[0]
                    break
            else:
                raise RuntimeError(f"no host interface with MAC {c['host_mac']} (10G adapter not plugged into this PC?)")
        for i in range(30):
            out = sh(["ip", "-br", "addr", "show", c["iface"]], check=False)
            if " UP " in out:
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"{c['iface']} did not come up (10G link to the board down?)")
        if f"{c['src']}/24" not in out:
            sh(["sudo", "-n", "ip", "addr", "add", f"{c['src']}/24", "dev", c["iface"]], check=False)
        sh(["sudo", "-n", "ip", "neigh", "replace", c["dst"], "lladdr", c["mac"], "dev", c["iface"], "nud", "permanent"])
        log(f"host: {c['iface']} up, {c['src']} -> {c['dst']} ({c['mac']})")

    def run_capture(self, pcap_path, log, pacing=("--gap-ms", str(GAP_MS))):
        """poc_server poll in the background on the board, reset the IP, replay the pcap from this
        PC, stop the poll and bring the capture text back."""
        host = self.cfg["ssh"]; cap = "/home/ubuntu/hwrun_capture.txt"
        ssh(host, "sudo pkill -x poc_server 2>/dev/null; sleep 0.5; "
                  f"sudo bash -c 'nohup ./poc_server poll > {cap} 2>&1 &'; sleep 1.5; "
                  "sudo ./poc_server reset >/dev/null; sleep 0.5", timeout=60)
        log("board: poc_server poll started, parser reset")
        c = self.cfg
        out = sh([sys.executable, os.path.join(ROOT, "scripts", "send_pcap_udp.py"), pcap_path,
                  *pacing, "--src", c["src"], "--dst", c["dst"], "--port", str(c["port"])], timeout=120)
        log("host: " + out.strip())
        text = ssh(host, f"sleep 1; sudo pkill -INT -x poc_server; sleep 1; cat {cap}", timeout=60)
        log(f"board: capture retrieved ({len(text.splitlines())} lines)")
        return text


def pct(sorted_values, p):
    """Percentile by linear interpolation between order statistics (position p*(n-1)); the page's app.js does the same."""
    pos = (len(sorted_values) - 1) * p; lo = int(pos); hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)

def lat_stats(values):
    """min / mean / median / p95 / p99 / max (ns, 1 decimal) or None when nothing is stamped."""
    if not values: return None
    v = sorted(values)
    return {"count": len(v), "min": v[0], "mean": round(statistics.fmean(v), 1), "median": round(pct(v, 0.5), 1),
            "p95": round(pct(v, 0.95), 1), "p99": round(pct(v, 0.99), 1), "max": v[-1]}

def score(capture_path, pcap_path, tick=TICK):
    """Per-message rows + summary from a `poc_server poll` capture, the way eval_sim.py scores it.
    `tick` = ns per recv.time / parse.time count of the implementation that produced the capture."""
    hdrs, cmds = eval_sim.records(capture_path)
    frames = eval_sim.pcap_frames(pcap_path)
    first = next((i for i, w in enumerate(cmds) if w[12] in (0, 1) and w[15] == 0xDEADBEEF), None)
    stale = first or 0
    cmds = cmds[stale:]
    truth = [(f, m) for f, (plen, ms) in enumerate(frames) for m in ms]
    rows, frame_t0 = [], {}
    for i, w in enumerate(cmds):
        # recv.time 0 = the LabVIEW parser's stalled-cycle quirk (todo item 19): no valid latency
        lat_ok = w[13] != 0 and 0 <= w[14] - w[13] < 10 ** 6
        row = {"index": i + 1, "seq": w[12], "cmd_type": w[0],
               "cmd_type_name": CMD_TYPE_NAMES[w[0]] if 0 <= w[0] < len(CMD_TYPE_NAMES) else f"?{w[0]}",
               "recv_ticks": w[13], "parse_ticks": w[14],
               "latency_ns": round((w[14] - w[13]) * tick, 1) if lat_ok else None}
        if i < len(truth):
            f, m = truth[i]; e = eval_sim.expect(m)
            got = {"type": w[0]}
            if "orderId" in e: got["orderId"] = eval_sim.s8(w[2])
            if "qty" in e: got["qty"] = w[3]
            if "price" in e: got["price"] = w[5]
            if "executed.qty" in e: got["executed.qty"] = w[6]
            if "canceled.qty" in e: got["canceled.qty"] = w[7]
            if "remaining.qty" in e: got["remaining.qty"] = w[8]
            if "symbol" in e: got["symbol"] = eval_sim.s8(w[4])[:len(e["symbol"])]   # record pads to 8, as eval_sim.py compares
            diff = {k: [got[k], e[k]] for k in got if got[k] != e[k]}
            t0 = frame_t0.setdefault(f, w[13]) if lat_ok else frame_t0.get(f)
            row.update({"frame": f + 1, "pitch_type": f"0x{e['pitch']:02X}",
                        "pitch_name": MSG_TYPES.get(e["pitch"], "unsupported"),
                        "order_id": e.get("orderId", ""), "symbol": e.get("symbol", "").strip(),
                        "quantity": e.get("qty", ""), "price": e.get("price", ""),
                        "since_frame_start_ns": round((w[14] - t0) * tick, 1) if lat_ok and t0 else None,
                        "match": "ok" if not diff else "MISMATCH", "mismatch": diff})
        else:
            row.update({"frame": "", "pitch_type": "", "pitch_name": "(extra record)", "order_id": eval_sim.s8(w[2]),
                        "symbol": "", "quantity": "", "price": "", "since_frame_start_ns": "", "match": "EXTRA", "mismatch": {}})
        rows.append(row)
    lats = [r["latency_ns"] for r in rows if r["match"] == "ok" and r["latency_ns"] is not None]
    sfs = [r["since_frame_start_ns"] for r in rows if r["match"] == "ok" and r["since_frame_start_ns"] not in (None, "")]
    per_frame = {}
    for r in rows:
        if r["match"] == "ok" and r["latency_ns"] is not None: per_frame.setdefault(r["frame"], []).append(r["latency_ns"])
    summary = {
        "frames_in_pcap": len(frames), "messages_in_pcap": len(truth),
        "records_captured": len(cmds), "stale_records_skipped": stale,
        "records_matching": sum(1 for r in rows if r["match"] == "ok"),
        "records_mismatching": sum(1 for r in rows if r["match"] == "MISMATCH"),
        "records_extra": sum(1 for r in rows if r["match"] == "EXTRA"),
        "records_missing": max(0, len(truth) - len(cmds)),
        "debug_header_records": len(hdrs),
        "records_without_recv_time": sum(1 for r in rows if r["latency_ns"] is None),
        "latency_ns": lat_stats(lats),
        "since_frame_start_ns": lat_stats(sfs),
        "per_frame": [{"frame": f, "messages": len(v), "first_ns": v[0], "last_ns": max(v)} for f, v in sorted(per_frame.items())],
        "tick_ns": tick,
    }
    summary["pass"] = (summary["records_matching"] == len(truth) and not summary["records_mismatching"]
                       and not summary["records_extra"])
    return summary, rows


CSV_COLUMNS = ["index", "seq", "frame", "pitch_type", "pitch_name", "cmd_type", "cmd_type_name", "order_id", "symbol",
               "quantity", "price", "recv_ticks", "parse_ticks", "latency_ns", "since_frame_start_ns", "match"]


def rows_to_csv(rows):
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore"); w.writeheader()
    for r in rows: w.writerow(r)
    return buf.getvalue()


class Runner:
    def __init__(self, runs_dir):
        self.runs_dir = runs_dir; os.makedirs(runs_dir, exist_ok=True)
        self.runs, self.order = {}, []
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.boards = {k: Board(v) for k, v in CATALOG["boards"].items()}
        self.current = None
        threading.Thread(target=self.worker, daemon=True).start()

    def submit(self, req):
        if self.q.qsize() >= QUEUE_MAX:
            raise ValueError(f"queue full ({QUEUE_MAX} runs waiting), try again in a minute")
        rid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        run = {"id": rid, "request": req, "status": "queued", "submitted": now(), "log": [], "summary": None}
        with self.lock:
            self.runs[rid] = run; self.order.append(rid)
            while len(self.order) > KEEP_RUNS:
                self.runs.pop(self.order.pop(0), None)
        self.q.put(rid)
        return run, self.q.qsize()

    def worker(self):
        while True:
            rid = self.q.get()
            run = self.runs.get(rid)
            if not run: continue
            self.current = rid
            run["status"] = "running"; run["started"] = now()
            rows = None
            def log(msg):
                line = f"{datetime.datetime.now().strftime('%H:%M:%S')} {msg}"
                run["log"].append(line); print(f"[{rid}] {line}", flush=True)
            try:
                req = run["request"]
                pc, impl, board = CATALOG["pcaps"][req["pcap"]], CATALOG["implementations"][req["implementation"]], self.boards[req["board"]]
                speed = SPEEDS[req.get("speed") or DEFAULT_SPEED]
                log(f"run: {req['pcap']} with {impl['label']} on {board.cfg['label']}, playback: {speed['label']}")
                run["step"] = "load"; board.select_app(impl["app"], log)
                run["step"] = "capture"
                text = board.run_capture(os.path.join(ROOT, pc["file"]), log, speed["args"])
                cap = os.path.join(self.runs_dir, f"{rid}.capture.txt")
                with open(cap, "w") as fh: fh.write(text)
                run["step"] = "score"
                summary, rows = score(cap, os.path.join(ROOT, pc["file"]), impl.get("tick_ns", TICK))
                run["summary"] = summary
                run["report"] = sh([sys.executable, os.path.join(ROOT, "ip_export", "netlist_sim", "eval_sim.py"), cap,
                                    os.path.join(ROOT, pc["file"]), "--short-price-scale", "100"], check=False)
                log(f"score: {summary['records_matching']}/{summary['messages_in_pcap']} messages match"
                    + (f", latency min/median/max {summary['latency_ns']['min']}/{summary['latency_ns']['median']}/{summary['latency_ns']['max']} ns"
                       if summary["latency_ns"] else ""))
                run["status"] = "done"
            except Exception as e:          # noqa: BLE001 - every failure must land in the run record
                log(f"error: {e}")
                run["status"] = "failed"; run["error"] = str(e)
            run["finished"] = now(); run.pop("step", None)
            with open(os.path.join(self.runs_dir, f"{rid}.json"), "w") as fh:
                json.dump({**run, "rows": rows}, fh)
            if rows is not None:
                with open(os.path.join(self.runs_dir, f"{rid}.csv"), "w") as fh: fh.write(rows_to_csv(rows))
            self.current = None
            self.q.task_done()

    def get(self, rid, with_rows=False):
        run = self.runs.get(rid)
        if run is None and re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", rid or ""):
            p = os.path.join(self.runs_dir, f"{rid}.json")       # older run, read back from disk
            if os.path.exists(p):
                with open(p) as fh: run = json.load(fh)
                if not with_rows: run = {k: v for k, v in run.items() if k != "rows"}
                return run
        if run is None: return None
        out = dict(run)
        if with_rows and run["status"] == "done":
            with open(os.path.join(self.runs_dir, f"{rid}.json")) as fh: out["rows"] = json.load(fh)["rows"]
        if run["status"] == "queued":
            out["position"] = 1 + list(self.q.queue).index(rid) if rid in list(self.q.queue) else 0
        return out

    def catalog(self):
        c = json.loads(json.dumps(CATALOG))
        for v in c["pcaps"].values():
            frames = eval_sim.pcap_frames(os.path.join(ROOT, v["file"]))
            v["frames"] = len(frames); v["messages"] = sum(len(m) for _, m in frames)
        for k, v in c["boards"].items():
            b = self.boards[k]
            v["loaded_app"] = b.loaded; v["state_age_s"] = round(time.time() - b.last_seen) if b.last_seen else None
            for s in ("ssh", "mac"): v.pop(s, None)
        c["speeds"] = {k: {"label": v["label"], "description": v["description"]} for k, v in SPEEDS.items()}
        c["default_speed"] = DEFAULT_SPEED
        c["busy"] = self.current is not None; c["queued"] = self.q.qsize()
        c["recent"] = [self.summary_of(self.runs[r]) for r in reversed(self.order[-10:])]
        return c

    @staticmethod
    def summary_of(run):
        return {k: run.get(k) for k in ("id", "request", "status", "submitted", "finished", "summary", "error")}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def make_handler(runner, token):
    class H(BaseHTTPRequestHandler):
        server_version = "hwrun/1.0"

        def log_message(self, fmt, *args):
            print(f"{self.address_string()} {fmt % args}", flush=True)

        def send_json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def authed(self):
            if not token: return True
            h = self.headers.get("Authorization", "")
            if h == f"Bearer {token}": return True
            self.send_json(401, {"error": "unauthorized"}); return False

        def do_GET(self):
            if not self.authed(): return
            path = self.path.split("?")[0]
            if path == "/api/catalog": return self.send_json(200, runner.catalog())
            if path == "/api/runs":
                return self.send_json(200, [runner.summary_of(runner.runs[r]) for r in reversed(runner.order[-50:])])
            m = re.fullmatch(r"/api/runs/([0-9a-f-]+)(/csv)?", path)
            if m:
                run = runner.get(m[1], with_rows=True)
                if run is None: return self.send_json(404, {"error": "no such run"})
                if m[2]:
                    if run["status"] != "done": return self.send_json(409, {"error": "run not finished"})
                    body = rows_to_csv(run["rows"]).encode()
                    self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="hwrun_{run["id"]}.csv"')
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
                return self.send_json(200, run)
            self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if not self.authed(): return
            if self.path.split("?")[0] != "/api/runs": return self.send_json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(n) or b"{}")
                sel = {"pcap": str(req.get("pcap", "")), "implementation": str(req.get("implementation", "")),
                       "board": str(req.get("board", "")), "speed": str(req.get("speed") or DEFAULT_SPEED)}
                if sel["speed"] not in SPEEDS:
                    return self.send_json(400, {"error": f"unknown speed {sel['speed']!r}", "choices": list(SPEEDS)})
                allowed = CATALOG["implementations"].get(sel["implementation"], {}).get("speeds")
                if allowed and sel["speed"] not in allowed:
                    return self.send_json(400, {"error": f"speed {sel['speed']!r} is not available for this implementation", "choices": allowed})
                for k, table in (("pcap", "pcaps"), ("implementation", "implementations"), ("board", "boards")):
                    if sel[k] not in CATALOG[table]:
                        return self.send_json(400, {"error": f"unknown {k} {sel[k]!r}", "choices": sorted(CATALOG[table])})
                run, pos = runner.submit(sel)
            except ValueError as e:
                return self.send_json(429, {"error": str(e)})
            except Exception as e:          # noqa: BLE001
                return self.send_json(400, {"error": str(e)})
            self.send_json(202, {"id": run["id"], "status": run["status"], "position": pos})
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bind", default="127.0.0.1",
                    help="listen address (default localhost only; use the docker bridge address, e.g. 172.17.0.1, "
                         "to serve the WordPress container)")
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--token", default=os.environ.get("HWRUN_TOKEN"),
                    help="bearer token the clients must send (default: $HWRUN_TOKEN, or the contents of tools/hwrun/token)")
    ap.add_argument("--runs-dir", default=os.path.join(HERE, "runs"))
    a = ap.parse_args()
    token = a.token
    tf = os.path.join(HERE, "token")
    if token is None and os.path.exists(tf):
        token = open(tf).read().strip()
    if not token:
        print("warning: no token configured (--token / $HWRUN_TOKEN / tools/hwrun/token): the API is open", flush=True)
    runner = Runner(a.runs_dir)
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(runner, token))
    print(f"hwrun: listening on {a.bind}:{a.port}, runs in {a.runs_dir}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
