# Generated message-type VIs (AIXML sources)

`gen_message_vi.py <ModifyOrder|DeleteOrder|Trade|OrderExecuted> <out.xml> <placeholder subVI name>`
emits the AIXML for one PITCH message-type VI in the style of `message.types/AddOrder.vi`;
`ReduceSize.xml` was written by hand the same way. The VIs in
`submodules/Market.Data.Bats.Parser/fpga/message.types/` were built from these files on
2026-09-29 with the Zuehlke labview-mcp plugin driving LabVIEW 2026 Q3 (Nigel open):

1. `lvai_placeholder_subvi` on `new.uxx.be.vi` gives the placeholder name used as `Call target`
   (AIXML refuses calls to project VIs).
2. `lvai_check_aixml` -> `lvai_generate_vi` (pane pattern 4833 like AddOrder.vi).
3. `lvai_swap_subvis` once per Call (LabVIEW's own Replace) until `socketsLeft` is 0.
4. `lvai_exec_state` (1 = executable), `lvai_run_vi_and_read_values` on real messages from
   `tests/data/generated_2026_09_17_multi.pcap`.
5. LabVIEW 2026 over COM: `SaveForPrevious(path, "", "20.0")` writes the LabVIEW 2020 file
   (the version is the THIRD argument). Save it beside the sibling VIs so the relative
   `../new.uxx.be.vi` link holds. Each result was loaded and run in LabVIEW 2020.

2026-10-07 additions:
- `gen_compress_buffer_vi.py` -> `compress.buffer.xml` -> `fpga/compress.buffer.generated.vi`
  (todo.txt item 3; verified against `ip_export/netlist_sim/compress_fix_proto.py`).
- `gen_message_vi.py AddOrder|ModifyOrder|Trade|DeleteOrder <out.xml> <stub> <vi name>` now
  also emits AddOrder (6-char symbol fix, Add flag), scales 2-byte prices by 100 unless
  `--unscaled`, and uses the 12-item enum everywhere. `ReduceSize.xml` got the same enum by
  hand. The resulting `*.generated.vi` files are beside the originals in `message.types/`.
- `orderbook.command.type.generated.ctl` was made with `lvai_create_typedef` (type literal
  `uint8{...,Get.Top,Trade,Unsupported}`) and saved for 2020 the same way as the VIs.
- `set_terminals_small.xml`: a scripting helper VI (Open VI Reference -> Front Panel ->
  Controls[] -> Terminal -> `{LV.ControlTerminal}` property `Icon View?` := false ->
  Save.Instrument). Run it on every generated VI before SaveForPrevious; AIXML has no way
  to express the terminal view and LabVIEW's option defaults to icons.
- `lvai_swap_subvis` replaces ONE stub node per call; loop until the exported AIXML shows no
  `LVMCP Stub` target (the response's `diagramSubVis` is the state before that call).
- bats.parser.vi, poc.ip.kria.vi and filter.filter.other.vi cannot be regenerated: their
  FPGA FIFO/memory nodes export as `Call target="niFpgaContainer.xnode"` and are lost.

Pitfalls found: Bundle By Name cannot address dotted cluster fields (`canceled.qty`,
`executed.qty`, `remaining.qty`) on import — those go through a positional Unbundle/Bundle;
case selectors are decimal; typedefs are not expressible, so the OrderBook.Command constant
and indicator are bare clusters; Trade.vi uses an enum with `Trade`=10 and `Unsupported`=11
appended, which `orderbook.command.type.ctl` must gain before it is wired in.

2026-10-11 addition:
- `gen_poc_ip_kria_timestamps.py` -> `poc.ip.kria.timestamps.xml` -> `fpga/poc.ip.kria.generated.vi`:
  a REFERENCE snippet for todo item 10 (tick counter + frame-start latch of the 156.25 MHz loop
  in a For Loop with array I/O, comment boxes saying where each group goes). poc.ip.kria.vi itself
  cannot be regenerated. Verified in LabVIEW 2026 and 2020. Feedback Node spelling learned from the
  export of poc.ip.kria.vi: `inputs="initializer:,next value:NET" outputs="previous value:NET"`;
  `Not` -> `.not. x?`; bool arrays are `array{bool}`; For Loop `count=""` with `mode="index"` tunnels.

2026-10-14 (todo.txt item 18, cause A — the x100 price multiply fails timing):
- `gen_message_vi.py` gained `--shift-add`: the short-variant price x100 is built as
  `(p<<6) + (p<<5) + (p<<2)` on U32 (To Unsigned Long Integer, three Logical Shift with int16
  constants 6/5/2, two Add, then To Unsigned Quad Integer) instead of a U64 Multiply, so no
  DSP48 cascade sits in series with the decode. `AddOrder.xml`, `ModifyOrder.xml`, `Trade.xml`
  are now the `--shift-add` outputs (regenerate without the flag for the old Multiply form).
- Built `AddOrder/ModifyOrder/Trade.generated.vi` (pane 4833, stubs swapped, exec state 1),
  compared against the 2026-10-07 Multiply versions on 32 real messages from
  `generated_2026_09_17_multi.pcap` (4 of each of 0x21/0x22/0x2F, 0x27/0x28, 0x2A/0x2B/0x30):
  identical OrderBook.Command clusters; export shows 0 Multiply, 3 Logical Shift, no stub.
  Terminals set small, SaveForPrevious 20.0, loaded and run in LabVIEW 2020 (ExecState 1).
  Delivered beside the originals in message.types/ (repo and OneDrive) as REFERENCE copies:
  the hand VIs keep their typedefs, so copy the shift-add group into frames 34 / 40 / 43 by
  hand rather than swapping the files.
- The full recipe is in the workspace `CLAUDE_LABVIEW.md`.

2026-10-14 (second batch): `bats.parser.generated.vi` + `FIFO.WRITE.vi` + `FIFO.READ.vi`
- `FIFO.WRITE.xml` / `FIFO.READ.xml`: stand-ins for the FPGA FIFO Method Nodes with the handshake
  interface (Write: FIFO In, Element, Input Valid -> Ready for Input, FIFO Out; Read: FIFO In,
  Ready for Output -> Element, Output Valid, FIFO Out) plus two string inputs, FIFO Name and
  Data Type, that the caller wires as constants. Element is a Variant (To Variant / Variant To
  Data in the caller). On My Computer the write always reports ready and the read never has data.
- `bats.parser.export.2026-10-14.xml` is LabVIEW's export of the OneDrive bats.parser.vi of that
  day; `parser_export_to_generated.py` turns it into `bats.parser.generated.xml` (the two FIFO
  writes -> FIFO.WRITE.vi calls with "TS-Filter.Command" / "TS-Debug" constants, plus the three
  repairs the importer needs - see the script docstring: nameless Bundle, dotted field names ->
  positional Bundle/Unbundle, hex case selectors -> decimal). Generated with the parser's subVIs
  loaded through lvai_open_file (no stubs), pane 4815; export shows the 11 real call targets and 0
  FPGA nodes; exec state 1 in LabVIEW 2026 and 2020; runs on My Computer. The diagram is ~4800 px
  wide (positional 18-element Unbundles) - run Clean Up Diagram, it is a reference copy only.

2026-10-16: **FPGA FIFO nodes CAN be created by script** — `fpga_fifo_experiment/`. NI's unsupported
FPGA scripting API (`vi.lib\rvi\ClientSDK\Core\Script\Fifo`, `nirviPiFifo_Create/SetValue/Commit`
+ `nirvififoDropXNodeFromProject.vi`) run from an AIXML-generated helper VI in LabVIEW 2020 created a
target-scoped U64 FIFO in a scratch copy of the project and dropped its Write node onto a
target VI (picture, result VI and lvproj item in that folder). The helper is generated in 2026,
SaveForPrevious'd to 20.0, and run over 32-bit COM. The node's inputs still need wiring.
