// Dual-clock FIFO with gray-coded pointers and first-word-fall-through read side.
// Write: wen is honoured only while !wfull. Read: rdata/rvalid show the head word;
// ren consumes it. Both resets are synchronous to their own clock.
module async_fifo #(
    parameter WIDTH = 8,
    parameter ADDR  = 10
) (
    input              wclk,
    input              wrst,
    input              wen,
    input  [WIDTH-1:0] wdata,
    output             wfull,
    input              rclk,
    input              rrst,
    input              ren,
    output reg [WIDTH-1:0] rdata,
    output reg         rvalid
);
    reg [WIDTH-1:0] mem [0:(1<<ADDR)-1];
    reg  [ADDR:0] wbin = 0, wgray = 0;
    reg  [ADDR:0] rbin = 0, rgray = 0;
    reg  [ADDR:0] rgray_w1 = 0, rgray_w2 = 0;      // read pointer synchronised into wclk
    reg  [ADDR:0] wgray_r1 = 0, wgray_r2 = 0;      // write pointer synchronised into rclk

    // ---- write side ----
    wire [ADDR:0] wbin_n  = wbin + (wen & ~wfull);
    wire [ADDR:0] wgray_n = wbin_n ^ (wbin_n >> 1);
    assign wfull = (wgray == {~rgray_w2[ADDR:ADDR-1], rgray_w2[ADDR-2:0]});

    always @(posedge wclk) begin
        if (wrst) begin
            wbin <= 0; wgray <= 0; rgray_w1 <= 0; rgray_w2 <= 0;
        end else begin
            rgray_w1 <= rgray; rgray_w2 <= rgray_w1;
            if (wen && !wfull) mem[wbin[ADDR-1:0]] <= wdata;
            wbin <= wbin_n; wgray <= wgray_n;
        end
    end

    // ---- read side ----
    wire          rempty = (rgray == wgray_r2);
    wire          fetch  = !rempty && (!rvalid || ren);
    wire [ADDR:0] rbin_n  = rbin + fetch;
    wire [ADDR:0] rgray_n = rbin_n ^ (rbin_n >> 1);

    always @(posedge rclk) begin
        if (rrst) begin
            rbin <= 0; rgray <= 0; wgray_r1 <= 0; wgray_r2 <= 0; rvalid <= 0;
        end else begin
            wgray_r1 <= wgray; wgray_r2 <= wgray_r1;
            if (fetch) begin
                rdata  <= mem[rbin[ADDR-1:0]];
                rvalid <= 1'b1;
            end else if (ren) begin
                rvalid <= 1'b0;
            end
            rbin <= rbin_n; rgray <= rgray_n;
        end
    end
endmodule
