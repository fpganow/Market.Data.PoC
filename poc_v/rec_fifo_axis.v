// Record FIFO + AXI-stream serialiser: each record is WORDS x 64 bit, pushed in one
// cycle, and leaves as WORDS beats of 64 bit with TLAST on the last beat (TKEEP 0xFF).
// afull = fewer than 2 free slots (one record may be in flight in the producer).
module rec_fifo_axis #(
    parameter WORDS = 16,
    parameter ADDR  = 5
) (
    input                  clk,
    input                  rst,
    input                  wen,
    input  [64*WORDS-1:0]  wdata,
    output                 full,
    output                 afull,
    input                  tready,
    output                 tvalid,
    output                 tlast,
    output [7:0]           tkeep,
    output [63:0]          tdata
);
    localparam IW = (WORDS > 1) ? $clog2(WORDS) : 1;
    reg [64*WORDS-1:0] mem [0:(1<<ADDR)-1];
    reg [ADDR:0] wp = 0, rp = 0;
    wire [ADDR:0] count = wp - rp;
    wire empty = (wp == rp);
    assign full  = count[ADDR];
    assign afull = (count >= ((1 << ADDR) - 2));

    reg [64*WORDS-1:0] cur = 0;
    reg [IW-1:0] idx = 0;
    reg busy = 0;
    wire last = (idx == WORDS - 1);
    wire adv  = busy && tready;
    wire load = !empty && (!busy || (adv && last));

    always @(posedge clk) begin
        if (rst) begin
            wp <= 0; rp <= 0; busy <= 0; idx <= 0;
        end else begin
            if (wen && !full) begin
                mem[wp[ADDR-1:0]] <= wdata;
                wp <= wp + 1;
            end
            if (load) begin
                cur  <= mem[rp[ADDR-1:0]];
                rp   <= rp + 1;
                busy <= 1'b1;
                idx  <= 0;
            end else if (adv) begin
                if (last) busy <= 1'b0; else idx <= idx + 1;
            end
        end
    end

    assign tvalid = busy;
    assign tlast  = busy && last;
    assign tkeep  = 8'hFF;
    assign tdata  = cur[idx*64 +: 64];
endmodule
