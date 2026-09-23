`timescale 1ps / 1ps
// Testbench for the LabVIEW-exported poc_ip_kria netlist (via its VHDL wrapper).
// Mirrors the KR260 block design: 100 MHz pl_clk0 on Clk40MhzDerived5x2B00MHz,
// 156.25 MHz rx clock on Clk40MhzDerived168x43B56_28MHz, enable_in=1, enable_clr=0,
// all three output TREADYs held high (the AXI-stream FIFOs never back-pressure
// in the idle board), ip_reset pulsed 0->1->0 like `poc_server reset`.
module tb;
    localparam real T100 = 10000.0;   // ps
    localparam real T156 = 6400.0;    // ps  (156.25 MHz)

    reg clk100 = 0, clk156 = 0;
    always #(T100/2) clk100 = ~clk100;
    always #(T156/2) clk156 = ~clk156;

    reg        reset = 1;
    reg        enable_in = 1;
    wire       enable_out;
    reg        enable_clr = 0;
    reg  [0:0] ip_reset = 0;

    reg  [0:0] in_tuser = 0, in_tlast = 0, in_tvalid = 0;
    reg  [7:0] in_tkeep = 0;
    reg [63:0] in_tdata = 0;

    wire [0:0] dbg_tvalid, dbg_tlast, cmd_tvalid, cmd_tlast, mdbg_tvalid, mdbg_tlast;
    wire [7:0] dbg_tkeep, cmd_tkeep, mdbg_tkeep;
    wire [63:0] dbg_tdata, cmd_tdata, mdbg_tdata;

    NiFpgaAG_poc_ip_kria dut (
        .tDiagramEnableOut(1'b1),
        .reset(reset), .enable_in(enable_in), .enable_out(enable_out), .enable_clr(enable_clr),
        .ctrlind_00_DEBUG_TREADY(1'b1),
        .ctrlind_01_DEBUG_TVALID(dbg_tvalid), .ctrlind_02_DEBUG_TLAST(dbg_tlast),
        .ctrlind_03_DEBUG_TKEEP(dbg_tkeep),   .ctrlind_04_DEBUG_TDATA(dbg_tdata),
        .ctrlind_05_CMD_TREADY(1'b1),
        .ctrlind_06_CMD_TVALID(cmd_tvalid),   .ctrlind_07_CMD_TLAST(cmd_tlast),
        .ctrlind_08_CMD_TKEEP(cmd_tkeep),     .ctrlind_09_CMD_TDATA(cmd_tdata),
        .ctrlind_10_MDEBUG_TREADY(1'b1),
        .ctrlind_11_MDEBUG_TVALID(mdbg_tvalid), .ctrlind_12_MDEBUG_TLAST(mdbg_tlast),
        .ctrlind_13_MDEBUG_TKEEP(mdbg_tkeep),   .ctrlind_14_MDEBUG_TDATA(mdbg_tdata),
        .ctrlind_15_TUSER(in_tuser), .ctrlind_16_TLAST(in_tlast), .ctrlind_17_TVALID(in_tvalid),
        .ctrlind_18_TKEEP(in_tkeep), .ctrlind_19_TDATA(in_tdata),
        .ctrlind_20_ip_reset(ip_reset),
        .Clk40MhzDerived5x2B00MHz(clk100),
        .Clk40MhzDerived168x43B56_28MHz(clk156)
    );

    // ---- output monitors (sampled on the 100 MHz output clock) -------------
    integer dbg_n = 0, cmd_n = 0, mdbg_n = 0;
    integer cyc100 = 0;
    always @(posedge clk100) cyc100 <= cyc100 + 1;

    always @(posedge clk100) begin
        if (dbg_tvalid) begin
            $display("%0d DEBUG  w%0d 0x%016h%s", cyc100, dbg_n, dbg_tdata, dbg_tlast ? " LAST" : "");
            dbg_n = dbg_tlast ? 0 : dbg_n + 1;
        end
        if (cmd_tvalid) begin
            $display("%0d CMD    w%0d 0x%016h%s", cyc100, cmd_n, cmd_tdata, cmd_tlast ? " LAST" : "");
            cmd_n = cmd_tlast ? 0 : cmd_n + 1;
        end
        if (mdbg_tvalid) begin
            $display("%0d MDEBUG w%0d 0x%016h%s", cyc100, mdbg_n, mdbg_tdata, mdbg_tlast ? " LAST" : "");
            mdbg_n = mdbg_tlast ? 0 : mdbg_n + 1;
        end
    end

    // ---- stimulus ----------------------------------------------------------
    integer fd, r, beat = 0, fno, last_fno = -1, tv = 1;
    reg [63:0] d; reg [7:0] k; reg l;
    integer gap;

    initial begin
        repeat (100) @(posedge clk100);
        reset = 0;
        $display("# reset released at cyc %0d", cyc100);
        repeat (300) @(posedge clk100);
        $display("# enable_out = %b at cyc %0d (stays low for a free-running VI)", enable_out, cyc100);
        repeat (200) @(posedge clk100);

        // ip_reset pulse (as poc_server reset does): 0 -> 1 -> 0
        ip_reset = 1; repeat (20) @(posedge clk100);
        ip_reset = 0; $display("# ip_reset pulsed, released at cyc %0d", cyc100);
        repeat (500) @(posedge clk100);

        fd = $fopen("frames.txt", "r");
        if (fd == 0) begin $display("ERROR: frames.txt not found"); $finish; end
        @(posedge clk156);
        while (!$feof(fd)) begin
            r = $fscanf(fd, "%h %h %d %d %d\n", d, k, l, fno, tv);
            if (r == 4) tv = 1;
            if (r >= 4) begin
                if (fno != last_fno) begin
                    // inter-frame gap: idle beats
                    in_tvalid <= 0; in_tlast <= 0;
                    repeat (64) @(posedge clk156);
                    $display("# frame %0d starts at cyc100=%0d (156 MHz beat %0d)", fno, cyc100, beat);
                    last_fno = fno;
                end
                in_tdata <= d; in_tkeep <= k; in_tlast <= l; in_tvalid <= tv;
                @(posedge clk156);
                beat = beat + 1;
            end
        end
        in_tvalid <= 0; in_tlast <= 0;
        $fclose(fd);
        // drain: the CMD stream serialises 16 words per message at 100 MHz (160 ns/message),
        // so a dense multi-frame file needs well over 100 us after the last beat.
        repeat (20000) @(posedge clk100);
        $display("# done at cyc %0d", cyc100);
        $finish;
    end

    initial begin
        #(2_000_000_000); // 2 ms hard stop
        $display("# TIMEOUT");
        $finish;
    end
endmodule
