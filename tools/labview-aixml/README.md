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

Pitfalls found: Bundle By Name cannot address dotted cluster fields (`canceled.qty`,
`executed.qty`, `remaining.qty`) on import — those go through a positional Unbundle/Bundle;
case selectors are decimal; typedefs are not expressible, so the OrderBook.Command constant
and indicator are bare clusters; Trade.vi uses an enum with `Trade`=10 and `Unsupported`=11
appended, which `orderbook.command.type.ctl` must gain before it is wired in.
