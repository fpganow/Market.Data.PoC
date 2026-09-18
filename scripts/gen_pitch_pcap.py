#!/usr/bin/env python3
"""Generate a multi-frame pcap of coherent CBOE PITCH (BATS) market data.

Uses the project's cboe_pitch library (Generator keeps a per-symbol order
book, so Modify/Reduce/Execute/Delete/Trade messages always refer to orders it
added earlier; Time messages are emitted whenever the second rolls over) and
packs the messages into Sequenced Unit Headers, one UDP datagram per frame,
with sequence numbers continuing across frames.

Frames are addressed to the NI IP's filter (dst MAC 00:0a:35:18:3c:1f,
10.0.1.14:8000) so the same file works for the cable path, poc_inject, the
netlist testbench (gen_frames.py) and the LabVIEW host runner.

    python3 scripts/gen_pitch_pcap.py                       # defaults below
    python3 scripts/gen_pitch_pcap.py -n 40 -b 1200 --seed 7 -o tests/data/x.pcap

Needs: pip install -e cboe_pitch numpy pyyaml scapy prettytable ruamel.yaml
"""
import argparse
import collections
import contextlib
import io
from datetime import datetime
from pathlib import Path

from scapy.all import Ether, IP, UDP, Raw, wrpcap  # noqa: E402

from cboe_pitch.generator import Generator, WatchListItem
from cboe_pitch.seq_unit_header import SequencedUnitHeader

DST_MAC, SRC_MAC = "00:0a:35:18:3c:1f", "24:5e:be:8b:b1:94"
DST_IP, SRC_IP = "10.0.1.14", "10.0.1.10"
DST_PORT, SRC_PORT = 8000, 54816

# NOTE: the Generator draws order sizes as size_min + k*25 and, for a Modify,
# loops until it finds a size different from the old one -- so every size range
# must span at least two 25-share steps or getNextMsg() never returns.
WATCH_LIST = [
    #             ticker  weight  book size   price range        order size
    WatchListItem("GE",   0.25,   [3, 8],     [50.00, 60.00],    [25, 200]),
    WatchListItem("MSFT", 0.35,   [10, 20],   [320.00, 340.00],  [5, 105]),
    WatchListItem("AAPL", 0.25,   [10, 20],   [185.00, 195.00],  [10, 110]),
    WatchListItem("TSLA", 0.15,   [5, 12],    [240.00, 260.00],  [5, 80]),
]


def build(num_frames: int, max_payload: int, msg_rate: int, seed: int):
    gen = Generator(
        watch_list=WATCH_LIST,
        msg_rate_p_sec=msg_rate,
        start_time=datetime(2026, 9, 17, 9, 30, 0),   # fixed → reproducible
        seed=seed,
    )
    frames = []
    hdr = SequencedUnitHeader(hdr_sequence=1)
    sink = io.StringIO()   # the library print()s on every Remove; keep stdout clean
    while len(frames) < num_frames:
        with contextlib.redirect_stdout(sink):
            msg = gen.getNextMsg()
        if msg is None:
            continue
        if hdr.getLength() + msg.length() > max_payload:
            frames.append(hdr)
            hdr = SequencedUnitHeader(hdr_sequence=hdr.getNextSequence())
        hdr.addMessage(msg)
    return frames


def write_outputs(frames, pcap_path: Path):
    packets = []
    for hdr in frames:
        packets.append(
            Ether(dst=DST_MAC, src=SRC_MAC)
            / IP(src=SRC_IP, dst=DST_IP)
            / UDP(sport=SRC_PORT, dport=DST_PORT)
            / Raw(load=bytes(hdr.get_all_bytes()))
        )
    wrpcap(str(pcap_path), packets)

    # Audit text in the same style as generated_2025_05_02.txt
    lines = []
    for hdr in frames:
        lines.append(f"{hdr}, get_all_bytes length: {len(hdr.get_all_bytes())}")
        rb = hdr.get_bytes()
        lines.append("        " + " ".join(f"{x:02x}" for x in rb[0:4]) + "    " + " ".join(f"{x:02x}" for x in rb[4:8]))
        for idx, msg in enumerate(hdr.getMessages()):
            mb = msg.get_bytes()
            lines.append(f"  - [{idx}] {msg}, length={len(mb)}")
            for r in range(0, len(mb), 8):
                row = mb[r:r + 8]
                lines.append("         " + " ".join(f"{x:02x}" for x in row[0:4]) + "    " + " ".join(f"{x:02x}" for x in row[4:8]))
    pcap_path.with_suffix(".txt").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-n", "--frames", type=int, default=20, help="number of Ethernet frames (default 20)")
    ap.add_argument("-b", "--max-payload", type=int, default=1000, help="max UDP payload bytes per frame (default 1000)")
    ap.add_argument("-r", "--msg-rate", type=int, default=100, help="messages per second → a Time message every N (default 100)")
    ap.add_argument("--seed", type=int, default=20260917)
    ap.add_argument("-o", "--output", default="tests/data/generated_2026_09_17_multi.pcap")
    a = ap.parse_args()

    frames = build(a.frames, a.max_payload, a.msg_rate, a.seed)
    out = Path(a.output)
    write_outputs(frames, out)

    counts = collections.Counter(type(m).__name__ for h in frames for m in h.getMessages())
    nmsg = sum(counts.values())
    print(f"wrote {out} and {out.with_suffix('.txt')}")
    print(f"  {len(frames)} frames, {nmsg} messages, sequence {frames[0].hdr_sequence()}..{frames[-1].hdr_sequence() + frames[-1].hdr_count() - 1}")
    print(f"  payload bytes per frame: min {min(len(h.get_all_bytes()) for h in frames)} max {max(len(h.get_all_bytes()) for h in frames)}")
    for name, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:26s} {c:5d}")


if __name__ == "__main__":
    main()
