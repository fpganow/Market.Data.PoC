# Netlist simulation of poc_ip_kria (xsim, no LabVIEW, no pysv)

Simulates `vivado/ip/NiFpgaAG_poc_ip_kria.v` (the encrypted netlist the block
design uses) with the same clocking as the KR260 design: 100 MHz on
`Clk40MhzDerived5x2B00MHz` (pl_clk0, the parser loop) and 156.25 MHz on
`Clk40MhzDerived168x43B56_28MHz` (the 10G RX clock, the MAC/IP/UDP filter loop).
The VHDL wrapper is bypassed because xsim rejects the netlist's alias ports in
mixed-language mode; the wrapper only ties `tDiagramEnableOut` high.

```bash
python3 gen_frames.py frames.txt ../../tests/data/generated_2025_05_02.pcap ../../tests/data/raw_run_25_02_03.pcap
./run.sh          # ~4 min: compile + elaborate + simulate; output in sim_out.txt
```

`sim_out.txt` lines: `<cycle100> <CMD|DEBUG|MDEBUG> w<n> 0x<64-bit> [LAST]`.

## Stream formats (from fpga/poc.ip.kria.vi and bats.parser.vi, 2026-09-15)

CMD = 16 x U64 per message: 0 type, 1 side, 2 orderId, 3 quantity, 4 symbol,
5 price, 6 executed.qty, 7 canceled.qty, 8 remaining.qty, 9 seconds,
10 nanoseconds, 11 Add/Edit/Remove flags, 12 seq no, 13 recv.time,
14 parse.time, 15 0xDEADBEEF (reserved for filter time).
recv.time = parser `time` at the frame's first valid word; parse.time = `time`
when the message is emitted. `time` advances once per 100 MHz cycle (10 ns).

DEBUG = 4 x U64 parser trace records: [0xAAAB,0,1,2] on ip_reset,
[0xDE<<32|len, len, first 8 bytes, 0] when the Sequenced Unit Header is parsed,
[8 msg bytes, 0, 0, 0x99] per message, 0xAAAA / 0xBBBB when waiting for data.
MDEBUG = 4 x U64 per parser cycle: [time, msg length, msg type, ...].
