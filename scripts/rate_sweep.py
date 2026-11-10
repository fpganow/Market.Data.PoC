#!/usr/bin/env python3
"""Replay a pcap to the KR260 over the 10G cable at increasing rates and report where
records start to go missing.

    python3 scripts/rate_sweep.py tests/data/generated_2026_09_17_multi.pcap \
        --mbps 5 10 20 50 100 200 500 --loop 20 [--host kr260u] [--out sweep_dir]

Per rate: on the board start `poc_server poll cmd` (its own reset clears the CMD capture
FIFO), pulse the NI IP reset, tick the XXV MAC counters; send the file --loop times with
scripts/send_pcap_udp.py at that rate; wait for the capture to stop growing; stop the
poller, tick the counters again and fetch the capture. Then count:

    mac_rx     frames the XXV MAC received since the first tick (xxv_stats); 0 means the
               IP's statistics counters read zero on this bitstream, not that nothing arrived
    records    CMD records the host got (expected = loops x messages in the pcap)
    seq_gaps   records missing between consecutive parser sequence numbers (CMD word 12):
               non-zero means the parser emitted them and the CMD capture path dropped them
    fr_lost    frames of which not a single message came back (lost before the parser)
    fr_trunc   frames that came back with messages missing (the parser was back-pressured
               and the NI IP dropped the tail of the frame); msg_lost counts those messages
    lat p50/max  parse.time - recv.time; a p50 in the ms range means the pipeline is
               queueing behind the host readout, not parsing at speed

Frames are identified by aligning the records, in order, against the pcap's message
sequence (type enum + orderId), so repeated passes and truncated frames are both handled.
The 2026-11-06 result: the PS readout (`poc_server poll`, two 32-bit UIO reads per word)
drains ~8k records/s; above ~2.5 Mbit/s of PITCH the CMD capture FIFO back-pressures the
parser and frames come back truncated. Measuring the parser itself needs a harness that
does not move every record through AXI-Lite (counters / DMA sink; see CLAUDE.md).

--sink (needs the 2026-11-08 bitstream with axis_mon / axi_gpio_mon and `poc_mon` on the
board): no poc_server at all. Per rate the in-fabric monitor is put in sink mode (TREADY held
high to the NI IP, records dropped) and cleared, the file is sent, and the counters are
snapshotted:

    rx_frames  frames the 10G MAC handed to the NI IP (expected = datagrams sent)
    records    CMD records the parser emitted (expected = loops x messages)
    seq_gaps   parser sequence-number gaps (0 unless the capture path dropped something)
    bad_len    records that were not 16 beats
    stall      cycles the CMD stream was back-pressured (0 in sink mode by construction)
    lat_max    max parse.time - recv.time inside the parser

This measures the parser itself at any rate up to line rate. Without --sink the host readout
caps the test at ~3 Mbit/s (see above). Rates can be given as --mbps, --pps or --speed
(pcap-timestamp multiplier); see send_pcap_udp.py. Captures are kept in --out (default:
scratch dir under /tmp)."""
import argparse, os, re, subprocess, sys, time, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SENDER = os.path.join(HERE, "send_pcap_udp.py")

def load_eval_sim():
    spec = importlib.util.spec_from_file_location("eval_sim", os.path.join(REPO, "ip_export/netlist_sim/eval_sim.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def ssh(host, cmd, timeout=120):
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr

def mac_counts(text):
    m = re.search(r"RX total (\d+) RX good (\d+) TX total (\d+)", text)
    return (int(m[1]), int(m[2])) if m else (None, None)

def mon_counts(text):
    """poc_mon snap/stop output: one 'name value' per line."""
    d = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try: d[parts[0]] = int(parts[1], 0)
            except ValueError: pass
    return d

def sweep_sink(a, mode, rates, exp_frames, exp_records, n_frames):
    """Counters-only sweep through axis_mon (no poc_server)."""
    M = f"{a.remote_dir}/poc_mon"; R = f"{a.remote_dir}/poc_server"
    chk = ssh(a.host, f"sudo pkill -INT -x poc_server; sudo {M} id")
    if "id 0x4d4f4e3" not in chk.lower():            # MON1 / MON2
        sys.exit(f"axis_mon not reachable on {a.host}: {chk.strip()}\n(bitstream without axi_gpio_mon, or poc_mon not deployed: make -C apps/poc_inject deploy)")
    hdr = f"{'rate':>8} {'sent':>7} {'ach_mbps':>9} | {'rx_frames':>9} {'rx_bad':>6} {'records':>8} {'seq_gaps':>8} {'bad_len':>7} {'stall':>8} {'lat_min':>8} {'lat_max':>9}  verdict"
    print(hdr); print("-" * len(hdr))
    rows = []
    for rate in rates:
        ssh(a.host, f"sudo {R} reset >/dev/null 2>&1; sleep 0.3; sudo {M} start sink >/dev/null")
        r = subprocess.run([sys.executable, SENDER, a.pcap, f"--{mode}", str(rate), "--loop", str(a.loop),
                            "--src", a.src, "--dst", a.dst, "--port", str(a.port)], capture_output=True, text=True)
        m = re.search(r"sent (\d+) datagrams .* in ([\d.]+) s: ([\d,]+) pps, ([\d,.]+) Mbit/s", r.stdout)
        if not m: print(f"{rate:>8}  sender failed: {r.stdout.strip()} {r.stderr.strip()}"); continue
        sent, mbps = int(m[1]), float(m[4].replace(",", ""))
        time.sleep(a.settle)
        c = mon_counts(ssh(a.host, f"sudo {M} stop"))
        if "records" not in c: print(f"{rate:>8}  poc_mon stop failed"); continue
        rxf, rxb, rec, gaps = c["rx_frames"], c["rx_bad"], c["records"], c["seq_gaps"]
        lat_ns = c["lat_max_ticks"] * 10
        numbered = rec + gaps                       # messages the parser assigned a seq to
        if rxf == sent and rec == exp_records and gaps == 0: verdict = "ok"
        elif rxf < sent: verdict = f"{sent - rxf} frames lost before the parser (MAC/xgmii2axis)"
        elif rxf > sent: verdict = f"{rxf - sent} more frames than datagrams (fragmentation?)"
        elif numbered > exp_records * 1.01:
            verdict = f"parser DESYNC: numbered {numbered} messages for {exp_records} sent, output {rec}"
        elif gaps:
            # sink mode: TREADY is held high, so a seq gap is a message the parser numbered but
            # never output -- dropped inside the NI IP (parser loop -> CMD writer FIFO)
            verdict = f"parser dropped {gaps} of {numbered} numbered messages inside the NI IP ({100 * gaps / numbered:.1f}%)"
        elif rec < exp_records: verdict = f"parser never numbered {exp_records - rec} messages ({100 * (exp_records - rec) / exp_records:.1f}%)"
        else: verdict = f"parser emitted {rec - exp_records} extra records"
        if c.get("bad_magic"): verdict += f"; {c['bad_magic']} bad magic"
        lat_min = f"{c['lat_min_ticks'] * 10 / 1e3:>6.2f}us" if "lat_min_ticks" in c else f"{'-':>8}"
        print(f"{rate:>8g} {sent:>7} {mbps:>9.1f} | {rxf:>9} {rxb:>6} {rec:>8} {gaps:>8} {c['bad_len']:>7} {c['stall_cycles']:>8} {lat_min} {lat_ns / 1e3:>7.2f}us  {verdict}")
        rows.append((rate, sent, mbps, c))
    print(f"\nexpected per rate: {exp_frames} frames, {exp_records} records (sink mode, nothing captured)")
    return rows

def analyze(ev, path, truth, passes):
    """truth: per pass, list of frames, each a list of (type enum, orderId) per message; passes = loops sent."""
    hdrs, cmds = ev.records(path)
    first = next((i for i, w in enumerate(cmds) if w[12] == 1 and w[15] == 0xDEADBEEF), None)
    if first: cmds = cmds[first:]
    r = dict(records=len(cmds), seq_gaps=0, fr_lost=0, fr_trunc=0, msg_lost=0, lat_p50_ns=0, lat_max_ns=0)
    if not cmds: return r
    seqs = [w[12] for w in cmds]
    r["seq_gaps"] = sum(max(0, b - a - 1) for a, b in zip(seqs, seqs[1:]))
    lat = sorted((w[14] - w[13]) * ev.TICK for w in cmds)
    r["lat_p50_ns"], r["lat_max_ns"] = lat[len(lat) // 2], lat[-1]
    # align records to the pcap message sequence (cyclic over passes), greedy smallest skip
    flat = [(fi, (t, oid)) for fi, fr in enumerate(truth) for (t, oid) in fr]
    N = len(flat); p = 0; seen = {}
    for w in cmds:
        key = (w[0], ev.s8(w[2]) if w[0] != 0 else "")      # Time records carry no orderId
        for k in range(N):
            fi, m = flat[(p + k) % N]
            if m == key:
                seen[(p + k) // N, fi] = seen.get(((p + k) // N, fi), 0) + 1
                p += k + 1; break
        else:
            p += 1                                   # unmatched record: step on
    for ps in range(passes):
        for fi, fr in enumerate(truth):
            got = seen.get((ps, fi), 0)
            if got == 0: r["fr_lost"] += 1
            elif got < len(fr): r["fr_trunc"] += 1
    r["msg_lost"] = max(0, N * passes - len(cmds))      # every message the host did not get
    return r

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pcap")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mbps", type=float, nargs="+"); g.add_argument("--pps", type=float, nargs="+")
    g.add_argument("--speed", type=float, nargs="+")
    ap.add_argument("--loop", type=int, default=20, help="passes of the file per rate (default 20)")
    ap.add_argument("--host", default="kr260u"); ap.add_argument("--remote-dir", default="/home/ubuntu")
    ap.add_argument("--out", default=None, help="directory for the per-rate captures")
    ap.add_argument("--src", default="10.0.1.10"); ap.add_argument("--dst", default="10.0.1.14"); ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--settle", type=float, default=1.0, help="seconds the capture must stay the same size before stopping")
    ap.add_argument("--sink", action="store_true", help="counters only via axis_mon/poc_mon, no poc_server (parser measured directly)")
    a = ap.parse_args()
    mode, rates = next((k, v) for k, v in (("mbps", a.mbps), ("pps", a.pps), ("speed", a.speed)) if v)
    if a.sink:
        ev = load_eval_sim()
        frames = ev.pcap_frames(a.pcap); n_msgs = sum(len(ms) for _, ms in frames); n_frames = len(frames)
        print(f"pcap: {n_frames} frames / {n_msgs} messages per pass, {a.loop} passes -> expect {n_frames * a.loop} frames, {n_msgs * a.loop} records per rate")
        sweep_sink(a, mode, rates, n_frames * a.loop, n_msgs * a.loop, n_frames)
        return
    out = a.out or os.path.join(os.environ.get("TMPDIR", "/tmp"), f"rate_sweep_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    ev = load_eval_sim()
    frames = ev.pcap_frames(a.pcap); n_msgs = sum(len(ms) for _, ms in frames); n_frames = len(frames)
    truth = [[(ev.expect(m)["type"], m[6:14].decode("latin1") if m[1] in ev.ENUM and m[1] != 0x20 else "") for m in ms] for _, ms in frames]
    exp_records, exp_frames = n_msgs * a.loop, n_frames * a.loop
    R = f"{a.remote_dir}/poc_server"; S = f"{a.remote_dir}/xxv_stats"; cap = f"{a.remote_dir}/cap_sweep.txt"
    print(f"pcap: {n_frames} frames / {n_msgs} messages per pass, {a.loop} passes -> expect {exp_frames} frames, {exp_records} records per rate")
    print(f"captures: {out}")
    hdr = f"{'rate':>8} {'sent_pps':>9} {'ach_mbps':>9} | {'mac_rx':>6} {'records':>8} {'seq_gaps':>8} {'fr_lost':>7} {'fr_trunc':>8} {'msg_lost':>8} {'lat_p50':>9} {'lat_max':>9}  verdict"
    print(hdr); print("-" * len(hdr))
    for rate in rates:
        ssh(a.host, f"sudo pkill -INT -x poc_server; sleep 0.5; sudo bash -c 'nohup {R} poll cmd > {cap} 2>&1 &'; sleep 1.5; "
                    f"sudo {R} reset >/dev/null; sleep 0.5; sudo {S} >/dev/null")
        r = subprocess.run([sys.executable, SENDER, a.pcap, f"--{mode}", str(rate), "--loop", str(a.loop),
                            "--src", a.src, "--dst", a.dst, "--port", str(a.port)], capture_output=True, text=True)
        m = re.search(r"sent (\d+) datagrams .* in ([\d.]+) s: ([\d,]+) pps, ([\d,.]+) Mbit/s", r.stdout)
        if not m: print(f"{rate:>8}  sender failed: {r.stdout.strip()} {r.stderr.strip()}"); continue
        sent, pps, mbps = int(m[1]), float(m[3].replace(",", "")), float(m[4].replace(",", ""))
        last = -1
        for _ in range(60):
            time.sleep(a.settle)
            size = int(ssh(a.host, f"stat -c %s {cap}").split()[0])
            if size == last: break
            last = size
        tail = ssh(a.host, f"sudo pkill -INT -x poc_server; sleep 0.5; sudo {S}")
        mac_rx, mac_good = mac_counts(tail)
        local = os.path.join(out, f"cap_{mode}_{rate:g}.txt")
        subprocess.run(["scp", "-q", f"{a.host}:{cap}", local], check=True)
        s = analyze(ev, local, truth, a.loop)
        if s["records"] == exp_records and s["seq_gaps"] == 0: verdict = "ok"
        elif s["seq_gaps"]: verdict = f"CMD capture path dropped {s['seq_gaps']} (parser kept up)"
        elif mac_rx and mac_rx < sent: verdict = f"{sent - mac_rx} frames never reached the MAC"
        else: verdict = f"{100 * s['msg_lost'] / exp_records:.0f}% of messages lost; parser back-pressured (p50 latency {s['lat_p50_ns'] / 1e6:.0f} ms)"
        print(f"{rate:>8g} {pps:>9,.0f} {mbps:>9.1f} | {str(mac_rx):>6} {s['records']:>8} {s['seq_gaps']:>8} {s['fr_lost']:>7} {s['fr_trunc']:>8} {s['msg_lost']:>8} {s['lat_p50_ns'] / 1e3:>7.0f}us {s['lat_max_ns'] / 1e3:>7.0f}us  {verdict}")
    print(f"\nexpected per rate: {exp_frames} frames, {exp_records} records; captures in {out}")

if __name__ == "__main__":
    main()
