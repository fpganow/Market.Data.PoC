#!/usr/bin/env python3
"""Insert Cboe PITCH heartbeats (Sequenced Unit Header with count 0, length 8) into a pcap.

    python3 scripts/make_heartbeat_pcap.py tests/data/generated_2026_09_17_multi.pcap \
        tests/data/heartbeat_repro.pcap

A heartbeat is sent once per second per unit on a live feed; it carries the NEXT expected
sequence number and no messages. Each one here is a real-wire Ethernet frame: the 42-byte
Ethernet/IPv4/UDP header of the following data frame, IP total length 36, UDP length 16,
8-byte payload 08 00 00 <unit> <seq LE32>, zero-padded to the 60-byte Ethernet minimum.
NI's Find IPv4 Subframe drops the pad, so the parser sees exactly one 8-byte word with eof.
Placement: one before the first frame, one before frame 5, TWO in a row before frame 10,
one before frame 15, one after the last frame (todo.txt item 7).
"""
import struct, sys

def pcap_records(d):
    swap = d[:4] == b"\xd4\xc3\xb2\xa1"
    fmt = "<IIII" if swap else ">IIII"
    off = 24
    while off + 16 <= len(d):
        hdr = struct.unpack(fmt, d[off:off + 16])
        yield hdr, d[off + 16:off + 16 + hdr[2]]
        off += 16 + hdr[2]

def ip_checksum(h):
    s = sum(struct.unpack(">10H", h[:10] + b"\0\0" + h[12:20]))
    while s >> 16: s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF

def heartbeat(template, seq):
    eth, ip, udp = template[:14], bytearray(template[14:34]), bytearray(template[34:42])
    unit = template[42 + 3]
    payload = bytes([8, 0, 0, unit]) + struct.pack("<I", seq)
    ip[2:4] = struct.pack(">H", 20 + 8 + len(payload))
    ip[10:12] = b"\0\0"; ip[10:12] = struct.pack(">H", ip_checksum(bytes(ip)))
    udp[4:6] = struct.pack(">H", 8 + len(payload)); udp[6:8] = b"\0\0"
    f = eth + bytes(ip) + bytes(udp) + payload
    return f + b"\0" * max(0, 60 - len(f))

def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = open(src, "rb").read()
    swap = d[:4] == b"\xd4\xc3\xb2\xa1"
    fmt = "<IIII" if swap else ">IIII"
    recs = list(pcap_records(d))
    before = {0: 1, 5: 1, 10: 2, 15: 1}
    out, audit = [], []
    def add(hdr, frame, note):
        out.append(struct.pack(fmt, hdr[0], hdr[1], len(frame), len(frame)) + frame)
        p = frame[42:42 + struct.unpack(">H", frame[38:40])[0] - 8]
        audit.append(f"frame {len(out) - 1:3d}: {note:9s} udp payload {len(p):4d} bytes, hdr length {p[0] | p[1] << 8:4d}, "
                     f"count {p[2]:3d}, unit {p[3]}, seq {struct.unpack('<I', p[4:8])[0]}")
    for i, (hdr, frame) in enumerate(recs):
        seq = struct.unpack("<I", frame[42 + 4:42 + 8])[0]
        for _ in range(before.get(i, 0)):
            add(hdr, heartbeat(frame, seq), "HEARTBEAT")
        add(hdr, frame, "data")
    hdr, frame = recs[-1]
    add(hdr, heartbeat(frame, struct.unpack("<I", frame[46:50])[0] + frame[44]), "HEARTBEAT")
    open(dst, "wb").write(d[:24] + b"".join(out))
    open(dst.rsplit(".", 1)[0] + ".txt", "w").write(__doc__.strip().split("\n")[0] + f"\nsource: {src}\n" + "\n".join(audit) + "\n")
    print(f"wrote {dst}: {len(out)} frames ({len(recs)} data + {len(out) - len(recs)} heartbeats)")

if __name__ == "__main__":
    main()
