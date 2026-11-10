# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A LabVIEW FPGA proof-of-concept that ingests 10 Gigabit Ethernet market data (CBOE/BATS PITCH over UDP),
parses it into normalized order-book messages, and filters it against a watchlist — all in FPGA fabric.
Target hardware is the AMD Kria KR260 Starter Kit; the LabVIEW FPGA target class in the project is
`USRP-X410` (the IP is exported as a netlist and dropped into a Vivado block design for the KR260).

```
10GbE ──> [Ethernet MAC] ──> [BATS Parser] ──> [Filter + Watchlist] ──> DMA FIFOs ──> Host
```

## Working with this repo

**Most of the source is binary LabVIEW.** `.vi`, `.ctl`, and `.lvclass` files cannot be read, diffed,
or edited with text tools — only with the LabVIEW IDE. Do not attempt to "fix" them by editing bytes.
`.lvproj`/`.lvclass` are XML wrappers and can be *inspected* (targets, build specs, FIFOs, VI lists),
but editing them by hand risks corrupting the project.

**Reading VIs: `lvkit`** (read-only parser — `lvkit describe <vi>`, `lvkit render`, `lvkit diff`;
`--search-path` resolves sub-VIs; `--format lvnet` shows wiring). It is how every "via lvkit" fact
below was obtained. The checkout is the sibling workspace dir `../lvkit`
(`/mnt/c/work/fpganow/lvkit`); it is not on PATH and there is no `pip`/`uv` outside a venv, so set
it up per session: `python3 -m venv $SCRATCH/lvkit-venv && $SCRATCH/lvkit-venv/bin/pip install
../lvkit`. Limits: FPGA register/FIFO/clock nodes show only as opaque `xNode`, so FIFO item names
and their wiring cannot be confirmed with it.

**Writing VIs** is only possible through LabVIEW itself. `tools/labview-aixml/` holds the one
scripted route that has worked: AIXML sources + `gen_message_vi.py`, turned into VIs by the
labview-mcp plugin driving LabVIEW 2026 and saved back to LV2020 with `SaveForPrevious` (recipe and
pitfalls in its README).

`*.generated.vi` / `*.generated.ctl` files beside an original are AIXML-built replacements from
`tools/labview-aixml/`; whether the parser already calls the generated one is tracked per item in
`todo.txt` (as of 2026-10-11 all are wired in except that the old `compress.buffer.vi` still exists
for `fpga/tests/*`). `bats.parser.vi`, `poc.ip.kria.vi` and `filter.filter.other.vi` cannot be
regenerated that way (their FPGA FIFO nodes are dropped by the AIXML round trip) — those are hand
edits in the IDE, written up step by step in `todo.txt`.

Text-editable parts: Python (`ip_export/`, `s_parse.py`, `udp_send.py`, `cboe_pitch/`),
Makefiles, TCL (`vivado/`, `ip_export/gen.tcl`), SystemVerilog/Verilog testbenches and HDL
(including `poc_v/`, the hand-written Verilog parser that can replace the LabVIEW netlist, see
below), and the C sources under `apps/*/main.c`.

**Where things are written down** (read in this order when resuming):

| File | Holds |
|------|-------|
| `CLAUDE.md` § Work in progress | Current state, hardware-proven constraints, dated results log |
| `todo.txt` | Live manual to-do list: LabVIEW IDE hand steps with 🟢/🟡/⚪ status, export results |
| `docs/kr260/design-decisions.txt` | Closed KR260 block-design decision log (25 items) — read before changing the BD |
| `rest.of.order.types.txt` | PITCH message field map used to build the message-type VIs |
| `tools/labview-aixml/README.md` | The scripted VI-generation recipe and its pitfalls |
| `ip_export/netlist_sim/README.md` | xsim testbench of the exported netlist, stream formats |
| `docs/kr260/mktdata_poc.CLAUDE.md`, `advice*.txt`, `recommendations.txt` | Hardware architecture, PS address map, timing-closure playbook |

**One submodule remains** — `cboe_pitch/` at the repo root (tracks branch `dev`). Fresh clones need:

```bash
git submodule update --init --recursive
```

The former `submodules/Market.Data.Bats.Parser`, `submodules/Market.Data.Common`, and
`submodules/Market.Data.Filter` submodules were folded into this repo as regular directories
(same paths); their standalone GitHub repos hold the pre-fold history.

**LabVIEW version.** The whole tree is currently LabVIEW 2020 (`LVVersion="20008000"` in every
`.lvproj`/`.lvclass`), the result of an in-progress downgrade from LV2025 (see commits
`Before downgrade` / `Before downgrade to LV2020`). The untracked `submodules/*.2020/` directories and
`PoC.2020.old.7z` are scratch output from that downgrade, not part of the build. On this machine the
project resolves against the **32-bit** LabVIEW 2020 install
(`C:\Program Files (x86)\National Instruments\LabVIEW 2020`).

**`Market.Data.Common` is linked from source, not from its build output.** The PoC project references
`submodules/Market.Data.Common/{fpga,host}/fpganow.common.*.lvlib` directly. The Common README describes
building into `submodules/builds/fpganow.common/` (gitignored) — nothing in this project points there, so
treat that step as optional/legacy unless you are consuming Common from a different project.

External LabVIEW dependencies: Cluster Toolkit (Autotestware, via VIPM) and NI's Instrument Design
Libraries add-on (`niidl` — supplies the `niInstr` Ethernet MAC / Network Types / Basic Elements libraries).

## LabVIEW project layout (`Market.Data.PoC.lvproj`)

One FPGA Target plus "My Computer" (host).

- **FPGA top levels** in `fpga/`: `poc.ip.kria.vi` (the shipping IP, has the only build spec —
  `poc.ip.kria`, output `FPGA Bitfiles/market.data.poc_FPGATarget_poc.ip.kria_*.lvbitx`), `poc.vi`,
  `poc.test.vi` / `poc.ip.test.vi` (bench harnesses), `fpga.sandbox*.vi`, plus a legacy
  `poc.ip.versal.vi` no longer referenced by the project.
- **`fpga/Ethernet MAC - Custom/`** — LabVIEW class wrapping the AXI-stream ↔ raw-Ethernet interface
  (`Read Axi.In.vi`, `Write Axi.In.vi`, `Reader.vi`, `Writer.vi`); its wire type is `fpga/axi_2_eth_raw.ctl`.
- **DMA FIFOs**: `HT-RAW_ETH` (host→target, raw Ethernet frames for simulation/injection);
  `TH-Command.out`, `TH-DEBUG`, `TH-MDEBUG` (target→host); `TS-Filter.Command`, `TS-Debug`, `TS-MDebug`
  (target-scoped, between parser and filter).
- **Clocks**: 40 MHz base, 100 MHz (top-level timing source) and 156.28 MHz derived (the 10G MAC domain).
- **Host** in `host/`: `Test.Runner.kria.bats.parser.vi` is the current entry point (renamed from
  `Test.Runner.kria.vi` in a1fde2d; `Test.Runner.versal.vi` and `Test.Runner.vi` are older
  variants). `host/FpgaRunner/` is the class that opens the bitfile and pushes/pulls DMA data (`openFpga.vi`, `Write.Data.vi`, `Read.Data.vi`, `Close.Fpga.vi`);
  `Read.Pcap.File.vi` feeds it from `tests/data/*.pcap`.

The functional VIs live in the submodules — `Market.Data.Bats.Parser/fpga/bats.parser*.vi`,
`Market.Data.Filter/fpga/filter*.vi` + `Filter.lvclass`, and shared types/utilities in
`Market.Data.Common/fpga/` (`orderbook.command.ctl` is the normalized message type crossing the
parser→filter→host boundary).

## Two paths to hardware

1. **Pure LabVIEW bitfile** — compile the `poc.ip.kria` build spec, run `Test.Runner.kria.bats.parser.vi`.
2. **Netlist export into Vivado** (what the KR260 design actually does) — export the LabVIEW IP to a
   netlist, convert the `.dcp` to Verilog, and instantiate it in the Vivado block design alongside the
   XXV Ethernet core, the FIFOs, and `vivado/ip/{axis2xgmii.v,xgmii2axis.v}`. A Vitis app reads the
   parsed messages off AXI DMA. See `ip_export/README.md`.

**Two parser implementations, one block design (since 2026-10-20).** The BD cell
`NiFpgaIPWrapper_poc_0` is either the LabVIEW netlist wrapper (default) or
`poc_v/mktdata_parser_rtl.v`, a hand-written Verilog parser with the identical port list and
CMD/DEBUG/MDEBUG formats: `PARSER_IMPL=rtl make xsa-clean xsa` builds with the RTL,
`DUT=rtl ./run.sh` / `DUT=rtl ./sim_all.sh` simulate it (outputs `sim_out_rtl_*.txt`,
`eval_rtl_*.txt`). Always `xsa-clean` when switching. Design notes, differences and scores:
`poc_v/README.md`. Keep both in step when the stream formats change.

The current Vivado flow lives in `vivado/` (brought over from the `mktdata_poc` repo): Vivado 2024.1
recreates the project via `vivado/mktdata_poc.tcl` and builds/exports the XSA via `vivado/build.tcl`
(see `vivado/Makefile`); tracked sources are the TCL, `constraints.xdc`, and the RTL + LabVIEW netlist
in `vivado/ip/`. The generated project dir `vivado/mktdata_poc/` and the XSA are gitignored.

The rest of that repo's KR260 flow lives here too: the root `Makefile` (`make help` — `make xsa`,
bare-metal/FreeRTOS/Linux app builds, Kria app packaging/deploy, board utilities), `apps/`
(`mktdata_poc_bm`/`_rtos`/`_test` run the same three self-tests — GPIO accumulator, FIFO echo,
DMA echo — bare-metal, FreeRTOS, and Linux-userspace respectively; `poc_server` is the C++ Linux
app with the continuous market-data FIFO dumpers (`debug`/`mdebug`/`cmd`/`poll`), a `serve` mode
that broadcasts frames as NDJSON over TCP — wire-compatible with `scripts/fifo_server.py`, the
Python implementation of the same server — and the NI IP `reset`), `kria_app/` (xmutil-loadable
package), `scripts/` (board-side helpers, plus `fifo_server.py`/`fifo_subscribe.py` — the Python
server and its client, which also works against `poc_server serve`). Only ONE FIFO consumer may
run at a time (`poc_server` poll/serve or `fifo_server.py`) — they pop the same FIFOs, and `docs/kr260/design-decisions.txt` (the KR260 design-decision log, formerly todo.txt — read it before changing the
BD). `docs/kr260/` holds the ported knowledge base: `mktdata_poc.CLAUDE.md` (hardware architecture,
PS address map, 32-bit PIO constraints, JTAG quirks — paths in it refer to the old repo layout) and
the timing-closure playbook (`advice*.txt`, `recommendations.txt`, Verilog extracts, PDFs).

The superseded predecessor tree (the old `poc_kr260` block-design project, `sdk/` bare-metal
sources, `pcs_pma`/`arty_z7` experiments) was removed; it lives at the `pre_clean` git tag as
`vivado.old/`. `boot_jtag.tcl` holds the XSCT sequence for putting the KR260 into JTAG boot mode.

## Commands

The IP-export targets live in `ip_export/Makefile` and are also delegated from the repo-root
`Makefile` (`make help-ip`; `local-gen-%` resolves its paths from the Makefile's own directory
via `MK_DIR` and fails with guidance when no matching `.dcp` is present). Paths are hardcoded:
Vivado 2021.1 at `C:\NIFPGA\programs\Vivado2021_1` (invoked via `powershell.exe`) for Verilog generation, and `/tools/Xilinx/Vivado/2024.1` for Linux-side
simulation. `make help` / `make help2` list targets. After `local-gen-poc_ip_kria`, `make
ip-install-poc_ip_kria` copies the `.v` + wrapper `.vhd` into `vivado/ip/`; then `make xsa-clean &&
make xsa` — always with the clean: `mktdata_poc.tcl` adds the netlist with `import_files`, so the
generated project holds its own copy and a plain `make xsa` (or an existing XSA) rebuilds the old one.

```bash
make ip-export-list          # list LabVIEW compilations under /mnt/c/NIFPGA/compilation
make ip-export-copy-<N>      # copy .dcp/.vhd from compilation #N into ip_export/
make local-list              # show locally copied exports and whether .v has been generated
make local-gen-<vi-name>     # run gen.tcl to write Verilog from that export's .dcp
make ip-install-<vi-name>    # copy the .v + wrapper .vhd into vivado/ip/
```

**End-to-end: new LabVIEW export → simulated → on the board → scored.** Every step is runnable
from here except the LabVIEW export itself (done on the other PC, lands in `C:\NIFPGA\compilation`).

```bash
make ip-export-list && make ip-export-copy-<N> && make local-gen-poc_ip_kria && make ip-install-poc_ip_kria
# port numbering changes between exports and the wrapper .vhd can be stale — always run:
python3 ip_export/netlist_sim/ports_from_dcp.py ip_export/NiFpgaAG_poc_ip_kria.dcp \
    ip_export/netlist_sim/tb.sv vivado/mktdata_poc.tcl --check vivado/ip/NiFpgaIPWrapper_poc_ip_kria.vhd
# netlist simulation (xsim 2024.1, ~1 min/pcap, no LabVIEW needed) and scoring; DUT=rtl ./run.sh simulates poc_v/ instead
cd ip_export/netlist_sim && python3 gen_frames.py frames.txt ../../tests/data/generated_2026_09_17_multi.pcap && ./run.sh
python3 eval_sim.py sim_out.txt ../../tests/data/generated_2026_09_17_multi.pcap --short-price-scale 100; cd -
# Vivado build: MUST be detached (the harness kills background tasks; ~20 min; JOBS=8 peaks ~15 GB)
setsid nohup bash -c "make xsa-clean && make xsa JOBS=2" > xsa.log 2>&1 &   # always clean: the project IMPORTS (copies) the netlist
#   PARSER_IMPL=rtl in front of that command builds the same BD with poc_v/*.v instead of the LabVIEW netlist
make kria-build kria-stage kria-deploy-staged kria-reload-app   # board = ssh host kr260u
make server-build server-deploy poc-deploy && make -C apps/poc_inject deploy
# traffic: PCS-loopback injection (apps/poc_inject) or the 10G cable from WSL eth1:
python3 scripts/send_pcap_udp.py tests/data/generated_2026_09_17_multi.pcap --gap-ms 5
# capture with `poc_server poll` on the board (see Resume procedure below), then score it:
python3 ip_export/netlist_sim/eval_sim.py capture.txt tests/data/generated_2026_09_17_multi.pcap --short-price-scale 100
python3 apps/poc_inject/decode_capture.py capture.txt           # human-readable DEBUG trace + CMD records
```

Test pcaps in `tests/data/`: `generated_2025_05_02.pcap` (1 frame, 10 msgs), `frame_boundary_repro.pcap`
(6 frames, 203 msgs), `generated_2026_09_17_multi.pcap` (20 frames, 659 msgs, 14 types; built by
`scripts/gen_pitch_pcap.py`), `heartbeat_repro.pcap` (the multi pcap with 6 heartbeats inserted by
`scripts/make_heartbeat_pcap.py`), `unsupported_repro.pcap` (the multi pcap with three undecoded PITCH
types spliced into frame 10, 662 msgs; `scripts/make_unsupported_pcap.py`). Expected scores for the
current export: all headers, all messages, 0 content mismatches (sim-verified on all four, 2026-10-12).

Simulation (pysv bridges the SystemVerilog testbench to Python so it can replay pcap traffic):

```bash
make install_deps            # python3.8 -m pip install -r requirements-test.txt
make py_codegen              # build libpysv.so + pysv_pkg.sv into sim/
make simulate                # compile -> elaborate -> simulate (chained)
make wave                    # open the .wdb in the xsim GUI
SIM_DIR=sim/impl/timing make simulate    # variants: sim/{synth,impl}/{func,timing}
make clean
```

Python message generation / capture tooling (`cboe_pitch/`, installed with
`pip install -e .`, needs Python ≥3.8; console scripts `generator`, `parser`, `player`, `receiver`).
Its `make test` expects a `venv_wsl/` with `python3.11`, neither of which exists in this WSL
(system Python is 3.12 without `pip`), so use a scratch venv:

```bash
python3 -m venv $SCRATCH/venv && $SCRATCH/venv/bin/pip install -e cboe_pitch numpy pyyaml scapy prettytable ruamel.yaml
$SCRATCH/venv/bin/python -m pytest cboe_pitch/tests                              # full suite
$SCRATCH/venv/bin/python -m pytest cboe_pitch/tests/test_add_order.py::TestAddOrder   # single test
```

`submodules/Market.Data.Bats.Parser/Makefile` carries the same
`py_codegen / compile / elaborate / simulate / waveform` flow for simulating the parser block in
isolation (`make py_test` runs its Python testbench tests); the Filter submodule has no Makefile.

LabVIEW-side tests are VIs, run from the IDE, not the shell: `*/fpga/tests/*runFpgaTests.vi` and
`*/host/tests/`, `*/host/*runHostToFpgaTests.vi` (the host→FPGA tests need a bitfile on real hardware).

Ad-hoc traffic tools at the repo root: `udp_send.py` blasts UDP to `10.0.1.14:8000`; `s_parse.py`
reconstructs Ethernet frames from a LabVIEW debug text dump into a pcap. Both hardcode their target
addresses and input paths.

## Known rough edges

- `ip_export/Makefile`'s `pytest` and `py_codegen` targets reference `poc_gen.py` / `tests_poc_gen.py`,
  but the files present are `poc_ip.py` / `tests_poc_ip.py`. `tests_poc_ip.py` also imports `poc_gen`.
  Renamed at some point without updating the callers — fix the reference rather than assuming it's broken.
- `make gen-verilog` reads `.dcp_file`/`.v_file` dotfiles that are not in the repo (the old import flow
  wrote them); `make local-gen-<name>` is the working replacement.
- `MESSAGE ==` on line 10 of `udp_send.py` is a comparison, not an assignment — intentional-looking dead code.
- Stale statements elsewhere: `README.md`'s layout table still calls `todo.txt` the design-decision
  log (that moved to `docs/kr260/design-decisions.txt`; `todo.txt` is now the manual to-do list), and
  `ip_export/netlist_sim/README.md` still says one `time` tick is 10 ns (it is 6.4 ns, see Stream
  formats below). `host/Test.Runner.kria.vi` in the README is now `Test.Runner.kria.bats.parser.vi`.
- Only one consumer may pop the capture FIFOs at a time (`poc_server poll`/`serve` or
  `scripts/fifo_server.py`), and the NI IP reset does not clear them — stale records come out first.

## Work in progress (read this first when resuming)

The dated subsections below are a chronological log (2026-09-15 … 10-11); where an earlier one
says "unresolved" and a later one says "FIXED", the later one wins. Durable facts (build/deploy,
stream formats, netlist sim, injection, 10G path) are in the `###` sections; the rest is history.

**Current state (2026-10-20):** the LabVIEW fixes for the timing failure below are all in
(todo item 18: Fix B b1 parser-stall handshake, Fix A as a shift-add ×100 instead of the DSP
multiply, `compress.buffer.vi` swapped back). The **2026-10-20 09:20 export** (dcp md5
3d922117, `.v` 16.1 MB vs 22.7 MB before) is installed in `vivado/ip/`, port numbering
unchanged, and the netlist sim scores **100 % on all four pcaps** (203/203, 659/659, 659/659,
662/662, scored with `--short-price-scale 100`). Clean `make xsa JOBS=2` of it (09:56–10:12):
**timing met, WNS +0.007 ns, hold +0.010 ns, 0 failing endpoints** — `vivado/mktdata_poc.xsa`
of 10:12 is a good build (the worst paths are input CDC FIFO read → DEBUG FIFO data, 9.3 ns of
10, so the parser cycle has no slack left for further logic). **Deployed and run on the board
the same day** (bit.bin md5 a6b4460c…, `xmutil loadapp` needed the stale-overlay fix below):
loopback injection = the sim's 10 records; over the 10G cable all four pcaps score 100 %
(203/203, 659/659, 659/659, 662/662), first message 13–96 ns, last of a frame ≈ 1.3 µs. Test
tools fixed on the way: `scripts/send_pcap_udp.py` now sends only the UDP length (it used to
include the Ethernet pad of 60-byte heartbeat frames, which produced bogus Unsupported
records on hardware), `eval_sim.py` resyncs on seq 0 or 1. Still open: todo item 19 (three
records per run carry recv.time 0 after a stalled parser cycle), items 10, 13, 8.
**Second implementation:** `poc_v/` holds a hand-written Verilog parser (`mktdata_parser_rtl`,
same ports and stream formats as the LabVIEW IP) that scores the same 100 % on the four pcaps
(`DUT=rtl ./sim_all.sh`) and closes timing standalone (out-of-context P&R: WNS +2.18 ns at
100 MHz, +1.40 ns at 156.25 MHz; 5.0 k LUTs, 3.5 k FFs, 37.5 BRAM36, 0 DSP). Select it with
`PARSER_IMPL=rtl make xsa-clean xsa`. **Built and run on the board 2026-10-20 evening:** WNS
+1.852 ns, all four pcaps 100 % over the cable, last message of a frame ≈ 580 ns vs ≈ 1.3 µs for
the LabVIEW bitstream, no zero recv.time. Both builds' XSA/bit.bin/timing reports are saved under
`builds/{labview,rtl}_2026-10-20/` (untracked, 2.3–2.7 MB each) because `xsa-clean` deletes the
previous one. Both implementations are to be maintained — see `poc_v/README.md`. After an app
reload the static ARP entry on eth1 can vanish (link flap): re-add it before a cable run.
**Web page "Run on Hardware" (2026-10-21):** `tools/hwrun/hwrun_server.py` (README there)
runs any of the five test pcaps on the board with either implementation on request from
the fpganow.com WordPress page (plugin `fpganow-hwrun` in `~/work/shigsoft/websites`,
page `/run-on-hardware/`): loads `mktdata_poc_labview` / `mktdata_poc_rtl` (both installed
on the board via `make -C kria_app package-variant/deploy-variant` from `builds/*`), replays
the pcap, scores with eval_sim.py, returns per-message latencies, CSV and a chart.
`make hwrun` starts it. Verified end to end through the page on 2026-10-21 (LabVIEW
203/203, RTL 659/659, same latencies as the day before).

**State 2026-10-12:** the 19:37 export below **fails timing in Vivado: WNS -4.616 ns, 722
failing endpoints**, all in the 100 MHz parser loop (clean build 2026-10-12, `vivado/mktdata_poc.xsa`
of 15:38 is that failing build — do not package or deploy it). Two causes: the U64×100 short-price
multiply (item 9) put a DSP multiplier cascade in series with the decode (128 paths, -4.6 ns), and
the 6-shifter `compress.buffer.generated.vi` (item 3) costs ~2 ns on 594 more paths that had
+0.035 ns before. Fix options and the path listing: `todo.txt` item 18,
`docs/kr260/timing_2026-10-12_fail.txt`. Also done 2026-10-12: `todo.txt` item 2 confirmed in sim with
`tests/data/unsupported_repro.pcap` (three undecoded PITCH types → three type-11 records, 662/662).

**State 2026-10-11 evening:** the 19:37 IP export (dcp md5 7e039484) is installed in
`vivado/ip/` and simulated here with **100 % content match**: repro 203/203, 20-frame 659/659,
`tests/data/heartbeat_repro.pcap` (new, 6 heartbeats) 659/659, all headers present, Trades typed 10,
prices ×100 for short variants (`eval_sim.py --short-price-scale 100`), DEBUG stream one record per
message. The 14:22 export earlier that day still had Trades typed 9 because the target-scoped FPGA
FIFO `TS-Filter.Command` kept a private copy of the element type with the old 10-item enum (FIFO
data types do not follow typedef edits; re-pick the typedef in the FIFO properties). Not yet done:
`make xsa` (detached) and the board run with this netlist. **This export renumbered the IP's `ctrlind_NN` ports**
(TREADYs first, then DEBUG/CMD/MDEBUG, ip_reset 15, input stream 16–20; the names are only readable
in `NiFpgaIPWrapper_poc_ip_kria.vhd`, the `.v` is encrypted). `ip_export/netlist_sim/tb.sv` and
`vivado/mktdata_poc.tcl` were remapped — and the 19:37 export of the same day went **back** to the
original numbering while LabVIEW left the 14:22 wrapper `.vhd` in place (so the wrapper is not a
reliable source). The reliable source is the `.dcp` (a zip holding `*_stub.v`):
`python3 ip_export/netlist_sim/ports_from_dcp.py ip_export/NiFpgaAG_poc_ip_kria.dcp
ip_export/netlist_sim/tb.sv vivado/mktdata_poc.tcl --check vivado/ip/NiFpgaIPWrapper_poc_ip_kria.vhd`
remaps both files by port name and exits 1 on a stale wrapper. Run it after every `ip-install`.
When the numbering differs from the last `make xsa`, build with `make xsa-clean && make xsa`
(detached); the 19:37 export has the numbering the existing project was built with. `eval_sim.py` now needs `--short-price-scale 100` (short prices
are ×100 in the parser), checks every symbol, reads the UDP length, and groups latency by pcap frame
(recv.time is per record since the frame-start latch was removed, todo item 10).
`apps/poc_inject/decode_capture.py` names CMD types 0–11. Open items: `todo.txt` summary block.

**State 2026-10-05 (superseded above):**

- Fixed and hardware-verified: 10G TX reset polarity, 32-bit capture-FIFO readout, the
  frame-boundary bug (parser bug 1). Everything through commit a1fde2d is committed.
- **Remaining PITCH message types: DONE in LabVIEW, exported 2026-10-05, simulated 2026-10-06.**
  `bats.parser.vi` now has frames "37, 38" → `ReduceSize.generated.vi`, "39, 40" → `ModifyOrder.vi`,
  "41" → `DeleteOrder.vi`, "42, 43, 48" → `Trade.vi`, and `OrderExecuted.vi` handles 0x24 itself
  (commit 00553be). Netlist sim of that export: repro pcap 203/203 messages, 20-frame pcap
  659/659, every field right **except** that all Trades report type 9 — `orderbook.command.type.ctl`
  still ends at `Get.Top = 9`, so Trade.vi's value 10 is clamped by the typedef coercion.
  `eval_sim.py` checks the new types. **The hand-work that remains is in `todo.txt`** (the live
  manual to-do list; the old KR260 design-decision log moved to `docs/kr260/design-decisions.txt`).
  Field map and build recipe stay in `rest.of.order.types.txt` and `tools/labview-aixml/`.
  Not yet done after this export: `make xsa-clean && make xsa` (margin was +0.035 ns before the
  netlist grew from 15.7 to 16.2 MB) and the board run.
- Parser bugs 2 (`compress.buffer.vi` remainder) and 4 (6-char symbols) were fixed in LabVIEW on
  2026-10-07..09 via `compress.buffer.generated.vi` / `AddOrder.generated.vi` and are sim-confirmed
  in the 2026-10-11 export (`todo.txt` items 3 and 4); hardware confirmation is still pending.

### Build / deploy facts (hardware-proven 2026-09-15)
- `make xsa` from Claude Code must run **detached** (`setsid nohup bash -c "make xsa JOBS=2 …" &`)
  — the harness kills it as a background task "for low memory"; JOBS=8 really does peak ~15 GB.
  Clean build ~20 min. Results: July netlist WNS +0.863 ns; Sept-11 netlist WNS **+0.127 ns**
  (0 failing, hold +0.011). A clean build of the July tree reproduced the old `mktdata_poc`
  `bit.bin` byte-for-byte, which is why `mktdata_poc/` is archivable.
- `make kria-build` rebuilds only the dtbo when just the dtso changed (bit.bin keyed on the XSA).
- **`xmutil loadapp` fails after a power cycle / redeploy** with "remove from slot 0 returns: -1"
  when the factory `k26-starter-kits_image_1` overlay is still in configfs but dfx-mgr thinks
  nothing is loaded (kernel: "Region already has overlay applied"). Fix on the board:
  `sudo rmdir /sys/kernel/config/device-tree/overlays/k26-starter-kits_image_1 && sudo systemctl
  restart dfx-mgr && sudo xmutil loadapp mktdata_poc`. Success = the PL UIO devices appear
  (13 with the old dtso, 15 with the new one: + axi_dma_0, xxv_ethernet_0).
- Apps: `make server-build server-deploy poc-build poc-deploy board-setup` (needs
  `g++-aarch64-linux-gnu`; installed here 2026-09-15; the board has no compiler). Over one ssh
  script never `pkill -f` a pattern that appears in the script text — use `pkill -INT -x poc_server`;
  under `sudo bash -c` `~` is root's home.
- Self-tests (`mktdata_poc_test test`) pass on the Sept bitstream; ip_reset pulse produces one
  32-byte DEBUG frame.

### Stream formats (from `fpga/poc.ip.kria.vi`, `bats.parser.vi` via lvkit)
- **CMD** = 16 × U64 per message: 0 type, 1 side, 2 orderId, 3 quantity, 4 symbol, 5 price,
  6 executed.qty, 7 canceled.qty, 8 remaining.qty, 9 seconds, 10 nanoseconds, 11 Add/Edit/Remove
  flags, 12 seq no, **13 recv.time, 14 parse.time**, 15 0xDEADBEEF (reserved for filter time).
  recv.time = parser `time` at the frame's first valid word (OneDrive edit: `frame.start` in
  `my.network.data.stream` is now a U64 set via a Select); parse.time = `time` when emitted.
  `time` is a counter in the **156.25 MHz** MAC/IP/UDP loop (`n_Timed_Loop_3470`, rx clock), so one
  tick = **6.4 ns** (corrected 2026-10-11; earlier notes said 10 ns - every latency figure quoted
  before that date is 1.56x too large). The parser loop `n_Timed_Loop_4241` is clk_pl_0 (100 MHz)
  and reads the counter through a Register (the clock-domain crossing, 1-3 ticks late).
  `decode_capture.py` / `eval_sim.py` use 6.4 ns. Since the 2026-10-11 01:20 edit recv.time is a
  per-word stamp (frame-start latch removed) - see `todo.txt` item 10 for the choice.
- **DEBUG** = 4 × U64 parser trace: `[0xAAAB,0,1,2]` on ip_reset; `[0xDE<<32|len,len,first8B,0]`
  on Sequenced Unit Header; `[8 msg bytes,0,0,0x99]` per message; 0xAAAA/0xBBBB = waiting.
- **MDEBUG** = 4 × U64 per parser cycle `[time, msg len, msg type, …]`.
- **Measured parse latency** (xsim of the Sept netlist, `tests/data/generated_2025_05_02.pcap`):
  1st message 30–40 ns after the frame's first word enters the parser, ~+90 ns per following
  ~34-byte AddOrder (parser ≈ 9 cycles/message ≈ half of 10G line rate for dense frames), 10th
  message 570–650 ns. Excludes MAC/xgmii2axis/CDC FIFO/CMD serialization (160 ns)/PS readout.
- Sim anomaly: three frames 64 beats apart → the 3rd produced 34 records for a 10-message frame
  (frames 2 and 4 fine) — possible frame-boundary bug ("TODO: If End of Frame" in bats.parser.vi).

### Netlist simulation without LabVIEW/pysv — `ip_export/netlist_sim/`
`gen_frames.py <out> <pcap>…` then `./run.sh` (~4 min, xsim 2024.1). Instantiates the encrypted
`vivado/ip/NiFpgaAG_poc_ip_kria.v` directly (the VHDL wrapper breaks mixed-language xsim; it only
ties `tDiagramEnableOut` high). `enable_out` never rises for this free-running VI — don't wait on
it. Output `sim_out.txt`: `<cyc100> CMD|DEBUG|MDEBUG w<n> 0x<word> [LAST]`. README there has the
formats.

### Board readout problem (FIXED 2026-09-17, see below — kept for the devmem warning)
Hardware `poc_server poll` returned `[0xAAAB,1,2,2]` for the reset record the IP demonstrably
emits as `[0xAAAB,0,1,2]` (same netlist in sim). Pattern = each 32-bit half of the 64-bit RDFD
load pops its own beat, contradicting design-decisions.txt #23. Until fixed, CMD timestamps read on hardware
are not trustworthy; consider a 64→32 `axis_dwidth_converter` + 32-bit capture FIFOs (rebuild).
**Never `devmem` the axi_fifo data port (+0x1000/+0x1004) by hand** — a 32-bit read at +0x1004
after RDFO read 0 hung the AXI bus and the whole PS (2026-09-15); JTAG/UART USB is *not* visible
from this WSL VM (no Xilinx USB device), but since 2026-10-23 both work through Windows:
`make hw-server-win` (Vivado 2025.1 hw_server on 127.0.0.1:3121, which `make jtag-targets` /
`make jtag-reboot` / `make board-reset` connect to via HW_SERVER_URL) and `make uart-win
CMD='...'` (scripts/kr260_uart.ps1 on COM6). Verified: xsct lists the PSU/APU chain, the UART
shows the login prompt. Gotchas from that day: a board reset while hw_server is attached left two
A53 cores in "Reset Catch" (boot stalled, ssh dead) -- `make board-reset` + `make hw-server-win-stop`
recovered it; and any keystroke on the console during U-Boot's countdown stops autoboot
(`make uart-listen` watches without sending, `make uart-win CMD=boot` continues).

### 2026-09-16 evening results (both injection paths now work)
- **BD bug fixed in `vivado/mktdata_poc.tcl`:** `axis2xgmii_0/rst` (active-HIGH) was driven by
  `tx_rst_n/Res` (active-low), so the TX adapter sat in reset forever (idles only, TREADY=0 — the
  design's 10G TX had never worked). Now driven by `xxv_ethernet_0/user_tx_reset_0`. Rebuilt
  (WNS **+0.031 ns**, 0 failing) and deployed; `kria_app/build` bit.bin md5 810ab582….
- **PCS loopback injection works:** `poc_inject` → TX → loopback → S2MM got the 307 B frame back
  byte-identical, and the NI IP emitted DEBUG/MDEBUG/CMD (5 hw CMD records = 10 messages under the
  readout defect, matching the sim). `poc_inject <frame.hex> --loopback-off --rx-only --rx-wait-ms 10` (the frame file must come first)
  restores cable RX (the loopback bit persists across runs — always clear it afterwards).
- **Cable path works from WSL without Windows admin:** mirrored mode accepts a Linux-only address:
  `sudo ip addr add 10.0.1.10/24 dev eth1; sudo ip neigh replace 10.0.1.14 lladdr
  00:0a:35:18:3c:1f dev eth1 nud permanent`, then a plain UDP socket bound to 10.0.1.10 →
  10.0.1.14:8000 reaches the parser (S2MM saw the frame with src MAC 24:5e:be:8b:b1:94). The
  `Start-Process -Verb RunAs` UAC route does not work from this session. (These Linux-side
  settings vanish on WSL restart.)
- **Readout defect confirmed quantitatively:** predicting each hardware 64-bit word as
  `low32(beat 2k) | high32(beat 2k+1) << 32` from the sim's CMD beat stream reproduces the
  captured words (see session notes) — every 64-bit CPU load pops two FIFO beats. Proposed fix:
  `axis_dwidth_converter` 64→32 in front of `axi_fifo_{debug,mdebug,cmd}` with the FIFOs' AXI4
  data width set to 32, and `poc_server` reading 32-bit pairs (LSW first). Needs a rebuild.
- Ground truth for `generated_2025_05_02.pcap` (10 messages: Time, AddOrder ORID0001..ORID0008,
  …) with recv/parse timestamps is in `ip_export/netlist_sim/sim_out.txt` (frame 0).

### 2026-09-17: readout FIXED — hardware now returns complete CMD/DEBUG records
`axis_dw_{debug,mdebug,cmd}` (axis_dwidth_converter 64→32) sit between the NI IP and the capture
FIFOs, whose `C_S_AXI4_DATA_WIDTH` is now 32; `poc_server` and `scripts/fifo_server.py` read two
32-bit RDFD words per stream beat (LSW first). Rebuilt (WNS **+0.364 ns**), deployed (bit.bin md5
081d8afa…), loopback run: DEBUG trace identical to the sim (`[0xAAAB,0,1,2]`, header 265 B,
per-message 0x99 records), 10 complete CMD records with recv.time = 0x6d3 for all and parse.time
0x6d5…0x707 → **20 ns (Time msg) / 120 ns (1st AddOrder) … 520 ns (10th message)**. design-decisions.txt
items 24 (TX reset) and 25 (readout) record both BD changes. `decode_capture.py` decodes it all.
Oddity to look at in LabVIEW: the CMD `symbol` field comes out byte-reversed ('    TFSM') for
most AddOrders but forward ('MSFT    ') for ORID0004 — probably type-dependent packing.

### Multi-frame test pcap — `scripts/gen_pitch_pcap.py` (2026-09-17)
Builds `tests/data/generated_2026_09_17_multi.pcap` (+ `.txt` audit listing) with the cboe_pitch
Generator: 20 frames, 659 messages, 14 PITCH types (Add long/short/expanded, Modify, ReduceSize,
OrderExecuted, Delete, Trade, Time), sequence 1..659 continuing across frames, ~1000 B payloads,
addressed to the IP's filter. Independently validated (spec lengths, SUH length/count, sequence
continuity, edits only reference live orders). Needs a venv with `pip install -e cboe_pitch numpy
pyyaml scapy prettytable ruamel.yaml`. **Generator trap:** order-size ranges must span ≥ 2 steps of
25 shares (sizes are min + k·25) or `getNextMsg()` loops forever on a Modify.

### LabVIEW parser bugs found with the multi-frame pcap (2026-09-17, hardware + xsim agree)
Status 2026-10-11: bug 1 fixed on hardware (09-23); bugs 2, 3, 4 fixed in LabVIEW and confirmed by
netlist sim of the 10-11 export, board run pending. Kept in full for the mechanisms and tooling.
1. **Frame-boundary corruption — root cause (2026-09-18): NI's IPv4/UDP stream VIs mangle the
   tail of any frame whose LAST AXI BEAT has 7 or 8 valid bytes** (frame length ≡ 7 or 0 mod 8 ⇔
   UDP payload ≡ 5 or 6 mod 8). After the real last payload word (whose byte 4 arrives stale) they
   emit one EXTRA data-valid word holding the frame's last 8 bytes with 7 or 8 byte enables. The
   parser (correctly) never clears its buffer, so the next frame's Sequenced Unit Header is read
   from that leftover and it desyncs for many frames. Evidence: the garbage header lengths seen on
   hardware and in xsim (0, 12593, 21071) equal LE16(frame[-8:][:2]) of the preceding frame in every
   case; a bit-exact Python model of add.data.to.buffer/compress.buffer/bats.parser
   (`ip_export/netlist_sim/parser_model.py`) parses all 20 frames when fed clean payload words, so
   the parser's buffer arithmetic is NOT the bug. The spec (Cboe Multicast PITCH, "UDP delivered
   data will not cross frame boundaries and a single Ethernet frame will contain only one Sequenced
   Unit Header") is only half-used: bats.parser.vi reads eof.good/eof.bad just to jump to the
   header state and never discards leftovers at a frame start.
   Ruled out by xsim: appending an FCS (moves the problem, adds leftover), signalling EOF on a
   separate data-valid=false beat (breaks every frame — Reader.vi's "EOF on the last data word" is
   right), splitting the last beat 6+1 / 4+3, or an empty TKEEP=0 EOF beat (NI's stream stalls on
   any mid-frame partial beat). **What works (`frames_pad.txt` run):** pad such frames with 1–2
   bytes so the final beat is short — then the frame arrives intact and the only leftover is the
   known pad.
   **Fix (both in LabVIEW):** (a) `fpga/Ethernet MAC - Custom/Reader.vi`: when TLAST && TKEEP ∈
   {0x7F,0xFF}, send the beat without TLAST and follow it with a 2-byte (0x7F) / 1-byte (0xFF) pad
   beat carrying TLAST (needs one pipeline stage; the 10G inter-frame gap covers the extra beat);
   (b) `bats.parser.vi`: at the first word of a new frame (Timestamp change, or an explicit
   start-of-frame flag added in poc.ip.kria.vi = data valid && !previous data valid) set
   buffer.length := 0 before adding — this is the spec-compliant "each frame starts with a SUH"
   rule and also discards the pad. (b) alone stops the desync but leaves the frame's last byte(s)
   corrupted in the 7/8 cases; (a)+(b) fixes both. tb.sv now takes an optional 5th column (tvalid).
   **Status 2026-09-22 (OneDrive working tree, verified with lvkit + the model):** (a) is done in
   Reader.vi exactly as designed (cluster Feedback Node → split = TVALID∧TLAST∧(TKEEP∈{7F,FF}) →
   `pad pending` FB → five Selects; pad beat = TKEEP 0x01, TLAST, TDATA 0). (b) is done as an
   end-of-frame clear in Read.Msg only (L ≥ len branch: buffer.length := 0 and state := header
   when done ∨ eof). Model on the 20-frame pcap: shipped Reader + this parser 10/20 headers;
   padded Reader + this parser **20/20 headers, 659/659 messages**. NI's Find IPv4 Subframe drops
   every byte past the IP Total Length, so the pad bytes never reach the parser (no leftover at
   all). Still recommended for bad/truncated frames: the same eof clear in the header state
   (L < 8 branch) and in Read.Msg's L < len branch — with those two the model recovers all 20
   headers even with the shipped Reader. Checker: `ip_export/netlist_sim/check_parser_variants.py <frames.txt> <pcap>`
   (pads beats in software, runs parser variants).
   **2026-09-23 export of these edits (dcp md5 5acb0ed4…, wrapper VHDL unchanged) — netlist sim
   results:** `frame_boundary_repro.pcap` 6/6 headers, 203/203 messages; the 20-frame pcap
   659/659 messages, every header the DEBUG stream carried correct. Only remaining content error
   is bug 2 (OrderExecuted after Time, frame 9 msg 24). Scorer: `ip_export/netlist_sim/eval_sim.py
   <sim_out.txt | poc_server-poll capture> <pcap>`. Testbench notes: `gen_frames.py` now writes the
   5th (tvalid) column tb.sv expects — a 4-column file is read mis-aligned and NO frames reach the
   IP; tb.sv now drains 20 000 cycles after the last beat because the CMD stream serialises 16
   words/message (160 ns) and the 20-frame file needs > 100 µs to flush; the DEBUG stream (4 words
   every parser cycle) overflows its FIFO on dense input and silently drops records (7 of 20
   header records missing in the multi run) — score by CMD records, match headers by sequence no.
   **Hardware 2026-09-23 (rebuilt: WNS +0.035 ns, 0 failing; bit.bin md5 84f3e78d…):** loopback
   injection = 10 CMD records as in sim; over the 10G cable (`scripts/send_pcap_udp.py <pcap>
   --gap-ms 5` from WSL eth1) the repro pcap gives 6/6 headers, 203/203 messages and the 20-frame
   pcap 20/20 headers, 659/659 messages, all content right except bug 2. **Frame-boundary bug
   (bug 1) is FIXED on hardware.** Latency per frame: first message 20–140 ns, last ~2.0–2.1 µs.
   Gotchas met on the way: `poc_inject` needs the frame file as its first argument
   (`poc_inject <hex> --loopback-off --rx-only`), otherwise the loopback bit stays set and the
   cable path is dead; the IP reset does not clear the capture FIFOs, so frames parsed while no
   consumer runs come out first (and, after an overflow, mis-framed) in the next `poll` —
   eval_sim.py resyncs on the parser's seq counter (CMD word 12 restarts at 1 after reset).
   Timestamp quirk: the Time message that starts a frame can show parse.time 20 ns *before*
   recv.time (recv.time is latched a cycle after the first word); harmless, not investigated.
   **Bit-exact model (2026-09-18): `ip_export/netlist_sim/ni_stream_model.py`** transcribes
   Reader.vi + NI's Stream Filter MAC / Find IPv4 Subframe / Stream Filter IPv4 / UDP Rx State
   Machine + the poc.ip.kria glue + bats.parser (parser_model.py) register by register and
   reproduces the netlist simulation's parser DEBUG stream word for word on six runs (frame pairs
   4-5, 5-6, 9-10, 12-13, 14-15 and the padded set). Two facts lvkit cannot show were established
   by that match: (1) `Delete From Array` nodes with an unwired index delete from the END (this
   sets the role schedules and makes the MAC filter's Purge test look at byte-enable lanes 6–7 and
   the IPv4 filter's at lanes 4–7); (2) the MAC filter's two-word data and byte-enable histories
   (fb20/fb21, fb19/fb22) are enable-gated and only shift on a valid input word.
   **Exact mechanism for a final beat with 7 or 8 valid bytes:** the MAC filter sees lanes 6–7
   valid on the TLAST beat and enters its one-cycle Purge to flush the two tail bytes, but its
   history cannot advance during the idle gap, so Purge re-emits the previous assembled word
   (A_L = prev[6:8]+last[0:6]) with 8 byte enables and the real tail bytes are never emitted. The
   IPv4 filter therefore receives A_L twice: it outputs A_L[4:8]+A_L[0:4] with 8 enables (byte 4 of
   the frame's last message is now A_L[0] instead of the true byte), then, because that word had
   lanes 4–7 valid at EOF, takes its own Purge and outputs the same word again with 4 enables.
   Net: the parser gets 12 bytes where the frame had 5 — one wrong byte and 7 junk bytes that
   become the next frame's header. With ≤ 6 valid bytes no MAC Purge occurs and everything aligns.
   **Repro:** `tests/data/frame_boundary_repro.pcap` (+ `.txt`): 6 frames, frames 3 and 5 end in
   7- and 8-byte beats and break frames 4 and 6. **Library fix validated in the model:** letting the
   MAC filter's history registers shift every cycle (or at least during Purge) makes all 20 test
   frames parse with correct headers (as shipped: 9/20). The IPv4 filter needs no change.
   **NI's IDL VIs are readable with lvkit** (block diagrams intact): `/mnt/c/Program Files (x86)/
   National Instruments/LabVIEW 2020/instr.lib/_niInstr/Network/{Ethernet/Utility/v1/FPGA/Stream
   Filter MAC.vi, IPv4/FPGA/v1/{Stream Filter IPv4.vi,Find IPv4 Subframe.vi}, IPv4/UDP/FPGA/v1/UDP
   Rx State Machine.vi}` (use `--search-path` = that Network dir). Mechanism seen there: the MAC
   filter strips 14 B with a two-word history (output = word[n-2] bytes 6–7 + word[n-1] bytes 0–5),
   ends a frame with ONE "Purge" flush cycle that also carries the deferred End-of-Good-Frame, and
   the IPv4 subframe finder counts Total Length bytes then "caches the last data and holds it until
   the packet ends, so we can align the last data with End of Good Frame". A last input word with
   bytes 6–7 valid (7 or 8 valid) needs a second flush that the single Purge cycle does not give,
   so EOF lands one cycle off the last data and the IPv4 cache re-emits the tail → the extra word.
2. **[FIXED in sim 2026-10-11 by `compress.buffer.generated.vi`]** **OrderExecuted right after a 6-byte Time message that starts at byte 1 of a word** gets byte 2
   of its orderId zeroed (`'OR\x00D0204'`, frame 9 msg 24). All other Add/Exec alignments were
   correct (300+ checked). **Root cause (model-reproduced, 2026-09-25): `compress.buffer.vi`**, not
   `OrderExecuted.vi`/`new.uxx.be.vi` — it only rebuilds word 0 of the remainder, so when a message
   was already complete in the buffer before the new word was added the 9–15-byte remainder loses
   everything from byte 8 on. Fix: build `buffer.out[1]` (and `[2]`) with the same shift logic on
   words widx+1/widx+2 (`rest.of.order.types.txt` §4).
3. **[FIXED, commit 00553be + 10-11 export]** ReduceSize/Modify/Delete/Trade unsupported (type 0, which collides with Time).
   0x24 OrderExecutedAtPriceSize is decoded with the 0x23 layout.
4. **[FIXED in sim 2026-10-11 by `AddOrder.generated.vi`]** 6-char symbols land byte-reversed vs 8-char ones: `new.uxx.be.vi`'s Length = 6 little-endian
   frame lacks the Swap Bytes/Words of the Length = 8 frame. Cheapest fix: read the symbol with
   Length 8 in `AddOrder.vi`, AND 0x0000FFFFFFFFFFFF, OR 0x2020000000000000.
Measured on clean frames (363 msgs, ~30 msgs/frame): first message 10–140 ns after the frame's
first word, ~56–74 ns per additional message, last message ~2.0–2.1 µs; median 1.03 µs.
Capture: `scripts/gen_pitch_pcap.py` file sent from WSL eth1 5 ms apart, `poc_server poll`,
decoded with `apps/poc_inject/decode_capture.py` (group CMDs by recv.time = frame).

### Frame injection without a 10G source — `apps/poc_inject/`
`poc_inject <frame.hex>`: sets XXV PCS local loopback (`MODE_REG` 0x0008 bit 31, waits for
`STAT_RX_BLOCK_LOCK` 0x040C), DMAs the frame out through `axi_dma_0` MM2S (SG, **32-bit
addressing → buffer page must be < 2 GiB PA**; the K26 hands out high pages first, so the code
maps a 1 GiB region and scans its pagemap for a low page) → tx_data_fifo →
axis2xgmii → xxv TX → loopback → RX → xgmii2axis → NI IP, and captures the looped copy with S2MM
(zy stream) as proof. `generated_2025_05_02.hex` (307 B, dst 00:0a:35:18:3c:1f / 10.0.1.14:8000,
matches the IP's filter) is the frame; `decode_capture.py` decodes a `poc_server poll` capture
into DEBUG trace + parsed CMD messages + recv→parse latency. Register offsets come from
`vivado/mktdata_poc/…/xxv_ethernet_0_0/header_files/*_axi4lite_reg.h`.

**Resume procedure once the board answers ssh (`kr260u` = 192.168.1.197):**
```bash
make kria-stage kria-deploy-staged        # new dtbo (+2 UIO nodes)
make kria-reload-app                      # if it errors: stale-overlay fix above, then loadapp
make server-deploy poc-deploy && make -C apps/poc_inject deploy
ssh kr260u 'sudo pkill -x poc_server; sudo bash -c "nohup ./poc_server poll > /home/ubuntu/cap.txt 2>&1 &"; sleep 2; \
  sudo ./poc_server reset; sleep 1; sudo ./poc_inject /home/ubuntu/generated_2025_05_02.hex; sleep 2; \
  sudo pkill -INT -x poc_server; sleep 1; cat /home/ubuntu/cap.txt'   > capture.txt
python3 apps/poc_inject/decode_capture.py capture.txt   # compare with ip_export/netlist_sim/sim_out.txt (frame 0)
```
If `poc_inject` reports no block lock, try GT-level loopback instead (not in the PCS header;
check PG210) or the real cable path below.

### Real 10G path from this PC (undocumented until now)
Windows has a **QNAP QNA-T310G1S** Thunderbolt 10GbE SFP+ adapter ("Ethernet 3", Marvell AQtion
driver, MAC 24-5E-BE-8B-B1-94), seen "Disconnected" with only a link-local address on 2026-09-16.
To use it: static IP e.g. 10.0.1.10/24 on Ethernet 3; static ARP `arp -s 10.0.1.14
00-0a-35-18-3c-1f` from an elevated prompt (the FPGA never answers ARP); SFP+ cable to the KR260;
app loaded (link only rises once the XXV PCS transmits). Senders (`udp_send.py`, cboe_pitch
`player`) open a plain UDP socket to 10.0.1.14:8000 and must run **on Windows** (WSL2 is NAT'd);
Windows currently has no Python (Store stub only). **WSL already sees the adapter**: `.wslconfig`
has `networkingMode=mirrored`, so it is `eth1` (MAC 24:5e:be:8b:b1:94), DOWN until the SFP+ link
rises, then it carries the Windows IP. Bring-up: elevated PowerShell `New-NetIPAddress
-InterfaceAlias "Ethernet 3" -IPAddress 10.0.1.10 -PrefixLength 24` and `netsh interface ipv4 add
neighbors "Ethernet 3" 10.0.1.14 00-0a-35-18-3c-1f`; in WSL `sudo ip neigh replace 10.0.1.14 lladdr
00:0a:35:18:3c:1f dev eth1 nud permanent`; check `ip -br addr` shows `eth1 UP 10.0.1.10/24`.
Then senders can run from WSL too (plain UDP sockets; no raw L2). `player`'s default `--mac` is
00-0A-35-18-3C-**0F** but the IP filter/pcaps use …3C-**1F** — pass `--mac` explicitly. The old
raw_run pcaps came from 10.0.1.10 with a Mellanox MAC (a different NIC).

### 2026-10-27/28: production "Run on Hardware" page verified end to end (resume point)

**State:** the public page https://fpganow.com/index.php/run-on-hardware/ (WordPress plugin
`fpganow-hwrun`, source in `~/work/shigsoft/websites/fpganow/wp-content/plugins/fpganow-hwrun/`,
still untracked there) talks through shigsoft's cron-kept SSH tunnel (172.17.0.1:8301 →
bayside:2222 → this PC 172.17.0.1:8300) to `tools/hwrun/hwrun_server.py`, which runs here as
the *system* unit `hwrun.service` (auto-starts, `Restart=always`; stop it with
`fuser -k 8300/tcp`, never `pkill -f`). Verified 2026-10-28 from a real browser
(`tools/hwrun/pagecheck/`, see its README): LabVIEW 203/203 median 684.8 ns, RTL 203/203 median
332.8 ns on `frame_boundary_repro`; CSV, chart, report toggle, 20 s cooldown (429 from the proxy),
shareable `?hwrun=<id>` link and phone layout all OK. Run records: `tools/hwrun/runs/20261028-*`.

**Changes made, uncommitted:** `hwrun_server.py` finds the QNAP adapter by MAC
`24:5e:be:8b:b1:94` (`host_mac` in the board catalog) because WSL renumbers ethN after the
adapter re-enumerates; `ip_export/netlist_sim/eval_sim.py` per-frame latency block now skips
records with recv.time 0 (same rule as the service's JSON summary) — before, the scorer report
shown on the page printed ~5e8 ns for frames 1/3/5 of the LabVIEW build. New dir
`tools/hwrun/pagecheck/` (API + puppeteer page tests). Workspace `CLAUDE.md` refreshed.

**Incident:** 2026-10-27 ~22:45 hot-plugging the QNAP Thunderbolt adapter froze Windows (WSL
rebooted, board unaffected). Re-plugging on 2026-10-28 did not. Prefer plugging it in before boot.

**Open before announcing the page:** (1) site-wide broken header logo — the DB still references
`http://localhost:8200/wp-content/uploads/...rect10-9.png` from the dev stack (42 hits in
`fpganow_wrd.sql`); fix on shigsoft with `wp search-replace 'http://localhost:8200'
'https://fpganow.com' --all-tables`; (2) the page is not in the site menu; (3) commit the plugin
in the websites repo and `tools/hwrun/` + the eval_sim fix here; (4) LabVIEW build still emits 3
records without recv.time (todo item 19) — shown as a warning card on the page.

**Resume commands:** `ip -br link | grep 24:5e:be:8b:b1:94` (want LOWER_UP), `systemctl status
hwrun`, `ssh kr260u uptime`, then `python3 -I tools/hwrun/pagecheck/prodrun.py frame_boundary_repro labview`
(wait 20 s between runs) or the browser test in `tools/hwrun/pagecheck/README.md`.

### 2026-11-02: latency statistics table; development moving to a Linux machine (resume point)

**Done today:** the page got a "Latency statistics" table (count / min / mean / median / p95 /
p99 / max for recv→parse latency and for time since the frame's first message; computed in
`assets/app.js` over matched, stamped messages) and `hwrun_server.py` returns the same numbers in
the JSON summary (`latency_ns`, `since_frame_start_ns`, `lat_stats()`); plugin 1.0.0 → 1.1.0.
Verified on the local dev stack with the stored 2026-10-28 runs (`tools/hwrun/pagecheck/stats.js`);
no fresh hardware run because the board was powered off. **Production still runs 1.0.0:** the two
files are staged on shigsoft in `~/fpganow-hwrun-update/`; install needs sudo there (command in
`docs/HANDOFF_2026-11-02.md` §2).

**Machine move:** this PC (ASUS15, Windows + WSL2) stops being the lab PC. Everything needed to
continue on a Linux-only machine — what to copy, what is uncommitted in the three working trees,
how to rebuild the hwrun service / inbound tunnel / 10G path / JTAG / dcp→Verilog step without
Windows, the proposed LabVIEW-PC → Linux transfer workflow, and the first-session checklist — is
in **`docs/HANDOFF_2026-11-02.md`** (also at `/mnt/c/work/fpganow/handoff_2026-11-02/` with the
Claude memory files, the systemd unit, the sshd snippet and the tunnel key). Read it first.

### 2026-11-10: branch `asus15-local-work` = everything this PC (ASUS15) had uncommitted

All 2026-10-07..11-02 work from this PC was committed on branch `asus15-local-work` (from
`bca72d1`) and pushed on 2026-11-10; `main` here was then cleaned and fast-forwarded to the
Linux-side `aa7bcf5`. The branch is **not merged**. It carries: the netlist conversion of the
2026-10-20 IP export (`vivado/ip/NiFpgaAG_poc_ip_kria.v`, 16.1 MB — `main` still has an older
conversion), `poc_v/` (the `mktdata_poc_rtl` bitstream's sources, `DUT=rtl` sim hooks,
`PARSER_IMPL=rtl` in `vivado/`), `tools/hwrun/`, the AIXML tooling, the 2026-10-20 builds and
board captures under `builds/` (bit/bit.bin/xsa via LFS), and the October notes in this file
and `todo.txt`. When merging into `main`, re-apply on top of the Linux-side versions:
`send_pcap_udp.py` must cut at the UDP length (heartbeat Ethernet pad fix), `eval_sim.py` /
`decode_capture.py` use a **6.4 ns** tick (sim-verified 2026-10-11; `main` went back to 10 ns),
and `vivado/mktdata_poc.tcl` must keep `axis_mon` when the `PARSER_IMPL` switch is merged in.
Local-only variants replaced by the owner's resaves on 2026-11-09 are archived outside the repo
in `/mnt/c/work/fpganow/old/reconcile_2026-11-09/`.
