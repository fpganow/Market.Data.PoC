#!/usr/bin/env python3
"""Send every UDP payload of a pcap to the FPGA over the 10G cable from a plain UDP socket.

    python3 scripts/send_pcap_udp.py tests/data/generated_2026_09_17_multi.pcap [--gap-ms 5]
      [--src 10.0.1.10] [--dst 10.0.1.14] [--port 8000]

Needs the Linux-side address and static neighbour on the 10G interface (see CLAUDE.md,
"Real 10G path"): sudo ip addr add 10.0.1.10/24 dev eth1; sudo ip neigh replace 10.0.1.14
lladdr 00:0a:35:18:3c:1f dev eth1 nud permanent."""
import argparse, socket, struct, time

def payloads(path):
    d = open(path, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off = 24
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        frame = d[off + 16:off + 16 + incl]; off += 16 + incl
        ihl = (frame[14] & 0xF) * 4
        yield frame[14 + ihl + 8:]          # after Ethernet + IPv4 + UDP headers

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pcap"); ap.add_argument("--gap-ms", type=float, default=5.0)
    ap.add_argument("--src", default="10.0.1.10"); ap.add_argument("--dst", default="10.0.1.14")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((a.src, 0))
    n = 0
    for p in payloads(a.pcap):
        s.sendto(p, (a.dst, a.port)); n += 1; time.sleep(a.gap_ms / 1000)
    print(f"sent {n} datagrams to {a.dst}:{a.port} from {a.src}")

if __name__ == "__main__":
    main()
