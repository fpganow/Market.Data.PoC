`timescale 1ns / 1ps
// pitch_decode -- turns one extracted PITCH message into the 16 x U64 CMD
// record the rest of the project already understands (poc_server,
// decode_capture.py, eval_sim.py, axis_mon). Same word layout as the LabVIEW
// parser (CLAUDE.md "Stream formats"), one 1024-bit beat per message:
//
//   0 type enum          orderbook.command.type: Time 0, AddOrder 1, OrderExecuted 2,
//                        OrderExecutedAtPriceSize 3, ReduceSize 4, ModifyOrder 5,
//                        DeleteOrder 6, Trade 10, Unsupported 11
//   1 side       raw ASCII byte ('B' / 'S'), 0 when the message has no side
//   2 orderId    8 bytes as on the wire (little-endian packed, byte 0 in bits 7:0)
//   3 quantity   4 symbol (8 chars, space padded)   5 price (short prices x SHORT_SCALE)
//   6 executed   7 canceled   8 remaining   9 seconds (last Time message)
//  10 nanoseconds (time offset)
//  11 [7:0] add/modify flags, [15:8] raw PITCH type, [23:16] length, [31:24] unit, [63:32] PITCH sequence
//  12 seq no (parser counter, restarts at 1 after ip_reset)
//  13 recv.time  14 parse.time (10 ns ticks)   15 0xDEADBEEF
//
// Field offsets are the Cboe Multicast PITCH equities layouts, cross-checked
// against cboe_pitch/ (the generator behind the test pcaps).

module pitch_decode #(
    parameter MAXB        = 48,
    parameter SHORT_SCALE = 100          // 2-byte prices are in 1/100, long ones in 1/10000
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,
    input  wire              ip_reset,     // synchronous, level: restarts the seq counter
    input  wire              m_valid,
    input  wire [8*MAXB-1:0] m_bytes,
    input  wire [7:0]        m_len,
    input  wire [31:0]       m_seq,
    input  wire [7:0]        m_unit,
    input  wire [31:0]       m_recv_time,
    input  wire [31:0]       time10,
    output reg               r_valid,
    output reg  [1023:0]     r_data,
    output reg  [31:0]       seq_counter   // value of the last record's word 12
);

    function [63:0] u64(input [8*MAXB-1:0] b, input integer o); u64 = b[o*8 +: 64]; endfunction
    function [31:0] u32(input [8*MAXB-1:0] b, input integer o); u32 = b[o*8 +: 32]; endfunction
    function [15:0] u16(input [8*MAXB-1:0] b, input integer o); u16 = b[o*8 +: 16]; endfunction
    function [7:0]  u8 (input [8*MAXB-1:0] b, input integer o); u8  = b[o*8 +: 8];  endfunction

    wire [7:0] t = u8(m_bytes, 1);

    reg [7:0]  enum_t;
    always @* begin
        case (t)
            8'h20: enum_t = 8'd0;
            8'h21, 8'h22, 8'h2F: enum_t = 8'd1;
            8'h23: enum_t = 8'd2;
            8'h24: enum_t = 8'd3;
            8'h25, 8'h26: enum_t = 8'd4;
            8'h27, 8'h28: enum_t = 8'd5;
            8'h29: enum_t = 8'd6;
            8'h2A, 8'h2B, 8'h30: enum_t = 8'd10;
            default: enum_t = 8'd11;
        endcase
    end

    wire is_time = (t == 8'h20);
    wire known   = (enum_t != 8'd11);

    // per-type field selection
    reg [7:0]  side; reg [63:0] oid; reg [31:0] qty; reg [63:0] sym; reg [63:0] price;
    reg [31:0] executed, canceled, remaining, nanos; reg [7:0] flags;
    wire [63:0] sym6_19 = {16'h2020, m_bytes[19*8 +: 48]};
    wire [63:0] sym6_17 = {16'h2020, m_bytes[17*8 +: 48]};
    wire [63:0] sym8_19 = m_bytes[19*8 +: 64];
    wire [63:0] p_short23 = u16(m_bytes, 23) * SHORT_SCALE;
    wire [63:0] p_short16 = u16(m_bytes, 16) * SHORT_SCALE;

    always @* begin
        side = 0; qty = 0; sym = 0; price = 0; executed = 0; canceled = 0; remaining = 0; flags = 0;
        oid   = (is_time || !known) ? 64'd0 : u64(m_bytes, 6);
        nanos = (is_time || !known) ? 32'd0 : u32(m_bytes, 2);
        case (t)
            8'h21: begin side = u8(m_bytes,14); qty = u32(m_bytes,15); sym = sym6_19; price = u64(m_bytes,25); flags = u8(m_bytes,33); end
            8'h22: begin side = u8(m_bytes,14); qty = u16(m_bytes,15); sym = sym6_17; price = p_short23;       flags = u8(m_bytes,25); end
            8'h2F: begin side = u8(m_bytes,14); qty = u32(m_bytes,15); sym = sym8_19; price = u64(m_bytes,27); flags = u8(m_bytes,35); end
            8'h23: begin executed = u32(m_bytes,14); end
            8'h24: begin executed = u32(m_bytes,14); remaining = u32(m_bytes,18); price = u64(m_bytes,30); end
            8'h25: begin canceled = u32(m_bytes,14); end
            8'h26: begin canceled = u16(m_bytes,14); end
            8'h27: begin qty = u32(m_bytes,14); price = u64(m_bytes,18); flags = u8(m_bytes,26); end
            8'h28: begin qty = u16(m_bytes,14); price = p_short16;       flags = u8(m_bytes,18); end
            8'h29: ;
            8'h2A: begin side = u8(m_bytes,14); qty = u32(m_bytes,15); sym = sym6_19; price = u64(m_bytes,25); end
            8'h2B: begin side = u8(m_bytes,14); qty = u16(m_bytes,15); sym = sym6_17; price = p_short23; end
            8'h30: begin side = u8(m_bytes,14); qty = u32(m_bytes,15); sym = sym8_19; price = u64(m_bytes,27); end
            default: ;
        endcase
    end

    reg [31:0] seconds;
    wire [31:0] seq_next = seq_counter + 32'd1;
    wire [31:0] sec_out  = is_time ? u32(m_bytes, 2) : seconds;

    always @(posedge clk) begin
        if (!rst_n || ip_reset) begin
            r_valid <= 1'b0; seq_counter <= 0; seconds <= 0;
            if (!rst_n) r_data <= 0;
        end else if (en) begin
            r_valid <= m_valid;
            if (m_valid) begin
                if (is_time) seconds <= u32(m_bytes, 2);
                seq_counter <= seq_next;
                r_data[ 0*64 +: 64] <= {56'd0, enum_t};
                r_data[ 1*64 +: 64] <= {56'd0, side};
                r_data[ 2*64 +: 64] <= oid;
                r_data[ 3*64 +: 64] <= {32'd0, qty};
                r_data[ 4*64 +: 64] <= sym;
                r_data[ 5*64 +: 64] <= price;
                r_data[ 6*64 +: 64] <= {32'd0, executed};
                r_data[ 7*64 +: 64] <= {32'd0, canceled};
                r_data[ 8*64 +: 64] <= {32'd0, remaining};
                r_data[ 9*64 +: 64] <= {32'd0, sec_out};
                r_data[10*64 +: 64] <= {32'd0, nanos};
                r_data[11*64 +: 64] <= {m_seq, m_unit, m_len, t, flags};
                r_data[12*64 +: 64] <= {32'd0, seq_next};
                r_data[13*64 +: 64] <= {32'd0, m_recv_time};
                r_data[14*64 +: 64] <= {32'd0, time10};
                r_data[15*64 +: 64] <= {32'd0, 32'hDEADBEEF};
            end
        end
    end

endmodule
