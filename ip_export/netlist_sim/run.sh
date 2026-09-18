#!/bin/bash
# xsim the LabVIEW-exported poc_ip_kria netlist directly (no VHDL wrapper, no pysv).
# Usage: ./run.sh            (uses frames.txt; regenerate with gen_frames.py <out> <pcap>...)
set -e
cd "$(dirname "$0")"
source /tools/Xilinx/Vivado/2024.1/settings64.sh >/dev/null 2>&1
NET=../../vivado/ip/NiFpgaAG_poc_ip_kria.v
GLBL=/tools/Xilinx/Vivado/2024.1/data/verilog/src/glbl.v
xvlog "$NET" > xvlog_net.log 2>&1
xvlog -sv tb.sv "$GLBL" > xvlog_tb.log 2>&1
xelab -L unisims_ver -L unimacro_ver -L secureip --timescale 1ps/1ps -s tb_sim tb glbl > xelab.log 2>&1
xsim tb_sim -R 2>&1 | grep -E '^[0-9]+ (CMD|DEBUG|MDEBUG)|^#' > sim_out.txt
echo "wrote sim_out.txt ($(wc -l < sim_out.txt) lines)"
