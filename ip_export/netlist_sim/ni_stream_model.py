#!/usr/bin/env python3
"""Cycle-accurate model of the LabVIEW receive path in front of bats.parser.vi:

    AXI beat -> Reader.vi -> niInstr Stream Filter MAC.vi -> Find IPv4 Subframe.vi
             -> Stream Filter IPv4.vi -> UDP Rx State Machine.vi -> poc.ip.kria glue
             -> (CDC FIFO) -> bats.parser.vi   (parser_model.py)

Transcribed literally from the lvkit `--format lvnet -v` dumps of NI's instr.lib VIs
(LabVIEW 2020, niInstr Network v1) on 2026-09-18. Every LabVIEW feedback node is a
register named fbN exactly as in the dump; each `step()` computes one SCTL iteration
from the inputs and the registers, then commits the registers.

    python3 ni_stream_model.py frames_f9_10.txt sim_f9_10.txt ../../tests/data/<pcap>

Validation: the parser's DEBUG record stream (header records and per-message
records) must match the netlist simulation word for word.
"""
import re, struct, sys, importlib.util

HERE = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
_spec = importlib.util.spec_from_file_location("parser_model", HERE + "/parser_model.py")
pm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pm)

MAC_ADDR = [0x00, 0x0a, 0x35, 0x18, 0x3c, 0x1f]
IP_ADDR = [10, 0, 1, 14]
UDP_PORT = 8000


def rot(schedule):
    """LabVIEW `Delete From Array(index 0)` + `Build Array(rest, x)` = rotate/replace."""
    return schedule[1:]


# ----------------------------------------------------------------------------- MAC filter
class MacFilter:
    SCHED = [dict(dest=True, src=False, eth=False, pd=False),
             dict(dest=False, src=True, eth=True, pd=False),
             dict(dest=False, src=False, eth=False, pd=True)]
    NONE = dict(dest=False, src=False, eth=False, pd=False)
    LANES_6426 = (6, 7)
    # The two-word data history (fb20/fb21) and byte-enable history (fb19/fb22) are
    # enable-gated feedback nodes that only shift on a valid input word (lvkit does not
    # render enable terminals; established by matching the netlist simulation bit-exactly).
    GATE_DATA = True; GATE_BE = True

    def __init__(self):
        self.fb0 = 0                      # FSM state: 0 Idle, 1 Wait For Last, 2 Purge
        self.fb1 = False
        self.fb2 = dict(self.NONE)        # roles for this cycle
        self.fb7 = False                  # Packet Data (data valid out)
        self.fb8 = (False, False); self.fb9 = (False, False); self.fb10 = (False, False)
        self.fb19 = [False] * 8; self.fb20 = [0] * 8; self.fb21 = [0] * 8; self.fb22 = [False] * 8
        self.fb23 = self.SCHED[0:2]       # Delete_From_Array_5054 (index unwired = from the end): output = [S0,S1], deleted = S2
        self.fb24 = [0] * 8; self.fb5 = [False] * 8

    def step(self, data, valid, be, eog, eob):
        S = self.SCHED
        or_4970 = eog or eob
        bundle_4981 = (eog, eob)
        and_5266 = [b and valid for b in be]
        rx_hvalid = valid; rx_valid = valid; rx_tlast = or_4970
        history = data[0:6]
        # case_1748 frame "8": assemble from the two previous words
        ba = self.fb21 + self.fb20
        out1 = ba[6:14]
        bae = self.fb22 + self.fb19
        out4 = bae[6:14]
        # output byte enables for this cycle
        and_5255 = [e and self.fb7 for e in self.fb5]
        # FSM
        if self.fb0 == 0:   # Idle
            match = all((history[i] == MAC_ADDR[i]) or (history[i] == 0xFF) for i in range(6))
            and_3369 = rx_hvalid and match
            nxt = 1 if rx_hvalid else 0
            roles_next = {k: (and_3369 and v) for k, v in S[0].items()}   # Delete_3527 (index 0) on [S0,S1]
            sched_next = [S[1]] + [S[2]]                                    # Build_3549: rest + deleted-last (S2)
            o1 = and_3369
            eof_next = (bundle_4981[0] and and_3369, bundle_4981[1] and and_3369)
        elif self.fb0 == 1:  # Wait For Last
            and_3684 = rx_valid and self.fb1
            case_6426 = any(and_5266[i] for i in self.LANES_6426)   # Delete_From_Array_3765 (length 2, index unwired)
            if not self.fb1:
                nxt = 0 if rx_tlast else 1
            else:
                nxt = 1 if not rx_tlast else (2 if case_6426 else 0)
            roles_next = {k: (and_3684 and v) for k, v in self.fb23[0].items()}
            sched_next = self.fb23[1:] + [S[2]]
            o1 = self.fb1 and not rx_tlast
            c4066 = (not case_6426) and self.fb1
            eof_next = (bundle_4981[0] and c4066, bundle_4981[1] and c4066)
        else:               # Purge
            nxt = 0; o1 = False
            roles_next = dict(S[2])          # Purge: Delete_5054 deleted portion = Packet Data -> one flush word
            sched_next = self.fb23
            eof_next = self.fb10
        out = dict(data=list(self.fb24), valid=self.fb7, be=and_5255,
                   eog=self.fb9[0], eob=self.fb9[1])
        # commit registers
        self.fb7 = self.fb2["pd"]          # fb7 each = Bundle_4407::Packet Data (unbundled from fb2): one cycle later
        self.fb0, self.fb1, self.fb2 = nxt, o1, roles_next
        self.fb9, self.fb8, self.fb10 = self.fb8, eof_next, bundle_4981
        if valid or not self.GATE_DATA:
            self.fb21, self.fb20 = self.fb20, list(data)
        if valid or not self.GATE_BE:
            self.fb22, self.fb19 = self.fb19, and_5266
        self.fb23 = sched_next
        self.fb24 = out1; self.fb5 = out4
        return out


# ----------------------------------------------------------------------------- Find IPv4 Subframe
class FindSubframe:
    GATE = False

    def __init__(self):
        self.fb0 = 0          # 0 Idle, 1 Small Packet, 2 Normal Wait For Last, 3 Small Wait For Last
        self.fb1 = False; self.fb5 = [False] * 8; self.fb6 = [0] * 8
        self.prev_eof = (False, False)

    def step(self, data, valid, be, eog, eob):
        or_2940 = eog or eob
        and_3713 = or_2940 and valid
        hvalid = valid; history = data[0:4]
        if self.fb0 == 0:
            c861 = (history[0] == 0x45) and hvalid   # EtherType 0x0800 assumed (IPv4 test frames)
            c946 = (data[2] == 0) and (data[3] < 46)
            nxt = 0 if and_3713 else ((1 if c946 else 2) if c861 else 0)
            o1, o2, o3 = list(data), list(be), valid
        elif self.fb0 == 2:
            nxt = 0 if and_3713 else 2
            o1, o2, o3 = list(data), list(be), valid
        else:
            raise NotImplementedError("small-packet path not needed for these frames")
        out = dict(data=list(self.fb6), valid=self.fb1, be=list(self.fb5),
                   eog=self.prev_eof[0], eob=self.prev_eof[1])
        self.fb0, self.fb1 = nxt, o3
        if valid or not self.GATE:
            self.fb6, self.fb5 = o1, o2
        self.prev_eof = (eog, eob)
        return out


# ----------------------------------------------------------------------------- IPv4 filter
class Ipv4Filter:
    SCHED = [dict(dip=False, h2=False, h1=True, pd=False, adv=True),
             dict(dip=False, h2=True, h1=False, pd=False, adv=True),
             dict(dip=True, h2=False, h1=False, pd=False, adv=True),
             dict(dip=False, h2=False, h1=False, pd=True, adv=False)]
    LANES_9712 = (4, 5, 6, 7)
    GATE_DATA = False; GATE_BE = False

    def __init__(self):
        self.fb0 = 0; self.fb1 = False
        self.fb2 = {k: False for k in self.SCHED[0]}
        self.fb6 = False
        self.fb7 = (False, False); self.fb8 = (False, False); self.fb9 = (False, False)
        self.fb18 = [0] * 8; self.fb19 = [0] * 8; self.fb20 = [False] * 8; self.fb21 = [False] * 8
        self.fb22 = self.SCHED[0:3]      # Delete_9985 output
        self.fb23 = [0] * 8; self.fb24 = [False] * 8
        self.fb3 = [0] * 4; self.fb4 = [0] * 8; self.fb5 = [0] * 8
        self.out2_3698 = [False] * 8; self.out3_3698 = [0] * 8

    def header(self):
        w0, w1, dip = self.fb5, self.fb4, self.fb3
        return dict(total_len=(w0[2] << 8) | w0[3], ident=(w0[4] << 8) | w0[5],
                    flags=(w0[6] >> 5) & 7, frag=((w0[6] & 0x1F) << 8) | w0[7],
                    proto=w1[1], dst_ip=list(dip))

    def step(self, data, valid, be, eog, eob):
        S = self.SCHED
        roles_now = dict(self.fb2)         # fb2 as it is during this cycle
        or_6746 = eog or eob
        b6757 = (eog, eob)
        rx_valid = valid; rx_hvalid = valid
        # case_3698 frame "8"
        ba = self.fb19 + self.fb18
        o3698 = dict(out0=ba[8:12], out1=ba[8:16], out3=ba[4:12], out4=ba[8:16])
        bae = self.fb21 + self.fb20
        o3698["out2"] = bae[4:12]
        if self.fb0 == 0:      # Wait for First Data
            eq = data[0] == 0x45
            and_4965 = rx_valid and eq
            s4990 = 1 if eq else 3
            s4976 = s4990 if rx_valid else 0
            nxt = 0 if or_6746 else s4976
            roles = {k: (and_4965 and v) for k, v in S[0].items()}    # Delete_10642 (index 0) on [F,Sec,Third]
            sched = S[1:3] + [S[3]]                                     # Build_10674: [Sec,Third] + deleted-last (PD)
            o1 = False; eof_o = (False, False)
        elif self.fb0 == 1:    # Wait for Second Data
            adv = self.fb22[0]["adv"]
            and_5031 = rx_valid and adv
            nxt = 0 if or_6746 else (2 if and_5031 else 1)
            roles = {k: (rx_valid and v) for k, v in self.fb22[0].items()}
            sched = self.fb22[1:] + [S[3]]
            o1 = False; eof_o = (False, False)
        elif self.fb0 == 2:    # Wait for Third Data
            match = all((data[i] == IP_ADDR[i]) or (data[i] == 0xFF) for i in range(4))
            adv = self.fb22[0]["adv"]
            and_10255 = rx_valid and adv
            and_5334 = and_10255 and match
            eof_o = (b6757[0] and and_5334, b6757[1] and and_5334)
            nxt = 2 if or_6746 else (3 if and_10255 else 2)
            roles = {k: (and_5334 and v) for k, v in self.fb22[0].items()}
            sched = self.fb22[1:] + [S[3]]
            o1 = and_5334
        elif self.fb0 == 3:    # Wait For Last
            and_5666 = rx_valid and self.fb1
            c9712 = any(be[i] for i in self.LANES_9712)   # Delete_From_Array_5929 (length 4, index unwired)
            if not self.fb1:
                nxt = 0 if or_6746 else 3
            else:
                nxt = 3 if not or_6746 else (4 if c9712 else 0)
            c5955 = (not c9712) and self.fb1
            eof_o = (b6757[0] and c5955, b6757[1] and c5955)
            roles = {k: (and_5666 and v) for k, v in self.fb22[0].items()}
            sched = self.fb22[1:] + [S[3]]
            o1 = self.fb1
        else:                  # Purge
            nxt = 0; o1 = False
            roles = dict(S[3])               # Purge: Delete_9985 deleted portion = Packet Data -> one flush word
            eof_o = self.fb9
            sched = S[1:3] + [S[3]]          # Build_10880
        out = dict(data=list(self.fb23), valid=self.fb6, be=list(self.fb24),
                   eog=self.fb8[0], eob=self.fb8[1], hdr=self.header())
        # commit
        self.fb6 = self.fb2["pd"]          # fb6 each = Bundle_6364::Packet Data (from fb2)
        self.fb0, self.fb1, self.fb2 = nxt, o1, roles
        self.fb8, self.fb7, self.fb9 = self.fb7, eof_o, b6757
        if valid or not self.GATE_DATA:
            self.fb19, self.fb18 = self.fb18, list(data)
        if valid or not self.GATE_BE:
            self.fb21, self.fb20 = self.fb20, list(be)
        self.fb22 = sched
        self.fb23, self.fb24 = o3698["out3"], o3698["out2"]
        # header registers are enable-gated feedback nodes (lvkit does not render the
        # enable terminal): they only latch while the matching role is active this cycle
        if roles_now["h1"]:  self.fb5 = o3698["out4"]   # Latch First Header
        if roles_now["h2"]:  self.fb4 = o3698["out1"]   # Latch Second Header
        if roles_now["dip"]: self.fb3 = o3698["out0"]   # Latch Dest IP
        return out


# ----------------------------------------------------------------------------- UDP Rx state machine
class UdpRx:
    def __init__(self):
        self.fb0 = False   # accepted
        self.fb2 = False   # packet active
        self.fb3 = 0       # previous Identification
        self.fb4 = False   # expecting fragments

    def step(self, data, valid, be, eog, eob, hdr):
        h = data                                   # history size 8 = current word
        dport = (h[2] << 8) | h[3]
        c282 = (dport == UDP_PORT) and (hdr["proto"] == 17) and (hdr["frag"] == 0)
        eq_2729 = hdr["ident"] == self.fb3
        or_3306 = c282 or (self.fb4 and eq_2729)
        more_frag = bool((hdr["flags"] >> 0) & 1)   # Number To Boolean Array [0]
        hvalid = valid
        eof_any = eog or eob
        if not self.fb2:
            c1291 = hvalid and not eof_any
            c317 = hvalid and or_3306
            if c317:
                o5, o1, o3 = more_frag, c282, (not c282)
            else:
                o5, o1, o3 = self.fb4, False, False
            o0, o2 = c317, c1291
        else:
            and_886 = valid and eof_any
            o2 = False if and_886 else self.fb2
            o3 = self.fb0 and valid
            o0, o1, o5 = self.fb0, False, self.fb4
        out = dict(data=list(data), valid=o3, be=list(be),
                   eog=eog and o0, eob=eob and o0)
        self.fb0, self.fb2, self.fb3, self.fb4 = o0, o2, hdr["ident"], o5
        return out


# ----------------------------------------------------------------------------- driver
def beats_from_file(path):
    rows = []
    for l in open(path):
        p = l.split()
        if not p: continue
        td, tk, tl, fno = int(p[0], 16), int(p[1], 16), int(p[2]), int(p[3])
        tv = int(p[4]) if len(p) > 4 else 1
        rows.append((td, tk, tl, fno, tv))
    return rows


def run(beats_path, gap=64, trace=False):
    mac, sub, ip4, udp = MacFilter(), FindSubframe(), Ipv4Filter(), UdpRx()
    P = pm.Parser()
    records = []          # parser DEBUG-equivalent records
    elements = []         # what the CDC FIFO carries to the parser
    rows = beats_from_file(beats_path)
    # replicate tb.sv: 64 idle cycles before each frame, data/keep held, tlast/tvalid low
    cycles = []
    last_f, hold = -1, (0, 0)
    for td, tk, tl, fno, tv in rows:
        if fno != last_f:
            cycles += [(hold[0], hold[1], 0, 0, fno)] * gap
            last_f = fno
        cycles.append((td, tk, tl, tv, fno)); hold = (td, tk)
    cycles += [(hold[0], hold[1], 0, 0, last_f)] * 200
    for cyc, (td, tk, tl, tv, fno) in enumerate(cycles):
        data = list(td.to_bytes(8, "little"))       # Reader.vi: byte 0 = TDATA[7:0]
        be = [bool((tk >> i) & 1) for i in range(8)]
        o = mac.step(data, bool(tv), be, bool(tl), False)
        o = sub.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"])
        o = ip4.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"])
        o = udp.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"], o["hdr"])
        if o["valid"] or o["eog"] or o["eob"]:
            o["cyc"] = cyc
            elements.append((fno, o))
    # feed the parser (one FIFO element per parser cycle)
    for fno, e in elements:
        keep = sum(1 << i for i, b in enumerate(e["be"]) if b)
        rec = P.step_elem(fno, bytes(e["data"]), keep, e["valid"], e["eog"] or e["eob"])
        if rec: records.append(rec)
    return elements, records


def sim_records(path):
    """DEBUG records from a netlist-sim output: ('HDR', len, w2) or ('MSG', w0)."""
    out, cur = [], []
    for l in open(path):
        m = re.match(r'(\d+) DEBUG\s+w(\d+) 0x([0-9a-f]+)( LAST)?', l)
        if not m: continue
        cur.append(int(m[3], 16))
        if m[4]:
            w = cur; cur = []
            if len(w) != 4 or w[0] in (0xBBBB, 0xAAAB): continue
            if w[0] == 0xAAAA: out.append(("AAAA",)); continue
            if (w[0] >> 32) == 0xDE: out.append(("HDR", w[0] & 0xFFFFFFFF, w[2]))
            elif w[3] == 0x99: out.append(("MSG", w[0]))
    return out


def main():
    beats, simfile = sys.argv[1], sys.argv[2]
    elements, records = run(beats)
    sim = sim_records(simfile)
    print(f"model: {len(elements)} FIFO elements, {len(records)} DEBUG-equivalent records; sim: {len(sim)} records")
    n = min(len(records), len(sim)); first_bad = None
    for i in range(n):
        if records[i] != sim[i]:
            first_bad = i; break
    if first_bad is None and len(records) == len(sim):
        print("MATCH: every header and message record identical")
    else:
        i = first_bad if first_bad is not None else n
        print(f"first difference at record {i}: model {records[i] if i < len(records) else '-'}  sim {sim[i] if i < len(sim) else '-'}")
        for k in range(max(0, i - 3), min(i + 3, n)):
            print(f"   {k:4d} model {records[k]}   sim {sim[k]}")
    # show the parser input around each frame end
    print("\nparser input at frame ends (valid words with byte-enable count, eog):")
    for i, (fno, e) in enumerate(elements):
        if i + 1 < len(elements) and elements[i + 1][0] != fno or i == len(elements) - 1:
            for j in range(max(0, i - 2), i + 1):
                f, x = elements[j]
                print(f"   frame {f}: data {bytes(x['data']).hex()} be={sum(x['be'])} valid={int(x['valid'])} eog={int(x['eog'])}")
            print("   --")


if __name__ == "__main__":
    main()
