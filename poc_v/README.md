# poc_v/ — hand-written Verilog parser (second implementation of the LabVIEW IP)

`mktdata_parser_rtl` is a plain-Verilog re-implementation of the LabVIEW FPGA IP
`fpga/poc.ip.kria.vi` (NI stream filters + `bats.parser.vi` + the `message.types/*.vi`
decoders). It has the **same port list as `vivado/ip/NiFpgaIPWrapper_poc_ip_kria.vhd`**,
produces the **same CMD / DEBUG / MDEBUG stream formats** (see `ip_export/netlist_sim/README.md`
and `CLAUDE.md` "Stream formats"), and is scored by the same `eval_sim.py` and board tools.
Written 2026-10-20 from the bit-exact Python models (`ip_export/netlist_sim/ni_stream_model.py`,
`parser_model.py`), `rest.of.order.types.txt` and the CMD records of the 2026-10-20 export.

Both implementations are kept and selectable; nothing in the LabVIEW flow changes.

| | LabVIEW IP (default) | this RTL |
|---|---|---|
| sources | `vivado/ip/NiFpgaAG_poc_ip_kria.v` (encrypted) + VHDL wrapper, from `make ip-export-copy-N local-gen-… ip-install-…` | `poc_v/*.v` |
| netlist sim | `cd ip_export/netlist_sim && ./run.sh` / `./sim_all.sh` | `DUT=rtl ./run.sh` / `DUT=rtl ./sim_all.sh` (outputs `sim_out_rtl_*.txt`, `eval_rtl_*.txt`) |
| Vivado block design | `make xsa-clean && make xsa JOBS=2` (detached) | `PARSER_IMPL=rtl make xsa-clean xsa JOBS=2` (detached) |
| BD cell | `NiFpgaIPWrapper_poc_0` = module `NiFpgaIPWrapper_poc_ip_kria` | `NiFpgaIPWrapper_poc_0` = module `mktdata_parser_rtl` (same pins) |

`vivado/mktdata_poc.tcl` reads `PARSER_IMPL` (`labview` | `rtl`) and imports either file set;
`vivado/Makefile` exports it. **Always `xsa-clean` when switching** — the project imports its
own copy of the sources, so the old implementation stays in a stale project.

## Files

| file | clock | what |
|---|---|---|
| `mktdata_parser_rtl.v` | both | top: reset synchronisers, ip_reset, 64-bit tick counter (156.25 MHz, 6.4 ns), overflow policy, instances |
| `udp_rx_filter.v` | 156.25 MHz | Reader.vi + NI MAC / IPv4 / UDP filters: dst MAC `00:0a:35:18:3c:1f`, IPv4, no fragments, dst IP `10.0.1.14`, UDP port 8000 (0xFF bytes match anything, as in NI's VIs). Strips the 42-byte header, re-aligns the UDP payload to 8-byte words with a byte count, `sof`/`eof`, and the tick-counter stamp (`recv.time`). Ethernet padding beyond the UDP length is dropped. |
| `async_fifo.v` | 156→100 | 4096-word gray-pointer CDC FIFO (`{ts, eof, sof, nbytes, data}`) |
| `time_cdc.v` | 156→100 | brings the tick counter into the 100 MHz domain (req/ack snapshot + 25/16-per-cycle extrapolation) for `parse.time` |
| `pitch_parser.v` | 100 MHz | 64-byte byte window; per cycle: append one input word **and** consume one unit (SUH 8 bytes, or one message of `len` bytes, or a chunk of a >56-byte unsupported message). Decode stage builds the 16×U64 CMD record. |
| `rec_fifo_axis.v` | 100 MHz | record FIFO + AXI-stream serialiser: CMD 512 records × 16 words, DEBUG / MDEBUG 256 × 4 words, TLAST on the last word |

## Behaviour that differs from the LabVIEW IP (on purpose)

- **Throughput**: one message per cycle in the parser (~10 ns/msg, LabVIEW ≈ 9 cycles/msg). The
  CMD stream itself still needs 16 cycles per message (160 ns), so dense input queues up in the
  CDC FIFO (4096 words ≈ 21 full frames) and the 512-record CMD FIFO.
- **Overflow**: when the CDC FIFO is full the *rest of that frame* is dropped whole
  (`dropped_frames` counter in the top), never a word in the middle; the parser resynchronises at
  the next frame start. LabVIEW's FIFO overflows silently mid-frame.
- **Frame start = header**: the first payload word of every frame resets the window (Cboe spec:
  one Sequenced Unit Header per frame), which is the LabVIEW "eof clear" generalised. Bytes
  beyond the unit length (`hdr_len`) are dropped until the next frame.
- **recv.time** is the tick at which the filter produced the word that *completed* the message
  (a 16-entry (end-position, timestamp) queue keeps this exact while the parser is stalled), so
  latency includes any queueing in the CDC FIFO. No zero recv.time (LabVIEW todo item 19).
- **DEBUG** carries only the reset, header and per-message records (no 0xAAAA/0xBBBB idle
  records, which flood and overflow the LabVIEW DEBUG FIFO). **MDEBUG** = one record per
  message `[time, len, type, window bytes]` instead of one per parser cycle.
- `enable_out` = running (LabVIEW's stays low); `enable_in`/`enable_clr` ignored.
- Short prices (0x22, 0x28, 0x2B) are ×100 with a shift-add like the current LabVIEW VIs
  (`--short-price-scale 100` when scoring).

## Item 19 (recv.time = 0 on stalled-cycle messages) — solved here

LabVIEW's parser takes recv.time from the input word of the *current* cycle, so a message
that is emitted one cycle late (the Fix B stall: two messages completed by one word) gets the
Select's default constant, recv.time 0 — three records per test pcap (seq 101, 284, 378),
confirmed on the board 2026-10-20. In `pitch_parser.v` every inserted word pushes
(end position, timestamp) into a 16-entry queue; when a message is consumed, the queue entry
covering its last byte supplies recv.time, whatever the delay. Result on the four pcaps:
0 zero stamps in 2183 records, and those three messages read e.g. recv 1455 / parse 1485
(30 ticks) instead of recv 0. The LabVIEW-side fix is still open in `todo.txt` item 19.

## Verification (2026-10-20, xsim 2024.1, `DUT=rtl ./sim_all.sh`)

| pcap | headers | messages | content |
|---|---|---|---|
| frame_boundary_repro | 6/6 | 203/203 | 203/203 |
| generated_2026_09_17_multi | 20/20 | 659/659 | 659/659 |
| heartbeat_repro | 26/26 | 659/659 | 659/659 |
| unsupported_repro | 20/20 | 662/662 | 662/662 |

Same scores as the 2026-10-20 09:20 LabVIEW export on the same testbench. First-message
latency 64–140 ns, last message of a 30-message frame ≈ 520 ns (LabVIEW: ≈ 1.2–1.3 µs).

Debug traces: compile with `-d PARSER_TRACE` / `-d FILTER_TRACE` (see the `ifdef` blocks).

## Timing and resources (Vivado 2024.1, out-of-context synth + place + route, xck26-sfvc784-2LV-c, 2026-10-20)

Both clocks met: WNS **+2.18 ns** at 100 MHz (worst path 15 logic levels, CMD FIFO pointer →
parser), **+1.40 ns** at 156.25 MHz. 5 045 CLB LUTs, 3 500 registers, 37.5 BRAM36 (CDC FIFO
16, CMD FIFO 15, DEBUG/MDEBUG 4 + 4), 0 DSP, 0 critical warnings. Script: a `read_verilog
poc_v/*.v; synth_design -mode out_of_context; create_clock 10 ns / 6.4 ns; opt/place/route`
run (`report_cdc` still lists the handshake bus and reset synchronisers, see below).

## Board run (2026-10-20 18:17 build, `PARSER_IMPL=rtl`, bit.bin md5 2d297a51…)

Full BD build: timing met, **WNS +1.852 ns** (LabVIEW netlist build of the same day: +0.007 ns),
whole design 35.8 k LUTs / 42.8 k FFs / 76 BRAM (the LabVIEW variant's whole-design numbers were
not saved; standalone the RTL is 5.0 k LUTs / 37.5 BRAM). Loopback injection: 10/10 records.
10G cable, `scripts/send_pcap_udp.py --gap-ms 5`, scored with `eval_sim.py --short-price-scale 100`:

| pcap | headers | records | content | first msg (ns) | last msg of frame (ns) |
|---|---|---|---|---|---|
| frame_boundary_repro | 6/6 | 203/203 | 203/203 | 64–90 | 576–589 |
| generated_2026_09_17_multi | 20/20 | 659/659 | 659/659 | 51–83 | 563–589 |
| heartbeat_repro | 26/26 | 659/659 | 659/659 | | |
| unsupported_repro | 20/20 | 662/662 | 662/662 | | |

Versus the LabVIEW bitstream on the same frames: first message 13–96 ns (LabVIEW is ~30 ns
faster on the first message, the RTL has one more pipeline stage and the handshake-sampled
parse.time), last message of a ~33-message frame **≈ 580 ns vs ≈ 1.3 µs**, median 326 ns vs
685 ns, and 0 zero recv.time records vs 3 (item 19). Captures (in `builds/rtl_2026-10-20/captures/`): `capture_rtl_loopback.txt`,
`capture_rtl_cable_<pcap>.txt`; artefacts: `builds/rtl_2026-10-20/` (LabVIEW build:
`builds/labview_2026-10-20/`). Gotcha met: after an app reload the 10G link flaps and WSL drops
the static ARP entry for 10.0.1.14 — the board then only sees ARP requests (visible with
`poc_inject … --rx-only`); re-add it with `ip neigh replace`.

## Not yet done

- The CDC constraints are covered by the BD's generic `set_max_delay -datapath_only` pair in
  `vivado/constraints.xdc`; `report_cdc` still lists the handshake bus and reset synchronisers.
- `set_false_path` / CDC constraints for `time_cdc` (`cap` → `snap` is a handshake-stable bus) and
  the reset synchronisers; `report_cdc` will flag them until added to `vivado/constraints.xdc`.
