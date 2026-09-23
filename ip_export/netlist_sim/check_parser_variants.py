"""Usage: python3 check_parser_variants.py <frames.txt from gen_frames.py> <pcap>

Feed the 20-frame pcap through the bit-exact NI stream model with Reader.vi's
pad-beat change applied, then through parser variants:
  A = the parser as now in the OneDrive bats.parser.vi (clear only in Read.Msg when L>=ln and (done or eof))
  B = A + clear in Read.Sequenced.Unit.Header when L<8 and eof
  C = B + clear in Read.Msg when L<ln and eof
"""
import sys
sys.path.insert(0, "/mnt/c/work/fpganow/Market.Data.PoC/ip_export/netlist_sim")
import ni_stream_model as nm, parser_model as pm

def pad_beats(rows):
    out = []
    for td, tk, tl, fno, tv in rows:
        if tv and tl and tk in (0x7F, 0xFF):
            out.append((td, 0xFF, 0, fno, tv)); out.append((0, 0x01, 1, fno, 1))
        else:
            out.append((td, tk, tl, fno, tv))
    return out

class P:
    HDR, MSG = 2, 3
    def __init__(self, hdr_clear, msg_lt_clear):
        self.hdr_clear, self.msg_lt_clear = hdr_clear, msg_lt_clear
        self.buf, self.L, self.state, self.total, self.hdr_len = [0]*pm.NB, 0, self.HDR, 0, 0
        self.hdrs, self.msgs = [], []
    def step(self, fno, data8, keep, valid, eof):
        if valid:
            self.buf, self.L = pm.add_data_to_buffer(self.buf, self.L, data8, keep)
        if self.state == self.HDR:
            if self.L >= 8:
                self.hdr_len = pm.byte_at(self.buf, 0) | (pm.byte_at(self.buf, 1) << 8)
                self.hdrs.append((fno, self.hdr_len))
                self.buf, self.L = pm.compress_buffer(self.buf, self.L, 8)
                self.total, self.state = 8, self.MSG
            elif eof and self.hdr_clear:
                self.L = 0
            return
        if self.L == 0: return
        ln, ty = pm.byte_at(self.buf, 0), pm.byte_at(self.buf, 1)
        if self.L >= ln:
            self.msgs.append((fno, ln, ty))
            self.buf, self.L = pm.compress_buffer(self.buf, self.L, ln)
            done = (self.total + ln) >= self.hdr_len
            self.total += ln
            if done or eof:
                self.state, self.L = self.HDR, 0          # user's Select_1344 / Select_856
        else:
            if eof:
                self.state = self.HDR
                if self.msg_lt_clear: self.L = 0

def run(beats, variant):
    mac, sub, ip4, udp = nm.MacFilter(), nm.FindSubframe(), nm.Ipv4Filter(), nm.UdpRx()
    p = P(*variant)
    rows = pad_beats(nm.beats_from_file(beats))
    cycles, last_f, hold = [], -1, (0, 0)
    for td, tk, tl, fno, tv in rows:
        if fno != last_f:
            cycles += [(hold[0], hold[1], 0, 0, fno)] * 64; last_f = fno
        cycles.append((td, tk, tl, tv, fno)); hold = (td, tk)
    cycles += [(hold[0], hold[1], 0, 0, last_f)] * 200
    for td, tk, tl, tv, fno in cycles:
        data = list(td.to_bytes(8, "little")); be = [bool((tk >> i) & 1) for i in range(8)]
        o = mac.step(data, bool(tv), be, bool(tl), False)
        o = sub.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"])
        o = ip4.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"])
        o = udp.step(o["data"], o["valid"], o["be"], o["eog"], o["eob"], o["hdr"])
        if o["valid"] or o["eog"] or o["eob"]:
            keep = sum(1 << i for i, b in enumerate(o["be"]) if b)
            p.step(fno, bytes(o["data"]), keep, o["valid"], o["eog"] or o["eob"])
    return p

truth = pm.pcap_msgs(sys.argv[2])
flat_truth = [(ln, ty) for plen, m in truth for o, ln, ty in m]
# NOTE: frame tags on parser output lag by one frame (the NI pipeline drains a frame's tail during
# the next frame's idle gap), so compare the flattened sequence, not per-frame lists.
for name, variant in (("A parser: eof clear in Read.Msg L>=len only", (False, False)),
                      ("B +eof clear in header state L<8", (True, False)),
                      ("C +eof clear in Read.Msg L<len", (True, True))):
    p = run(sys.argv[1], variant)
    flat = [(ln, ty) for f, ln, ty in p.msgs]
    ok_hdr = sum(1 for i, (f, l) in enumerate(p.hdrs) if i < len(truth) and l == truth[i][0])
    ok_msg = sum(1 for a, b in zip(flat, flat_truth) if a == b)
    print(f"{name:46s} headers {ok_hdr}/{len(truth)} correct ({len(p.hdrs)} seen)   messages {len(flat)}/{len(flat_truth)}, {ok_msg} correct in sequence")
