`timescale 1ns / 1ps
// pitch_rtl_top -- the pure-RTL replacement for NiFpgaIPWrapper_poc_0 in the
// KR260 block design (vivado_rtl/mktdata_rtl.tcl). Everything runs in the
// 156.25 MHz 10G receive clock: filter -> word FIFO -> message extractor ->
// field decoder -> one 1024-bit CMD beat per message. No LabVIEW, no 100 MHz
// parser loop, no 16-beat record serialisation (the two limits measured on
// 2026-11-08, see optimize.txt).
//
// Streams (all rx_clk):
//   lv_*      xgmii2axis output (TVALID-only, FCS stripped, TUSER[0] = good)
//   cmd_*     16 x U64 record per beat, TLAST always 1; back-pressure honoured
//   dbg_*     4 x U64 DEBUG records, LabVIEW-compatible markers:
//             [0xAAAB,0,1,2] on ip_reset, [0xDE<<32|len, len, SUH bytes MSB-first, 0]
//             per Sequenced Unit Header. Dropped (counted) when the stream is busy.
//   mdbg_*    4 x U64 per message: [parse.time, length, type, PITCH seq]. Dropped when busy.
//   ip_reset  level from axi_gpio_1 (PL 100 MHz domain), synchronised here;
//             restarts the record seq counter and emits the DEBUG reset record.
//   stats[]   one-cycle pulses for axis_mon_w:
//             0 frame_pass  1 frame_filtered  2 frame_trunc  3 frame_drop_full
//             4 hdr         5 bad_len         6 msg_trunc    7 dbg_drop
//             8 mdbg_drop   9 frame_crc_bad
//   time10    free-running 10 ns tick counter (6.4 ns clock, fractional
//             accumulator), so recv/parse times keep the LabVIEW unit.

module pitch_rtl_top #(
    parameter [47:0] DST_MAC        = 48'h000a35183c1f,
    parameter        ACCEPT_MCAST   = 1,
    parameter        ACCEPT_ANY_MAC = 0,
    parameter [31:0] DST_IP         = 32'h0,
    parameter [15:0] UDP_PORT       = 16'd8000,
    parameter        SHORT_SCALE    = 100,
    parameter        FIFO_LOG2      = 6
) (
    input  wire          rx_clk,
    input  wire          rx_aresetn,
    input  wire          ip_reset,
    // xgmii2axis lv_ stream
    input  wire [63:0]   lv_data,
    input  wire [7:0]    lv_keep,
    input  wire          lv_valid,
    input  wire          lv_last,
    input  wire [0:0]    lv_user,
    // CMD records
    output wire [1023:0] cmd_data,
    output wire          cmd_valid,
    output wire          cmd_last,
    input  wire          cmd_ready,
    // DEBUG / MDEBUG traces
    output wire [63:0]   dbg_data,
    output wire          dbg_valid,
    output wire          dbg_last,
    input  wire          dbg_ready,
    output wire [63:0]   mdbg_data,
    output wire          mdbg_valid,
    output wire          mdbg_last,
    input  wire          mdbg_ready,
    // statistics
    output wire [15:0]   stats,
    output wire [31:0]   time10_out
);
    localparam MAXB = 48;

    // ------------------------------------------------------------------
    // 10 ns tick counter from the 6.4 ns clock (64/100 per cycle)
    // ------------------------------------------------------------------
    reg [31:0] time10;
    reg [6:0]  frac;                       // tenths of ns, 0..99
    wire [7:0] fsum = {1'b0, frac} + 8'd64;
    always @(posedge rx_clk) begin
        if (!rx_aresetn) begin time10 <= 0; frac <= 0; end
        else if (fsum >= 8'd100) begin frac <= fsum[6:0] - 7'd100; time10 <= time10 + 1; end
        else frac <= fsum[6:0];
    end
    assign time10_out = time10;

    // ------------------------------------------------------------------
    // ip_reset: level from the PL clock domain -> pulse here
    // ------------------------------------------------------------------
    wire ipr_s;
    sync2 u_ipr (.clk(rx_clk), .d(ip_reset), .q(ipr_s));
    reg ipr_d;
    always @(posedge rx_clk) ipr_d <= rx_aresetn ? ipr_s : 1'b0;
    wire ipr_rise = ipr_s & ~ipr_d;

    // ------------------------------------------------------------------
    // filter -> word FIFO
    // ------------------------------------------------------------------
    wire [63:0] f_data; wire [3:0] f_nb; wire f_valid, f_sof, f_eof, f_bad; wire [7:0] f_fits;
    wire st_frame, st_crc_bad, st_pass, st_filt, st_ftrunc;

    eth_rx_filter #(
        .DST_MAC(DST_MAC), .ACCEPT_MCAST(ACCEPT_MCAST), .ACCEPT_ANY_MAC(ACCEPT_ANY_MAC),
        .DST_IP(DST_IP), .UDP_PORT(UDP_PORT)
    ) u_filter (
        .clk(rx_clk), .rst_n(rx_aresetn),
        .s_tdata(lv_data), .s_tkeep(lv_keep), .s_tvalid(lv_valid), .s_tlast(lv_last), .s_tuser(lv_user[0]),
        .m_tdata(f_data), .m_nbytes(f_nb), .m_tvalid(f_valid), .m_sof(f_sof), .m_eof(f_eof), .m_bad(f_bad), .m_fits(f_fits),
        .st_frame(st_frame), .st_frame_crc_bad(st_crc_bad), .st_frame_pass(st_pass),
        .st_frame_filtered(st_filt), .st_frame_trunc(st_ftrunc)
    );

    // drop whole frames when the FIFO is full (never stall the MAC)
    wire fifo_full;
    reg  dropping;
    wire drop_now = f_valid & (f_sof ? fifo_full : (fifo_full | dropping));
    wire st_drop  = f_valid & fifo_full & ~dropping;
    always @(posedge rx_clk) begin
        if (!rx_aresetn) dropping <= 1'b0;
        else if (f_valid) begin
            if (f_sof) dropping <= fifo_full;
            else if (fifo_full) dropping <= 1'b1;
            if (f_eof) dropping <= 1'b0;
        end
    end

    wire [78:0] w_q; wire w_valid, w_rd;
    fwft_fifo #(.W(79), .D_LOG2(FIFO_LOG2)) u_fifo (
        .clk(rx_clk), .rst_n(rx_aresetn),
        .wr_en(f_valid & ~drop_now), .wr_data({f_fits, f_bad, f_eof, f_sof, f_nb, f_data}), .full(fifo_full),
        .rd_en(w_rd), .rd_data(w_q), .rd_valid(w_valid)
    );

    // ------------------------------------------------------------------
    // extractor -> decoder -> output register (rigid 2-stage pipeline)
    // ------------------------------------------------------------------
    wire r_valid; wire [1023:0] r_data;
    wire en = ~r_valid | cmd_ready;

    wire m_valid; wire [8*MAXB-1:0] m_bytes; wire [7:0] m_len, m_unit; wire [31:0] m_seq, m_recv;
    wire h_valid; wire [63:0] h_bytes; wire [31:0] h_recv;
    wire st_trunc, st_bad_len, st_fbad;

    pitch_extract #(.MAXB(MAXB)) u_ext (
        .clk(rx_clk), .rst_n(rx_aresetn), .en(en),
        .w_data(w_q[63:0]), .w_nbytes(w_q[67:64]), .w_sof(w_q[68]), .w_eof(w_q[69]), .w_bad(w_q[70]), .w_fits(w_q[78:71]),
        .w_valid(w_valid), .w_rd(w_rd), .time10(time10),
        .m_valid(m_valid), .m_bytes(m_bytes), .m_len(m_len), .m_seq(m_seq), .m_unit(m_unit), .m_recv_time(m_recv),
        .h_valid(h_valid), .h_bytes(h_bytes), .h_recv_time(h_recv),
        .st_trunc(st_trunc), .st_bad_len(st_bad_len), .st_frame_bad(st_fbad)
    );

    wire [31:0] seq_counter;
    pitch_decode #(.MAXB(MAXB), .SHORT_SCALE(SHORT_SCALE)) u_dec (
        .clk(rx_clk), .rst_n(rx_aresetn), .en(en), .ip_reset(ipr_rise),
        .m_valid(m_valid), .m_bytes(m_bytes), .m_len(m_len), .m_seq(m_seq), .m_unit(m_unit), .m_recv_time(m_recv),
        .time10(time10), .r_valid(r_valid), .r_data(r_data), .seq_counter(seq_counter)
    );

    assign cmd_data  = r_data;
    assign cmd_valid = r_valid;
    assign cmd_last  = 1'b1;

    // ------------------------------------------------------------------
    // DEBUG: reset record + one header record per frame
    // ------------------------------------------------------------------
    wire [63:0] suh_be = {h_bytes[7:0], h_bytes[15:8], h_bytes[23:16], h_bytes[31:24],
                          h_bytes[39:32], h_bytes[47:40], h_bytes[55:48], h_bytes[63:56]};   // bytes MSB-first
    wire [15:0] suh_len = h_bytes[15:0];
    wire [255:0] dbg_rec = ipr_rise ? {64'd2, 64'd1, 64'd0, 64'h000000000000AAAB}
                                    : {64'd0, suh_be, {48'd0, suh_len}, {24'd0, 8'hDE, 16'd0, suh_len}};
    wire dbg_drop;
    dbg_writer u_dbg (
        .clk(rx_clk), .rst_n(rx_aresetn), .push(ipr_rise | (h_valid & en)), .rec(dbg_rec), .dropped(dbg_drop),
        .m_tdata(dbg_data), .m_tvalid(dbg_valid), .m_tlast(dbg_last), .m_tready(dbg_ready)
    );

    // MDEBUG: one record per message as it is emitted downstream
    wire mdbg_drop;
    wire cmd_hs = r_valid & cmd_ready;
    dbg_writer u_mdbg (
        .clk(rx_clk), .rst_n(rx_aresetn), .push(cmd_hs),
        .rec({{32'd0, r_data[11*64+32 +: 32]}, {56'd0, r_data[11*64+8 +: 8]}, {56'd0, r_data[11*64+16 +: 8]}, {32'd0, r_data[14*64 +: 32]}}),
        .dropped(mdbg_drop),
        .m_tdata(mdbg_data), .m_tvalid(mdbg_valid), .m_tlast(mdbg_last), .m_tready(mdbg_ready)
    );

    // ------------------------------------------------------------------
    // statistics pulses
    // ------------------------------------------------------------------
    assign stats = {6'd0, st_crc_bad, mdbg_drop, dbg_drop, st_trunc & en, st_bad_len & en, h_valid & en,
                    st_drop, st_fbad & en, st_filt, st_pass};

endmodule
