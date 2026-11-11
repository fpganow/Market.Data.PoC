#!/usr/bin/env python3
"""Score a netlist-sim output (sim_out.txt) against the pcap it was fed.

    python3 eval_sim.py sim_out.txt ../../tests/data/generated_2026_09_17_multi.pcap [--short-price-scale 100]

Also accepts a `poc_server poll` capture from the board instead of sim_out.txt.
Checks: Sequenced Unit Header lengths seen by the parser (DEBUG 0xDE records) vs the
pcap, number of CMD records vs messages, and per message the parser's type enum plus
every field the parser is specified to fill for that type (rest.of.order.types.txt):
orderId, side, quantity, symbol, price, executed / canceled / remaining quantity.
Prints recv->parse latency per frame (10 ns per tick).

--short-price-scale N: the short-variant messages (0x22, 0x28, 0x2B) carry a 2-byte price
in 1/100 units. Pass 100 when the FPGA multiplies them up to the long 1/10000 scale (the
2026-10-11 export and the bitstream on the board as of 2026-11-06 do), leave it at 1 when
the scaling is left to the host."""
import argparse, re, struct, sys

TICK = 10
# orderbook.command.type: the 10-item typedef plus Trade = 10 / Unsupported = 11 appended
# (rest.of.order.types.txt). Hardware mapping confirmed on the 2026-11-06 cable run.
ENUM = {0x20: 0, 0x21: 1, 0x22: 1, 0x2F: 1, 0x23: 2, 0x24: 3, 0x25: 4, 0x26: 4,
        0x27: 5, 0x28: 5, 0x29: 6, 0x2A: 10, 0x2B: 10, 0x30: 10}
UNSUPPORTED = 11
# CMD record word carrying each field (CLAUDE.md "Stream formats")
WORD = {"type": 0, "side": 1, "orderId": 2, "qty": 3, "symbol": 4, "price": 5,
        "executed": 6, "canceled": 7, "remaining": 8}
SHORT_PRICE_SCALE = 1

def pcap_frames(path):
    d = open(path, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off, out = 24, []
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        p = d[off + 16 + 42:off + 16 + incl]; off += 16 + incl
        msgs, o = [], 8
        while o < len(p) and p[o]:                # length byte 0 = Ethernet padding after a heartbeat, not a message
            msgs.append(p[o:o + p[o]]); o += p[o]
        out.append((len(p), msgs))
    return out

def expect(m):
    """Fields the parser should deliver for PITCH message m (offset/length per rest.of.order.types.txt)."""
    t = m[1]; e = {"type": ENUM.get(t, UNSUPPORTED), "pitch": t}
    u = lambda o, n: int.from_bytes(m[o:o + n], "little")
    if t == 0x20 or t not in ENUM:
        return e                                   # Time / Unsupported: type only
    e["orderId"] = m[6:14].decode("latin1")
    if t in (0x21, 0x2F, 0x2A, 0x30):              # AddOrder / Trade, long + expanded
        n = 6 if t in (0x21, 0x2A) else 8
        e["side"] = m[14]; e["qty"] = u(15, 4)
        e["symbol"] = m[19:19 + n].decode("latin1"); e["price"] = u(19 + n, 8)
    elif t in (0x22, 0x2B):                        # AddOrder / Trade short
        e["side"] = m[14]; e["qty"] = u(15, 2)
        e["symbol"] = m[17:23].decode("latin1"); e["price"] = u(23, 2) * SHORT_PRICE_SCALE
    elif t == 0x23: e["executed"] = u(14, 4)
    elif t == 0x24: e["executed"] = u(14, 4); e["remaining"] = u(18, 4); e["price"] = u(30, 8)
    elif t == 0x25: e["canceled"] = u(14, 4)
    elif t == 0x26: e["canceled"] = u(14, 2)
    elif t == 0x27: e["qty"] = u(14, 4); e["price"] = u(18, 8)
    elif t == 0x28: e["qty"] = u(14, 2); e["price"] = u(16, 2) * SHORT_PRICE_SCALE
    # 0x29 DeleteOrder: orderId only
    return e

def delivered(w, e):
    """The CMD record's values for the fields expect() lists, in the same units."""
    got = {}
    for k in e:
        if k == "pitch": continue
        v = w[WORD[k]]
        if k in ("orderId", "symbol"): v = s8(v)[:len(e[k])]   # symbol is space-padded to 8 in the record
        got[k] = v
    return got

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
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("capture", help="netlist-sim sim_out.txt or a `poc_server poll` capture")
    ap.add_argument("pcap")
    ap.add_argument("--short-price-scale", type=int, default=1, metavar="N",
                    help="multiply 2-byte short-variant prices by N before comparing (100 if the FPGA scales them)")
    a = ap.parse_args(); SHORT_PRICE_SCALE = a.short_price_scale
    hdrs, cmds = records(a.capture); frames = pcap_frames(a.pcap)
    # A board capture can start with stale records: the capture FIFOs are not cleared by the
    # NI IP reset, so anything parsed before `poc_server poll` was started (and possibly cut
    # mid-record by a FIFO overflow) comes out first. The parser's own seq counter (word 12)
    # restarts at 1 after reset, so resync on the first record with seq == 1.
    first = next((i for i, w in enumerate(cmds) if w[12] == 1 and w[15] == 0xDEADBEEF), None)
    if first:
        print(f"note: skipped {first} stale CMD records before the first seq-1 record")
        cmds = cmds[first:]
    truth = [(f, m) for f, (plen, ms) in enumerate(frames) for m in ms]
    # the DEBUG stream drops records when its FIFO is full (it writes 4 words every parser
    # cycle), so match header records to pcap frames by sequence number, not by order
    seq2frame = {}
    d = open(a.pcap, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off, f = 24, 0
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16]); p = d[off + 16 + 42:off + 16 + incl]; off += 16 + incl
        seq2frame[struct.unpack("<I", p[4:8])[0]] = (f, len(p)); f += 1
    seen = {}
    for ln, sq in hdrs: seen.setdefault(sq, ln)
    hdr_ok = sum(1 for sq, (f, plen) in seq2frame.items() if seen.get(sq) == plen)
    hdr_bad = [(f + 1, seen[sq], plen) for sq, (f, plen) in seq2frame.items() if sq in seen and seen[sq] != plen]
    hdr_missing = [f + 1 for sq, (f, plen) in seq2frame.items() if sq not in seen]
    print(f"headers: {len(hdrs)} DEBUG header records, {hdr_ok}/{len(frames)} frames with the right length"
          + (f"   WRONG (frame, parsed, true): {hdr_bad[:8]}" if hdr_bad else "")
          + (f"   not in DEBUG stream (dropped records): frames {hdr_missing}" if hdr_missing else ""))
    print(f"messages: {len(cmds)} CMD records, {len(truth)} in pcap")
    bad, lat_by_frame, per_type = [], {}, {}
    for i, w in enumerate(cmds):
        if i >= len(truth): break
        f, m = truth[i]; e = expect(m); got = delivered(w, e)
        diff = {k: (got[k], e[k]) for k in got if got[k] != e[k]}
        if diff: bad.append((i + 1, f + 1, hex(e["pitch"]), diff))
        n = per_type.setdefault(e["pitch"], [0, 0]); n[1] += 1; n[0] += not diff
        lat_by_frame.setdefault(w[13], []).append(w[14] - w[13])
    checked = sorted({k for i, w in enumerate(cmds[:len(truth)]) for k in expect(truth[i][1]) if k != "pitch"})
    print(f"content: {len(cmds) - len(bad)} of {len(cmds)} records match the pcap ({', '.join(checked)})")
    print("   per PITCH type (ok/total): " + "  ".join(f"{t:#04x} {ok}/{n}" for t, (ok, n) in sorted(per_type.items())))
    for b in bad[:12]: print("   mismatch msg", b, "  (record, frame, pitch type, {field: (delivered, expected)})" if b is bad[0] else "")
    if len(bad) > 12: print(f"   ... {len(bad) - 12} more")
    print("\nrecv->parse latency per frame (ns): first / last / count")
    for k, (rt, ls) in enumerate(sorted(lat_by_frame.items())):
        print(f"   frame {k + 1:2d}: {ls[0] * TICK:5d} / {max(ls) * TICK:5d} / {len(ls)}")
    # symbol layouts (bug 3)
    syms = {}
    for i, w in enumerate(cmds[:len(truth)]):
        e = expect(truth[i][1])
        if "symbol" in e: syms.setdefault(hex(e["pitch"]), set()).add(s8(w[4]))
    print("\nsymbol field as delivered per PITCH type:", {k: sorted(v)[:3] for k, v in syms.items()})

if __name__ == "__main__":
    main()
