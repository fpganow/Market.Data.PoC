#!/bin/bash
# xsim the parser IP on frames.txt (regenerate with gen_frames.py <out> <pcap>...).
#   ./run.sh            LabVIEW-exported netlist vivado/ip/NiFpgaAG_poc_ip_kria.v (default)
#   DUT=rtl ./run.sh    hand-written Verilog implementation poc_v/*.v (same ports)
# Output: sim_out.txt, lines "<cyc100> CMD|DEBUG|MDEBUG w<n> 0x<word> [LAST]".
set -e
cd "$(dirname "$0")"
source /tools/Xilinx/Vivado/2024.1/settings64.sh >/dev/null 2>&1
DUT=${DUT:-labview}
GLBL=/tools/Xilinx/Vivado/2024.1/data/verilog/src/glbl.v
if [ "$DUT" = rtl ]; then
    xvlog -sv ../../poc_v/*.v > xvlog_net.log 2>&1
    xvlog -sv -d RTL_DUT tb.sv "$GLBL" > xvlog_tb.log 2>&1
else
    xvlog ../../vivado/ip/NiFpgaAG_poc_ip_kria.v > xvlog_net.log 2>&1
    xvlog -sv tb.sv "$GLBL" > xvlog_tb.log 2>&1
fi
xelab -L unisims_ver -L unimacro_ver -L secureip --timescale 1ps/1ps -s tb_sim tb glbl > xelab.log 2>&1
xsim tb_sim -R 2>&1 | grep -E '^[0-9]+ (CMD|DEBUG|MDEBUG)|^#' > sim_out.txt
echo "wrote sim_out.txt ($(wc -l < sim_out.txt) lines) [DUT=$DUT]"
