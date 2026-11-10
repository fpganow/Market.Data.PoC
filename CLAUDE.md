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
`--search-path` resolves sub-VIs). It is how every "via lvkit" fact below was obtained. The source
checkout is `~/work/lvkit`; as of 2026-10-05 it is not installed on PATH in this WSL — install it
into a venv (`pip install -e ~/work/lvkit`) before relying on it.

**Writing VIs** is only possible through LabVIEW itself. `tools/labview-aixml/` holds the one
scripted route that has worked: AIXML sources + `gen_message_vi.py`, turned into VIs by the
labview-mcp plugin driving LabVIEW 2026 and saved back to LV2020 with `SaveForPrevious` (recipe and
pitfalls in its README).

Text-editable parts: Python (`ip_export/`, `s_parse.py`, `udp_send.py`, `cboe_pitch/`),
Makefiles, TCL (`vivado/`, `ip_export/gen.tcl`), SystemVerilog/Verilog testbenches and HDL, and the
C sources under `apps/*/main.c`.

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

## Three paths to hardware

1. **Pure LabVIEW bitfile** — compile the `poc.ip.kria` build spec, run `Test.Runner.kria.bats.parser.vi`.
2. **Netlist export into Vivado** (what the KR260 design actually does) — export the LabVIEW IP to a
   netlist, convert the `.dcp` to Verilog, and instantiate it in the Vivado block design alongside the
   XXV Ethernet core, the FIFOs, and `vivado/ip/{axis2xgmii.v,xgmii2axis.v}`. A Vitis app reads the
   parsed messages off AXI DMA. See `ip_export/README.md`.
3. **Pure-RTL parser in the same harness** (`vivado_rtl/`, since 2026-11-08) -- `mktdata_rtl.tcl`
   sources `vivado/mktdata_poc.tcl` and swaps the LabVIEW netlist for the hand-written
   `vivado_rtl/ip/pitch_rtl_top.v` (156.25 MHz, one message per clock, one 1024-bit record beat).
   Same PS address map, same Kria packaging (`make rtl-kria-*`, app `mktdata_rtl`), same host
   tools. It is the testbed for the speed-ups in `optimize.txt`; ideas proven there are ported
   back into LabVIEW by hand. `vivado_rtl/README.md` has the layout; `make -C vivado project` /
   `make -C vivado_rtl project` (or `gui`) recreate either Vivado project for inspection, on
   Windows `source mktdata_poc.tcl` / `source mktdata_rtl.tcl` from their directories.

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
run at a time (`poc_server` poll/serve or `fifo_server.py`) — they pop the same FIFOs, and `todo.txt` (the KR260 design-decision log — read it before changing the
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
make xsa` (xsa does not track the netlist).

```bash
make ip-export-list          # list LabVIEW compilations under /mnt/c/NIFPGA/compilation
make ip-export-copy-<N>      # copy .dcp/.vhd from compilation #N into ip_export/
make local-list              # show locally copied exports and whether .v has been generated
make local-gen-<vi-name>     # run gen.tcl to write Verilog from that export's .dcp
```

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
`pip install -e .`, needs Python ≥3.8; console scripts `generator`, `parser`, `player`, `receiver`):

```bash
cd cboe_pitch && make test                                 # full suite via venv_wsl
python3.11 -m pytest tests/test_add_order.py               # single file
python3.11 -m pytest tests/test_add_order.py::TestAddOrder # single test
```

The parser and filter submodules each carry their own `Makefile` with the same
`py_codegen / compile / elaborate / simulate / waveform` flow for simulating that block in isolation
(`make py_test` runs their Python testbench tests).

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

## Work in progress (read this first when resuming)

The dated subsections below are a chronological log (2026-09-15 … 09-23); where an earlier one
says "unresolved" and a later one says "FIXED", the later one wins. **Current state (2026-10-05):**

- Fixed and hardware-verified: 10G TX reset polarity, 32-bit capture-FIFO readout, the
  frame-boundary bug (parser bug 1). Everything through commit a1fde2d is committed.
- **Active task: the remaining PITCH message types** (ReduceSize, ModifyOrder, DeleteOrder, Trade,
  OrderExecutedAtPriceSize). The plan, per-message field map, and status are in
  `rest.of.order.types.txt` (untracked — read it before touching the parser). Generated LV2020 VIs
  `ModifyOrder.vi`, `DeleteOrder.vi`, `Trade.vi`, `OrderExecuted.generated.vi`,
  `ReduceSize.generated.vi` sit untracked in `submodules/Market.Data.Bats.Parser/fpga/message.types/`
  beside the hand-made `OrderExecuted.vi` / `ReduceSize.vi` (the latter is still a copy of
  OrderExecuted). Still to do in the IDE: append `Trade = 10`, `Unsupported = 11` to
  `orderbook.command.type.ctl`; add the parser case frames; then export, simulate
  (`netlist_sim`), extend `eval_sim.py`'s expectations, rebuild (timing margin is only +0.035 ns).
- Uncommitted LabVIEW edits in progress: `bats.parser.vi`, `OrderExecuted.vi`, `openFpga.vi`,
  `Test.Runner.kria.bats.parser.vi`, and the `.lvproj` (adds a `bats.parser` folder to the target
  and switches the FPGA target's execution mode to simulation with simulated I/O — check before
  compiling a bitfile).
- Open parser bugs: bug 2 (root cause in `compress.buffer.vi`) and bug 4 (6-char symbols) below.
- **2026-11-08 (later): pure-RTL parser bitstream `vivado_rtl/`** -- see the last dated entry and
  `optimize.txt`; xsim scores 659/659 on the 20-frame pcap, hardware results in that entry.
- **2026-11-08: in-fabric counters (`axis_mon`) deployed; the NI parser holds 1.5 Gbit/s and
  desyncs from 2 Gbit/s** (`scripts/rate_sweep.py --sink`; dated entry at the end). The board's
  `mktdata_poc` app now runs the committed 2026-09-23 export (content score 136/659); the
  2d297a51 parser is still loadable as the `mktdata_poc_rtl` app. `make xsa` needs `Performance_ExplorePostRoutePhysOpt` (default now).
- **2026-11-06: first real-cable hardware run from Linux passed** (see the dated entry at the end
  of this file): 659/659 records, every field correct, with the bitstream already on the board.
  `eval_sim.py` now knows the full type enum and all per-type fields (`--short-price-scale 100`).

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
  `sudo rmdir /sys/kernel/config/device-tree/overlays/<whatever ls shows: k26-starter-kits_image_1
  or mktdata_poc_image_1> && sudo systemctl restart dfx-mgr && sudo xmutil loadapp mktdata_poc`. Success = the PL UIO devices appear
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
  `time` ticks once per 100 MHz parser-loop cycle (**10 ns**; the parser loop `n_Timed_Loop_4241`
  is clk_pl_0, the MAC/IP/UDP filter loop `n_Timed_Loop_3470` is the 156.25 MHz rx clock).
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

### Board readout problem (unresolved — affects every hardware CMD/DEBUG capture)
Hardware `poc_server poll` returned `[0xAAAB,1,2,2]` for the reset record the IP demonstrably
emits as `[0xAAAB,0,1,2]` (same netlist in sim). Pattern = each 32-bit half of the 64-bit RDFD
load pops its own beat, contradicting todo.txt #23. Until fixed, CMD timestamps read on hardware
are not trustworthy; consider a 64→32 `axis_dwidth_converter` + 32-bit capture FIFOs (rebuild).
**Never `devmem` the axi_fifo data port (+0x1000/+0x1004) by hand** — a 32-bit read at +0x1004
after RDFO read 0 hung the AXI bus and the whole PS (2026-09-15); JTAG/UART USB is *not* visible
from this WSL VM (no Xilinx USB device → `make jtag-reboot` finds no targets), so it needs a
power cycle.

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
0x6d5…0x707 → **20 ns (Time msg) / 120 ns (1st AddOrder) … 520 ns (10th message)**. todo.txt
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
2. **OrderExecuted right after a 6-byte Time message that starts at byte 1 of a word** gets byte 2
   of its orderId zeroed (`'OR\x00D0204'`, frame 9 msg 24). All other Add/Exec alignments were
   correct (300+ checked). **Root cause (model-reproduced, 2026-09-25): `compress.buffer.vi`**, not
   `OrderExecuted.vi`/`new.uxx.be.vi` — it only rebuilds word 0 of the remainder, so when a message
   was already complete in the buffer before the new word was added the 9–15-byte remainder loses
   everything from byte 8 on. Fix: build `buffer.out[1]` (and `[2]`) with the same shift logic on
   words widx+1/widx+2 (`rest.of.order.types.txt` §4).
3. ReduceSize/Modify/Delete/Trade unsupported (type 0, which collides with Time) — the active
   task above. 0x24 OrderExecutedAtPriceSize is decoded with the 0x23 layout.
4. 6-char symbols land byte-reversed vs 8-char ones: `new.uxx.be.vi`'s Length = 6 little-endian
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

### 2026-11-06: real 10G cable run from the MS-02 Ultra (first hardware run from Linux)
The Linux box is now a MINISFORUM MS-02 Ultra (hostname still `asus`); the KR260's SFP+ cage is
on a 3 m passive DAC into its Intel E810-XXV port `eno2np1` (10GBASE-CR, autoneg off, no FEC),
and its USB JTAG/UART is attached too. The recipe lives in the workspace `../CLAUDE.md` ("10G
path from this machine"): `make kria-reload-app` (link up within 1 s), `ip addr replace
10.0.1.10/24 dev eno2np1`, permanent neighbour 10.0.1.14 → 00:0a:35:18:3c:1f, `poc_server poll`
+ `reset` on the board, `scripts/send_pcap_udp.py tests/data/generated_2026_09_17_multi.pcap`.
- **Result:** 20/20 Sequenced Unit Headers with the right length, 659/659 CMD records,
  **659/659 content matches** on type, side, orderId, quantity, symbol, price, executed /
  canceled / remaining quantity; recv→parse latency 100–920 ns. No PCS loopback involved.
- **Bitstream provenance:** the package on the board (`/lib/firmware/xilinx/mktdata_poc`, files
  dated 2026-10-20 18:17, `mktdata_poc.bit.bin` md5 `2d297a51…`) is **not** any build this file
  records by md5 (810ab582 / 84f3e78d / …). It implements the ten-item enum (0x24→3, 0x25/26→4,
  0x27/28→5, 0x29→6, 0x2A/2B/30→10) and multiplies short-variant prices by 100 in the FPGA,
  i.e. it is the 2026-10-11 19:37 export or a sibling — the one `todo.txt` item 18 says fails
  timing (WNS −4.616 ns). It parsed this pcap perfectly anyway; treat that as luck, not closure.
  **Correction 2026-11-08 evening:** the board also holds `/lib/firmware/xilinx/mktdata_poc_rtl`
  (bit.bin md5 `2d297a51…`, the same file) and `mktdata_poc_labview` (md5 `a6b4460c…`), both
  installed 2026-10-21 with the pre-axis_mon address map. So the 2d297a51 bitstream is the
  user's **`mktdata_poc_rtl`** build (the "Claude IP export" whose changes get ported into the
  LabVIEW design by hand), not a LabVIEW export; its sources are not in this clone. The
  three-bitstream picture is in `vivado_rtl/README.md`.
- **Scorer:** `ip_export/netlist_sim/eval_sim.py` was still the 2026-09-23 version (enum knew only
  Add=1 / Executed=2, everything else expected 0) and reported 325/659 on this capture. It now
  carries the full `ENUM` (unknown types → 11), checks every field in
  `rest.of.order.types.txt` per type (word map: side 1, orderId 2, qty 3, symbol 4, price 5,
  executed 6, canceled 7, remaining 8), prints an ok/total per PITCH type, and takes
  `--short-price-scale N` (100 for this bitstream; the default 1 flags exactly the 170 short
  AddOrder/ModifyOrder/Trade records). The Windows PC's copy of `eval_sim.py` may be a
  different extension of the same file — diff before overwriting either.

### 2026-11-06: rate sweep over the cable — the PS readout is the ceiling, not the parser
Tools (all in this commit): `scripts/send_pcap_udp.py` now paces with a busy-wait clock and
takes `--gap-ms` (old behaviour, default 5), `--pps N`, `--mbps M` (wire bits incl. 42 B
headers), `--speed X` (follow the pcap's own timestamps X times faster; this pcap spans
9 ms = ~18 Mbit/s at X=1), `--topspeed`, `--loop N`, and prints the achieved rate (a Python
socket reaches ~400k pps / 3.4 Gbit/s unpaced, so the sender is never the limit here).
`scripts/rate_sweep.py <pcap> --mbps … --loop N` runs one capture per rate (`poc_server poll
cmd` + IP reset + `xxv_stats` tick on the board, send, wait for the capture to stop growing,
fetch) and aligns the records with the pcap's message order to report records, parser
seq gaps, frames lost whole, frames truncated, messages lost, latency p50/max.
`apps/poc_inject/xxv_stats` (tick + read XXV STAT_RX/TX_TOTAL/RX_GOOD) was added for a
MAC-level frame count, but those registers read 0 on this bitstream although
`INCLUDE_STATISTICS_COUNTERS` is set — unresolved; the sweep ignores a 0.
- **Result (generated_2026_09_17_multi, 10–20 passes):** 100 % of records up to **3 Mbit/s**
  (~370 frames/s, ~12k msg/s); at 4 Mbit/s 12 % of messages are lost, at 6 Mbit/s 33 %, and
  from 50 Mbit/s up only ~1.6k of 13k records come back whatever the rate. Parser seq numbers
  stay contiguous at every rate (the CMD capture path never drops a record it was given) and
  `poc_server` drains a steady **7–10k records/s** (~1 MB/s: 32 UIO reads + a hex dump per
  128-byte record). Loss shows up as **truncated frames**: the CMD FIFO fills, TREADY stalls
  the NI IP, its filter→parser stream drops the tail of frames, and parse.time − recv.time
  climbs to a median of 50–160 ms (queueing in rx_data_fifo + the NI IP's internal buffer,
  ~1200 records deep). At 3 Mbit/s the max latency already reaches 65 ms — the knee.
- **So the current harness measures the PS readout, not the parser.** The parser's own limit
  (xsim says ~half of 10G for dense AddOrder frames) can only be measured once records stop
  going through AXI-Lite. Options, cheapest first, all outside the LabVIEW datapath:
  1. **Counters in the block design** (hand-written Verilog is fine in the harness): a small
     AXI-Stream monitor on the CMD stream that always asserts TREADY, counts records (TLAST)
     and seq discontinuities, and a frame counter on the xgmii2axis→NI IP stream; expose both
     through AXI GPIO/registers. The sweep then compares frames-in / records-out against the
     sender with no data moved. Needs `make xsa` (Vivado is on this box now) + kria-build.
  2. **DMA sink:** route CMD into `axi_dma_0` S2MM (cyclic SG ring in DDR) instead of
     `axi_fifo_cmd`. ~1 GB/s, but CMD is 128 B per ~35-byte message (3.7× the wire rate), so
     it still cannot keep up with 10G — fine up to ~2 Gbit/s of PITCH.
  3. **LabVIEW side** (Windows PC): make the CMD write non-blocking with a drop counter,
     add parsed-message / dropped-frame counters as registers, or a count-only mode.

### 2026-11-08: axis_mon — in-fabric counters; the parser itself holds 1.5 Gbit/s
Option 1 from the 2026-11-06 entry, built and deployed. Everything lives in the harness, so
the LabVIEW → IP Export → `make ip-install-NAME && make xsa-clean && make xsa` workflow is
unchanged; a new export just needs the same `ctrlind_NN_CMD_*` / `ctrlind_NN_T*` port names.
- **`vivado/ip/axis_mon.v`** (module reference `axis_mon_0` in the BD): zero-latency
  pass-through between `NiFpgaIPWrapper_poc_0` CMD and `axis_dw_cmd`, plus taps on the
  `xgmii2axis` → NI IP `lv_*` stream (156.25 MHz). Counters: records, beats, stall cycles
  (TVALID & !TREADY), seq gaps (word 12), bad-length records, signed lat max/min
  (word 14 − word 13), unsupported (type 11), bad magic, forwarded records, rx frames /
  bad / beats, first/last seq. **Sink mode** holds TREADY high and drops the records so
  `poc_server` is out of the loop. RX-domain counters cross via toggle handshakes
  (ASYNC_REG), bounded by the existing `set_max_delay` pair in `constraints.xdc`.
  Controlled through **`axi_gpio_mon` @ 0x80120000** (dual: ch1 out = ctrl, ch2 in =
  selected counter; register map in the Verilog header). Id register reads `MON2`
  (0x4D4F4E32).
- **Board tool `apps/poc_inject/poc_mon`** (`id | sink on|off | clear | snap | show |
  start [sink] | stop`; `make -C apps/poc_inject deploy`). dtso node `axi_gpio_mon@80120000`.
- **`scripts/rate_sweep.py --sink`**: per rate `poc_server reset`, `poc_mon start sink`,
  send `--loop N`, `poc_mon stop`; compares rx_frames with datagrams sent and records with
  messages sent, no capture at all.
- **Build:** the 2026-09-23 export only had +0.035 ns at 100 MHz; with axis_mon added the
  default strategy failed (WNS −0.281 ns, 80 endpoints, all inside the NI FIFO→FIFO parser
  paths, none in axis_mon). `Performance_ExplorePostRoutePhysOpt` closes it (+0.134 /
  +0.142 ns) and is now the default in `build.tcl` (`make xsa STRATEGY=…` overrides;
  `vivado/reimpl.tcl` re-runs impl only). Full `make xsa JOBS=8` on the MS-02 Ultra: ~12 min,
  5.8 GB peak. `vivado/Makefile` now passes `-log/-journal` **before** `-tclargs` — after
  `-tclargs` Vivado hands them to the script as `$argv`. The first `kria-build` on this box
  (bootgen + dtc from PetaLinux 2024.1) worked unchanged.
- **Deployed:** bit.bin md5 `d39fc071…` = committed 2026-09-23 export + axis_mon. `xmutil
  loadapp` failed after the first redeploy exactly as documented ("remove from slot 0
  returns: -1", kernel "Region already has overlay applied"); the stale overlay was
  `mktdata_poc_image_1`, so the rmdir must target whatever `/sys/kernel/config/device-tree/
  overlays/` lists, not only `k26-starter-kits_image_1`. The previous `mktdata_poc` package
  (md5 `2d297a51…`) is backed up at `/home/john/work/fpganow/board_backup/2026-11-08_2d297a51/
  mktdata_poc/` -- redundantly, it turned out: the board's `mktdata_poc_rtl` app is the same
  bit.bin, so `sudo xmutil unloadapp; sudo xmutil loadapp mktdata_poc_rtl` brings that parser
  back (without the monitor; `poc_mon` needs the axi_gpio_mon node, which only the two
  2026-11-08 apps have).
  Consequence: the board now runs the older parser — `eval_sim.py` scores headers 20/20,
  records 659/659, seq 1..659 contiguous, but only **136/659 on content** (this export emits
  the three-value enum 0x20→0, 0x21/0x22/0x2F→1, 0x23/0x24→2, rest 0; six-character symbols;
  unscaled short prices). To get the 2d297a51 parser back **with** the monitor, copy that
  export's `NiFpgaAG_poc_ip_kria.v` from the Windows PC and run the normal
  ip-install / xsa-clean / xsa / kria-build flow.
- **Result (sink mode, generated_2026_09_17_multi × 20 = 400 frames / 13180 messages per
  rate, 10 ns ticks):**

  | offered     | rx_frames | records | seq gaps | lat max | verdict |
  |-------------|-----------|---------|----------|---------|---------|
  | 1 Mbit/s – 1.5 Gbit/s | 400 | 13180 | 0 | 2.1 µs (≤100 Mbit/s) → 16 µs (1 Gbit/s) | **100 %** |
  | 2 Gbit/s    | 400 | 12496 | 2287 | 18 µs | parser desync: numbered 14783 for 13180 sent |
  | 3 Gbit/s    | 400 | 9425  | 5017 | 18 µs | desync, numbered 14442 |
  | 4 Gbit/s    | 400 | 8416  | 4762 | 13 µs | 36 % numbered but never output (internal drop) |

  Every frame reaches the parser at every rate (rx_frames = sent, rx_bad 0) and nothing is
  back-pressured (stall 0), so this is the NI IP's own ceiling: **flawless to 1.5 Gbit/s,
  broken from 2 Gbit/s**. In messages: the pcap averages 29.9 B of payload / 31.2 B of wire
  per message (659 msgs, 20566 wire bytes), so 1.5 Gbit/s = **6.0 M msg/s** passed and
  2 Gbit/s = 8.0 M msg/s failed. The CMD stream serialises 16 × U64 per message at 100 MHz
  (160 ns → **6.25 M msg/s**), and parse.time deltas show the parser loop itself at 6–9
  cycles/message (11–16 M msg/s), so the ceiling sits exactly where the 16-word record
  output saturates: the record width, not the parser state machine, is the first limit
  (packing the record to ≤ 4 words would lift it to ≥ 25 M msg/s). Utilisation of the
  routed design (report_utilization -hierarchical): NI IP 11.3k LUTs (9.6 %) but **92 of 144
  RAMB36 (64 %)** — its DMA/target FIFOs; device total 130.5/144 BRAM, 37.7 % LUTs. A second
  parser instance only fits after the IP's FIFOs are shrunk (drop/shorten TH-DEBUG,
  TH-MDEBUG, HT-RAW_ETH); `tx_data_fifo` (16 RAMB36, injector path) is the harness's own
  slack. `lat_min` is −1 to −3 ticks: the parser
  stamps parse.time before recv.time when it is not stalled (hence the signed counters;
  MON1 read 0xFFFFFFFF). With `poc_server poll` running instead (non-sink), the same
  1.7 Mbit/s single pass shows **stall_cycles ≈ 3.5–4 M** — the readout back-pressure of the
  2026-11-06 entry, now directly visible.
- **Sender ceiling:** `send_pcap_udp.py` reaches ~4.4 Gbit/s with these ~1 kB frames and
  falls back to ~3 Gbit/s when asked for 8+ (the busy-wait pacing loop); testing the
  parser at true line rate needs a faster source (several sender processes, a C sender,
  or pktgen/trafgen; the monitor's expected counts just add up).

### 2026-11-08 (later): `vivado_rtl/` -- a third bitstream with the parser in plain Verilog
Asked for after the rate sweep: keep bitstream 1 (LabVIEW bitfile) and 2 (LabVIEW IP export in
the Vivado harness) untouched, and add a pure-RTL fork where the `optimize.txt` recommendations
can be tried and then ported back into LabVIEW by hand. Layout and commands: `vivado_rtl/README.md`.
- **Fork mechanism:** `vivado_rtl/mktdata_rtl.tcl` sets `::origin_dir_loc ../vivado` and
  `::user_project_name mktdata_rtl`, sources `vivado/mktdata_poc.tcl` (whole harness BD built as
  for bitstream 2), then deletes `NiFpgaIPWrapper_poc_0` + `axis_mon_0`, adds module references
  `pitch_rtl_0` / `axis_mon_w_0`, three async `axis_data_fifo`s (RX clock -> pl_clk0) in front of
  the existing width converters, widens `axis_dw_cmd` to 1024 -> 32, removes the NI sources. The
  RTL files are referenced, not imported. Address map unchanged, so `kria_app/mktdata_rtl.dtso`
  differs from the poc one only in `firmware-name`; `kria_app/Makefile` takes
  `APP_NAME=mktdata_rtl XSA_DIR=../vivado_rtl` (root `make rtl-kria-*`).
- **What the RTL does differently (the optimize.txt list):** (1) one 1024-bit beat per message
  instead of 16 x 64-bit beats -- the output can never be the limit; (2) the extractor consumes
  one 64-bit word per clock and emits one message per clock (an extra cycle only when two
  messages end in the same word, i.e. a Time message), instead of 6-9 cycles per message;
  (3) everything in the 156.25 MHz RX domain, no 100 MHz loop, no CDC FIFO between filter and
  parser; (4) no parallel copies needed -- a single instance is at line rate. The filter bounds
  the payload by the IPv4 total length and clears at every frame, so the 2026-09-18 frame-tail
  bug class cannot occur. Record layout = the LabVIEW 16-word layout (word 11 also carries the
  raw type / length / unit / PITCH sequence), short prices scaled x100 in fabric
  (`eval_sim.py --short-price-scale 100`). DEBUG keeps the `[0xAAAB,0,1,2]` reset and
  `[0xDE<<32|len, len, SUH, 0]` header records; MDEBUG is `[parse.time, len, type, pitch seq]`
  per message; both drop when busy instead of stalling.
- **Monitor:** `axis_mon_w.v` = MON2's ctrl/status protocol and sel 0..16, id `MON3`
  (0x4D4F4E33), sel 17..24 = frames_pass / filtered / trunc / dropped_full, hdr_records,
  msg_trunc, dbg_dropped, pitch_seq_gaps. `poc_mon` accepts MON2 or MON3 and reads status until
  two reads agree (MON3 refreshes it through a clock-domain handshake).
- **xsim (`make rtl-sim`, `vivado_rtl/sim/run.sh`):** 20-frame pcap 20/20 headers, 659/659
  records, 659/659 content; `frame_boundary_repro.pcap` 203/203; `generated_2025_05_02.pcap`
  10/10; unchanged with `GAP=1 READY=2` (minimum inter-frame gap, random CMD back-pressure).
  Latency first message 20-40 ns, last ~800 ns after the frame's first byte (the 1012-byte frame
  needs 810 ns to arrive). Gotcha: xsim's `string.atohex()` truncates to 32 bits -- the
  testbench parses the 64-bit words with `$sscanf("%h")`.
- **Build:** `make rtl-xsa` (JOBS=8) ~12 min; routed **WNS +0.865 ns** (worst path xgmii2axis
  TKEEP -> `eth_rx_filter` fits bits, 16 levels, 5.5 ns of 6.4). Utilisation: `pitch_rtl_0`
  2.3k LUTs / 2.1k FFs / **0 BRAM** (the NI IP: 11.3k LUTs, 92 BRAM); whole design 36.8k LUTs
  (31 %), 38.5 BRAM (27 %). First build's monitor read id 0: the status ping-pong waited for the
  RX side to answer a request the PL side never sent; fixed (PL side initiates) and covered by
  `vivado_rtl/sim/tb_mon.sv`.
- **Hardware, first load (bit.bin md5 `5af10218…`, monitor still broken):** over the cable with
  `poc_server poll`, `send_pcap_udp.py --gap-ms 5`: **20/20 headers, 659/659 records, 659/659
  content** on the 20-frame pcap, all 14 message types right, first run. `xmutil loadapp
  mktdata_rtl` needed the stale-overlay fix once (overlay name `mktdata_rtl_image_1`).
- **Hardware with the fixed monitor (bit.bin md5 `af88aab3…`, WNS +0.578 ns, loaded as app
  `mktdata_rtl`, 2026-11-08 23:10):** `rate_sweep.py --sink --mbps 1 100 1000 1500 2000 3000
  4000 5000 --loop 20`: **400/400 frames, 13180/13180 records, 0 seq gaps, 0 stall, lat_max
  0.81 µs at every rate** up to the sender's 4.75 Gbit/s ceiling (the LabVIEW IP desyncs at
  2 Gbit/s). Line-rate burst: four `send_pcap_udp.py --topspeed --loop 2000` in parallel =
  160 000 frames / 164.5 MB, host NIC counters confirm 160 000 packets left in 0.159 s wall
  (8.3 Gbit/s including process start-up, i.e. the wire was at 10G for the burst):
  **rx_frames 160 000, records 5 272 000, seq 1..5 272 000 contiguous, 0 gaps, 0 stall,
  0 frames dropped, 0 truncated, lat_max 0.81 µs, lat_min 0.01 µs**. `dbg_dropped` 5.4 M is
  the DEBUG/MDEBUG traces being discarded by design when nobody drains them. The 0.81 µs max is
  the time a 1012-byte frame takes to arrive -- the parser adds no queueing at all.
  Sustained (seconds-long) 10G has not been generated yet; that needs pktgen or a C sender.
