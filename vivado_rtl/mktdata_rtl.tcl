# mktdata_rtl.tcl -- recreate the Vivado 2024.1 project for the pure-RTL bitstream
# (project `mktdata_rtl`, block design `kr260_starter_kit`).
#
#   Linux:    make -C vivado_rtl project        (or `make gui` to open it)
#   Windows:  Vivado 2024.1 Tcl console:  cd <repo>/vivado_rtl ; source mktdata_rtl.tcl
#
# How it forks the LabVIEW design: it sources ../vivado/mktdata_poc.tcl with the
# project name overridden, so the whole KR260 harness (PS, XXV 10G Ethernet,
# xgmii2axis/axis2xgmii, DMA, capture FIFOs, GPIOs, address map, constraints)
# is built exactly as for bitstream 2, then it swaps the parser:
#   - deletes NiFpgaIPWrapper_poc_0 (the LabVIEW netlist) and axis_mon_0
#   - adds pitch_rtl_0 (ip/pitch_rtl_top.v) and axis_mon_w_0 (ip/axis_mon_w.v),
#     both in the 156.25 MHz RX clock domain
#   - adds three async FIFOs (RX clock -> PL 100 MHz) in front of the existing
#     width converters, and widens axis_dw_cmd to 1024 -> 32 bits
#   - removes the NI netlist sources from the project
# The RTL sources are *referenced* (not copied into the project), so editing
# vivado_rtl/ip/*.v in Vivado edits the repo files. The harness files under
# vivado/ip are imported copies, as in the original project.
# Everything the PS sees (UIO addresses, FIFO ports, GPIO maps) is unchanged, so
# poc_server / poc_mon / the dtso work with one firmware-name edit.

set here [file dirname [file normalize [info script]]]
cd $here
set ::origin_dir_loc   [file normalize "$here/../vivado"]
set ::user_project_name "mktdata_rtl"
set ::argv {}
set ::argc 0
source "$::origin_dir_loc/mktdata_poc.tcl"

# ---------------------------------------------------------------------------
# RTL sources
# ---------------------------------------------------------------------------
set rtl_files [list \
  "$here/ip/pitch_support.v" \
  "$here/ip/eth_rx_filter.v" \
  "$here/ip/pitch_extract.v" \
  "$here/ip/pitch_decode.v" \
  "$here/ip/pitch_rtl_top.v" \
  "$here/ip/axis_mon_w.v" ]
add_files -norecurse -fileset sources_1 $rtl_files
update_compile_order -fileset sources_1

# ---------------------------------------------------------------------------
# Swap the parser in the block design
# ---------------------------------------------------------------------------
open_bd_design [get_files kr260_starter_kit.bd]

delete_bd_objs [get_bd_cells NiFpgaIPWrapper_poc_0] [get_bd_cells axis_mon_0]
# nets that lost one end and still hold pins we need
foreach pat {NiFpgaIPWrapper_poc_0_* axis_mon_0_* axis_dw_cmd_s_axis_tready axi_gpio_mon_gpio_io_o axi_gpio_1_gpio_io_o} {
  foreach n [get_bd_nets -quiet $pat] { delete_bd_objs $n }
}

set pitch_rtl_0 [create_bd_cell -type module -reference pitch_rtl_top pitch_rtl_0]
set axis_mon_w_0 [create_bd_cell -type module -reference axis_mon_w axis_mon_w_0]

# RX-clock -> PL-clock FIFOs for the three record streams
foreach {name bytes} {cmd_cdc 128 dbg_cdc 8 mdbg_cdc 8} {
  set f [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo:2.0 $name]
  set_property -dict [list \
    CONFIG.TDATA_NUM_BYTES $bytes \
    CONFIG.FIFO_DEPTH {16} \
    CONFIG.IS_ACLK_ASYNC {1} \
    CONFIG.HAS_TLAST {1} \
    CONFIG.HAS_TKEEP {0} \
  ] $f
}
# the CMD record is one 1024-bit beat now
set_property CONFIG.S_TDATA_NUM_BYTES {128} [get_bd_cells axis_dw_cmd]

# clocks and resets
connect_bd_net -net S02_ACLK_1 [get_bd_pins pitch_rtl_0/rx_clk] [get_bd_pins axis_mon_w_0/rx_clk] \
  [get_bd_pins cmd_cdc/s_axis_aclk] [get_bd_pins dbg_cdc/s_axis_aclk] [get_bd_pins mdbg_cdc/s_axis_aclk]
connect_bd_net -net S02_ARESETN_1 [get_bd_pins pitch_rtl_0/rx_aresetn] [get_bd_pins axis_mon_w_0/rx_aresetn] \
  [get_bd_pins cmd_cdc/s_axis_aresetn] [get_bd_pins dbg_cdc/s_axis_aresetn] [get_bd_pins mdbg_cdc/s_axis_aresetn]
connect_bd_net -net zynq_ultra_ps_e_0_pl_clk0 [get_bd_pins axis_mon_w_0/clk] \
  [get_bd_pins cmd_cdc/m_axis_aclk] [get_bd_pins dbg_cdc/m_axis_aclk] [get_bd_pins mdbg_cdc/m_axis_aclk]
connect_bd_net -net proc_sys_reset_0_peripheral_aresetn [get_bd_pins axis_mon_w_0/aresetn]

# 10G input stream (xgmii2axis lv_ port) -> parser + monitor frame counters
connect_bd_net -net xgmii2axis_0_lv_TDATA  [get_bd_pins pitch_rtl_0/lv_data]
connect_bd_net -net xgmii2axis_0_lv_TKEEP  [get_bd_pins pitch_rtl_0/lv_keep]
connect_bd_net -net xgmii2axis_0_lv_TVALID [get_bd_pins pitch_rtl_0/lv_valid] [get_bd_pins axis_mon_w_0/rx_valid]
connect_bd_net -net xgmii2axis_0_lv_TLAST  [get_bd_pins pitch_rtl_0/lv_last]  [get_bd_pins axis_mon_w_0/rx_last]
connect_bd_net -net xgmii2axis_0_lv_TUSER  [get_bd_pins pitch_rtl_0/lv_user]  [get_bd_pins axis_mon_w_0/rx_user]

# control
connect_bd_net [get_bd_pins axi_gpio_1/gpio_io_o]   [get_bd_pins pitch_rtl_0/ip_reset]
connect_bd_net [get_bd_pins axi_gpio_mon/gpio_io_o] [get_bd_pins axis_mon_w_0/ctrl]
connect_bd_net [get_bd_pins axis_mon_w_0/status]    [get_bd_pins axi_gpio_mon/gpio2_io_i]
connect_bd_net [get_bd_pins pitch_rtl_0/stats]      [get_bd_pins axis_mon_w_0/stats]

# CMD: parser -> monitor (sink) -> async FIFO -> 1024->32 -> axi_fifo_cmd
connect_bd_net [get_bd_pins pitch_rtl_0/cmd_data]     [get_bd_pins axis_mon_w_0/cmd_i_data]
connect_bd_net [get_bd_pins pitch_rtl_0/cmd_valid]    [get_bd_pins axis_mon_w_0/cmd_i_valid]
connect_bd_net [get_bd_pins pitch_rtl_0/cmd_ready]    [get_bd_pins axis_mon_w_0/cmd_i_ready]
connect_bd_net [get_bd_pins axis_mon_w_0/cmd_o_data]  [get_bd_pins cmd_cdc/s_axis_tdata]
connect_bd_net [get_bd_pins axis_mon_w_0/cmd_o_valid] [get_bd_pins cmd_cdc/s_axis_tvalid]
connect_bd_net [get_bd_pins axis_mon_w_0/cmd_o_ready] [get_bd_pins cmd_cdc/s_axis_tready]
connect_bd_net [get_bd_pins pitch_rtl_0/cmd_last]     [get_bd_pins cmd_cdc/s_axis_tlast]
connect_bd_intf_net [get_bd_intf_pins cmd_cdc/M_AXIS] [get_bd_intf_pins axis_dw_cmd/S_AXIS]

# DEBUG / MDEBUG: parser -> async FIFO -> existing 64->32 converters -> capture FIFOs
foreach {pfx fifo dw} {dbg dbg_cdc axis_dw_debug mdbg mdbg_cdc axis_dw_mdebug} {
  connect_bd_net [get_bd_pins pitch_rtl_0/${pfx}_data]  [get_bd_pins $fifo/s_axis_tdata]
  connect_bd_net [get_bd_pins pitch_rtl_0/${pfx}_valid] [get_bd_pins $fifo/s_axis_tvalid]
  connect_bd_net [get_bd_pins pitch_rtl_0/${pfx}_ready] [get_bd_pins $fifo/s_axis_tready]
  connect_bd_net [get_bd_pins pitch_rtl_0/${pfx}_last]  [get_bd_pins $fifo/s_axis_tlast]
  connect_bd_intf_net [get_bd_intf_pins $fifo/M_AXIS] [get_bd_intf_pins $dw/S_AXIS]
}

regenerate_bd_layout
validate_bd_design
save_bd_design
close_bd_design kr260_starter_kit

# the LabVIEW netlist and its monitor are not part of this bitstream
foreach f {NiFpgaAG_poc_ip_kria.v NiFpgaIPWrapper_poc_ip_kria.vhd axis_mon.v} {
  set o [get_files -quiet "*$f"]
  if {$o ne ""} { remove_files $o }
}
update_compile_order -fileset sources_1
puts "INFO: mktdata_rtl project created in [get_property DIRECTORY [current_project]]"
