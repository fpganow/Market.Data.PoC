#!/usr/bin/env bash
# xsim the pure-RTL PITCH parser on pcap frames and score it with eval_sim.py.
#   ./run.sh [pcap ...]            default: tests/data/generated_2026_09_17_multi.pcap
#   GAP=1 READY=2 LOOP=3 ./run.sh  idle beats between frames / TREADY policy (1 always, 2 random,
#                                  0 held low for 3000 cycles) / repeat the pcap set
# Outputs: beats.txt (stimulus), sim_out.txt (records, eval_sim.py format), xsim logs.
set -euo pipefail
cd "$(dirname "$0")"
REPO=$(cd ../.. && pwd)
PCAPS=("$@"); [ ${#PCAPS[@]} -eq 0 ] && PCAPS=("$REPO/tests/data/generated_2026_09_17_multi.pcap")
GAP=${GAP:-4}; READY=${READY:-1}; LOOP=${LOOP:-1}; BAD=${BAD_EVERY:-0}
source /tools/Xilinx/Vivado/2024.1/settings64.sh >/dev/null

python3 pcap2beats.py beats.txt "${PCAPS[@]}" --gap "$GAP" --loop "$LOOP" --bad-every "$BAD"
xvlog ../ip/pitch_support.v ../ip/eth_rx_filter.v ../ip/pitch_extract.v ../ip/pitch_decode.v ../ip/pitch_rtl_top.v > xvlog.log 2>&1 || { cat xvlog.log; exit 1; }
xvlog -sv tb_pitch_rtl.sv >> xvlog.log 2>&1 || { cat xvlog.log; exit 1; }
xelab --timescale 1ns/1ps -s tb_rtl tb_pitch_rtl > xelab.log 2>&1 || { tail -30 xelab.log; exit 1; }
xsim tb_rtl -R -testplusarg "ready=$READY" 2>&1 | grep -E '^[0-9]+ (CMD|DEBUG|MDEBUG)|^#' > sim_out.txt
grep '^#' sim_out.txt | grep -v -E 'xsim|run|exit|finish|Time|Start|^# *$' || true
if [ ${#PCAPS[@]} -eq 1 ] && [ "$LOOP" = 1 ]; then
    python3 "$REPO/ip_export/netlist_sim/eval_sim.py" sim_out.txt "${PCAPS[0]}" --short-price-scale 100
fi
