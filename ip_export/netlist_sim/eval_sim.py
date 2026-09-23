#!/usr/bin/env python3
"""Score a netlist-sim output (sim_out.txt) against the pcap it was fed.

    python3 eval_sim.py sim_out.txt ../../tests/data/generated_2026_09_17_multi.pcap

Also accepts a `poc_server poll` capture from the board instead of sim_out.txt.
Checks: Sequenced Unit Header lengths seen by the parser (DEBUG 0xDE records) vs the
pcap, number of CMD records vs messages, the parser's type enum per message, and for
Add/Executed messages the orderId (and quantity for Adds) against the pcap bytes.
Prints recv->parse latency per frame (10 ns per tick)."""
import re, struct, sys

TICK = 10
ENUM = {0x20: 0, 0x21: 1, 0x22: 1, 0x2F: 1, 0x23: 2, 0x24: 2}   # bats.parser.vi cases; others -> 0 (unsupported)

def pcap_frames(path):
    d = open(path, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off, out = 24, []
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        p = d[off + 16 + 42:off + 16 + incl]; off += 16 + incl
        msgs, o = [], 8
        while o < len(p):
            msgs.append(p[o:o + p[o]]); o += p[o]
        out.append((len(p), msgs))
    return out

def expect(m):
    t = m[1]; e = {"type": ENUM.get(t, 0), "pitch": t}
    if t in (0x21, 0x22, 0x2F, 0x23, 0x24):
        e["orderId"] = m[6:14].decode("latin1")
    if t in (0x21, 0x2F): e["qty"] = struct.unpack("<I", m[15:19])[0]
    if t == 0x22: e["qty"] = struct.unpack("<H", m[15:17])[0]
    if t in (0x21, 0x22): e["symbol"] = m[19:25].decode("latin1") if t == 0x21 else m[17:23].decode("latin1")
    if t == 0x2F: e["symbol"] = m[19:27].decode("latin1")
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
    hdrs, cmds = records(sys.argv[1]); frames = pcap_frames(sys.argv[2])
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
    seq2frame, seq = {}, None
    for f, (plen, ms) in enumerate(frames):
        pass
    d = open(sys.argv[2], "rb").read()
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
    bad, lat_by_frame = [], {}
    for i, w in enumerate(cmds):
        if i >= len(truth): break
        f, m = truth[i]; e = expect(m)
        got = {"type": w[0]}
        if "orderId" in e: got["orderId"] = s8(w[2])
        if "qty" in e: got["qty"] = w[3]
        diff = {k: (got[k], e[k]) for k in got if got[k] != e[k]}
        if diff: bad.append((i + 1, f + 1, hex(e["pitch"]), diff))
        lat_by_frame.setdefault(w[13], []).append(w[14] - w[13])
    print(f"content: {len(cmds) - len(bad)} of {len(cmds)} records match the pcap (type enum, orderId, quantity)")
    for b in bad[:12]: print("   mismatch msg", b)
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
