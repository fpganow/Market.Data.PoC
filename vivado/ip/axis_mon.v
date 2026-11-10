`timescale 1ns / 1ps
// axis_mon -- in-fabric counters for the NI IP's CMD output stream and its
// 10G input stream, so the parser can be measured without moving every record
// through the PS (the AXI-Lite readout tops out near 8k records/s, see
// CLAUDE.md 2026-11-06). Sits between NiFpgaIPWrapper_poc_0 (CMD) and
// axis_dw_cmd as a zero-latency pass-through; read/controlled by one dual
// channel AXI GPIO (axi_gpio_mon, 0x80120000: ch1 = ctrl out, ch2 = status in).
//
// ctrl (ch1, written by the PS)
//   bit 0      sink      1 = assert TREADY to the NI IP and drop the records
//                        (the capture FIFO sees nothing). Switch only while idle.
//   bit 1      clear     rising edge clears every counter (both clock domains)
//   bit 2      snap      rising edge copies every counter into the snapshot
//                        registers that `status` reads; the RX-domain ones
//                        arrive a few cycles later (poll sel 14 until bit0 = 0)
//   bits 12:8  sel       which snapshot value `status` (ch2) shows:
//      0 records       CMD records accepted from the NI IP (TLAST handshakes)
//      1 beats         CMD 64-bit beats accepted
//      2 stall_cycles  cycles with CMD TVALID high and TREADY low (back-pressure)
//      3 seq_gaps      sum of (seq[n] - seq[n-1] - 1) over consecutive records, seq = word 12
//      4 bad_len       records not 16 beats long
//      5 lat_max       max (word 14 - word 13), 10 ns ticks (parse.time - recv.time), signed:
//                      the parser stamps parse.time 1-5 ticks BEFORE recv.time when it is
//                      not back-pressured, so an unsigned max would read 0xFFFFFFFx
//      6 unsupported   records whose word 0 (type enum) == 11
//      7 bad_magic     records whose word 15 low half != 0xDEADBEEF
//      8 fwd_records   records actually forwarded downstream (== records unless sink)
//      9 rx_frames     frames presented to the NI IP (TVALID & TLAST on the lv_ stream)
//     10 rx_bad        of those, flagged bad by the MAC (TUSER[0] low at TLAST)
//     11 rx_beats      64-bit beats presented to the NI IP (x8 ~ bytes)
//     12 first_seq     seq of the first record after clear
//     13 last_seq      seq of the most recent record
//     14 flags         bit0 = snapshot still pending (RX-domain copy in flight)
//     15 id            0x4D4F4E32 ("MON2"; MON1 had an unsigned lat_max and no lat_min)
//     16 lat_min       min (word 14 - word 13), signed 32-bit two's complement
//
// Counters are 32 bits and wrap; clear before every measurement. The CMD side
// runs on the 100 MHz PL clock with the GPIO, so no crossing there. The RX
// side runs on the 156.25 MHz 10G receive clock; clear/snap reach it through
// toggle synchronizers and the snapshot comes back on a second toggle, with
// the data held stable until the toggle is seen (bounded by the existing
// set_max_delay -datapath_only constraints between clk_pl_0 and S02_ACLK_1).

module axis_mon (
    // ---- 100 MHz PL clock domain (pl_clk0) ----
    input  wire        clk,
    input  wire        aresetn,
    // CMD stream from the NI IP
    input  wire [63:0] cmd_i_data,
    input  wire        cmd_i_valid,
    input  wire        cmd_i_last,
    output wire        cmd_i_ready,
    // CMD stream to axis_dw_cmd / axi_fifo_cmd
    output wire [63:0] cmd_o_data,
    output wire        cmd_o_valid,
    output wire        cmd_o_last,
    input  wire        cmd_o_ready,
    // AXI GPIO
    input  wire [31:0] ctrl,
    output reg  [31:0] status,
    // ---- 156.25 MHz RX clock domain (xxv rx_clk_out_0) ----
    input  wire        rx_clk,
    input  wire        rx_aresetn,
    input  wire        rx_valid,
    input  wire        rx_last,
    input  wire [0:0]  rx_user
);

    // ------------------------------------------------------------------
    // pass-through / sink
    // ------------------------------------------------------------------
    wire sink = ctrl[0];
    assign cmd_i_ready = sink ? 1'b1 : cmd_o_ready;
    assign cmd_o_valid = sink ? 1'b0 : cmd_i_valid;
    assign cmd_o_data  = cmd_i_data;
    assign cmd_o_last  = cmd_i_last;

    wire hs   = cmd_i_valid & cmd_i_ready;      // beat accepted from the NI IP
    wire fwd  = cmd_o_valid & cmd_o_ready;      // beat accepted downstream

    // ------------------------------------------------------------------
    // control edges
    // ------------------------------------------------------------------
    reg [2:0] ctrl_d;
    always @(posedge clk) ctrl_d <= aresetn ? ctrl[2:0] : 3'b000;
    wire clr_pulse  = ctrl[1] & ~ctrl_d[1];
    wire snap_pulse = ctrl[2] & ~ctrl_d[2];

    // ------------------------------------------------------------------
    // CMD-side counters
    // ------------------------------------------------------------------
    reg [31:0] c_records, c_beats, c_stall, c_seq_gaps, c_bad_len, c_lat_max, c_lat_min,
               c_unsupp, c_bad_magic, c_fwd, c_first_seq, c_last_seq;
    reg [3:0]  beat;              // index of the current beat within the record
    reg        have_seq;          // c_last_seq is valid (a record was seen since clear)
    reg [31:0] recv_time;         // word 13 of the record in flight
    reg        first_done;

    wire [31:0] seq_w  = cmd_i_data[31:0];
    wire [31:0] lat_w  = cmd_i_data[31:0] - recv_time;
    wire [31:0] gap_w  = seq_w - c_last_seq - 32'd1;

    always @(posedge clk) begin
        if (!aresetn || clr_pulse) begin
            c_records <= 0; c_beats <= 0; c_stall <= 0; c_seq_gaps <= 0; c_bad_len <= 0;
            c_lat_max <= 32'h80000000; c_lat_min <= 32'h7FFFFFFF;   // signed -2^31 / +2^31-1
            c_unsupp <= 0; c_bad_magic <= 0; c_fwd <= 0;
            c_first_seq <= 0; c_last_seq <= 0; have_seq <= 1'b0; first_done <= 1'b0;
            beat <= 4'd0; recv_time <= 0;
        end else begin
            if (cmd_i_valid & ~cmd_i_ready) c_stall <= c_stall + 1;
            if (fwd & cmd_o_last)           c_fwd   <= c_fwd + 1;
            if (hs) begin
                c_beats <= c_beats + 1;
                case (beat)
                    4'd0:  if (cmd_i_data[7:0] == 8'd11) c_unsupp <= c_unsupp + 1;
                    4'd12: begin
                        if (have_seq && seq_w != c_last_seq + 32'd1) c_seq_gaps <= c_seq_gaps + gap_w;
                        if (!first_done) begin c_first_seq <= seq_w; first_done <= 1'b1; end
                        c_last_seq <= seq_w; have_seq <= 1'b1;
                    end
                    4'd13: recv_time <= cmd_i_data[31:0];
                    4'd14: begin
                        if ($signed(lat_w) > $signed(c_lat_max)) c_lat_max <= lat_w;
                        if ($signed(lat_w) < $signed(c_lat_min)) c_lat_min <= lat_w;
                    end
                    4'd15: if (cmd_i_data[31:0] != 32'hDEADBEEF) c_bad_magic <= c_bad_magic + 1;
                    default: ;
                endcase
                if (cmd_i_last) begin
                    c_records <= c_records + 1;
                    if (beat != 4'd15) c_bad_len <= c_bad_len + 1;
                    beat <= 4'd0;
                end else begin
                    beat <= beat + 1;     // wraps at 16; a >16-beat record shows as bad_len via the TLAST check
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // RX-side counters (rx_clk) with toggle-synchronized clear / snapshot
    // ------------------------------------------------------------------
    reg clr_tgl, snap_tgl;                  // clk domain request toggles
    always @(posedge clk) begin
        if (!aresetn) begin clr_tgl <= 1'b0; snap_tgl <= 1'b0; end
        else begin
            if (clr_pulse)  clr_tgl  <= ~clr_tgl;
            if (snap_pulse) snap_tgl <= ~snap_tgl;
        end
    end

    (* ASYNC_REG = "TRUE" *) reg [2:0] clr_sync, snap_sync;   // into rx_clk
    reg [31:0] r_frames, r_bad, r_beats;
    reg [31:0] r_frames_sh, r_bad_sh, r_beats_sh;            // rx-domain snapshot, stable until next snap
    reg        ack_tgl;                                        // toggles after the snapshot is written

    always @(posedge rx_clk) begin
        if (!rx_aresetn) begin
            clr_sync <= 3'b000; snap_sync <= 3'b000;
            r_frames <= 0; r_bad <= 0; r_beats <= 0;
            r_frames_sh <= 0; r_bad_sh <= 0; r_beats_sh <= 0; ack_tgl <= 1'b0;
        end else begin
            clr_sync  <= {clr_sync[1:0],  clr_tgl};
            snap_sync <= {snap_sync[1:0], snap_tgl};
            if (clr_sync[2] ^ clr_sync[1]) begin
                r_frames <= 0; r_bad <= 0; r_beats <= 0;
            end else begin
                if (rx_valid)                          r_beats  <= r_beats + 1;
                if (rx_valid & rx_last)                r_frames <= r_frames + 1;
                if (rx_valid & rx_last & ~rx_user[0])  r_bad    <= r_bad + 1;
            end
            if (snap_sync[2] ^ snap_sync[1]) begin
                r_frames_sh <= r_frames; r_bad_sh <= r_bad; r_beats_sh <= r_beats;
                ack_tgl <= ~ack_tgl;                 // one cycle after the shadow regs settle is fine:
            end                                      // the ack still takes >= 2 clk cycles to be seen
        end
    end

    (* ASYNC_REG = "TRUE" *) reg [2:0] ack_sync;    // back into clk
    reg        snap_pending;
    reg [31:0] s_records, s_beats, s_stall, s_seq_gaps, s_bad_len, s_lat_max, s_lat_min,
               s_unsupp, s_bad_magic, s_fwd, s_first_seq, s_last_seq,
               s_rx_frames, s_rx_bad, s_rx_beats;

    always @(posedge clk) begin
        if (!aresetn) begin
            ack_sync <= 3'b000; snap_pending <= 1'b0;
            s_records <= 0; s_beats <= 0; s_stall <= 0; s_seq_gaps <= 0; s_bad_len <= 0;
            s_lat_max <= 0; s_lat_min <= 0; s_unsupp <= 0; s_bad_magic <= 0; s_fwd <= 0;
            s_first_seq <= 0; s_last_seq <= 0; s_rx_frames <= 0; s_rx_bad <= 0; s_rx_beats <= 0;
        end else begin
            ack_sync <= {ack_sync[1:0], ack_tgl};
            if (snap_pulse) begin
                s_records <= c_records; s_beats <= c_beats; s_stall <= c_stall;
                s_seq_gaps <= c_seq_gaps; s_bad_len <= c_bad_len; s_lat_max <= c_lat_max; s_lat_min <= c_lat_min;
                s_unsupp <= c_unsupp; s_bad_magic <= c_bad_magic; s_fwd <= c_fwd;
                s_first_seq <= c_first_seq; s_last_seq <= c_last_seq;
                snap_pending <= 1'b1;
            end
            if (ack_sync[2] ^ ack_sync[1]) begin
                s_rx_frames <= r_frames_sh; s_rx_bad <= r_bad_sh; s_rx_beats <= r_beats_sh;
                snap_pending <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------------
    // status mux
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        case (ctrl[12:8])
            5'd0:  status <= s_records;
            5'd1:  status <= s_beats;
            5'd2:  status <= s_stall;
            5'd3:  status <= s_seq_gaps;
            5'd4:  status <= s_bad_len;
            5'd5:  status <= s_lat_max;
            5'd6:  status <= s_unsupp;
            5'd7:  status <= s_bad_magic;
            5'd8:  status <= s_fwd;
            5'd9:  status <= s_rx_frames;
            5'd10: status <= s_rx_bad;
            5'd11: status <= s_rx_beats;
            5'd12: status <= s_first_seq;
            5'd13: status <= s_last_seq;
            5'd14: status <= {31'd0, snap_pending};
            5'd15: status <= 32'h4D4F4E32;
            5'd16: status <= s_lat_min;
            default: status <= 32'hFFFFFFFF;
        endcase
    end

endmodule
