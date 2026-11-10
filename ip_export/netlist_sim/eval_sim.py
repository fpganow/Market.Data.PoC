#!/usr/bin/env python3
"""Score a netlist-sim output (sim_out.txt) against the pcap it was fed.

    python3 eval_sim.py sim_out.txt ../../tests/data/generated_2026_09_17_multi.pcap [--short-price-scale 100]

--short-price-scale N multiplies the expected price of the short variants (0x22, 0x28, 0x2B,
2 implied decimals on the wire) by N; use 100 once the *.generated.vi message VIs (which scale
them to 4 implied decimals, todo.txt item 9) are in the export. Default 1 = as on the wire.
Also accepts a `poc_server poll` capture from the board instead of sim_out.txt.
Checks: Sequenced Unit Header lengths seen by the parser (DEBUG 0xDE records) vs the
pcap, number of CMD records vs messages, the parser's type enum per message, and for
Add/Executed messages the orderId (and quantity for Adds) against the pcap bytes.
Prints recv->parse latency per frame (10 ns per tick)."""
import re, struct, sys

TICK = 6.4   # ns per tick: the counter runs in the 156.25 MHz input loop of poc.ip.kria.vi (sim-verified 2026-10-11)
ENUM = {0x20: 0, 0x21: 1, 0x22: 1, 0x2F: 1, 0x23: 2, 0x24: 3, 0x25: 4, 0x26: 4, 0x27: 5, 0x28: 5,
        0x29: 6, 0x2A: 10, 0x2B: 10, 0x30: 10}   # orderbook.command.type values; others -> Unsupported (11)
UNSUPPORTED = 11
SHORT_PRICE_SCALE = 1

def udp_payload(frame):
    """UDP payload of an Ethernet/IPv4/UDP frame, without the Ethernet pad (a 60-byte minimum
    frame carrying an 8-byte heartbeat has 10 pad bytes; NI's IPv4 filter drops them too)."""
    return frame[42:42 + struct.unpack(">H", frame[38:40])[0] - 8]

def pcap_frames(path):
    d = open(path, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off, out = 24, []
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        p = udp_payload(d[off + 16:off + 16 + incl]); off += 16 + incl
        msgs, o = [], 8
        while o < len(p) and p[o]:
            msgs.append(p[o:o + p[o]]); o += p[o]
        out.append((len(p), msgs))
    return out

def le(b): return int.from_bytes(b, "little")

def expect(m):
    """Expected CMD fields per PITCH message (offsets from cboe_pitch / Cboe spec)."""
    t = m[1]; e = {"type": ENUM.get(t, UNSUPPORTED), "pitch": t}
    if t in (0x21, 0x22, 0x2F, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x30):
        e["orderId"] = m[6:14].decode("latin1")
    if t in (0x21, 0x2F, 0x2A, 0x30): e["qty"] = le(m[15:19])
    if t in (0x22, 0x2B): e["qty"] = le(m[15:17])
    if t in (0x21, 0x2A): e["symbol"] = m[19:25].decode("latin1") + "  "
    if t in (0x22, 0x2B): e["symbol"] = m[17:23].decode("latin1") + "  "
    if t in (0x2F, 0x30): e["symbol"] = m[19:27].decode("latin1")
    if t in (0x21, 0x2A): e["price"] = le(m[25:33])
    if t in (0x22, 0x2B): e["price"] = le(m[23:25]) * SHORT_PRICE_SCALE
    if t in (0x2F, 0x30): e["price"] = le(m[27:35])
    if t in (0x23, 0x24): e["executed.qty"] = le(m[14:18])
    if t == 0x24: e["remaining.qty"] = le(m[18:22]); e["price"] = le(m[30:38])
    if t == 0x25: e["canceled.qty"] = le(m[14:18])
    if t == 0x26: e["canceled.qty"] = le(m[14:16])
    if t == 0x27: e["qty"] = le(m[14:18]); e["price"] = le(m[18:26])
    if t == 0x28: e["qty"] = le(m[14:16]); e["price"] = le(m[16:18]) * SHORT_PRICE_SCALE
    return e

def hdr_rec(w):
    """(parsed length, sequence) from a DEBUG header record; w[2] holds the SUH's first 8 bytes."""
    b = w[2].to_bytes(8, "big")   # the record packs the stream bytes MSB-first
    return (w[0] & 0xFFFF, struct.unpack("<I", b[4:8])[0])

def records(path):
    """Accepts a netlist-sim sim_out.txt or a `poc_server poll` capture from the board."""
    hdrs, cmds, cur = [], [], {"DEBUG": [], "CMD": []}
    text = open(path).read().splitlines()
    if any(l.startswith("[CMD] frame") or l.startswith("[DEBUG] frame") for l in text):
        kind = None
        for l in text:
            m = re.match(r"\[(DEBUG|MDEBUG|CMD)\] frame (\d+)", l)
            if m:
                if kind in ("DEBUG", "CMD") and cur[kind]:
                    w = cur[kind]; cur[kind] = []
                    if kind == "DEBUG" and len(w) == 4 and (w[0] >> 32) == 0xDE: hdrs.append(hdr_rec(w))
                    if kind == "CMD" and len(w) == 16: cmds.append(w)
                kind = m[1]; continue
            m = re.match(r"\s+[0-9a-f]{4}: ([0-9a-f]{16})", l)
            if m and kind in ("DEBUG", "CMD"):
                cur[kind].append(int.from_bytes(bytes.fromhex(m[1]), "little"))
        for kind in ("DEBUG", "CMD"):
            w = cur[kind]
            if kind == "DEBUG" and len(w) == 4 and (w[0] >> 32) == 0xDE: hdrs.append(hdr_rec(w))
            if kind == "CMD" and len(w) == 16: cmds.append(w)
        return hdrs, cmds
    for l in text:
        m = re.match(r"(\d+) (CMD|DEBUG)\s+w(\d+) 0x([0-9a-f]+)( LAST)?", l)
        if not m: continue
        k = m[2]; cur[k].append(int(m[4], 16))
        if m[5]:
            w = cur[k]; cur[k] = []
            if k == "DEBUG" and len(w) == 4 and (w[0] >> 32) == 0xDE: hdrs.append(hdr_rec(w))
            if k == "CMD" and len(w) == 16: cmds.append(w)
    return hdrs, cmds

def s8(v):
    return v.to_bytes(8, "little").decode("latin1")

def main():
    global SHORT_PRICE_SCALE
    if "--short-price-scale" in sys.argv:
        i = sys.argv.index("--short-price-scale"); SHORT_PRICE_SCALE = int(sys.argv[i + 1]); del sys.argv[i:i + 2]
    hdrs, cmds = records(sys.argv[1]); frames = pcap_frames(sys.argv[2])
    # A board capture can start with stale records: the capture FIFOs are not cleared by the
    # NI IP reset, so anything parsed before `poc_server poll` was started (and possibly cut
    # mid-record by a FIFO overflow) comes out first. The parser's own seq counter (word 12)
    # restarts at 1 after reset, so resync on the first record with seq == 1.
    # (the hardware capture of 2026-10-20 numbered its first record 0, the sim numbers it 1)
    first = next((i for i, w in enumerate(cmds) if w[12] in (0, 1) and w[15] == 0xDEADBEEF), None)
    if first:
        print(f"note: skipped {first} stale CMD records before the first seq-1 record")
        cmds = cmds[first:]
    truth = [(f, m) for f, (plen, ms) in enumerate(frames) for m in ms]
    # the DEBUG stream drops records when its FIFO is full (it writes 4 words every parser
    # cycle), so match header records to pcap frames by sequence number, not by order
    seq2frame, seq = {}, None
    for f, (plen, ms) in enumerate(frames):
        pass
    d = open(sys.argv[2], "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off, f = 24, 0
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16]); p = udp_payload(d[off + 16:off + 16 + incl]); off += 16 + incl
        seq2frame.setdefault(struct.unpack("<I", p[4:8])[0], []).append((f, len(p))); f += 1
    # a heartbeat carries the sequence number of the data frame that follows it, so one
    # sequence number can name several frames: match each pcap frame to an unused DEBUG header
    # record with the same sequence, preferring one that parsed the right length
    seen = {}
    for ln, sq in hdrs: seen.setdefault(sq, []).append(ln)
    hdr_ok, hdr_bad, hdr_missing = 0, [], []
    for sq, fl in seq2frame.items():
        pool = list(seen.get(sq, []))
        for f, plen in fl:
            if plen in pool: pool.remove(plen); hdr_ok += 1
            elif pool: hdr_bad.append((f + 1, pool.pop(0), plen))
            else: hdr_missing.append(f + 1)
    print(f"headers: {len(hdrs)} DEBUG header records, {hdr_ok}/{len(frames)} frames with the right length"
          + (f"   WRONG (frame, parsed, true): {hdr_bad[:8]}" if hdr_bad else "")
          + (f"   not in DEBUG stream (dropped records): frames {hdr_missing}" if hdr_missing else ""))
    print(f"messages: {len(cmds)} CMD records, {len(truth)} in pcap")
    bad, lat_by_frame, no_stamp = [], {}, 0
    for i, w in enumerate(cmds):
        if i >= len(truth): break
        f, m = truth[i]; e = expect(m)
        got = {"type": w[0]}
        if "orderId" in e: got["orderId"] = s8(w[2])
        if "qty" in e: got["qty"] = w[3]
        if "price" in e: got["price"] = w[5]
        if "executed.qty" in e: got["executed.qty"] = w[6]
        if "canceled.qty" in e: got["canceled.qty"] = w[7]
        if "remaining.qty" in e: got["remaining.qty"] = w[8]
        if "symbol" in e: got["symbol"] = s8(w[4])   # 6-char symbols are space-padded (AddOrder since 2026-10-11, Trade before)
        diff = {k: (got[k], e[k]) for k in got if got[k] != e[k]}
        if diff: bad.append((i + 1, f + 1, hex(e["pitch"]), diff))
        if w[13] != 0 and 0 <= w[14] - w[13] < 10 ** 6:   # same validity rule as tools/hwrun: recv.time 0 = no stamp (todo item 19)
            lat_by_frame.setdefault(f, []).append(w[14] - w[13])   # by pcap frame (recv.time is per record since the 2026-10-11 export)
        else:
            no_stamp += 1
    print(f"content: {len(cmds) - len(bad)} of {len(cmds)} records match the pcap (type enum, orderId, qty/price/exec/cancel/remaining, Trade symbol)")
    for b in bad[:12]: print("   mismatch msg", b)
    if len(bad) > 12: print(f"   ... {len(bad) - 12} more")
    print("\nrecv->parse latency per frame (ns): first / last / count"
          + (f"   ({no_stamp} records without recv.time left out)" if no_stamp else ""))
    for k, (rt, ls) in enumerate(sorted(lat_by_frame.items())):
        print(f"   frame {k + 1:2d}: {ls[0] * TICK:6.1f} / {max(ls) * TICK:6.1f} / {len(ls)}")
    # symbol layouts (bug 3)
    syms = {}
    for i, w in enumerate(cmds[:len(truth)]):
        e = expect(truth[i][1])
        if "symbol" in e: syms.setdefault(hex(e["pitch"]), set()).add(s8(w[4]))
    print("\nsymbol field as delivered per PITCH type:", {k: sorted(v)[:3] for k, v in syms.items()})

if __name__ == "__main__":
    main()
