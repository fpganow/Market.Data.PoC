//Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
//Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
//--------------------------------------------------------------------------------
//Tool Version: Vivado v.2024.1 (win64) Build 5076996 Wed May 22 18:37:14 MDT 2024
//Date        : Thu Jul 31 16:06:21 2025
//Host        : Ryzen10 running 64-bit major release  (build 9200)
//Command     : generate_target design_1_wrapper.bd
//Design      : design_1_wrapper
//Purpose     : IP block netlist
//--------------------------------------------------------------------------------
`timescale 1 ps / 1 ps

module design_1_wrapper
   (fan_en_b,
    gt_ref_clk_clk_n,
    gt_ref_clk_clk_p,
    gt_rtl_grx_n,
    gt_rtl_grx_p,
    gt_rtl_gtx_n,
    gt_rtl_gtx_p,
    sfp_iic_scl_io,
    sfp_iic_sda_io,
    sfp_led_tri_o,
    sfp_tx_dis);
  output [0:0]fan_en_b;
  input gt_ref_clk_clk_n;
  input gt_ref_clk_clk_p;
  input [0:0]gt_rtl_grx_n;
  input [0:0]gt_rtl_grx_p;
  output [0:0]gt_rtl_gtx_n;
  output [0:0]gt_rtl_gtx_p;
  inout sfp_iic_scl_io;
  inout sfp_iic_sda_io;
  output [1:0]sfp_led_tri_o;
  output [0:0]sfp_tx_dis;

  wire [0:0]fan_en_b;
  wire gt_ref_clk_clk_n;
  wire gt_ref_clk_clk_p;
  wire [0:0]gt_rtl_grx_n;
  wire [0:0]gt_rtl_grx_p;
  wire [0:0]gt_rtl_gtx_n;
  wire [0:0]gt_rtl_gtx_p;
  wire sfp_iic_scl_i;
  wire sfp_iic_scl_io;
  wire sfp_iic_scl_o;
  wire sfp_iic_scl_t;
  wire sfp_iic_sda_i;
  wire sfp_iic_sda_io;
  wire sfp_iic_sda_o;
  wire sfp_iic_sda_t;
  wire [1:0]sfp_led_tri_o;
  wire [0:0]sfp_tx_dis;

  design_1 design_1_i
       (.fan_en_b(fan_en_b),
        .gt_ref_clk_clk_n(gt_ref_clk_clk_n),
        .gt_ref_clk_clk_p(gt_ref_clk_clk_p),
        .gt_rtl_grx_n(gt_rtl_grx_n),
        .gt_rtl_grx_p(gt_rtl_grx_p),
        .gt_rtl_gtx_n(gt_rtl_gtx_n),
        .gt_rtl_gtx_p(gt_rtl_gtx_p),
        .sfp_iic_scl_i(sfp_iic_scl_i),
        .sfp_iic_scl_o(sfp_iic_scl_o),
        .sfp_iic_scl_t(sfp_iic_scl_t),
        .sfp_iic_sda_i(sfp_iic_sda_i),
        .sfp_iic_sda_o(sfp_iic_sda_o),
        .sfp_iic_sda_t(sfp_iic_sda_t),
        .sfp_led_tri_o(sfp_led_tri_o),
        .sfp_tx_dis(sfp_tx_dis));
  IOBUF sfp_iic_scl_iobuf
       (.I(sfp_iic_scl_o),
        .IO(sfp_iic_scl_io),
        .O(sfp_iic_scl_i),
        .T(sfp_iic_scl_t));
  IOBUF sfp_iic_sda_iobuf
       (.I(sfp_iic_sda_o),
        .IO(sfp_iic_sda_io),
        .O(sfp_iic_sda_i),
        .T(sfp_iic_sda_t));
endmodule
