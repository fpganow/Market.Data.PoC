`timescale 1ns / 1ps
// Small helpers for the pure-RTL PITCH parser (vivado_rtl).

// ----------------------------------------------------------------------------
// fwft_fifo -- synchronous first-word-fall-through FIFO with a registered
// output stage (rd_data/rd_valid are flops, so the consumer's logic starts
// from a register, not from the LUTRAM read mux).
// ----------------------------------------------------------------------------
module fwft_fifo #(
    parameter W = 79,
    parameter D_LOG2 = 6
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         wr_en,
    input  wire [W-1:0] wr_data,
    output wire         full,
    input  wire         rd_en,
    output reg  [W-1:0] rd_data,
    output reg          rd_valid
);
    reg [W-1:0] mem [0:(1<<D_LOG2)-1];
    reg [D_LOG2:0] wp, rp;
    wire empty = (wp == rp);
    assign full = (wp[D_LOG2] != rp[D_LOG2]) && (wp[D_LOG2-1:0] == rp[D_LOG2-1:0]);
    wire advance = !rd_valid || rd_en;

    always @(posedge clk) begin
        if (!rst_n) begin
            wp <= 0; rp <= 0; rd_valid <= 1'b0;
        end else begin
            if (wr_en && !full) begin
                mem[wp[D_LOG2-1:0]] <= wr_data;
                wp <= wp + 1;
            end
            if (advance) begin
                if (!empty) begin
                    rd_data  <= mem[rp[D_LOG2-1:0]];
                    rp       <= rp + 1;
                    rd_valid <= 1'b1;
                end else begin
                    rd_valid <= 1'b0;
                end
            end
        end
    end
endmodule

// ----------------------------------------------------------------------------
// dbg_writer -- serialises 4 x U64 trace records onto a 64-bit AXI-Stream
// (TLAST on the 4th beat). Two-entry buffer; a record pushed while both
// entries are busy is dropped (`dropped` pulses). Debug streams must never
// back-pressure the parser.
// ----------------------------------------------------------------------------
module dbg_writer (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         push,
    input  wire [255:0] rec,
    output wire         dropped,
    output wire [63:0]  m_tdata,
    output wire         m_tvalid,
    output wire         m_tlast,
    input  wire         m_tready
);
    reg [255:0] buf0, buf1;
    reg [1:0]   count;        // records buffered (0..2)
    reg [1:0]   beat;
    assign dropped  = push && (count == 2'd2);
    assign m_tvalid = (count != 2'd0);
    assign m_tdata  = buf0[beat*64 +: 64];
    assign m_tlast  = (beat == 2'd3);
    wire pop = m_tvalid && m_tready && m_tlast;
    wire acc = push && (count != 2'd2);

    always @(posedge clk) begin
        if (!rst_n) begin
            count <= 0; beat <= 0; buf0 <= 0; buf1 <= 0;
        end else begin
            if (m_tvalid && m_tready) beat <= pop ? 2'd0 : beat + 1;
            case ({acc, pop})
                2'b10: begin
                    if (count == 2'd0) buf0 <= rec; else buf1 <= rec;
                    count <= count + 1;
                end
                2'b01: begin
                    buf0 <= buf1; count <= count - 1;
                end
                2'b11: begin
                    // pop buf0, shift buf1 down, push into the freed slot
                    if (count == 2'd1) buf0 <= rec; else begin buf0 <= buf1; buf1 <= rec; end
                end
                default: ;
            endcase
        end
    end
endmodule

// ----------------------------------------------------------------------------
// sync2 -- two-flop level synchroniser.
// ----------------------------------------------------------------------------
module sync2 #(parameter W = 1) (
    input  wire         clk,
    input  wire [W-1:0] d,
    output wire [W-1:0] q
);
    (* ASYNC_REG = "TRUE" *) reg [W-1:0] s0, s1;
    always @(posedge clk) begin s0 <= d; s1 <= s0; end
    assign q = s1;
endmodule
