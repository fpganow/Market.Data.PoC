#!/usr/bin/env python3
"""Prototype of todo item 3 / Fix A for compress.buffer.vi, checked against the pcaps.

Runs the bit-exact parser model twice over each pcap's UDP payloads (the same replay
parser_model.main() does, minus frames.txt): once with the current compress_buffer and once
with compress_buffer_fixA. Every emitted message is compared BYTE FOR BYTE with the pcap
(not just length/type), so the OR\\0D0204 corruption shows up as a content mismatch.

    python3 compress_fix_proto.py <pcap> [<pcap> ...]
"""
import struct, sys
sys.path.insert(0, "/mnt/c/work/fpganow/Market.Data.PoC/ip_export/netlist_sim")
import parser_model as pm

M64, NB = pm.M64, pm.NB


def lsh(x, y):
    """LabVIEW Logical Shift on U64: y>0 left, y<0 right, |y|>=64 -> 0."""
    if y >= 64 or y <= -64:
        return 0
    return (x << y) & M64 if y >= 0 else (x & M64) >> (-y)


def compress_buffer_fixA(buf, L, start):
    """Fix A exactly as it will be wired in compress.buffer.generated.vi (U8/I16 arithmetic).

    diff  = buffer.length - start.idx            (U8)
    s     = start.idx AND 7                       (U8)   byte offset inside the first word
    widx  = start.idx >> 3                        (U8)
    w0..w3 = buffer[widx .. widx+3]               (Index Array, out of range -> 0)
    for k in 0..2:
        raw_k  = s == 0 ? w_k : (w_k << 8s) OR (w_{k+1} >> 8(8-s))
        n_k    = clamp(diff - 8k, 0, 8)           (I16, Max&Min)
        mask_k = ((1 << 8 n_k) - 1) << 8(8 - n_k) i.e. the top n_k bytes
        out[k] = raw_k AND mask_k
    buffer.length.out = diff
    """
    diff = (L - start) & 0xFF
    s, widx = start & 7, start >> 3
    w = [buf[widx + k] if widx + k < NB else 0 for k in range(4)]
    out = [0] * NB
    for k in range(3):
        if s == 0:
            raw = w[k]
        else:
            raw = lsh(w[k], 8 * s) | lsh(w[k + 1], -8 * (8 - s))
        n = max(0, min(8, diff - 8 * k))                 # I16 clamp
        mask = lsh((lsh(1, 8 * n) - 1) & M64, 8 * (8 - n))   # (1<<64)=0, 0-1 = all ones
        out[k] = raw & mask
    return out, diff


class P(pm.Parser):
    def __init__(self, cb):
        super().__init__()
        self.cb = cb
        self.full = []     # (frame, off, bytes)

    def step(self, frame_no, off, data8, keep, eof):
        self.buf, self.L = pm.add_data_to_buffer(self.buf, self.L, data8, keep)
        if self.state == self.HDR:
            if self.L >= 8:
                self.hdr_len = pm.byte_at(self.buf, 0) | (pm.byte_at(self.buf, 1) << 8)
                self.buf, self.L = self.cb(self.buf, self.L, 8)
                self.total, self.state = 8, self.MSG
            return
        if self.L == 0:
            return
        ln = pm.byte_at(self.buf, 0)
        if self.L >= ln and ln > 0:
            self.full.append((frame_no, off, bytes(pm.byte_at(self.buf, i) for i in range(ln))))
            self.buf, self.L = self.cb(self.buf, self.L, ln)
            done = (self.total + ln) >= self.hdr_len
            self.total += ln
            if done or eof:
                self.state, self.L = self.HDR, 0        # user's eof/done clear
            else:
                self.state = self.MSG
        else:
            self.state = self.HDR if eof else self.MSG


def payloads(path):
    d = open(path, "rb").read()
    swap = d[:4] == b"\xd4\xc3\xb2\xa1"
    fmt = "<IIII" if swap else ">IIII"
    off, out = 24, []
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        out.append(d[off + 16 + 42:off + 16 + incl])
        off += 16 + incl
    return out


def run(path, cb):
    p = P(cb)
    truth = []
    for fno, pl in enumerate(payloads(path)):
        o = 8
        while o < len(pl):
            truth.append(pl[o:o + pl[o]]); o += pl[o]
        for off in range(0, len(pl), 8):
            chunk = pl[off:off + 8]
            p.step(fno, off, chunk.ljust(8, b"\0"), (1 << len(chunk)) - 1, off + 8 >= len(pl))
    got = [m for f, o, m in p.full]
    bad = [(i, t, g) for i, (t, g) in enumerate(zip(truth, got)) if t != g]
    return len(truth), len(got), bad


if __name__ == "__main__":
    # unit checks of the fixed function on synthetic buffers
    import random
    rnd = random.Random(1)
    for _ in range(20000):
        L = rnd.randint(0, 40); start = rnd.randint(0, L)
        data = bytes(rnd.randrange(1, 256) for _ in range(L)) + b"\0" * (NB * 8 - L)
        buf = [int.from_bytes(data[8 * i:8 * i + 8], "big") for i in range(NB)]
        # stale junk beyond L must not leak into the output
        junk = bytearray(data);
        for i in range(L, NB * 8): junk[i] = rnd.randrange(256)
        bufj = [int.from_bytes(bytes(junk[8 * i:8 * i + 8]), "big") for i in range(NB)]
        out, d = compress_buffer_fixA(bufj, L, start)
        rem = data[start:L]
        exp = rem.ljust(24, b"\0")
        gotb = b"".join(x.to_bytes(8, "big") for x in out[:3])
        if d <= 24:
            assert gotb == exp and d == L - start, (L, start, rem, gotb)
    print("synthetic: 20000 random (L, start) cases OK, stale bytes masked")
    for path in sys.argv[1:]:
        for name, cb in (("current", pm.compress_buffer), ("fix A  ", compress_buffer_fixA)):
            nt, ng, bad = run(path, cb)
            print(f"{path.split('/')[-1]:40s} {name}: truth {nt} model {ng} content mismatches {len(bad)}")
            for i, t, g in bad[:5]:
                print(f"      msg {i}: truth {t.hex()}\n              model {g.hex()}")
