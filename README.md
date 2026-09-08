# Market.Data.PoC

Parsing CBOE BATS PITCH market data at 10G line rate on an AMD Kria KR260 — with the
parsing logic authored in **LabVIEW FPGA**, not hand-written Verilog.

## Why this exists

FPGAs are the textbook answer for deterministic, sub-microsecond market-data processing —
but the standard path there costs a fortune: custom FPGA development averages well over
$1M once you count specialized boards, tooling, and (above all) scarce HDL engineers who
command premium salaries. That price gate leaves a large population interested but on the
sidelines:

- **Mid-tier and emerging trading firms** (smaller prop shops, regional market makers,
  crypto-native firms) that know every microsecond of software feed handling costs them,
  but can't fund a hardware team.
- **LabVIEW-native industrial and test & measurement firms** that already own graphical
  dataflow expertise and hit performance walls, but see Verilog as a different profession.
- **Research groups and SMEs** priced out by engineering-months, not by boards.

This PoC is an existence proof aimed at exactly that audience:

> **10G line-rate market-data parsing, running on a ~$400 off-the-shelf dev board,
> written by a LabVIEW developer — no hand-written HDL in the parsing datapath.**

The trade is stated honestly: elite HFT designs hand-craft RTL at 322 MHz+ and reach
lower absolute latency than this design's 64-bit / 156.25 MHz datapath (each pipeline
stage costs 6.4 ns here vs. their 3.1 ns). What you get in exchange is a datapath your
existing team can author, at full line rate, with hardware determinism that no software
feed handler can match — at a cost structure a mid-tier firm can actually approve.

## What it does

```
10GbE (SFP+) ──> MAC/IPv4/UDP filter ──> BATS PITCH Parser ──> orderbook.command ──┬──> host (DMA/AXI FIFOs)
                                                                                   └──> on-FPGA consumers
```

Raw Ethernet enters over the KR260's SFP+ cage, is filtered down to the configured
MAC/IP/UDP flow, and the PITCH messages inside are parsed into normalized
`orderbook.command` records (type, side, order id, quantity, symbol, price, timestamps)
delivered to the host over AXI-Stream FIFOs / DMA, or to other IP on the fabric.

A companion symbol-watchlist **Filter** block exists with its own IP wrapper and test
suite (`submodules/Market.Data.Filter/`); wiring it into the shipping Kria IP (via the
project's target-scoped FIFOs) is the next integration step — today the exported netlist
parses but does not yet filter.

## How it flows to hardware

1. **LabVIEW FPGA design** (`fpga/poc.ip.kria.vi` + `submodules/`) — authored and
   compiled/exported in LabVIEW on Windows.
2. **IP Export** produces a netlist; `ip_export/` converts it to Verilog
   (`make ip-export-list`, `make ip-export-copy-<N>`, `make local-gen-<ViName>`).
3. **Vivado block design** (`vivado/`, Vivado 2024.1) instantiates the netlist next to
   the 10G Ethernet path and AXI DMA: `make xsa`.
4. **Kria app** (`kria_app/`) packages the bitstream for runtime loading on the booted
   board — no reflash: `make kria-build kria-stage kria-deploy-staged kria-load-app`.
5. **Host apps** (`apps/`) exercise it: `mktdata_poc_bm` / `_rtos` / `_test` run the same
   three self-tests (GPIO accumulator, FIFO echo, DMA echo) bare-metal / FreeRTOS /
   Linux; `poc_server` reads the market-data streams (`poll` hex dumps, `serve`
   broadcasts frames as NDJSON over TCP — `scripts/fifo_subscribe.py` is the client).

`make help` at the repo root lists every target.

## Testing

- **Parser unit tests** (simulation): table-driven tests per parser stage
  (`submodules/Market.Data.Bats.Parser/fpga/tests/`).
- **Host→FPGA scenario tests** (hardware): directory-discovered test VIs for parser
  (7 scenarios) and filter (10 scenarios), run by the shared test runner in
  `submodules/Market.Data.Common/`.
- **End-to-end**: `host/Test.Runner.kria.vi` replays a `cboe_pitch`-generated pcap
  through the design and deserializes the parsed commands; xsim/pysv simulation of the
  exported netlist lives in `ip_export/` (`make simulate`).
- **Traffic tooling**: `cboe_pitch/` (Python, the one remaining git submodule) generates
  and decodes PITCH messages and pcaps.

## Repo layout

| Path | Contents |
|------|----------|
| `fpga/`, `host/` | Top-level LabVIEW FPGA design and host-side runners |
| `submodules/` | Parser / Filter / Common LabVIEW code (in-repo; no longer git submodules) |
| `cboe_pitch/` | Python PITCH tooling (git submodule, branch `dev`) |
| `ip_export/` | LabVIEW netlist → Verilog conversion + xsim/pysv simulation |
| `vivado/` | Vivado 2024.1 project TCL, constraints, RTL, exported netlist |
| `apps/` | Bare-metal / FreeRTOS / Linux exercisers + `poc_server` |
| `kria_app/` | xmutil-loadable Kria app package |
| `scripts/` | Board-side helpers, Python FIFO server/client |
| `docs/kr260/` | Hardware architecture notes and timing-closure playbook |
| `todo.txt` | Design-decision log (the "why" record — read before changing the BD) |

## Getting started

Cloned without `--recurse-submodules`? Run:

```
git submodule update --init --recursive
```

Toolchains: LabVIEW 2020 (Windows) for the FPGA design; Vivado / Vitis Classic /
PetaLinux 2024.1 (Linux) for the block design and apps. LabVIEW dependencies:
[Cluster Toolkit](https://www.vipm.io/package/autotestware_lib_cluster_toolkit/)
(Autotestware, via VIPM) and NI's Instrument Design Libraries (`niidl`).

Hardware: [AMD Kria KR260 Robotics Starter Kit](https://www.amd.com/en/products/system-on-modules/kria/k26/kr260-robotics-starter-kit.html)
with a 10G SFP+ connection.
