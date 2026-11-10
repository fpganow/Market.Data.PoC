// 156.25 MHz input stage: the equivalent of Reader.vi + NI's Stream Filter MAC /
// Find IPv4 Subframe / Stream Filter IPv4 / UDP Rx State Machine in poc.ip.kria.vi.
// Takes the 64-bit AXI-stream Ethernet frames from xgmii2axis (byte 0 of the frame in
// TDATA[7:0]), keeps frames addressed to MAC_ADDR/IP_ADDR/UDP_PORT (0xFF bytes match
// anything, as in the NI filters), drops fragments, and emits the UDP payload re-aligned
// to 8-byte words with a byte count, start/end-of-frame flags and the tick-counter value
// at which the word was produced (the parser's recv.time). Ethernet padding beyond the
// UDP length is dropped. Frames that fail the filter produce nothing.
module udp_rx_filter #(
    parameter [47:0] MAC_ADDR = 48'h1f3c18350a00,   // 00:0a:35:18:3c:1f, byte 0 in [7:0]
    parameter [31:0] IP_ADDR  = 32'h0e01000a,       // 10.0.1.14,          byte 0 in [7:0]
    parameter [15:0] UDP_PORT = 16'd8000
) (
    input             clk,
    input             rst,
    input      [63:0] ts,
    input             s_tvalid,
    input             s_tlast,
    input      [7:0]  s_tkeep,
    input      [63:0] s_tdata,
    input             s_tuser,
    output reg        o_valid,
    output reg [63:0] o_data,
    output reg [3:0]  o_nbytes,
    output reg        o_sof,
    output reg        o_eof,
    output reg [63:0] o_ts
);
    function [7:0] byte_of; input [63:0] w; input [2:0] i; begin byte_of = w[8*i +: 8]; end endfunction
    function match; input [7:0] b; input [7:0] want; begin match = (b == want) || (b == 8'hFF); end endfunction

    reg  [7:0]  bidx   = 0;     // beat index within the frame (saturates)
    reg         ok     = 0;     // header checks so far
    reg         accept = 0;     // frame passed every check (valid from beat 5 on)
    reg  [15:0] rem    = 0;     // payload bytes still to emit
    reg  [63:0] prev   = 0;     // previous beat
    reg         first  = 1;     // next emitted word is the frame's first
    reg         pend_v = 0;     // second word produced by one beat, sent next cycle
    reg  [63:0] pend_d = 0;
    reg  [3:0]  pend_n = 0;

    wire [3:0] keep_cnt = s_tkeep[0] + s_tkeep[1] + s_tkeep[2] + s_tkeep[3]
                        + s_tkeep[4] + s_tkeep[5] + s_tkeep[6] + s_tkeep[7];

    // header checks per beat (frame byte n = beat n/8, byte n%8)
    wire mac_ok = match(byte_of(s_tdata,0), MAC_ADDR[7:0])   && match(byte_of(s_tdata,1), MAC_ADDR[15:8])
               && match(byte_of(s_tdata,2), MAC_ADDR[23:16]) && match(byte_of(s_tdata,3), MAC_ADDR[31:24])
               && match(byte_of(s_tdata,4), MAC_ADDR[39:32]) && match(byte_of(s_tdata,5), MAC_ADDR[47:40]);
    wire eth_ok = (byte_of(s_tdata,4) == 8'h08) && (byte_of(s_tdata,5) == 8'h00)   // EtherType IPv4
               && (byte_of(s_tdata,6) == 8'h45);                                    // IPv4, IHL 5
    wire ip_ok  = (byte_of(s_tdata,7) == 8'd17)                                     // UDP
               && ((byte_of(s_tdata,4) & 8'h3F) == 8'h00) && (byte_of(s_tdata,5) == 8'h00); // no fragments
    wire dip01_ok = match(byte_of(s_tdata,6), IP_ADDR[7:0]) && match(byte_of(s_tdata,7), IP_ADDR[15:8]);
    wire dip23_ok = match(byte_of(s_tdata,0), IP_ADDR[23:16]) && match(byte_of(s_tdata,1), IP_ADDR[31:24]);
    wire port_ok  = ({byte_of(s_tdata,4), byte_of(s_tdata,5)} == UDP_PORT);
    wire [15:0] udp_len = {byte_of(s_tdata,6), byte_of(s_tdata,7)};

    // payload word k = frame bytes 42+8k .. 49+8k = beat(5+k)[bytes 2..7] ++ beat(6+k)[bytes 0..1]
    wire        in_payload = s_tvalid && accept && (bidx >= 8'd5);
    wire        doA  = in_payload && (bidx >= 8'd6) && (rem >= 16'd7);     // word needing this beat's bytes 0..1
    wire [3:0]  nA   = (rem >= 16'd8) ? 4'd8 : rem[3:0];
    wire [15:0] remB = doA ? (rem - {12'd0, nA}) : rem;
    wire        doB  = in_payload && (remB >= 16'd1) && (remB <= 16'd6);   // short tail word from bytes 2..7
    wire        trunc = in_payload && s_tlast && (remB > 16'd6);          // frame ended early
    wire [3:0]  nT   = (keep_cnt > 4'd2) ? (keep_cnt - 4'd2) : 4'd0;
    wire        doT  = trunc && (nT != 4'd0);
    wire        secondw = doB || doT;
    wire [3:0]  nBT  = doB ? remB[3:0] : nT;
    wire [63:0] wordA = {s_tdata[15:0], prev[63:16]};
    wire [63:0] wordB = {16'd0, s_tdata[63:16]};

    always @(posedge clk) begin
        if (rst) begin
            bidx <= 0; ok <= 0; accept <= 0; rem <= 0; prev <= 0; first <= 1;
            pend_v <= 0; o_valid <= 0; o_sof <= 0; o_eof <= 0;
        end else begin
            o_valid <= 1'b0;
            pend_v  <= 1'b0;
            if (pend_v) begin
                o_valid <= 1'b1; o_data <= pend_d; o_nbytes <= pend_n;
                o_sof <= 1'b0; o_eof <= 1'b1; o_ts <= ts;
            end
            if (s_tvalid) begin
                case (bidx)
                    8'd0: ok <= mac_ok;
                    8'd1: ok <= ok && eth_ok;
                    8'd2: ok <= ok && ip_ok;
                    8'd3: ok <= ok && dip01_ok;
                    8'd4: begin
                        accept <= ok && dip23_ok && port_ok && (udp_len >= 16'd8) && !s_tlast;
                        rem    <= udp_len - 16'd8;
                    end
                    default: ;
                endcase
                if (doA) begin
                    o_valid <= 1'b1; o_data <= wordA; o_nbytes <= nA; o_ts <= ts;
                    o_sof <= first; o_eof <= !secondw && ((remB == 16'd0) || s_tlast);
                    first <= 1'b0;
                    if (secondw) begin
                        pend_v <= 1'b1; pend_d <= wordB; pend_n <= nBT;
                    end
                end else if (secondw) begin
                    o_valid <= 1'b1; o_data <= wordB; o_nbytes <= nBT; o_ts <= ts;
                    o_sof <= first; o_eof <= 1'b1;
                    first <= 1'b0;
                end
                if (in_payload) rem <= secondw ? 16'd0 : remB;
                prev <= s_tdata;
                if (s_tlast) begin
                    bidx <= 0; first <= 1'b1; accept <= 1'b0; ok <= 1'b0;
                end else if (bidx != 8'hFF) begin
                    bidx <= bidx + 8'd1;
                end
            end
        end
    end
`ifdef FILTER_TRACE
    always @(posedge clk) if (o_valid)
        $display("F data=%016x n=%0d sof=%b eof=%b", o_data, o_nbytes, o_sof, o_eof);
`endif
endmodule
