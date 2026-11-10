#!/usr/bin/env python3
"""Turn pcap frames into the 64-bit beat stream xgmii2axis would produce on its lv_ port.

    python3 pcap2beats.py beats.txt <pcap> [<pcap> ...] [--gap N] [--loop N] [--bad-every N]

Output lines (read by tb_pitch_rtl.sv with $fscanf):
    <tdata hex16> <tkeep hex2> <tlast 0|1> <tuser 0|1>     one beat; tdata is little-endian
                                                            (frame byte 0 in bits 7:0), FCS not included
    idle <N>                                                N idle cycles (TVALID low)
--gap N        idle cycles between frames (default 4; the real 10G gap is >= 1 beat)
--loop N       send the whole set N times
--bad-every N  mark every Nth frame's TUSER low (bad FCS) to exercise the counters
The pcap's own link-layer FCS, if any, is assumed absent (pcaps written by scapy/the generator have none).
"""
import struct, sys, argparse

def frames(path):
    d = open(path, "rb").read()
    magic = struct.unpack("<I", d[:4])[0]
    fmt = "<IIII" if magic in (0xa1b2c3d4, 0xa1b23c4d) else ">IIII"
    off = 24
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16]); off += 16
        yield d[off:off + incl]; off += incl

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("pcaps", nargs="+")
    ap.add_argument("--gap", type=int, default=4); ap.add_argument("--loop", type=int, default=1)
    ap.add_argument("--bad-every", type=int, default=0)
    a = ap.parse_args()
    n = 0
    with open(a.out, "w") as f:
        for _ in range(a.loop):
            for p in a.pcaps:
                for fr in frames(p):
                    n += 1
                    user = 0 if (a.bad_every and n % a.bad_every == 0) else 1
                    for i in range(0, len(fr), 8):
                        chunk = fr[i:i + 8]
                        last = 1 if i + 8 >= len(fr) else 0
                        keep = (1 << len(chunk)) - 1
                        word = int.from_bytes(chunk + bytes(8 - len(chunk)), "little")
                        f.write(f"{word:016x} {keep:02x} {last} {user if last else 0}\n")
                    f.write(f"idle {a.gap}\n")
    print(f"{n} frames -> {a.out}")

if __name__ == "__main__":
    main()
