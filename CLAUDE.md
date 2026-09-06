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
- **Host** in `host/`: `Test.Runner.kria.vi` is the current entry point (`Test.Runner.versal.vi` and
  `Test.Runner.vi` are older variants). `host/FpgaRunner/` is the class that opens the bitfile and
  pushes/pulls DMA data (`openFpga.vi`, `Write.Data.vi`, `Read.Data.vi`, `Close.Fpga.vi`);
  `Read.Pcap.File.vi` feeds it from `tests/data/*.pcap`.

The functional VIs live in the submodules — `Market.Data.Bats.Parser/fpga/bats.parser*.vi`,
`Market.Data.Filter/fpga/filter*.vi` + `Filter.lvclass`, and shared types/utilities in
`Market.Data.Common/fpga/` (`orderbook.command.ctl` is the normalized message type crossing the
parser→filter→host boundary).

## Two paths to hardware

1. **Pure LabVIEW bitfile** — compile the `poc.ip.kria` build spec, run `Test.Runner.kria.vi`.
2. **Netlist export into Vivado** (what the KR260 design actually does) — export the LabVIEW IP to a
   netlist, convert the `.dcp` to Verilog, and instantiate it in the Vivado block design alongside the
   XXV Ethernet core, the FIFOs, and `vivado/ip/{axis2xgmii.v,xgmii2axis.v}`. A Vitis app reads the
   parsed messages off AXI DMA. See `ip_export/README.md`.

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

All `make` targets below run from `ip_export/` under WSL. Paths are hardcoded: Vivado 2021.1 at
`C:\NIFPGA\programs\Vivado2021_1` (invoked via `powershell.exe`) for Verilog generation, and
`/tools/Xilinx/Vivado/2024.1` for Linux-side simulation. `make help` / `make help2` list targets.

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
- `MESSAGE ==` on line 11 of `udp_send.py` is a comparison, not an assignment — intentional-looking dead code.
