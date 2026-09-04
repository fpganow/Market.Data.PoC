# (C) Copyright 2020 - 2021 Xilinx, Inc.
# SPDX-License-Identifier: Apache-2.0

set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]

#Fan Speed Enable
set_property PACKAGE_PIN A12 [get_ports {fan_en_b}]
set_property IOSTANDARD LVCMOS33 [get_ports {fan_en_b}]
set_property SLEW SLOW [get_ports {fan_en_b}]
set_property DRIVE 4 [get_ports {fan_en_b}]

# GTH pins
set_property PACKAGE_PIN Y6 [get_ports gt_ref_clk_clk_p]
set_property PACKAGE_PIN T2 [get_ports gt_rtl_grx_p]
set_property PACKAGE_PIN R4 [get_ports gt_rtl_gtx_p]

# sfp pins
set_property IOSTANDARD LVCMOS33 [get_ports {sfp_tx_dis[0]}]
set_property PACKAGE_PIN Y10 [get_ports {sfp_tx_dis[0]}]
set_property IOSTANDARD LVCMOS18 [get_ports {sfp_led_tri_o[0]}]
set_property PACKAGE_PIN G8 [get_ports {sfp_led_tri_o[0]}]
set_property IOSTANDARD LVCMOS18 [get_ports {sfp_led_tri_o[1]}]
set_property PACKAGE_PIN F7 [get_ports {sfp_led_tri_o[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {sfp_iic_scl_io}]
set_property PACKAGE_PIN AB11 [get_ports {sfp_iic_scl_io}]
set_property IOSTANDARD LVCMOS33 [get_ports {sfp_iic_sda_io}]
set_property PACKAGE_PIN AC11 [get_ports {sfp_iic_sda_io}]

# timing contraints
set_false_path -to [get_ports {sfp_iic_scl_io*}]
set_false_path -to [get_ports {sfp_iic_sda_io*}]
set_false_path -from [get_ports {sfp_iic_scl_io*}]
set_false_path -from [get_ports {sfp_iic_sda_io*}]

set_false_path -to [get_ports {sfp_led_tri_o*}]
