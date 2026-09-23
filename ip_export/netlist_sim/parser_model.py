#!/usr/bin/env python3
"""Bit-exact software model of the LabVIEW parser's buffer path
(bats.parser.vi Read.Sequenced.Unit.Header / Read.Msg states, add.data.to.buffer.vi,
compress.buffer.vi, zero.out.and.convert.vi) transcribed from the lvkit lvnet dumps
on 2026-09-17. Used to locate the frame-boundary bug without LabVIEW.

    python3 parser_model.py frames.txt <pcap>      # replay beats, compare with the pcap's messages
"""
import struct, sys

M64 = (1 << 64) - 1
NB = 9  # buffer is [U64] x 9


def rotr(x, bits):
    bits %= 64
    return ((x >> bits) | (x << (64 - bits))) & M64


def zero_out_and_convert(data8, keep):
    """u64.be with byte 0 in the MSB; bytes beyond Num.of.True zeroed."""
    n = bin(keep).count("1")
    u = int.from_bytes(data8, "big")
    if n == 8:
        return u, n
    mask = ((1 << (8 * n)) - 1) << (8 * (8 - n))   # byte-reversed low-n-byte mask = top n bytes
    return u & mask, n


def add_data_to_buffer(buf, L, data8, keep):
    """add.data.to.buffer.vi (data valid assumed true)."""
    buf = list(buf)
    u, n = zero_out_and_convert(data8, keep)
    idx, r = L >> 3, L & 7
    if r == 0:
        if n == 0:
            return buf, L
        if idx < NB:
            buf[idx] = u                   # frames "8" / default (Replace Array Subset: out of range = no-op)
        return buf, (L + n) & 0xFF
    rot = rotr(u, 8 * r)                   # Rotate by mux.rem(r) = -8r
    mask = (1 << (8 * (8 - r))) - 1        # reverse.u64(NOT((1<<8r)-1)) = low (8-r) bytes
    if idx < NB:
        buf[idx] = buf[idx] | (rot & mask) # Or_1222: OLD | new bytes
    if idx + 1 < NB:
        buf[idx + 1] = rot & (M64 ^ mask)  # And_1450: wrapped-around tail into the next word
    return buf, (L + n) & 0xFF


def compress_buffer(buf, L, start):
    """compress.buffer.vi: drop `start` bytes, keep the rest at word 0."""
    diff = (L - start) & 0xFF
    s, widx, b = start & 7, start >> 3, L & 7
    out = [0] * NB
    if s == 0:
        if diff == 0:
            return out, diff
        w = buf[widx] if widx < NB else 0
        sh = (((8 - diff) & 0xFF) << 3) & 0xFF            # U8 arithmetic as in LabVIEW (wraps for diff > 8)
        m = ((1 << (8 * min(diff, 8))) - 1) & M64
        out[0] = w & ((m << sh) & M64 if sh < 64 else 0)
        return out, diff
    w0 = buf[widx] if widx < NB else 0
    w1 = buf[widx + 1] if widx + 1 < NB else 0
    m_low = (1 << (8 * (8 - s))) - 1                  # Decrement_1598
    part0 = ((w0 & m_low) << (8 * s)) & M64           # Logical_Shift_1135
    m_top = (((1 << (8 * b)) - 1) << (8 * (8 - b))) & M64   # Decrement_1482 << (8-b)*8
    part1 = (w1 & m_top) >> (8 * (8 - s))             # Logical_Shift_865 (negative shift)
    out[0] = part0 | part1
    return out, diff


def byte_at(buf, i):
    return (buf[i >> 3] >> (8 * (7 - (i & 7)))) & 0xFF


class Parser:
    HDR, MSG = 2, 3

    def __init__(self):
        self.buf, self.L = [0] * NB, 0
        self.state, self.total, self.hdr_len = self.HDR, 0, 0
        self.out = []      # (frame_no, off_in_frame, len, type, first8)
        self.trace = []

    def step_elem(self, frame_no, data8, keep, valid, eof):
        """One CDC-FIFO element as the parser sees it. Returns the DEBUG record the
        parser would write: ('HDR', len, buffer word 0) or ('MSG', input word), else None.
        Mirrors bats.parser.vi: add.data.to.buffer no-ops when data valid is false, but
        the state logic still runs (eof can still move Read.Msg -> header state)."""
        inword = int.from_bytes(data8, "big")
        if valid:
            self.buf, self.L = add_data_to_buffer(self.buf, self.L, data8, keep)
        if self.state == self.HDR:
            if self.L >= 8:
                self.hdr_len = byte_at(self.buf, 0) | (byte_at(self.buf, 1) << 8)
                w0 = self.buf[0]
                self.buf, self.L = compress_buffer(self.buf, self.L, 8)
                self.total = 8
                self.state = self.MSG
                return ("HDR", self.hdr_len, w0)
            return ("AAAA",)                  # 0xAAAA "waiting for header data"
        if self.L == 0:
            return None                       # 0xBBBB "waiting for msg data"
        ln = byte_at(self.buf, 0)
        if self.L >= ln:
            self.buf, self.L = compress_buffer(self.buf, self.L, ln)
            done = (self.total + ln) >= self.hdr_len
            self.total += ln
            self.state = self.HDR if (done or eof) else self.MSG
        else:
            self.state = self.HDR if eof else self.MSG
        return ("MSG", inword)                # Read.Msg writes [input word,0,0,0x99] every cycle with L>0

    def step(self, frame_no, off, data8, keep, eof):
        self.buf, self.L = add_data_to_buffer(self.buf, self.L, data8, keep)
        if self.state == self.HDR:
            if self.L >= 8:
                self.hdr_len = byte_at(self.buf, 0) | (byte_at(self.buf, 1) << 8)
                self.trace.append((frame_no, off, "HDR", self.hdr_len, self.L))
                self.buf, self.L = compress_buffer(self.buf, self.L, 8)
                self.total = 8
                self.state = self.MSG
            return
        # Read.Msg
        if self.L == 0:
            return
        ln, ty = byte_at(self.buf, 0), byte_at(self.buf, 1)
        if self.L >= ln and ln > 0:
            first8 = bytes(byte_at(self.buf, i) for i in range(8))
            self.out.append((frame_no, off, ln, ty, first8))
            self.buf, self.L = compress_buffer(self.buf, self.L, ln)
            done = (self.total + ln) >= self.hdr_len
            self.total += ln
            self.state = self.HDR if (done or eof) else self.MSG
        else:
            self.state = self.HDR if eof else self.MSG


def pcap_msgs(path):
    d = open(path, "rb").read()
    swap = d[:4] == b"\xd4\xc3\xb2\xa1"
    fmt = "<IIII" if swap else ">IIII"
    off, out = 24, []
    while off + 16 <= len(d):
        ts, tu, incl, orig = struct.unpack(fmt, d[off:off + 16])
        p = d[off + 16 + 42:off + 16 + incl]
        off += 16 + incl
        o, msgs = 8, []
        while o < len(p):
            msgs.append((o, p[o], p[o + 1]))
            o += p[o]
        out.append((len(p), msgs))
    return out


def main():
    beats = [l.split() for l in open(sys.argv[1]) if l.strip()]
    truth = pcap_msgs(sys.argv[2])
    P = Parser()
    # frames.txt beats start at the Ethernet header; the parser sees only the UDP payload
    # (NI's MAC/IP/UDP filter strips 42 bytes), so replay each frame's payload re-packed
    # into 8-byte words with TKEEP on the last one, TLAST -> eof.
    frames = {}
    for tdata, tkeep, tlast, fno in beats:
        frames.setdefault(int(fno), []).append((int(tdata, 16), int(tkeep, 16), int(tlast)))
    for fno in sorted(frames):
        raw = b"".join(td.to_bytes(8, "little") for td, tk, tl in frames[fno])
        payload = raw[42:42 + truth[fno][0]]
        for off in range(0, len(payload), 8):
            chunk = payload[off:off + 8]
            keep = (1 << len(chunk)) - 1
            P.step(fno, off, chunk.ljust(8, b"\0"), keep, off + 8 >= len(payload))
    # compare
    got = {}
    for f, off, ln, ty, first8 in P.out:
        got.setdefault(f, []).append((ln, ty))
    print("frame  truth  model  first divergence")
    for f, (plen, msgs) in enumerate(truth):
        g = got.get(f, [])
        div = next((k for k, (o, ln, ty) in enumerate(msgs) if k >= len(g) or g[k] != (ln, ty)), None)
        status = "OK" if div is None and len(g) == len(msgs) else f"msg {div}: truth {msgs[div][1:] if div is not None and div < len(msgs) else '-'} model {g[div] if div is not None and div < len(g) else '-'}"
        print(f"{f + 1:5d}  {len(msgs):5d}  {len(g):5d}  {status}   (payload {plen} B, {plen % 8} leftover)")
    print("\nheader records (frame, off, len parsed, buffer.length):")
    for t in P.trace[:24]:
        print("  ", t)


if __name__ == "__main__":
    main()
