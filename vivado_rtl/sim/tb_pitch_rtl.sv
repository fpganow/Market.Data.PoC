`timescale 1ns / 1ps
// tb_pitch_rtl -- drives pitch_rtl_top with the beat file from pcap2beats.py and
// prints CMD / DEBUG / MDEBUG records in the ip_export/netlist_sim sim_out.txt
// format, so ip_export/netlist_sim/eval_sim.py scores the pure-RTL parser
// against the pcap exactly like the LabVIEW netlist:
//     <time10> CMD w<n> 0x<64-bit> [LAST]
// Plusargs: +beats=<file> (default beats.txt)  +ready=<0|1|2>  (1 = TREADY always,
//           2 = random TREADY, 0 = TREADY low for the first 3000 cycles then high)
//           +dbgready=<0|1>  (1 = debug streams always ready, 0 = never -> all dropped)

module tb_pitch_rtl;
    reg clk = 0; always #3.2 clk = ~clk;        // 156.25 MHz
    reg rst_n = 0;
    reg ip_reset = 0;

    reg [63:0] lv_tdata = 0; reg [7:0] lv_tkeep = 0; reg lv_tvalid = 0, lv_tlast = 0; reg [0:0] lv_tuser = 0;
    wire [1023:0] cmd_tdata; wire cmd_tvalid, cmd_tlast; reg cmd_tready = 1;
    wire [63:0] dbg_tdata, mdbg_tdata; wire dbg_tvalid, dbg_tlast, mdbg_tvalid, mdbg_tlast; reg dbg_tready = 1;
    wire [15:0] stats; wire [31:0] time10;

    pitch_rtl_top dut (
        .rx_clk(clk), .rx_aresetn(rst_n), .ip_reset(ip_reset),
        .lv_data(lv_tdata), .lv_keep(lv_tkeep), .lv_valid(lv_tvalid), .lv_last(lv_tlast), .lv_user(lv_tuser),
        .cmd_data(cmd_tdata), .cmd_valid(cmd_tvalid), .cmd_last(cmd_tlast), .cmd_ready(cmd_tready),
        .dbg_data(dbg_tdata), .dbg_valid(dbg_tvalid), .dbg_last(dbg_tlast), .dbg_ready(dbg_tready),
        .mdbg_data(mdbg_tdata), .mdbg_valid(mdbg_tvalid), .mdbg_last(mdbg_tlast), .mdbg_ready(dbg_tready),
        .stats(stats), .time10_out(time10)
    );

    // ---- statistics ----
    integer cnt [0:15]; integer k;
    integer n_cmd = 0, n_stall = 0;
    always @(posedge clk) if (rst_n) begin
        for (k = 0; k < 16; k = k + 1) if (stats[k]) cnt[k] = cnt[k] + 1;
        if (cmd_tvalid & ~cmd_tready) n_stall = n_stall + 1;
    end

    // ---- optional filter trace (+verbose) ----
    integer verbose = 0;
    always @(posedge clk) if (verbose > 1 && rst_n && lv_tvalid && dut.u_filter.widx < 7)
        $display("# beat widx=%0d data=%016h mac=%b eth=%b ip=%b accept=%b", dut.u_filter.widx, lv_tdata,
                 dut.u_filter.mac_ok, dut.u_filter.eth_ok, dut.u_filter.ip_ok, dut.u_filter.accept);
    always @(posedge clk) if (verbose && rst_n && lv_tvalid && lv_tlast)
        $display("# frame end: widx=%0d accept=%b mac=%b eth=%b ip=%b pl_len=%0d remaining=%0d", dut.u_filter.widx,
                 dut.u_filter.accept, dut.u_filter.mac_ok, dut.u_filter.eth_ok, dut.u_filter.ip_ok, dut.u_filter.pl_len, dut.u_filter.remaining);

    // ---- record printing ----
    integer w;
    always @(posedge clk) begin
        if (cmd_tvalid & cmd_tready) begin
            n_cmd = n_cmd + 1;
            for (w = 0; w < 16; w = w + 1)
                $display("%0d CMD w%0d 0x%016h%s", time10, w, cmd_tdata[w*64 +: 64], (w == 15) ? " LAST" : "");
        end
    end
    integer dw = 0, mw = 0;
    always @(posedge clk) begin
        if (dbg_tvalid & dbg_tready) begin
            $display("%0d DEBUG w%0d 0x%016h%s", time10, dw, dbg_tdata, dbg_tlast ? " LAST" : "");
            dw = dbg_tlast ? 0 : dw + 1;
        end
        if (mdbg_tvalid & dbg_tready) begin
            $display("%0d MDEBUG w%0d 0x%016h%s", time10, mw, mdbg_tdata, mdbg_tlast ? " LAST" : "");
            mw = mdbg_tlast ? 0 : mw + 1;
        end
    end

    // ---- TREADY policy ----
    integer ready_mode = 1, dbg_mode = 1, cyc = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        case (ready_mode)
            0: cmd_tready <= (cyc > 3000);
            2: cmd_tready <= ($urandom % 4) != 0;
            default: cmd_tready <= 1'b1;
        endcase
        dbg_tready <= (dbg_mode != 0);
    end

    // ---- stimulus ----
    integer fd, rc, n_idle, i;
    reg [63:0] d; reg [7:0] kp; reg lst, usr;
    string beats = "beats.txt", tok;
    initial begin
        for (k = 0; k < 16; k = k + 1) cnt[k] = 0;
        if (!$value$plusargs("beats=%s", beats)) beats = "beats.txt";
        if (!$value$plusargs("ready=%d", ready_mode)) ready_mode = 1;
        if (!$value$plusargs("dbgready=%d", dbg_mode)) dbg_mode = 1;
        if (!$value$plusargs("verbose=%d", verbose)) verbose = 0;
        fd = $fopen(beats, "r");
        if (fd == 0) begin $display("# cannot open %s", beats); $finish; end
        repeat (5) @(posedge clk);
        rst_n <= 1;
        repeat (10) @(posedge clk);
        ip_reset <= 1; repeat (4) @(posedge clk); ip_reset <= 0;
        repeat (20) @(posedge clk);
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%s", tok);
            if (rc != 1) break;
            if (tok == "idle") begin
                rc = $fscanf(fd, "%d", n_idle);
                lv_tvalid <= 0; lv_tlast <= 0;
                repeat (n_idle) @(posedge clk);
            end else begin
                rc = $sscanf(tok, "%h", d);          // string.atohex() truncates to 32 bits in xsim
                rc = $fscanf(fd, "%h %d %d", kp, lst, usr);
                lv_tdata <= d; lv_tkeep <= kp; lv_tlast <= lst; lv_tuser <= usr; lv_tvalid <= 1;
                @(posedge clk);
            end
        end
        lv_tvalid <= 0; lv_tlast <= 0;
        repeat (4000) @(posedge clk);
        $display("# records %0d  stall_cycles %0d  frames_pass %0d filtered %0d trunc %0d dropped_full %0d hdr %0d bad_len %0d msg_trunc %0d dbg_drop %0d mdbg_drop %0d crc_bad %0d",
                 n_cmd, n_stall, cnt[0], cnt[1], cnt[2], cnt[3], cnt[4], cnt[5], cnt[6], cnt[7], cnt[8], cnt[9]);
        $finish;
    end
endmodule
