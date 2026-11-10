`timescale 1ns / 1ps
// pitch_extract -- splits the re-aligned UDP payload stream into Cboe PITCH
// messages, one 64-bit word per clock, one message out per clock.
//
// This is the part the LabVIEW parser (bats.parser.vi: add.data.to.buffer /
// compress.buffer / Read.Msg, 6-9 cycles per message at 100 MHz) spends its
// time on. Here it runs in the 156.25 MHz receive clock and keeps up with
// 10 Gbit/s: every input word is consumed in one cycle except when a second
// message also ENDS inside the same word (only possible for messages shorter
// than 8 bytes, i.e. Time), which costs one extra cycle for that word.
//
// Frame rule (Cboe spec, and the 2026-09-22 LabVIEW fix): every UDP payload
// starts with an 8-byte Sequenced Unit Header, so the accumulator is cleared
// at `w_sof`. Messages cut by the end of a frame are counted (`st_trunc`) and
// discarded, a length byte outside 2..MAXB discards the rest of the frame
// (`st_bad_len`).
//
// Data path: `acc` holds the bytes of the message in progress, left-aligned
// (byte 0 = length byte). Each cycle the current word is placed at byte
// position acc_len-off (a registered shift, so the 48 byte-muxes are
// controlled by registered signals) and merged; if the message ends inside
// this word it is emitted and the word's tail becomes the next message's
// head in the same cycle. The "two messages end in one word" test uses the
// `w_fits` bits precomputed by eth_rx_filter, so it is a 1-bit mux.
//
// `en` freezes the whole stage (downstream back-pressure).

module pitch_extract #(
    parameter MAXB = 48                     // longest message accepted (PITCH max is 43)
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              en,
    // word stream (first-word-fall-through FIFO head)
    input  wire [63:0]       w_data,
    input  wire [3:0]        w_nbytes,
    input  wire              w_sof,
    input  wire              w_eof,
    input  wire              w_bad,
    input  wire [7:0]        w_fits,
    input  wire              w_valid,
    output wire              w_rd,
    input  wire [31:0]       time10,
    // message out, registered
    output reg               m_valid,
    output reg  [8*MAXB-1:0] m_bytes,
    output reg  [7:0]        m_len,
    output reg  [31:0]       m_seq,          // Sequenced Unit Header sequence + index in frame
    output reg  [7:0]        m_unit,
    output reg  [31:0]       m_recv_time,    // time10 at the frame's first payload word
    // Sequenced Unit Header out, registered
    output reg               h_valid,
    output reg  [63:0]       h_bytes,
    output reg  [31:0]       h_recv_time,
    // statistics pulses
    output reg               st_trunc,       // message (or header) cut by end of frame
    output reg               st_bad_len,     // length byte outside 2..MAXB; rest of frame skipped
    output reg               st_frame_bad    // eof word flagged bad by the filter (CRC / short)
);

    // ------------------------------------------------------------------
    // state
    // ------------------------------------------------------------------
    reg [8*MAXB-1:0] acc;
    reg [5:0]        acc_len;
    reg              in_hdr;
    reg [2:0]        off;            // byte offset of the next message in the held word (hold case)
    reg [7:0]        start_len;      // its length byte, captured when the hold was decided
    reg [7:0]        msg_len;        // length of the message in progress (acc_len != 0)
    reg signed [6:0] s_reg;          // acc_len - off: where the word's byte 0 lands in acc
    reg [31:0]       hdr_seq;
    reg [7:0]        unit;
    reg [7:0]        msg_idx;
    reg [31:0]       recv_time;
    reg              skipping;

    // effective values for this cycle (a sof word restarts everything)
    wire [5:0]        e_acc_len = w_sof ? 6'd0 : acc_len;
    wire              e_in_hdr  = w_sof ? 1'b1 : in_hdr;
    wire [2:0]        e_off     = w_sof ? 3'd0 : off;
    wire              e_skip    = w_sof ? 1'b0 : skipping;
    wire signed [6:0] e_s       = w_sof ? 7'sd0 : s_reg;
    wire [31:0]       e_recv    = w_sof ? time10 : recv_time;

    wire [3:0] nb    = w_nbytes;
    wire [3:0] avail = nb - {1'b0, e_off};

    wire [7:0] len = e_in_hdr ? 8'd8 :
                     (e_acc_len == 6'd0) ? ((e_off == 3'd0) ? w_data[7:0] : start_len) : msg_len;
    wire       len_ok   = e_in_hdr || ((len >= 8'd2) && (len <= MAXB));
    wire [7:0] need     = len - {2'd0, e_acc_len};
    wire       complete = (need <= {4'd0, avail});
    wire [3:0] end_pos  = {1'b0, e_off} + need[3:0];         // <= 8 when complete
    wire [3:0] leftover = nb - end_pos;
    wire       fits_next = (end_pos < 4'd8) ? w_fits[end_pos[2:0]] : 1'b0;

    // the word placed at byte position e_s and merged with the accumulator
    reg [8*MAXB-1:0] merged;
    integer k;
    reg signed [7:0] sel;
    always @* begin
        merged = acc;
        for (k = 0; k < MAXB; k = k + 1) begin
            sel = k - e_s;
            if (k >= e_acc_len) begin
                if (sel >= 0 && sel <= 7) merged[k*8 +: 8] = w_data[sel[2:0]*8 +: 8];
                else                      merged[k*8 +: 8] = 8'h00;
            end
        end
    end

    // the word's tail (bytes end_pos..nb-1) moved to byte 0: head of the next message
    reg [63:0] tail;
    reg [3:0]  tsel;
    always @* begin
        for (k = 0; k < 8; k = k + 1) begin
            tsel = k + end_pos;
            tail[k*8 +: 8] = (tsel < 4'd8) ? w_data[tsel[2:0]*8 +: 8] : 8'h00;
        end
    end
    wire [7:0] next_len = tail[7:0];        // length byte of the message starting at end_pos

    wire go = w_valid & en;

    // read the word unless we hold it for a second message ending inside it
    wire hold = go & ~e_skip & len_ok & complete & (leftover != 4'd0) & ~w_eof & fits_next;
    assign w_rd = go & ~hold;

    always @(posedge clk) begin
        if (!rst_n) begin
            acc <= 0; acc_len <= 0; in_hdr <= 1'b1; off <= 0; start_len <= 0; msg_len <= 0; s_reg <= 0;
            hdr_seq <= 0; unit <= 0; msg_idx <= 0; recv_time <= 0; skipping <= 1'b0;
            m_valid <= 1'b0; m_bytes <= 0; m_len <= 0; m_seq <= 0; m_unit <= 0; m_recv_time <= 0;
            h_valid <= 1'b0; h_bytes <= 0; h_recv_time <= 0;
            st_trunc <= 1'b0; st_bad_len <= 1'b0; st_frame_bad <= 1'b0;
        end else if (en) begin
            m_valid <= 1'b0; h_valid <= 1'b0;
            st_trunc <= 1'b0; st_bad_len <= 1'b0; st_frame_bad <= 1'b0;
            if (w_valid) begin
                recv_time <= e_recv;
                if (w_eof & w_bad) st_frame_bad <= 1'b1;
                if (e_skip) begin
                    skipping <= ~w_eof;
                    acc_len <= 0; in_hdr <= 1'b1; off <= 0; s_reg <= 0;
                end else if (!len_ok) begin
                    st_bad_len <= 1'b1;
                    skipping <= ~w_eof;
                    acc_len <= 0; in_hdr <= 1'b1; off <= 0; s_reg <= 0;
                end else if (complete) begin
                    if (e_in_hdr) begin
                        h_valid <= 1'b1; h_bytes <= merged[63:0]; h_recv_time <= e_recv;
                        hdr_seq <= merged[63:32];          // bytes 4..7 little-endian
                        unit    <= merged[31:24];          // byte 3
                        msg_idx <= 0;
                    end else begin
                        m_valid <= 1'b1; m_bytes <= merged; m_len <= len;
                        m_seq <= hdr_seq + {24'd0, msg_idx}; m_unit <= unit; m_recv_time <= e_recv;
                        msg_idx <= msg_idx + 1;
                    end
                    in_hdr <= 1'b0;
                    if (leftover == 4'd0) begin
                        acc_len <= 0; off <= 0; s_reg <= 0;
                        if (w_eof) in_hdr <= 1'b1;
                    end else if (w_eof) begin
                        st_trunc <= 1'b1;                  // bytes after the last message: a cut message
                        acc_len <= 0; off <= 0; s_reg <= 0; in_hdr <= 1'b1;
                    end else if (fits_next) begin
                        // hold the word: next message starts at end_pos and ends inside this word
                        off <= end_pos[2:0]; start_len <= next_len; acc_len <= 0;
                        s_reg <= -$signed({3'd0, end_pos});
                    end else begin
                        acc <= {{(8*(MAXB-8)){1'b0}}, tail};
                        acc_len <= {2'd0, leftover}; msg_len <= next_len; off <= 0;
                        s_reg <= $signed({3'd0, leftover});
                    end
                end else begin
                    // message continues into the next word
                    acc <= merged;
                    msg_len <= len; off <= 0;
                    if (w_eof) begin
                        st_trunc <= 1'b1;
                        acc_len <= 0; s_reg <= 0; in_hdr <= 1'b1;
                    end else begin
                        acc_len <= e_acc_len + {2'd0, avail};
                        s_reg <= $signed({1'b0, e_acc_len + {2'd0, avail}});
                        in_hdr <= e_in_hdr;
                    end
                end
            end
        end
    end

endmodule
