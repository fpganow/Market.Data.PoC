// Hand-written Verilog equivalent of the LabVIEW IP Export netlist NiFpgaAG_poc_ip_kria
// (fpga/poc.ip.kria.vi). Same port list as vivado/ip/NiFpgaIPWrapper_poc_ip_kria.vhd so
// the Vivado block design and ip_export/netlist_sim/tb.sv can use either one:
//   PARSER_IMPL=rtl make xsa        /  DUT=rtl ./run.sh
// Clocks: Clk40MhzDerived168x43B56_28MHz = 10G RX clock (156.25 MHz, input stream and
// the tick counter), Clk40MhzDerived5x2B00MHz = 100 MHz (parser and the three outputs).
// reset: active high, asynchronous (user_rx_reset). ip_reset: synchronous soft reset that
// also restarts the tick counter and the sequence number and emits the DEBUG record
// [0xAAAB,0,1,2]. enable_in/enable_clr are ignored; enable_out = running.
module mktdata_parser_rtl (
    input          reset,
    input          enable_in,
    output         enable_out,
    input          enable_clr,
    input  [0:0]   ctrlind_00_DEBUG_TREADY,
    output [0:0]   ctrlind_01_DEBUG_TVALID,
    output [0:0]   ctrlind_02_DEBUG_TLAST,
    output [7:0]   ctrlind_03_DEBUG_TKEEP,
    output [63:0]  ctrlind_04_DEBUG_TDATA,
    input  [0:0]   ctrlind_05_CMD_TREADY,
    output [0:0]   ctrlind_06_CMD_TVALID,
    output [0:0]   ctrlind_07_CMD_TLAST,
    output [7:0]   ctrlind_08_CMD_TKEEP,
    output [63:0]  ctrlind_09_CMD_TDATA,
    input  [0:0]   ctrlind_10_MDEBUG_TREADY,
    output [0:0]   ctrlind_11_MDEBUG_TVALID,
    output [0:0]   ctrlind_12_MDEBUG_TLAST,
    output [7:0]   ctrlind_13_MDEBUG_TKEEP,
    output [63:0]  ctrlind_14_MDEBUG_TDATA,
    input  [0:0]   ctrlind_15_TUSER,
    input  [0:0]   ctrlind_16_TLAST,
    input  [0:0]   ctrlind_17_TVALID,
    input  [7:0]   ctrlind_18_TKEEP,
    input  [63:0]  ctrlind_19_TDATA,
    input  [0:0]   ctrlind_20_ip_reset,
    input          Clk40MhzDerived5x2B00MHz,
    input          Clk40MhzDerived168x43B56_28MHz
);
    wire clk100 = Clk40MhzDerived5x2B00MHz;
    wire clk156 = Clk40MhzDerived168x43B56_28MHz;

    // ---- resets: async assert / sync release per domain, plus the ip_reset soft reset ----
    reg [1:0] rs156 = 2'b11, rs100 = 2'b11;
    always @(posedge clk156 or posedge reset) if (reset) rs156 <= 2'b11; else rs156 <= {rs156[0], 1'b0};
    always @(posedge clk100 or posedge reset) if (reset) rs100 <= 2'b11; else rs100 <= {rs100[0], 1'b0};
    reg [1:0] ipr156 = 0, ipr100 = 0;
    always @(posedge clk156) ipr156 <= {ipr156[0], ctrlind_20_ip_reset[0]};
    always @(posedge clk100) ipr100 <= {ipr100[0], ctrlind_20_ip_reset[0]};
    wire rst156 = rs156[1] | ipr156[1];
    wire rst100 = rs100[1] | ipr100[1];
    reg running = 0;
    always @(posedge clk100) running <= !rst100;
    assign enable_out = running;

    // ---- 156.25 MHz: tick counter and header filter ----
    reg [63:0] ts156 = 0;
    always @(posedge clk156) ts156 <= rst156 ? 64'd0 : ts156 + 64'd1;

    wire        f_valid, f_sof, f_eof;
    wire [63:0] f_data, f_ts;
    wire [3:0]  f_nbytes;
    udp_rx_filter u_filter (
        .clk(clk156), .rst(rst156), .ts(ts156),
        .s_tvalid(ctrlind_17_TVALID[0]), .s_tlast(ctrlind_16_TLAST[0]), .s_tkeep(ctrlind_18_TKEEP),
        .s_tdata(ctrlind_19_TDATA), .s_tuser(ctrlind_15_TUSER[0]),
        .o_valid(f_valid), .o_data(f_data), .o_nbytes(f_nbytes), .o_sof(f_sof), .o_eof(f_eof), .o_ts(f_ts)
    );

    // ---- clock-domain crossing into the parser domain ----
    // 4096 words = ~21 full-size frames of payload. The CMD stream drains one message per
    // 16 cycles (160 ns), so bursts queue here; when the FIFO is full the rest of that
    // frame is dropped whole (never a word in the middle), and the parser resynchronises
    // at the next frame start.
    wire         cdc_full, p_valid, p_ready;
    wire [133:0] p_elem;
    reg          ovf = 0;
    reg  [31:0]  dropped_frames = 0;
    wire         f_start = f_valid && f_sof;
    wire         cdc_wen = f_valid && !cdc_full && !(ovf && !f_start);
    always @(posedge clk156) begin
        if (rst156) begin ovf <= 0; dropped_frames <= 0; end
        else if (f_valid) begin
            if (f_start)       ovf <= cdc_full;
            else if (cdc_full) ovf <= 1'b1;
            if (cdc_full && (f_start || !ovf)) dropped_frames <= dropped_frames + 1;
        end
    end
    async_fifo #(.WIDTH(134), .ADDR(12)) u_cdc (
        .wclk(clk156), .wrst(rst156), .wen(cdc_wen), .wdata({f_ts, f_eof, f_sof, f_nbytes, f_data}), .wfull(cdc_full),
        .rclk(clk100), .rrst(rst100), .ren(p_ready), .rdata(p_elem), .rvalid(p_valid)
    );
    wire [63:0] time100;
    time_cdc u_time (.clk156(clk156), .rst156(rst156), .ts156(ts156), .clk100(clk100), .rst100(rst100), .time100(time100));

    // ---- 100 MHz: parser and the three record streams ----
    wire          cmd_wen, dbg_wen, mdbg_wen, cmd_afull, dbg_full, mdbg_full, cmd_full;
    wire [1023:0] cmd_rec;
    wire [255:0]  dbg_rec, mdbg_rec;
    pitch_parser u_parser (
        .clk(clk100), .rst(rst100),
        .in_valid(p_valid), .in_data(p_elem[63:0]), .in_nbytes(p_elem[67:64]), .in_sof(p_elem[68]),
        .in_ts(p_elem[133:70]), .in_ready(p_ready), .time_now(time100),
        .cmd_wen(cmd_wen), .cmd_rec(cmd_rec), .cmd_afull(cmd_afull),
        .dbg_wen(dbg_wen), .dbg_rec(dbg_rec), .mdbg_wen(mdbg_wen), .mdbg_rec(mdbg_rec)
    );
    // 512 records (15 BRAM36 at their full 512 depth): many frames of messages, so the
    // parser's parse.time is not delayed by the 16-cycle-per-record CMD serialiser
    rec_fifo_axis #(.WORDS(16), .ADDR(9)) u_cmd (
        .clk(clk100), .rst(rst100), .wen(cmd_wen), .wdata(cmd_rec), .full(cmd_full), .afull(cmd_afull),
        .tready(ctrlind_05_CMD_TREADY[0]), .tvalid(ctrlind_06_CMD_TVALID[0]), .tlast(ctrlind_07_CMD_TLAST[0]),
        .tkeep(ctrlind_08_CMD_TKEEP), .tdata(ctrlind_09_CMD_TDATA)
    );
    rec_fifo_axis #(.WORDS(4), .ADDR(8)) u_dbg (
        .clk(clk100), .rst(rst100), .wen(dbg_wen), .wdata(dbg_rec), .full(dbg_full), .afull(),
        .tready(ctrlind_00_DEBUG_TREADY[0]), .tvalid(ctrlind_01_DEBUG_TVALID[0]), .tlast(ctrlind_02_DEBUG_TLAST[0]),
        .tkeep(ctrlind_03_DEBUG_TKEEP), .tdata(ctrlind_04_DEBUG_TDATA)
    );
    rec_fifo_axis #(.WORDS(4), .ADDR(8)) u_mdbg (
        .clk(clk100), .rst(rst100), .wen(mdbg_wen), .wdata(mdbg_rec), .full(mdbg_full), .afull(),
        .tready(ctrlind_10_MDEBUG_TREADY[0]), .tvalid(ctrlind_11_MDEBUG_TVALID[0]), .tlast(ctrlind_12_MDEBUG_TLAST[0]),
        .tkeep(ctrlind_13_MDEBUG_TKEEP), .tdata(ctrlind_14_MDEBUG_TDATA)
    );
endmodule
