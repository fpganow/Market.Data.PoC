#!/usr/bin/env python3
"""Send every UDP payload of a pcap to the FPGA over the 10G cable from a plain UDP socket.

    python3 scripts/send_pcap_udp.py tests/data/generated_2026_09_17_multi.pcap [pacing] [--loop N]
      [--src 10.0.1.10] [--dst 10.0.1.14] [--port 8000]

Pacing (pick one; default --gap-ms 5):
    --gap-ms T      fixed gap of T ms between datagrams (the pcap's timestamps are ignored)
    --pps N         N datagrams per second
    --mbps M        M megabits per second on the wire (payload + 42 B of Ethernet/IPv4/UDP
                    headers, no preamble/IFG)
    --speed X       follow the pcap's own timestamps, X times faster (1 = real time)
    --topspeed      no pacing at all
--loop N repeats the whole file N times (N=0: until Ctrl-C). Pacing is enforced with a
busy-wait on a monotonic clock, so sub-millisecond gaps are honoured; the summary line
prints the achieved rate so you can tell when the sender itself is the limit.

Needs the Linux-side address and static neighbour on the 10G interface (see CLAUDE.md,
"10G path from this machine"): sudo ip addr replace 10.0.1.10/24 dev eno2np1; sudo ip neigh
replace 10.0.1.14 lladdr 00:0a:35:18:3c:1f dev eno2np1 nud permanent."""
import argparse, socket, struct, sys, time

WIRE_OVERHEAD = 42          # Ethernet 14 + IPv4 20 + UDP 8

def payloads(path):
    """Yield (timestamp_s, udp_payload) for every frame in the pcap."""
    d = open(path, "rb").read()
    fmt = "<IIII" if d[:4] == b"\xd4\xc3\xb2\xa1" else ">IIII"
    off = 24
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        frame = d[off + 16:off + 16 + incl]; off += 16 + incl
        ihl = (frame[14] & 0xF) * 4
        yield ts + tu / 1e6, frame[14 + ihl + 8:]          # after Ethernet + IPv4 + UDP headers

def schedule(msgs, a):
    """Return the send offset (s) of every datagram for one pass of the file."""
    if a.topspeed:  return [0.0] * len(msgs)
    if a.speed:     t0 = msgs[0][0]; return [(t - t0) / a.speed for t, _ in msgs]
    if a.pps:       return [i / a.pps for i in range(len(msgs))]
    if a.mbps:
        bits, out, acc = a.mbps * 1e6, [], 0.0
        for _, p in msgs: out.append(acc / bits); acc += (len(p) + WIRE_OVERHEAD) * 8
        return out
    return [i * a.gap_ms / 1000 for i in range(len(msgs))]

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pcap")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--gap-ms", type=float, default=None, help="fixed gap between datagrams (default 5)")
    g.add_argument("--pps", type=float); g.add_argument("--mbps", type=float)
    g.add_argument("--speed", type=float, help="replay the pcap timestamps X times faster")
    g.add_argument("--topspeed", action="store_true")
    ap.add_argument("--loop", type=int, default=1, help="repeat the file N times (0 = forever)")
    ap.add_argument("--src", default="10.0.1.10"); ap.add_argument("--dst", default="10.0.1.14")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--quiet", action="store_true", help="print only the summary line")
    a = ap.parse_args()
    if a.gap_ms is None and not (a.pps or a.mbps or a.speed or a.topspeed): a.gap_ms = 5.0
    msgs = list(payloads(a.pcap))
    if not msgs: sys.exit("no frames in pcap")
    offs = schedule(msgs, a)
    # one pass lasts until the last send plus one more inter-datagram step, so loops don't bunch up
    period = offs[-1] + (offs[-1] / (len(offs) - 1) if len(offs) > 1 else 0) if offs[-1] else 0.0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((a.src, 0))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
    n = nbytes = 0; loop = 0; t_start = time.perf_counter()
    try:
        while a.loop == 0 or loop < a.loop:
            base = t_start + loop * period
            for (ts, p), off in zip(msgs, offs):
                due = base + off
                while time.perf_counter() < due: pass          # busy-wait keeps sub-ms gaps honest
                s.sendto(p, (a.dst, a.port)); n += 1; nbytes += len(p) + WIRE_OVERHEAD
            loop += 1
    except KeyboardInterrupt:
        pass
    el = time.perf_counter() - t_start
    print(f"sent {n} datagrams ({nbytes} wire bytes, {loop} pass(es) of {len(msgs)}) to {a.dst}:{a.port} from {a.src} "
          f"in {el:.3f} s: {n / el:,.0f} pps, {nbytes * 8 / el / 1e6:,.2f} Mbit/s")

if __name__ == "__main__":
    main()
