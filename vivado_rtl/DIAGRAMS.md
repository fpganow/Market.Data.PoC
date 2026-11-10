# vivado_rtl -- diagrams of the pure-RTL PITCH parser

Mermaid source for the parser in `ip/` (renders on GitHub, in VS Code with a Mermaid
extension, or at mermaid.live). Every box and transition below names the signal or
register in the Verilog it was drawn from, so the diagram and the code can be checked
against each other. All stages run in `rx_clk` (156.25 MHz, 6.4 ns) unless marked.

| Diagram | Source files |
|---------|--------------|
| 1. Data flow (flow chart, with the cycle budget) | `ip/pitch_rtl_top.v`, `mktdata_rtl.tcl` |
| 2. State machines: `pitch_extract`, `eth_rx_filter`, frame dropper, `dbg_writer` | `ip/pitch_extract.v`, `ip/eth_rx_filter.v`, `ip/pitch_rtl_top.v`, `ip/pitch_support.v` |
| 3. Per-word decision flow chart of `pitch_extract` and per-beat flow of `eth_rx_filter` | `ip/pitch_extract.v`, `ip/eth_rx_filter.v` |
| 4. UML class diagram of the modules and the records they pass | all of `ip/` |

## 1. Data flow: one 10G frame in, one 1024-bit record per message out

Latency after the last byte of a message lands on the `lv_` stream: filter 1 cycle (+1 flush
cycle for the last word of a frame), FIFO 2 cycles, extractor 1, decoder 1, so about 6 cycles
(40 ns). Measured on hardware: 0.81 us for the last message of a 1012-byte frame, which is
the frame's own arrival time at 10 Gbit/s (cut-through).

```mermaid
flowchart LR
    subgraph RX["rx_clk 156.25 MHz (6.4 ns), inside pitch_rtl_top unless noted"]
        direction LR
        X["xgmii2axis_0 (harness)<br/>lv_data[63:0] lv_keep lv_last<br/>lv_user[0] = FCS good, FCS stripped"]
        F["u_filter: eth_rx_filter<br/>MAC / EtherType / IPv4 / UDP checks<br/>re-align payload to byte lane 0<br/>fits_of() per word<br/>1 cycle (+1 flush at TLAST)"]
        DROP{"fifo_full<br/>or dropping?"}
        Q["u_fifo: fwft_fifo<br/>64 x 79 bits<br/>{fits[7:0], bad, eof, sof, nb[3:0], data[63:0]}<br/>2 cycles"]
        E["u_ext: pitch_extract<br/>1 word in, 1 message out, per cycle<br/>acc[383:0] left-aligned<br/>hold = second message ends in same word"]
        D["u_dec: pitch_decode<br/>type enum, per-type field mux<br/>r_data[1023:0] = 16 x U64<br/>1 cycle"]
        DBG["u_dbg: dbg_writer<br/>reset record + 1 per Sequenced Unit Header"]
        MDBG["u_mdbg: dbg_writer<br/>1 per record handed downstream"]
        MON["axis_mon_w_0<br/>records, seq gaps, stalls, latency<br/>sink mode = cmd_ready forced 1"]
        X -- "lv_* (TVALID only, no back-pressure)" --> F
        F -- "f_data f_nb f_sof f_eof f_bad f_fits" --> DROP
        DROP -- "yes: whole frame dropped<br/>st_drop (stats[3])" --> LOST(("frame lost"))
        DROP -- "no: wr_en" --> Q
        Q -- "w_* head, w_rd = go & ~hold" --> E
        E -- "m_bytes[383:0] m_len m_seq m_unit m_recv_time" --> D
        E -. "h_bytes per frame (SUH)" .-> DBG
        D -- "cmd_data cmd_valid, cmd_last = 1" --> MON
        D -. "cmd_hs: parse.time, len, type, PITCH seq" .-> MDBG
        D -. "en = ~r_valid | cmd_ready<br/>freezes u_ext and u_dec" .-> E
    end
    MON -- "cmd_o_*" --> CDC["cmd_cdc<br/>axis_data_fifo, 16 deep, async"]
    subgraph PL["pl_clk0 100 MHz"]
        CDC --> DW["axis_dw_cmd<br/>1024 -> 32 bits<br/>32 beats = 320 ns per record"]
        DW --> AF["axi_fifo_cmd<br/>axi_fifo_mm_s, AXI4-Lite 32-bit"]
    end
    AF -- "PIO read, ~8k records/s" --> PS["poc_server poll / serve<br/>Cortex-A53, Linux"]
    DBG --> DC["dbg_cdc -> axis_dw -> axi_fifo_dbg"]
    MDBG --> MC["mdbg_cdc -> axis_dw -> axi_fifo_mdbg"]
    STATS["stats[15:0] pulses<br/>0 pass 1 filtered 2 trunc 3 drop_full 4 hdr<br/>5 bad_len 6 msg_trunc 7 dbg_drop 8 mdbg_drop 9 crc_bad"] --> MON
```

## 2. State machines

### 2a. `pitch_extract` (ip/pitch_extract.v)

The state is spread over `in_hdr`, `acc_len`, `off` and `skipping`; the names below are
those register combinations. Every transition is taken on a valid word (`w_valid & en`).
A word with `w_sof` makes the stage behave as if it were in HDR regardless of the state
it is in (the `e_*` muxes), which is how a frame whose tail was dropped by the FIFO
guard, or that ended mid-message, is recovered from.

```mermaid
stateDiagram-v2
    direction LR
    state "HDR<br/>in_hdr=1, len = 8 (Sequenced Unit Header)<br/>stays here while need > avail (acc_len += avail),<br/>restarts on w_eof (st_trunc)" as HDR
    state "MSG<br/>in_hdr=0, acc_len=0, off=0<br/>len = w_data[7:0] (new length byte)" as MSG
    state "MSG_ACC<br/>in_hdr=0, acc_len>0<br/>len = msg_len, acc holds the head" as MSG_ACC
    state "HOLD<br/>acc_len=0, off=end_pos<br/>w_rd=0: same word again next cycle<br/>len = start_len" as HOLD
    state "SKIP<br/>skipping=1<br/>discard words to end of frame" as SKIP
    state after_emit <<choice>>

    [*] --> HDR : rst_n low, or any w_sof word
    HDR --> after_emit : complete / h_valid, hdr_seq, unit, msg_idx=0

    MSG --> SKIP : len outside 2..48, !w_eof / st_bad_len
    MSG --> HDR : len outside 2..48, w_eof / st_bad_len
    MSG --> MSG_ACC : need > avail, !w_eof / acc = merged, msg_len = len
    MSG --> HDR : need > avail, w_eof / st_trunc
    MSG --> after_emit : complete / m_valid, msg_idx++

    MSG_ACC --> MSG_ACC : need > avail, !w_eof / acc_len += avail
    MSG_ACC --> HDR : need > avail, w_eof / st_trunc
    MSG_ACC --> after_emit : complete / m_valid, msg_idx++

    HOLD --> after_emit : always complete (fits) / m_valid, msg_idx++

    after_emit --> MSG : leftover == 0, !w_eof
    after_emit --> HDR : leftover == 0, w_eof
    after_emit --> HDR : leftover > 0, w_eof / st_trunc (cut message)
    after_emit --> HOLD : leftover > 0, fits_next / off = end_pos, start_len = next_len
    after_emit --> MSG_ACC : leftover > 0, !fits_next / acc = tail, acc_len = leftover

    SKIP --> SKIP : !w_eof
    SKIP --> HDR : w_eof
```

Signals used in the guards (all combinational from the FIFO head and the state):

```verilog
wire [3:0] avail    = nb - {1'b0, e_off};                       // bytes of this word still unused
wire [7:0] need     = len - {2'd0, e_acc_len};                  // bytes the message still needs
wire       complete = (need <= {4'd0, avail});                  // it ends inside this word
wire [3:0] end_pos  = {1'b0, e_off} + need[3:0];                // byte after it
wire [3:0] leftover = nb - end_pos;                             // bytes after it in this word
wire       fits_next = (end_pos < 4'd8) ? w_fits[end_pos[2:0]] : 1'b0;   // next one also ends here
wire hold = go & ~e_skip & len_ok & complete & (leftover != 4'd0) & ~w_eof & fits_next;
assign w_rd = go & ~hold;                                       // pitch_extract.v:85-127
```

### 2b. `eth_rx_filter` (ip/eth_rx_filter.v): one frame, beat by beat

The state is the beat index `widx` plus `accept`, `remaining` and `need_flush`. TLAST
returns to beat 0 from every state and fires the frame statistics.

```mermaid
stateDiagram-v2
    direction LR
    state "B0 MAC<br/>widx=0: mac_ok" as B0
    state "B1 ETH<br/>widx=1: EtherType 0800, ver/IHL 45" as B1
    state "B2 IP<br/>widx=2: proto 17, no fragments,<br/>pl_len = tot_len - 28" as B2
    state "B3<br/>widx=3: dst IP high half" as B3
    state "B4 UDP<br/>widx=4: dport, dst IP low half<br/>accept decided, remaining = pl_len" as B4
    state "B5 HEAD<br/>widx=5: payload bytes 0..5 held in prev" as B5
    state "PAYLOAD<br/>widx>=6, accept, remaining>0<br/>emit {s_tdata[15:0], prev[63:16]} every beat" as PAY
    state "PAD<br/>remaining==0 before TLAST<br/>eof already sent, swallow padding" as PAD
    state "REJECT<br/>accept=0: swallow to TLAST" as REJ
    state "FLUSH<br/>need_flush=1: emit bytes 2..7 of the<br/>TLAST beat as the eof word" as FL

    [*] --> B0
    B0 --> B1 : beat
    B1 --> B2 : beat
    B2 --> B3 : beat
    B3 --> B4 : beat
    B4 --> B5 : beat, accept && pl_len != 0
    B4 --> REJ : beat, !accept or pl_len == 0
    B5 --> PAY : beat (first word: m_sof)
    B5 --> B0 : TLAST, payload fits in bytes 2..nb-1 / one word sof+eof
    PAY --> PAY : beat, rem_after > 0
    PAY --> PAD : rem_after == 0, !TLAST / m_eof, m_bad=0
    PAY --> B0 : TLAST, rem_after == 0 / m_eof, m_bad = !tuser
    PAY --> FL : TLAST, tail bytes left (tail_avail != 0)
    PAY --> B0 : TLAST, tail empty but rem_after > 0 / m_eof, m_bad=1, st_frame_trunc
    FL --> B0 : next cycle / m_eof, flush_bad
    PAD --> B0 : TLAST
    REJ --> B0 : TLAST / st_frame_filtered
    B0 --> B0 : TLAST on beats 0..4 / st_frame_filtered
    B1 --> B0 : TLAST
    B2 --> B0 : TLAST
    B3 --> B0 : TLAST
    B4 --> B0 : TLAST
```

### 2c. Frame dropper in `pitch_rtl_top` (never stalls the MAC)

```mermaid
stateDiagram-v2
    direction LR
    state "PASS<br/>dropping=0: words go into u_fifo" as PASS
    state "DROP<br/>dropping=1: rest of this frame discarded" as DROP
    [*] --> PASS
    PASS --> DROP : f_valid && fifo_full / st_drop (stats[3])
    PASS --> PASS : f_valid && !fifo_full
    DROP --> DROP : f_valid && !f_eof
    DROP --> PASS : f_valid && f_eof
    DROP --> PASS : f_sof && !fifo_full (next frame starts clean)
```

`drop_now = f_valid & (f_sof ? fifo_full : (fifo_full | dropping))`. A frame cut mid-way
leaves no eof word in the FIFO; the next frame's `w_sof` word resets the extractor.

### 2d. `dbg_writer` (ip/pitch_support.v): two-entry record buffer, 4 beats per record

```mermaid
stateDiagram-v2
    direction LR
    state "EMPTY<br/>count=0, m_tvalid=0" as E0
    state "ONE<br/>count=1: beats 0..3 of buf0" as E1
    state "TWO<br/>count=2: buf0 streaming, buf1 waiting" as E2
    [*] --> E0
    E0 --> E1 : push / buf0 = rec
    E1 --> E2 : push, no pop / buf1 = rec
    E1 --> E0 : pop (4th beat accepted), no push
    E1 --> E1 : push and pop / buf0 = rec
    E2 --> E1 : pop, no push / buf0 = buf1
    E2 --> E2 : push and pop / buf0 = buf1, buf1 = rec
    E2 --> E2 : push, no pop / dropped (stats[7] or [8])
```

## 3. Flow charts

### 3a. `pitch_extract`: what happens to one word of the FIFO head

```mermaid
flowchart TD
    S(["w_valid & en"]) --> SOF{"w_sof?"}
    SOF -- yes --> R0["e_acc_len=0, e_in_hdr=1, e_off=0,<br/>e_skip=0, e_recv=time10"]
    SOF -- no --> R1["e_* = acc_len, in_hdr, off,<br/>skipping, recv_time"]
    R0 --> BAD{"w_eof & w_bad?"}
    R1 --> BAD
    BAD -- yes --> SB["st_frame_bad pulse"] --> SK
    BAD -- no --> SK{"e_skip?"}
    SK -- yes --> SKD["skipping = ~w_eof<br/>acc_len=0, in_hdr=1, off=0"] --> RD
    SK -- no --> LEN["len = in_hdr ? 8<br/>: acc_len==0 ? (off==0 ? w_data[7:0] : start_len)<br/>: msg_len"]
    LEN --> LOK{"len_ok?<br/>in_hdr or 2 <= len <= 48"}
    LOK -- no --> BL["st_bad_len pulse<br/>skipping = ~w_eof, reset acc"] --> RD
    LOK -- yes --> CMP{"complete?<br/>need = len - acc_len<br/>avail = nb - off<br/>need <= avail"}
    CMP -- no --> ACC["acc = merged (word placed at acc_len - off)<br/>msg_len = len, off = 0"]
    ACC --> EOF1{"w_eof?"}
    EOF1 -- yes --> T1["st_trunc pulse<br/>acc_len=0, in_hdr=1"] --> RD
    EOF1 -- no --> A2["acc_len += avail<br/>s_reg = acc_len + avail"] --> RD
    CMP -- yes --> HDR{"e_in_hdr?"}
    HDR -- yes --> HV["h_valid: h_bytes = merged[63:0]<br/>hdr_seq = bytes 4..7, unit = byte 3, msg_idx = 0"]
    HDR -- no --> MV["m_valid: m_bytes = merged, m_len = len<br/>m_seq = hdr_seq + msg_idx, msg_idx++"]
    HV --> IH["in_hdr = 0"]
    MV --> IH
    IH --> LO{"leftover = nb - end_pos<br/>== 0?"}
    LO -- yes --> L0["acc_len=0, off=0<br/>if w_eof: in_hdr=1"] --> RD
    LO -- no --> EOF2{"w_eof?"}
    EOF2 -- yes --> T2["st_trunc pulse (cut message)<br/>acc_len=0, in_hdr=1"] --> RD
    EOF2 -- no --> FN{"fits_next?<br/>w_fits[end_pos]"}
    FN -- yes --> HOLD["HOLD: off = end_pos, start_len = next_len<br/>acc_len = 0, s_reg = -end_pos<br/>w_rd = 0 (word stays at the FIFO head)"]
    FN -- no --> TAIL["acc = tail (bytes end_pos..nb-1 at byte 0)<br/>acc_len = leftover, msg_len = next_len<br/>s_reg = leftover"] --> RD
    RD(["w_rd = 1: pop the word"])
    HOLD --> NXT(["next cycle: same word, second message"])
```

### 3b. `eth_rx_filter`: one input beat

```mermaid
flowchart TD
    S(["s_tvalid beat"]) --> FLQ{"need_flush?"}
    FLQ -- yes --> FLU["emit flush_data / flush_nbytes<br/>m_eof=1, m_bad=flush_bad, need_flush=0"] --> PV
    FLQ -- no --> PV["prev = s_tdata, widx++"]
    PV --> W{"widx"}
    W -- 0 --> W0["mac_ok = ANY_MAC or dst==DST_MAC<br/>or (MCAST and bit0)<br/>accept=0, emitted_any=0"] --> TL
    W -- 1 --> W1["eth_ok = EtherType 0x0800<br/>and ver/IHL 0x45"] --> TL
    W -- 2 --> W2["ip_ok = proto 17, frag_off 0, !MF, tot_len>=28<br/>pl_len = tot_len - 28"] --> TL
    W -- 3 --> W3["dst_ip_hi = bytes 30..31"] --> TL
    W -- 4 --> W4["accept = mac_ok & eth_ok & ip_ok<br/>& dport==UDP_PORT & dst_ip==DST_IP<br/>remaining = pl_len"] --> TL
    W -- 5 --> W5{"TLAST & accept<br/>& remaining != 0?"}
    W5 -- yes --> W5E["payload = bytes 2..nb-1 of this beat<br/>emit one word: m_sof=m_eof=1<br/>m_bad = !tuser or too short"] --> TL
    W5 -- no --> TL
    W -- ">= 6" --> P{"accept &<br/>remaining != 0?"}
    P -- no --> TL
    P -- yes --> EM["m_tvalid=1<br/>m_tdata = {s_tdata[15:0], prev[63:16]}<br/>m_nbytes = min(remaining, word_avail)<br/>m_fits = fits_of(...), m_sof = !emitted_any<br/>remaining = rem_after"]
    EM --> TLQ{"TLAST?"}
    TLQ -- no --> R0{"rem_after == 0?"}
    R0 -- yes --> E1["m_eof=1, m_bad=0<br/>(padding follows)"] --> TL
    R0 -- no --> TL
    TLQ -- yes --> R1{"rem_after == 0?"}
    R1 -- yes --> E2["m_eof=1, m_bad = !tuser"] --> TL
    R1 -- no --> TA{"tail_avail != 0?<br/>(bytes 2..7 of this beat)"}
    TA -- yes --> FL2["need_flush=1, flush_data = tail_word<br/>flush_nbytes = min(rem_after, tail_avail)<br/>flush_bad = !tuser or still short"] --> TL
    TA -- no --> E3["m_eof=1, m_bad=1<br/>(IP length promised more)"] --> TL
    TL{"TLAST?"}
    TL -- yes --> ST["widx=0, st_frame=1, st_frame_crc_bad=!tuser<br/>accepted & pl_len!=0 ? st_frame_pass (+ st_frame_trunc if short)<br/>: st_frame_filtered"] --> END
    TL -- no --> END(["done"])
```

## 4. UML class diagram: modules, instances and the records between them

```mermaid
classDiagram
    direction TB

    class pitch_rtl_top {
        <<module>>
        param DST_MAC = 48'h000a35183c1f
        param ACCEPT_MCAST = 1, ACCEPT_ANY_MAC = 0
        param DST_IP = 0 any, UDP_PORT = 8000
        param SHORT_SCALE = 100, FIFO_LOG2 = 6
        in rx_clk, rx_aresetn, ip_reset
        in lv_data[63:0], lv_keep[7:0], lv_valid, lv_last, lv_user[0]
        out cmd_data[1023:0], cmd_valid, cmd_last=1 / in cmd_ready
        out dbg_data[63:0], dbg_valid, dbg_last / in dbg_ready
        out mdbg_data[63:0], mdbg_valid, mdbg_last / in mdbg_ready
        out stats[15:0], time10_out[31:0]
        reg time10[31:0], frac[6:0]  10 ns tick from the 6.4 ns clock
        reg dropping
        wire en = ~r_valid | cmd_ready
        wire drop_now, st_drop, ipr_rise
    }

    class eth_rx_filter {
        <<module>>
        param DST_MAC, ACCEPT_MCAST, ACCEPT_ANY_MAC, DST_IP, UDP_PORT
        in s_tdata[63:0], s_tkeep[7:0], s_tvalid, s_tlast, s_tuser
        out m_tdata[63:0], m_nbytes[3:0], m_tvalid
        out m_sof, m_eof, m_bad, m_fits[7:0]
        out st_frame, st_frame_crc_bad, st_frame_pass
        out st_frame_filtered, st_frame_trunc
        reg widx[7:0], prev[63:0], accept, remaining[15:0]
        reg mac_ok, eth_ok, ip_ok, pl_len[15:0], dst_ip_hi[15:0]
        reg need_flush, flush_data[63:0], flush_nbytes[3:0], flush_bad
        keep_count(k[7:0]) [3:0]
        byte_of(d[63:0], e[2:0]) [7:0]
        fits_of(d[63:0], nb[3:0]) [7:0]
    }

    class fwft_fifo {
        <<module>>
        param W = 79, D_LOG2 = 6
        in wr_en, wr_data[W-1:0] / out full
        in rd_en / out rd_data[W-1:0], rd_valid
        reg mem[64][W-1:0]  LUTRAM
        reg wp[6:0], rp[6:0]
        wire advance = !rd_valid || rd_en
    }

    class pitch_extract {
        <<module>>
        param MAXB = 48
        in en, w_data[63:0], w_nbytes[3:0], w_sof, w_eof, w_bad, w_fits[7:0], w_valid
        out w_rd
        in time10[31:0]
        out m_valid, m_bytes[383:0], m_len[7:0], m_seq[31:0], m_unit[7:0], m_recv_time[31:0]
        out h_valid, h_bytes[63:0], h_recv_time[31:0]
        out st_trunc, st_bad_len, st_frame_bad
        reg acc[383:0], acc_len[5:0], in_hdr, off[2:0], skipping
        reg start_len[7:0], msg_len[7:0], s_reg signed[6:0]
        reg hdr_seq[31:0], unit[7:0], msg_idx[7:0], recv_time[31:0]
        wire len, need, complete, end_pos, leftover, fits_next, hold
        merged[383:0] = acc with the word at byte acc_len - off
        tail[63:0] = word bytes end_pos..7 moved to byte 0
    }

    class pitch_decode {
        <<module>>
        param MAXB = 48, SHORT_SCALE = 100
        in en, ip_reset pulse, time10[31:0]
        in m_valid, m_bytes[383:0], m_len, m_seq, m_unit, m_recv_time
        out r_valid, r_data[1023:0], seq_counter[31:0]
        reg seconds[31:0]  last Time message
        enum_t = case of byte 1, 0x20..0x30 to 0,1,2,3,4,5,6,10,11
        u64(b, o) u32(b, o) u16(b, o) u8(b, o)
        per-type field mux side/oid/qty/sym/price/executed/canceled/remaining/flags
    }

    class dbg_writer {
        <<module>>
        in push, rec[255:0] / out dropped
        out m_tdata[63:0], m_tvalid, m_tlast / in m_tready
        reg buf0[255:0], buf1[255:0], count[1:0], beat[1:0]
    }

    class sync2 {
        <<module>>
        param W = 1
        in d[W-1:0] / out q[W-1:0]
        reg s0, s1  ASYNC_REG
    }

    class FifoWord79 {
        <<data>>
        [78:71] fits   one bit per start byte: message starting here ends in this word
        [70] bad   [69] eof   [68] sof
        [67:64] nbytes
        [63:0] data   payload bytes, byte 0 in lane 0
    }

    class Message {
        <<data>>
        m_bytes[383:0]  message left-aligned, byte 0 = length
        m_len[7:0]
        m_seq[31:0]  SUH sequence + index in frame
        m_unit[7:0]
        m_recv_time[31:0]  time10 at the frame's first payload word
    }

    class CmdRecord16xU64 {
        <<data>>
        w0 type enum   w1 side B or S   w2 orderId
        w3 quantity   w4 symbol 8 chars   w5 price
        w6 executed   w7 canceled   w8 remaining
        w9 seconds   w10 nanoseconds
        w11 flags, PITCH type, length, unit, PITCH seq
        w12 seq counter   w13 recv.time   w14 parse.time
        w15 0xDEADBEEF
    }

    class xgmii2axis_0 {
        <<harness vivado/ip>>
        lv_* 64-bit TVALID-only stream, FCS stripped
    }
    class axis_mon_w_0 {
        <<harness ip/axis_mon_w.v>>
        pass-through counters, sink mode
        cmd_i_* in / cmd_o_* out, stats[15:0] in
    }
    class cmd_path_100MHz {
        <<block design>>
        cmd_cdc axis_data_fifo 16, async
        axis_dw_cmd 1024 to 32
        axi_fifo_cmd axi_fifo_mm_s
    }

    pitch_rtl_top "1" *-- "1" eth_rx_filter : u_filter
    pitch_rtl_top "1" *-- "1" fwft_fifo : u_fifo (W=79, D_LOG2=6)
    pitch_rtl_top "1" *-- "1" pitch_extract : u_ext
    pitch_rtl_top "1" *-- "1" pitch_decode : u_dec
    pitch_rtl_top "1" *-- "2" dbg_writer : u_dbg, u_mdbg
    pitch_rtl_top "1" *-- "1" sync2 : u_ipr (ip_reset)

    eth_rx_filter ..> FifoWord79 : writes (when !drop_now)
    FifoWord79 ..> pitch_extract : w_* (FIFO head)
    pitch_extract ..> Message : m_*
    Message ..> pitch_decode : decodes
    pitch_decode ..> CmdRecord16xU64 : r_data
    pitch_extract ..> dbg_writer : h_bytes (SUH record)
    pitch_decode ..> dbg_writer : r_data words 11, 14 (MDEBUG)

    xgmii2axis_0 --> pitch_rtl_top : lv_*
    pitch_rtl_top --> axis_mon_w_0 : cmd_*, stats
    axis_mon_w_0 --> cmd_path_100MHz : cmd_o_*
```
