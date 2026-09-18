#!/usr/bin/env python3
"""Decode a `poc_server poll` capture (DEBUG / MDEBUG / CMD hex dumps) into
parser trace records and fully parsed orderbook commands.

Input lines look like:
    [CMD] frame 3 (128 bytes):
      0000: 0100000000000000
      0008: 5300000000000000
      ...
Each 8-byte row is one 64-bit stream word, printed as the raw bytes in memory
order (little-endian), so the word value is int.from_bytes(row, "little").

Formats (fpga/poc.ip.kria.vi, bats.parser.vi, 2026-09-15):
  CMD    16 words: type side orderId qty symbol price exec.qty cancel.qty
                   remain.qty seconds nanos flags seq recv.time parse.time 0xDEADBEEF
  DEBUG   4 words: parser trace, first word is a marker (0xAAAB reset, 0xDE<<32|len
                   header, 8 message bytes + 0x99, 0xAAAA/0xBBBB waiting)
  MDEBUG  4 words: [time, msg length, msg type, ...] per parser cycle
`time` ticks once per 100 MHz parser cycle (10 ns).
"""
import re, sys

TICK_NS = 10
CMD_NAMES = ["type", "side", "orderId", "qty", "symbol", "price", "exec.qty", "cancel.qty",
             "remain.qty", "seconds", "nanos", "flags", "seq", "recv.time", "parse.time", "reserved"]
MSG_TYPES = {0x20: "Time", 0x21: "AddOrder(long)", 0x22: "AddOrder(short)", 0x23: "OrderExecuted",
             0x24: "OrderExecutedAtPriceSize", 0x2F: "AddOrder(expanded)"}

def s8(v):
    b = v.to_bytes(8, "little")
    return b.decode("latin1") if all(0x20 <= c < 0x7F for c in b) else b.hex()

def parse(lines):
    frames = []   # (fifo, words)
    cur = None
    for line in lines:
        m = re.match(r"\[(DEBUG|MDEBUG|CMD)\] frame (\d+) \((\d+) bytes\)", line)
        if m:
            cur = (m[1], []); frames.append(cur); continue
        m = re.match(r"\s+([0-9a-f]{4}): ([0-9a-f]{16})", line)
        if m and cur:
            cur[1].append(int.from_bytes(bytes.fromhex(m[2]), "little"))
    return frames

def decode_debug(w):
    if w[0] == 0xAAAB: return f"RESET record {['0x%x' % x for x in w]}"
    if w[0] == 0xAAAA: return "waiting for header data"
    if w[0] == 0xBBBB: return "waiting for message data"
    if w[0] >> 32 == 0xDE:
        return f"Sequenced Unit Header parsed: length={w[0] & 0xFFFFFFFF} ({w[1]}), first bytes {w[2]:016x}"
    if w[3] == 0x99:
        b = w[0].to_bytes(8, "big")   # stream bytes are packed MSB-first in the parser's record
        return f"message record, data-stream bytes {b.hex()} ({b.decode('latin1')!r})"
    return "unknown " + " ".join(f"0x{x:x}" for x in w)

def main():
    text = open(sys.argv[1]).read().splitlines() if len(sys.argv) > 1 else sys.stdin.read().splitlines()
    frames = parse(text)
    n = {"DEBUG": 0, "MDEBUG": 0, "CMD": 0}
    for f, w in frames: n[f] += 1
    print(f"records: DEBUG={n['DEBUG']} MDEBUG={n['MDEBUG']} CMD={n['CMD']}\n")

    print("== DEBUG (parser trace) ==")
    for f, w in frames:
        if f == "DEBUG":
            print("  " + " ".join(f"{x:016x}" for x in w) + "   " + (decode_debug(w) if len(w) == 4 else f"({len(w)} words)"))

    print("\n== MDEBUG (per-cycle: time, len, type, ...) ==")
    for f, w in frames:
        if f == "MDEBUG":
            print("  " + " ".join(f"{x:016x}" for x in w) + f"   time={w[0]}" if len(w) == 4 else f"  ({len(w)} words)")

    print("\n== CMD (parsed orderbook commands) ==")
    lat = []
    for f, w in frames:
        if f != "CMD": continue
        if len(w) != 16:
            print(f"  ({len(w)} words, expected 16): " + " ".join(f"{x:x}" for x in w)); continue
        d = dict(zip(CMD_NAMES, w))
        ticks = d["parse.time"] - d["recv.time"]
        lat.append(ticks)
        side = chr(d["side"]) if 0x20 <= d["side"] < 0x7F else str(d["side"])
        print(f"  seq {d['seq']:3d}  type {d['type']}  side {side}  orderId {s8(d['orderId'])!r:12} qty {d['qty']:5d}  "
              f"symbol {s8(d['symbol'])!r:10} price {d['price']:8d}  sec {d['seconds']} ns {d['nanos']}  "
              f"flags {d['flags']:#x}  recv 0x{d['recv.time']:x} parse 0x{d['parse.time']:x} "
              f"-> {ticks} ticks = {ticks * TICK_NS} ns  reserved {d['reserved']:#x}")
    if lat:
        print(f"\nlatency recv->parse: min {min(lat) * TICK_NS} ns, max {max(lat) * TICK_NS} ns over {len(lat)} messages")

if __name__ == "__main__":
    main()
