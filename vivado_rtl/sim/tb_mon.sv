`timescale 1ns / 1ps
// tb_mon -- checks axis_mon_w's two-clock control/status path: id readback,
// counters, clear, snapshot, sink. Prints "name value" like poc_mon.
module tb_mon;
    reg clk = 0;    always #5   clk = ~clk;      // 100 MHz GPIO side
    reg rx_clk = 0; always #3.2 rx_clk = ~rx_clk; // 156.25 MHz
    reg aresetn = 0, rx_aresetn = 0;
    reg  [31:0] ctrl = 0; wire [31:0] status;
    reg  [1023:0] d = 0; reg v = 0; wire rdy; wire [1023:0] od; wire ov; reg ordy = 1;
    reg rx_valid = 0, rx_last = 0; reg [0:0] rx_user = 1; reg [15:0] stats = 0;

    axis_mon_w dut (.clk(clk), .aresetn(aresetn), .ctrl(ctrl), .status(status),
        .rx_clk(rx_clk), .rx_aresetn(rx_aresetn), .cmd_i_data(d), .cmd_i_valid(v), .cmd_i_ready(rdy),
        .cmd_o_data(od), .cmd_o_valid(ov), .cmd_o_ready(ordy),
        .rx_valid(rx_valid), .rx_last(rx_last), .rx_user(rx_user), .stats(stats));

    task wr(input [31:0] c); begin @(posedge clk); ctrl <= c; @(posedge clk); end endtask
    task rd(input [4:0] s, input [127:0] name); begin
        wr((ctrl & ~32'h1F00) | (s << 8)); repeat (12) @(posedge clk);
        $display("%0s %0d (0x%08x)", name, status, status);
    end endtask
    integer i, fwd = 0;
    always @(posedge rx_clk) if (ov & ordy) fwd = fwd + 1;

    initial begin
        repeat (4) @(posedge clk); aresetn <= 1; rx_aresetn <= 1;
        repeat (20) @(posedge clk);
        rd(15, "id");
        wr(32'h2); wr(32'h0);                         // clear
        // 5 records, seq 1..5 except a gap (1,2,4,5,6), lat = 3 ticks, one with unsupported type
        for (i = 1; i <= 5; i = i + 1) begin
            @(posedge rx_clk); d = 0; d[12*64 +: 32] = (i >= 3) ? i + 1 : i; d[13*64 +: 32] = 100; d[14*64 +: 32] = 103;
            d[15*64 +: 32] = 32'hDEADBEEF; d[7:0] = (i == 5) ? 8'd11 : 8'd1; d[11*64+32 +: 32] = 1000 + i; v = 1;
            @(posedge rx_clk); v = 0;
        end
        // 3 frames on the lv stream, one bad
        for (i = 0; i < 3; i = i + 1) begin
            @(posedge rx_clk); rx_valid = 1; rx_last = 0; @(posedge rx_clk); rx_last = 1; rx_user = (i != 1);
            @(posedge rx_clk); rx_valid = 0; rx_last = 0;
        end
        @(posedge rx_clk); stats = 16'h0001; @(posedge rx_clk); stats = 16'h0020; @(posedge rx_clk); stats = 0;
        repeat (10) @(posedge clk);
        wr(32'h4); wr(32'h0);                         // snap
        repeat (10) @(posedge clk);
        rd(14, "flags"); rd(0, "records"); rd(3, "seq_gaps"); rd(5, "lat_max"); rd(6, "unsupported");
        rd(8, "fwd_records"); rd(9, "rx_frames"); rd(10, "rx_bad"); rd(11, "rx_beats"); rd(12, "first_seq");
        rd(13, "last_seq"); rd(16, "lat_min"); rd(17, "frames_pass"); rd(4, "bad_len"); rd(24, "pitch_seq_gaps");
        // sink: records must not be forwarded, ready must be high
        wr(32'h1); repeat (10) @(posedge clk);
        @(posedge rx_clk); d[12*64 +: 32] = 7; v = 1; @(posedge rx_clk); v = 0;
        repeat (10) @(posedge clk); $display("sink: ready=%b forwarded_total=%0d (expect 5)", rdy, fwd);
        wr(32'h4); wr(32'h0); repeat (10) @(posedge clk); rd(0, "records_after_sink"); rd(8, "fwd_after_sink");
        $finish;
    end
endmodule
