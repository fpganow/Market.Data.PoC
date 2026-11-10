`timescale 1ns / 1ps
// eth_rx_filter -- Ethernet / IPv4 / UDP filter and payload re-aligner for the
// pure-RTL PITCH parser (vivado_rtl). Replaces the NI "Stream Filter MAC /
// Find IPv4 Subframe / Stream Filter IPv4 / UDP Rx State Machine" chain.
//
// Input : the xgmii2axis `lv_` stream (64-bit, TVALID-only, no back-pressure,
//         TKEEP on the last beat, TUSER[0] = 1 at TLAST means the FCS matched;
//         the FCS itself is already stripped, byte 0 of beat 0 is dst MAC[0]).
// Output: the UDP payload only, re-aligned so payload byte 0 is in byte lane 0,
//         8 bytes per word, `m_nbytes` valid bytes in the last word, bounded by the
//         IPv4 Total Length (Ethernet padding and anything past it is dropped --
//         the 2026-09-18 frame-boundary bug class cannot happen here). `m_sof`
//         marks the first payload word, `m_eof` the last, `m_bad` on the eof word
//         means the frame was bad (FCS error) or shorter than its IP length.
//         Also carries, for every word, `m_fits[e]` = "a PITCH message starting at
//         byte e of this word would end inside this word" (len byte <= nbytes-e),
//         precomputed here so the extractor's stall decision is a 1-bit mux.
//
// Accept rule (all must hold, else the frame is counted in `frame_filtered`):
//   dst MAC == DST_MAC, or (ACCEPT_MCAST and dst MAC[0] bit0 set), or ACCEPT_ANY_MAC
//   EtherType 0x0800, IPv4 version 4 with IHL 5, protocol 17 (UDP), not fragmented
//   dst IP == DST_IP unless DST_IP == 0 (any)
//   UDP dst port == UDP_PORT unless UDP_PORT == 0 (any)
//   IPv4 total length >= 28 (there is a payload)
//
// Latency: 1 cycle after the input beat that completes a payload word. The last
// payload word may need an extra "flush" cycle after TLAST; the 10G inter-frame
// gap guarantees at least one idle beat so no input is ever lost.

module eth_rx_filter #(
    parameter [47:0] DST_MAC        = 48'h000a35183c1f,
    parameter        ACCEPT_MCAST   = 1,
    parameter        ACCEPT_ANY_MAC = 0,
    parameter [31:0] DST_IP         = 32'h0,          // 0 = any
    parameter [15:0] UDP_PORT       = 16'd8000        // 0 = any
) (
    input  wire        clk,
    input  wire        rst_n,
    // xgmii2axis lv_ stream
    input  wire [63:0] s_tdata,
    input  wire [7:0]  s_tkeep,
    input  wire        s_tvalid,
    input  wire        s_tlast,
    input  wire        s_tuser,
    // payload words
    output reg  [63:0] m_tdata,
    output reg  [3:0]  m_nbytes,
    output reg         m_tvalid,
    output reg         m_sof,
    output reg         m_eof,
    output reg         m_bad,
    output reg  [7:0]  m_fits,
    // one-cycle statistics pulses
    output reg         st_frame,          // every frame seen (TLAST)
    output reg         st_frame_crc_bad,  // TUSER[0] low at TLAST
    output reg         st_frame_pass,     // accepted by the filter (payload emitted)
    output reg         st_frame_filtered, // rejected by the filter
    output reg         st_frame_trunc     // accepted but shorter than its IP total length
);

    // ------------------------------------------------------------------
    // per-frame header capture (big-endian fields, byte 0 = lane [7:0])
    // ------------------------------------------------------------------
    reg  [7:0]  widx;           // input beat index within the frame (saturates at 255)
    reg  [63:0] prev;           // previous input beat
    reg         mac_ok, eth_ok, ip_ok;
    reg  [15:0] pl_len;         // UDP payload length = IP total length - 28
    reg  [15:0] remaining;      // payload bytes still to emit
    reg         accept;         // header checks passed (valid from beat 5 on)
    reg         emitted_any;
    reg         need_flush;     // a tail word must be emitted this cycle
    reg  [63:0] flush_data;
    reg  [3:0]  flush_nbytes;
    reg         flush_bad;

    function [3:0] keep_count(input [7:0] k);
        case (k)
            8'h01: keep_count = 1; 8'h03: keep_count = 2; 8'h07: keep_count = 3; 8'h0F: keep_count = 4;
            8'h1F: keep_count = 5; 8'h3F: keep_count = 6; 8'h7F: keep_count = 7; default: keep_count = 8;
        endcase
    endfunction

    // byte e of word d, little-endian lane order
    function [7:0] byte_of(input [63:0] d, input [2:0] e);
        byte_of = d[e*8 +: 8];
    endfunction

    // "a message starting at byte e ends within this word": len byte at e, and e + len <= nbytes
    function [7:0] fits_of(input [63:0] d, input [3:0] nb);
        integer e;
        begin
            for (e = 0; e < 8; e = e + 1)
                fits_of[e] = (e < nb) && ({1'b0, byte_of(d, e[2:0])} + e <= {4'b0, nb}) && (byte_of(d, e[2:0]) != 8'd0);
        end
    endfunction

    wire [3:0]  nb_in   = s_tlast ? keep_count(s_tkeep) : 4'd8;
    wire [47:0] dst_mac = {s_tdata[7:0], s_tdata[15:8], s_tdata[23:16], s_tdata[31:24], s_tdata[39:32], s_tdata[47:40]};
    // beat 1: bytes 8-11 src MAC tail, 12-13 EtherType, 14 ver/IHL, 15 TOS
    wire [15:0] ethertype = {s_tdata[39:32], s_tdata[47:40]};
    wire [7:0]  ver_ihl   = s_tdata[55:48];
    // beat 2: 16-17 total length, 18-19 id, 20-21 flags/frag, 22 TTL, 23 proto
    wire [15:0] tot_len   = {s_tdata[7:0], s_tdata[15:8]};
    wire [12:0] frag_off  = {s_tdata[36:32], s_tdata[47:40]};
    wire        more_frag = s_tdata[37];
    wire [7:0]  proto     = s_tdata[63:56];
    // beat 3: 24-25 checksum, 26-29 src IP, 30-31 dst IP[0:1]   beat 4: 32-33 dst IP[2:3], 34-35 sport, 36-37 dport, 38-39 ulen
    reg  [15:0] dst_ip_hi;
    wire [31:0] dst_ip    = {dst_ip_hi, s_tdata[7:0], s_tdata[15:8]};
    wire [15:0] dport     = {s_tdata[39:32], s_tdata[47:40]};

    // re-aligned payload word j = beat (6+j) low 2 bytes ++ beat (5+j) high 6 bytes
    wire [63:0] realigned = {s_tdata[15:0], prev[63:16]};
    wire [63:0] tail_word = {16'd0, s_tdata[63:16]};            // bytes 2..7 of the TLAST beat
    wire [3:0]  tail_avail = (nb_in > 4'd2) ? (nb_in - 4'd2) : 4'd0;

    // bytes available in the realigned word completed by this beat
    wire [3:0]  word_avail = s_tlast ? ((nb_in >= 4'd2) ? 4'd8 : 4'd7) : 4'd8;   // nb_in >= 1 always on TLAST

    wire [3:0]  emit_nb    = (remaining < {12'd0, word_avail}) ? remaining[3:0] : word_avail;
    wire [15:0] rem_after  = remaining - {12'd0, emit_nb};
    wire [3:0]  tail_nb    = (rem_after < {12'd0, tail_avail}) ? rem_after[3:0] : tail_avail;

    always @(posedge clk) begin
        if (!rst_n) begin
            widx <= 0; accept <= 1'b0; mac_ok <= 1'b0; eth_ok <= 1'b0; ip_ok <= 1'b0;
            pl_len <= 0; remaining <= 0; emitted_any <= 1'b0; need_flush <= 1'b0;
            m_tvalid <= 1'b0; m_sof <= 1'b0; m_eof <= 1'b0; m_bad <= 1'b0; m_nbytes <= 0; m_tdata <= 0; m_fits <= 0;
            st_frame <= 1'b0; st_frame_crc_bad <= 1'b0; st_frame_pass <= 1'b0; st_frame_filtered <= 1'b0; st_frame_trunc <= 1'b0;
            flush_data <= 0; flush_nbytes <= 0; flush_bad <= 1'b0; prev <= 0; dst_ip_hi <= 0;
        end else begin
            // defaults: output idle, stats pulses low
            m_tvalid <= 1'b0; m_sof <= 1'b0; m_eof <= 1'b0; m_bad <= 1'b0;
            st_frame <= 1'b0; st_frame_crc_bad <= 1'b0; st_frame_pass <= 1'b0; st_frame_filtered <= 1'b0; st_frame_trunc <= 1'b0;

            if (need_flush) begin
                need_flush <= 1'b0;
                m_tvalid <= 1'b1; m_tdata <= flush_data; m_nbytes <= flush_nbytes; m_fits <= fits_of(flush_data, flush_nbytes);
                m_eof <= 1'b1; m_bad <= flush_bad; m_sof <= 1'b0;
            end

            if (s_tvalid) begin
                prev <= s_tdata;
                if (widx != 8'hFF) widx <= widx + 1;

                case (widx)
                    8'd0: begin
                        mac_ok <= ACCEPT_ANY_MAC || (dst_mac == DST_MAC) || (ACCEPT_MCAST && s_tdata[0]);
                        accept <= 1'b0; emitted_any <= 1'b0;
                    end
                    8'd1: eth_ok <= (ethertype == 16'h0800) && (ver_ihl == 8'h45);
                    8'd2: begin
                        ip_ok  <= (proto == 8'd17) && (frag_off == 13'd0) && !more_frag && (tot_len >= 16'd28);
                        pl_len <= tot_len - 16'd28;
                    end
                    8'd3: dst_ip_hi <= {s_tdata[55:48], s_tdata[63:56]};
                    8'd4: begin
                        accept  <= mac_ok && eth_ok && ip_ok && ((UDP_PORT == 16'd0) || (dport == UDP_PORT)) && ((DST_IP == 32'd0) || (dst_ip == DST_IP));
                        remaining <= pl_len;
                    end
                    default: ;
                endcase

                // payload words: beat 5 holds payload bytes 0..5 (no word complete yet unless TLAST)
                if (widx >= 8'd6 && accept && remaining != 16'd0) begin
                    m_tvalid <= 1'b1;
                    m_tdata  <= realigned;
                    m_nbytes <= emit_nb;
                    m_fits   <= fits_of(realigned, emit_nb);
                    m_sof    <= !emitted_any;
                    emitted_any <= 1'b1;
                    remaining <= rem_after;
                    if (s_tlast) begin
                        if (rem_after == 16'd0) begin
                            m_eof <= 1'b1; m_bad <= !s_tuser;
                        end else if (tail_avail != 4'd0) begin
                            // more payload in bytes 2..7 of this last beat -> flush next cycle
                            need_flush <= 1'b1; flush_data <= tail_word; flush_nbytes <= tail_nb;
                            flush_bad <= !s_tuser || (rem_after > {12'd0, tail_avail});
                        end else begin
                            m_eof <= 1'b1; m_bad <= 1'b1;      // IP length promised more than the frame had
                        end
                    end else if (rem_after == 16'd0) begin
                        m_eof <= 1'b1; m_bad <= 1'b0;          // padding follows; we stop here (bad CRC cannot be known yet)
                    end
                end else if (widx == 8'd5 && s_tlast && accept && remaining != 16'd0) begin
                    // frame ends in the beat that starts the payload: payload bytes are 2..nb-1
                    if (tail_avail != 4'd0) begin
                        m_tvalid <= 1'b1; m_tdata <= tail_word; m_nbytes <= tail_nb; m_fits <= fits_of(tail_word, tail_nb);
                        m_sof <= 1'b1; m_eof <= 1'b1; m_bad <= !s_tuser || (remaining > {12'd0, tail_avail});
                    end
                end

                if (s_tlast) begin
                    widx <= 0;
                    st_frame <= 1'b1;
                    st_frame_crc_bad <= !s_tuser;
                    if (widx >= 8'd5 && accept && pl_len != 16'd0) begin
                        st_frame_pass <= 1'b1;
                        // truncated if the frame ends before `remaining` reaches 0 (eof word carries m_bad)
                        if (widx >= 8'd6) begin
                            if (rem_after != 16'd0 && rem_after > {12'd0, tail_avail}) st_frame_trunc <= 1'b1;
                        end else begin
                            if (remaining > {12'd0, tail_avail}) st_frame_trunc <= 1'b1;
                        end
                    end else begin
                        st_frame_filtered <= 1'b1;
                    end
                end
            end
        end
    end

endmodule
