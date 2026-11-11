# vivado_rtl -- the pure-RTL PITCH parser bitstream (bitstream 3)

Three bitstreams now exist for the KR260:

| # | What parses the market data | Project / app name | Recreate the Vivado project |
|---|-----------------------------|--------------------|-----------------------------|
| 1 | LabVIEW FPGA bitfile (`poc.ip.kria` build spec, `.lvbitx`) | LabVIEW IDE, Windows PC | not a Vivado project |
| 2 | LabVIEW FPGA **IP export** (`vivado/ip/NiFpgaAG_poc_ip_kria.v`) inside the Vivado harness | `vivado/mktdata_poc`, Kria app `mktdata_poc` | `make -C vivado project` (or `gui`) |
| 3 | **Hand-written Verilog** in `vivado_rtl/ip/` inside the same harness | `vivado_rtl/mktdata_rtl`, Kria app `mktdata_rtl` | `make -C vivado_rtl project` (or `gui`) |

On the board (`/lib/firmware/xilinx/`, `xmutil listapps`) the older packages are still installed:
`mktdata_poc_labview` (md5 `a6b4460c…`, 2026-10-21) and `mktdata_poc_rtl` (md5 `2d297a51…`,
2026-10-21, the parser measured 659/659 on 2026-11-06; its sources are not in this clone). Do not
confuse `mktdata_poc_rtl` with the new `mktdata_rtl`. Neither old package has the `axi_gpio_mon`
node, so `poc_mon` / `rate_sweep.py --sink` only work with `mktdata_poc` (2026-11-08) and `mktdata_rtl`.

Bitstream 3 forks bitstream 2: `mktdata_rtl.tcl` sources `../vivado/mktdata_poc.tcl` (so the PS,
XXV 10G Ethernet, xgmii2axis/axis2xgmii, DMA, capture FIFOs, GPIOs, address map and constraints
are identical), then deletes the LabVIEW netlist cell and its monitor and drops in the RTL parser.
Nothing under `vivado/` or in the LabVIEW export workflow changes. Harness improvements made to
`vivado/mktdata_poc.tcl` flow into bitstream 3 automatically; parser ideas proven here can be
ported back into LabVIEW by hand (that is the point of this fork).

Diagrams of the parser (data flow, state machines, per-word flow charts, UML class diagram, all
Mermaid, all named after the signals in `ip/`): `DIAGRAMS.md`.

## Recreating / viewing the projects

Linux (this machine):

```bash
make -C vivado     project      # vivado/mktdata_poc/mktdata_poc.xpr,  ~3 min, no build
make -C vivado     gui          # same, then opens the Vivado GUI
make -C vivado_rtl project      # vivado_rtl/mktdata_rtl/mktdata_rtl.xpr
make -C vivado_rtl gui
```

Windows (Vivado 2024.1 installed, repo cloned, `git submodule update --init` not needed for this):

```
Vivado 2024.1 -> Tcl Console
cd C:/path/to/Market.Data.PoC/vivado      ; source mktdata_poc.tcl     # bitstream 2
cd C:/path/to/Market.Data.PoC/vivado_rtl  ; source mktdata_rtl.tcl     # bitstream 3
```

Both scripts create the project directory next to themselves (`vivado/mktdata_poc/`,
`vivado_rtl/mktdata_rtl/`, gitignored). In the RTL project the sources under `vivado_rtl/ip/`
are referenced in place, so editing them in the Vivado editor edits the repo files; the harness
RTL from `vivado/ip/` is imported (copied) as in the original project. Open the block design
`kr260_starter_kit` to see the parser cell `pitch_rtl_0` and the monitor `axis_mon_w_0`.

## Building and running

```bash
make rtl-sim                       # xsim: vivado_rtl/sim/run.sh, scores with eval_sim.py (~1 min)
make rtl-xsa                       # Vivado synth + impl + XSA (~12 min; detach it, see CLAUDE.md)
make rtl-kria-build rtl-kria-stage rtl-kria-deploy-staged rtl-kria-reload-app
make -C apps/poc_inject deploy     # poc_mon understands both monitors (MON2 / MON3)
python3 scripts/rate_sweep.py tests/data/generated_2026_09_17_multi.pcap --sink --mbps 100 1000 2000 4000 --loop 20
```

Switching bitstreams on the board: `sudo xmutil unloadapp; sudo xmutil loadapp mktdata_poc|mktdata_rtl`
(both packages live under `/lib/firmware/xilinx/`). If `loadapp` reports "remove from slot 0
returns: -1", apply the stale-overlay fix from the repo `CLAUDE.md`.

The host tooling is unchanged: `poc_server poll` reads the same FIFOs at the same addresses,
`decode_capture.py` and `eval_sim.py` read the same 16-word CMD record. Short-variant prices are
scaled to the long format in the FPGA, so score with `eval_sim.py ... --short-price-scale 100`.

## What is in `ip/`

| File | Role |
|------|------|
| `eth_rx_filter.v` | Ethernet / IPv4 / UDP filter (dst MAC or multicast, EtherType 0x0800, IHL 5, UDP, not fragmented, port 8000), strips the 42-byte header, re-aligns the payload to byte lane 0, bounds it by the IP total length (no padding reaches the parser), precomputes the "message fits in this word" bits. |
| `pitch_extract.v` | Splits the payload into PITCH messages: one 64-bit word in per clock, one message out per clock. Clears at every frame start (Sequenced Unit Header), counts truncated / bad-length messages. |
| `pitch_decode.v` | Per-type field extraction into the 16 x U64 CMD record (LabVIEW layout, see header comment). |
| `pitch_rtl_top.v` | Top: filter -> 64-word FIFO (drops whole frames when full, never stalls the MAC) -> extractor -> decoder -> one 1024-bit beat per message; DEBUG / MDEBUG trace writers; 10 ns tick counter; ip_reset sync; stats pulses. |
| `axis_mon_w.v` | The axis_mon counters for the 1024-bit record (id "MON3", sel 17..24 added). |
| `pitch_support.v` | FWFT FIFO, debug-record serialiser, 2-flop synchroniser. |

Everything runs in the 156.25 MHz receive clock. The three record streams cross to the PL 100 MHz
domain through `axis_data_fifo` instances (`cmd_cdc`, `dbg_cdc`, `mdbg_cdc`) in the block design,
then go through the existing width converters into the existing capture FIFOs.

## Simulation (`sim/`)

`sim/tb_mon.sv` exercises `axis_mon_w` alone (both clocks, id / counters / clear / snapshot / sink);
compile it with `xvlog ../ip/pitch_support.v ../ip/axis_mon_w.v; xvlog -sv tb_mon.sv; xelab -s m tb_mon; xsim m -R`.

`sim/run.sh [pcap ...]` converts the pcap to xgmii2axis beats (`pcap2beats.py`), runs
`tb_pitch_rtl.sv` in xsim and scores `sim_out.txt` with `ip_export/netlist_sim/eval_sim.py`.
Knobs: `GAP=1` (minimum inter-frame gap), `READY=2` (random back-pressure on the CMD stream),
`LOOP=N`, `BAD_EVERY=N` (bad-FCS frames). 2026-11-08 results: 659/659 on the 20-frame pcap,
203/203 on `frame_boundary_repro.pcap`, 10/10 on `generated_2025_05_02.pcap`, also with
`GAP=1 READY=2`; last message of a 1012-byte frame emitted ~800 ns after the frame's first byte
(the frame itself takes 810 ns to arrive at 10 Gbit/s).

## 2026-11-11 rebuild: `cmd_cdc` 16 -> 1024 records (bit.bin md5 `b00a2e33…`, WNS +0.108 ns, 67 BRAM tiles)

The 16-deep CMD FIFO sat in front of the 1024->32 converter (320 ns per record) and the PS readout
(~8k records/s). With `poc_server poll` in the loop a pcap sent at speed back-pressured the parser
(stall_cycles 378 697 for one top-speed pass), whose input FIFO then dropped 19 of 20 frames: 50 of
659 records reached the host, and even at 5 ms per frame the capture showed latencies up to 294 us.
With 1024 records of depth, hwrun runs pass 659/659 at every playback speed (gap5 .. top) with
latency 10..810 ns (median 410, p99 800); `rate_sweep.py --sink` 100 Mbit/s .. 3.9 Gbit/s and the
four-sender 160 000-frame burst (5 272 000 records) are unchanged: 0 gaps, 0 stall, lat_max 0.81 us.
The parser RTL is untouched. Previous build: `../../board_backup/2026-11-08_af88aab3_mktdata_rtl/`
and `/home/ubuntu/mktdata_rtl.af88aab3.bak` on the board. Multi-pass captures longer than ~1000
records at speed still overflow by design (use `--sink`).

## Hardware results (2026-11-08, app `mktdata_rtl`, bit.bin md5 `af88aab3…`)

| Test | Result |
|------|--------|
| `poc_server poll` + one pcap pass | 20/20 headers, 659/659 records, 659/659 content (`eval_sim.py --short-price-scale 100`) |
| `rate_sweep.py --sink`, 1 Mbit/s .. 4.75 Gbit/s (sender limit), 20 passes each | 400/400 frames, 13180/13180 records, 0 seq gaps, 0 stall, lat_max 0.81 µs at every rate |
| 4 parallel `--topspeed --loop 2000` senders, 160 000 frames, wire at 10G (host NIC counters) | rx_frames 160 000, records 5 272 000 contiguous, 0 gaps, 0 drops, 0 truncated, lat_max 0.81 µs |
| Build | WNS +0.578 ns at 156.25 MHz; parser 2.3k LUTs, 2.1k FFs, 0 BRAM (LabVIEW IP: 11.3k LUTs, 92 BRAM); design 31 % LUTs, 27 % BRAM |

For comparison the LabVIEW IP (app `mktdata_poc`, 2026-09-23 export) is clean to 1.5 Gbit/s and
desyncs from 2 Gbit/s on the same traffic (repo `CLAUDE.md`, 2026-11-08 entry).
