#!/usr/bin/env python3
"""Convert pcap frames into AXI-stream beats for the xsim testbench.

Output format per line:  <tdata_hex16> <tkeep_hex2> <tlast> <frame_no>
A line with tlast=1 ends a frame. Byte 0 of the frame goes in TDATA[7:0]
(standard AXI4-Stream byte lane order, as xgmii2axis.v produces).
"""
import struct, sys

def pcap_frames(path):
    d = open(path, "rb").read()
    swap = d[:4] == b"\xd4\xc3\xb2\xa1"
    fmt = "<IIII" if swap else ">IIII"
    off = 24
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        yield d[off + 16:off + 16 + incl]
        off += 16 + incl

def main():
    out = open(sys.argv[1], "w")
    fno = 0
    for path in sys.argv[2:]:
        for f in pcap_frames(path):
            nbeats = (len(f) + 7) // 8
            for i in range(nbeats):
                chunk = f[i * 8:(i + 1) * 8]
                keep = (1 << len(chunk)) - 1
                chunk = chunk + b"\x00" * (8 - len(chunk))
                tdata = int.from_bytes(chunk, "little")
                last = 1 if i == nbeats - 1 else 0
                out.write(f"{tdata:016x} {keep:02x} {last} {fno}\n")
            fno += 1
    out.close()
    print(f"wrote {fno} frames")

if __name__ == "__main__":
    main()
