#!/usr/bin/env python3
"""Insert PITCH message types the parser does not decode into one frame of a pcap.

    python3 scripts/make_unsupported_pcap.py tests/data/generated_2026_09_17_multi.pcap \
        tests/data/unsupported_repro.pcap [--frame 10]

Three messages are spliced into the chosen frame right after its first message:
  0x2D End of Session   6 bytes  (length, type, time offset)
  0x2C Trade Break     14 bytes  (+ execution id)
  0x31 Trading Status  18 bytes  (+ symbol 8, trading status, reg SHO, reserved 2)
The Sequenced Unit Header's length and count grow by 38 / 3, every later frame's sequence
number is shifted by 3 (unsupported messages are sequenced too), and the IPv4/UDP lengths
and the IPv4 checksum are recomputed (UDP checksum left 0). The parser must emit three
records of type 11 (Unsupported) for them and decode every following message normally
(todo.txt item 2); eval_sim.py expects type 11 for any PITCH type not in its ENUM table.
"""
import struct, sys

def pcap_records(d):
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off = 24
    while off + 16 <= len(d):
        hdr = struct.unpack(fmt, d[off:off + 16])
        yield hdr, d[off + 16:off + 16 + hdr[2]]
        off += 16 + hdr[2]

def ip_checksum(h):
    s = sum(struct.unpack(">10H", h[:10] + b"\0\0" + h[12:20]))
    while s >> 16: s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def rebuild(frame, payload):
    eth, ip, udp = frame[:14], bytearray(frame[14:34]), bytearray(frame[34:42])
    ip[2:4] = struct.pack(">H", 28 + len(payload))
    ip[10:12] = struct.pack(">H", ip_checksum(bytes(ip)))
    udp[4:6] = struct.pack(">H", 8 + len(payload)); udp[6:8] = b"\0\0"
    return eth + bytes(ip) + bytes(udp) + payload

UNSUPPORTED = (bytes([6, 0x2D]) + struct.pack("<I", 1000) +
               bytes([14, 0x2C]) + struct.pack("<I", 1001) + b"EXECID01" +
               bytes([18, 0x31]) + struct.pack("<I", 1002) + b"MSFT    " + b"T" + b"0" + b"\0\0")

def main():
    args = sys.argv[1:]
    target = 10
    if "--frame" in args:
        i = args.index("--frame"); target = int(args[i + 1]); del args[i:i + 2]
    src, dst = args
    d = open(src, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    out, audit, shift = [], [], 0
    for i, (hdr, frame) in enumerate(pcap_records(d)):
        p = bytearray(frame[42:42 + struct.unpack(">H", frame[38:40])[0] - 8])
        note = "data"
        if shift:
            p[4:8] = struct.pack("<I", struct.unpack("<I", p[4:8])[0] + shift)
        if i == target:
            first_len = p[8]
            p = p[:8 + first_len] + UNSUPPORTED + p[8 + first_len:]
            p[0:2] = struct.pack("<H", len(p)); p[2] += 3
            shift = 3; note = "data+UNSUP"
        frame = rebuild(frame, bytes(p))
        out.append(struct.pack(fmt, hdr[0], hdr[1], len(frame), len(frame)) + frame)
        audit.append(f"frame {i:3d}: {note:10s} udp payload {len(p):4d} bytes, hdr length {p[0] | p[1] << 8:4d}, "
                     f"count {p[2]:3d}, unit {p[3]}, seq {struct.unpack('<I', p[4:8])[0]}")
    open(dst, "wb").write(d[:24] + b"".join(out))
    open(dst.rsplit(".", 1)[0] + ".txt", "w").write(__doc__.strip().split("\n")[0] + f"\nsource: {src}, frame {target}\n" + "\n".join(audit) + "\n")
    print(f"wrote {dst}: {len(out)} frames, 3 unsupported messages in frame {target}")

if __name__ == "__main__":
    main()
