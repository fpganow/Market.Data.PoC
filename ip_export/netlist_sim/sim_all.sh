#!/bin/bash
# simulate the parser on the four test pcaps and score each (log: sim_all.log)
#   ./sim_all.sh            LabVIEW netlist -> sim_out_<pcap>.txt, eval_<pcap>.txt
#   DUT=rtl ./sim_all.sh    poc_v/*.v         -> sim_out_rtl_<pcap>.txt, eval_rtl_<pcap>.txt
cd "$(dirname "$0")"
export DUT=${DUT:-labview}
if [ "$DUT" = rtl ]; then T=rtl_; else T=; fi
for p in frame_boundary_repro generated_2026_09_17_multi heartbeat_repro unsupported_repro; do
  echo "===== $p  $(date +%H:%M:%S)"
  python3 gen_frames.py frames.txt ../../tests/data/$p.pcap > gen_$p.log 2>&1 || { echo "gen_frames failed"; cat gen_$p.log; continue; }
  ./run.sh 2>&1 | tail -1
  cp sim_out.txt sim_out_$T$p.txt
  python3 eval_sim.py sim_out_$T$p.txt ../../tests/data/$p.pcap --short-price-scale 100 > eval_$T$p.txt 2>&1
  grep -E -i 'headers|messages|content|mismatch|records' eval_$T$p.txt | head -8
done
echo "===== done $(date +%H:%M:%S)"
