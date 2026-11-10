`timescale 1ns / 1ps
// axis_mon_w -- the axis_mon counters (vivado/ip/axis_mon.v) for the pure-RTL
// parser, whose CMD record is one 1024-bit beat in the 156.25 MHz RX domain.
// Same ctrl/status protocol and the same `sel` map 0..16 as MON2, so poc_mon
// and scripts/rate_sweep.py --sink work unchanged; id reads "MON3", and
// sel 17.. add the RTL parser's own statistics:
//
//   ctrl (ch1): bit0 sink, bit1 clear (edge), bit2 snap (edge), bits 12:8 sel
//   sel  0 records       CMD records accepted from the parser
//        1 beats         == records (single-beat records)
//        2 stall_cycles  parser TVALID high while TREADY low
//        3 seq_gaps      sum of (seq[n]-seq[n-1]-1), seq = word 12 (parser counter)
//        4 bad_len       messages with a length byte outside 2..48 (frame rest skipped)
//        5 lat_max       max(word 14 - word 13), 10 ns ticks, signed
//        6 unsupported   records with type enum 11
//        7 bad_magic     records whose word 15 low half != 0xDEADBEEF
//        8 fwd_records   records forwarded downstream (== records unless sink)
//        9 rx_frames     frames on the lv_ stream (TVALID & TLAST)
//       10 rx_bad        of those, TUSER[0] low (FCS error)
//       11 rx_beats      64-bit beats on the lv_ stream
//       12 first_seq    13 last_seq    14 flags (bit0 snapshot pending)
//       15 id 0x4D4F4E33 ("MON3")      16 lat_min (signed)
//       17 frames_pass      frames accepted by the UDP filter
//       18 frames_filtered  frames rejected (MAC / EtherType / IP / port)
//       19 frames_trunc     accepted frames shorter than their IP length, or bad FCS
//       20 frames_dropped   frames dropped because the word FIFO was full
//       21 hdr_records      Sequenced Unit Headers parsed
//       22 msg_trunc        messages cut by the end of a frame
//       23 dbg_dropped      DEBUG + MDEBUG records dropped (stream busy)
//       24 pitch_seq_gaps   sum of gaps in the PITCH sequence (word 11 [63:32]), per unit ignored
//
// All counters live in rx_clk. The GPIO side (pl_clk0) reaches them through
// toggle synchronisers: clear/snap requests go over, and `status` is refreshed
// by a free-running request/acknowledge ping-pong that samples the selected
// snapshot register only while it is stable. Bounded by the set_max_delay
// -datapath_only pair in constraints.xdc (clk_pl_0 <-> S02_ACLK_1).

module axis_mon_w (
    // ---- pl_clk0 (100 MHz) ----
    input  wire          clk,
    input  wire          aresetn,
    input  wire [31:0]   ctrl,
    output reg  [31:0]   status,
    // ---- rx_clk (156.25 MHz) ----
    input  wire          rx_clk,
    input  wire          rx_aresetn,
    input  wire [1023:0] cmd_i_data,
    input  wire          cmd_i_valid,
    output wire          cmd_i_ready,
    output wire [1023:0] cmd_o_data,
    output wire          cmd_o_valid,
    input  wire          cmd_o_ready,
    input  wire          rx_valid,
    input  wire          rx_last,
    input  wire [0:0]    rx_user,
    input  wire [15:0]   stats
);
    localparam NREG = 25;

    // ------------------------------------------------------------------
    // ctrl into the rx domain
    // ------------------------------------------------------------------
    reg [2:0] ctrl_d;
    always @(posedge clk) ctrl_d <= aresetn ? ctrl[2:0] : 3'b000;
    wire clr_pulse  = ctrl[1] & ~ctrl_d[1];
    wire snap_pulse = ctrl[2] & ~ctrl_d[2];
    reg clr_tgl, snap_tgl;
    always @(posedge clk) begin
        if (!aresetn) begin clr_tgl <= 1'b0; snap_tgl <= 1'b0; end
        else begin
            if (clr_pulse)  clr_tgl  <= ~clr_tgl;
            if (snap_pulse) snap_tgl <= ~snap_tgl;
        end
    end
    wire sink_r; wire [4:0] sel_r; wire clr_r, snap_r;
    sync2 #(.W(1)) u_s0 (.clk(rx_clk), .d(ctrl[0]),    .q(sink_r));
    sync2 #(.W(5)) u_s1 (.clk(rx_clk), .d(ctrl[12:8]), .q(sel_r));
    sync2 #(.W(1)) u_s2 (.clk(rx_clk), .d(clr_tgl),    .q(clr_r));
    sync2 #(.W(1)) u_s3 (.clk(rx_clk), .d(snap_tgl),   .q(snap_r));
    reg clr_r_d, snap_r_d;
    always @(posedge rx_clk) begin clr_r_d <= clr_r; snap_r_d <= snap_r; end
    wire clr_rx  = clr_r ^ clr_r_d;
    wire snap_rx = snap_r ^ snap_r_d;

    // ------------------------------------------------------------------
    // pass-through / sink (rx domain)
    // ------------------------------------------------------------------
    assign cmd_i_ready = sink_r ? 1'b1 : cmd_o_ready;
    assign cmd_o_valid = sink_r ? 1'b0 : cmd_i_valid;
    assign cmd_o_data  = cmd_i_data;
    wire hs  = cmd_i_valid & cmd_i_ready;
    wire fwd = cmd_o_valid & cmd_o_ready;

    // ------------------------------------------------------------------
    // counters
    // ------------------------------------------------------------------
    reg [31:0] c [0:NREG-1];
    reg        have_seq, first_done, have_pseq;
    wire [31:0] seq_w  = cmd_i_data[12*64 +: 32];
    wire [31:0] pseq_w = cmd_i_data[11*64+32 +: 32];
    wire [31:0] lat_w  = cmd_i_data[14*64 +: 32] - cmd_i_data[13*64 +: 32];
    wire [31:0] gap_w  = seq_w - c[13] - 32'd1;
    reg  [31:0] last_pseq;
    wire [31:0] pgap    = pseq_w - last_pseq - 32'd1;

    integer i;
    always @(posedge rx_clk) begin
        if (!rx_aresetn || clr_rx) begin
            for (i = 0; i < NREG; i = i + 1) c[i] <= 0;
            c[5] <= 32'h80000000; c[16] <= 32'h7FFFFFFF;
            have_seq <= 1'b0; first_done <= 1'b0; have_pseq <= 1'b0; last_pseq <= 0;
        end else begin
            if (cmd_i_valid & ~cmd_i_ready) c[2] <= c[2] + 1;
            if (fwd)                        c[8] <= c[8] + 1;
            if (hs) begin
                c[0] <= c[0] + 1; c[1] <= c[1] + 1;
                if (cmd_i_data[7:0] == 8'd11)               c[6] <= c[6] + 1;
                if (cmd_i_data[15*64 +: 32] != 32'hDEADBEEF) c[7] <= c[7] + 1;
                if (have_seq && seq_w != c[13] + 32'd1)     c[3] <= c[3] + gap_w;
                if (!first_done) begin c[12] <= seq_w; first_done <= 1'b1; end
                c[13] <= seq_w; have_seq <= 1'b1;
                if ($signed(lat_w) > $signed(c[5]))  c[5]  <= lat_w;
                if ($signed(lat_w) < $signed(c[16])) c[16] <= lat_w;
                if (have_pseq && pseq_w != last_pseq + 32'd1) c[24] <= c[24] + pgap;
                last_pseq <= pseq_w; have_pseq <= 1'b1;
            end
            if (rx_valid)                         c[11] <= c[11] + 1;
            if (rx_valid & rx_last)               c[9]  <= c[9] + 1;
            if (rx_valid & rx_last & ~rx_user[0]) c[10] <= c[10] + 1;
            if (stats[0]) c[17] <= c[17] + 1;
            if (stats[1]) c[18] <= c[18] + 1;
            if (stats[2]) c[19] <= c[19] + 1;
            if (stats[3]) c[20] <= c[20] + 1;
            if (stats[4]) c[21] <= c[21] + 1;
            if (stats[5]) c[4]  <= c[4] + 1;
            if (stats[6]) c[22] <= c[22] + 1;
            if (stats[7] | stats[8]) c[23] <= c[23] + 1;
        end
    end

    // ------------------------------------------------------------------
    // snapshot (rx) and status transfer to clk
    // ------------------------------------------------------------------
    reg [31:0] s [0:NREG-1];
    reg        snap_ack;                  // toggles when a snapshot has been taken
    always @(posedge rx_clk) begin
        if (!rx_aresetn) begin
            for (i = 0; i < NREG; i = i + 1) s[i] <= 0;
            snap_ack <= 1'b0;
        end else if (snap_rx) begin
            for (i = 0; i < NREG; i = i + 1) s[i] <= c[i];
            snap_ack <= ~snap_ack;
        end
    end

    // ping-pong: clk toggles req; rx answers with the selected value + ack toggle
    reg  req_tgl;
    wire req_r; wire ack_c; wire snap_ack_c;
    sync2 #(.W(1)) u_s4 (.clk(rx_clk), .d(req_tgl),  .q(req_r));
    reg  req_r_d, ack_tgl;
    reg  [31:0] status_hold;
    always @(posedge rx_clk) begin
        if (!rx_aresetn) begin req_r_d <= 1'b0; ack_tgl <= 1'b0; status_hold <= 0; end
        else begin
            req_r_d <= req_r;
            if (req_r ^ req_r_d) begin
                case (sel_r)
                    5'd14:   status_hold <= {31'd0, 1'b0};             // pending bit is added on the clk side
                    5'd15:   status_hold <= 32'h4D4F4E33;
                    default: status_hold <= (sel_r < NREG) ? s[sel_r] : 32'hFFFFFFFF;
                endcase
                ack_tgl <= ~ack_tgl;
            end
        end
    end
    sync2 #(.W(1)) u_s5 (.clk(clk), .d(ack_tgl),  .q(ack_c));
    sync2 #(.W(1)) u_s6 (.clk(clk), .d(snap_ack), .q(snap_ack_c));
    reg ack_c_d, snap_seen;
    reg [31:0] status_c;
    // req_tgl == ack_c means "no request outstanding": capture the answer (stable, rx only
    // rewrites status_hold after it sees the next req) and send the next request. The clk
    // side initiates, so the loop runs from reset without waiting for anything.
    reg got_first;
    always @(posedge clk) begin
        if (!aresetn) begin
            req_tgl <= 1'b0; ack_c_d <= 1'b0; status_c <= 0; snap_seen <= 1'b0; status <= 0; got_first <= 1'b0;
        end else begin
            ack_c_d <= ack_c;
            if (req_tgl == ack_c) begin
                if (got_first) status_c <= status_hold;
                got_first <= 1'b1;
                req_tgl  <= ~req_tgl;
            end
            snap_seen <= snap_ack_c;
            status <= (ctrl[12:8] == 5'd14) ? {31'd0, (snap_tgl != snap_seen)} : status_c;
        end
    end

endmodule
