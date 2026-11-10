// 100 MHz Cboe PITCH parser: the equivalent of bats.parser.vi + add.data.to.buffer /
// compress.buffer + the message.types/*.vi decoders.
//
// Byte window W (64 bytes, byte i in W[8i+7:8i], W[i] == 0 for i >= L; messages longer
// than 56 bytes take the SKIP path, all decoded PITCH types are <= 47). Each cycle it
// can both append one input word (at byte L) and consume one unit from the head:
//   HDR : 8-byte Sequenced Unit Header  -> DEBUG header record
//   MSG : one message of W[0] bytes      -> CMD record (+ DEBUG and MDEBUG records)
//   SKIP: the rest of a message longer than the window (unsupported type)
// A frame's first word (sof) resets the window: every frame starts with a header
// (Cboe spec), which also discards leftovers of truncated or over-long frames.
// recv.time of a message is the timestamp of the input word that completed it; a small
// queue keeps (end position in W, timestamp) per inserted word to look it up.
// This is the fix for todo.txt item 19: in the LabVIEW parser a message emitted in a
// stalled cycle (no new input word) carries recv.time 0 because the stamp travels with the
// input word; here the stamp stays queued with the bytes, so a message consumed any number
// of cycles after its last byte arrived (stall, back-pressure, two messages in one word)
// still reports the tick at which that byte was received. Sim 2026-10-20: 0 zero stamps in
// 2183 records; the LabVIEW netlist shows 3 per pcap.
module pitch_parser (
    input               clk,
    input               rst,
    input               in_valid,
    input      [63:0]   in_data,
    input      [3:0]    in_nbytes,
    input               in_sof,
    input      [63:0]   in_ts,
    output              in_ready,
    input      [63:0]   time_now,
    output reg          cmd_wen,
    output reg [1023:0] cmd_rec,
    input               cmd_afull,
    output reg          dbg_wen,
    output reg [255:0]  dbg_rec,
    output reg          mdbg_wen,
    output reg [255:0]  mdbg_rec
);
    localparam S_HDR = 2'd0, S_MSG = 2'd1, S_SKIP = 2'd2;

    reg [1:0]   state   = S_HDR;
    reg [511:0] W       = 0;
    reg [6:0]   L       = 0;        // bytes in the window, 0..64
    reg [15:0]  hdr_len = 0;        // Sequenced Unit Header: length of the whole unit
    reg [15:0]  total   = 0;        // bytes of the unit consumed so far
    reg [15:0]  skip_rem = 0;
    reg         drop    = 0;        // discard input until the next sof
    reg [31:0]  seq     = 0;

    // ---------------- head of window: what can be consumed this cycle ----------------
    wire [7:0] b0 = W[7:0];         // message length
    wire [7:0] b1 = W[15:8];        // message type
    reg  [6:0] c;                   // bytes consumed this cycle
    reg        do_hdr, do_msg, do_skip, bad_len, partial;
    wire [15:0] skip_min = ({9'd0, L} < skip_rem) ? {9'd0, L} : skip_rem;

    always @* begin
        c = 7'd0; do_hdr = 0; do_msg = 0; do_skip = 0; bad_len = 0; partial = 0;
        case (state)
            S_HDR: if (L >= 7'd8) begin c = 7'd8; do_hdr = 1; end
            S_MSG: if (L != 7'd0) begin
                if (b0 == 8'd0) bad_len = 1;
                else if (!cmd_afull) begin
                    if (b0 <= 8'd56 && L >= b0[6:0]) begin c = b0[6:0]; do_msg = 1; end
                    else if (b0 > 8'd56)              begin c = L;       do_msg = 1; partial = 1; end
                end
            end
            S_SKIP: if (L != 7'd0) begin c = skip_min[6:0]; do_skip = 1; end
            default: ;
        endcase
    end

    wire [15:0] hdr_len_new = {b1, b0};
    wire [15:0] total_new   = total + {8'd0, b0};
    wire [15:0] skip_new    = skip_rem - {9'd0, c};
    // the unit is complete: back to HDR and discard the rest of the frame
    wire finish = (do_hdr  && hdr_len_new <= 16'd8)
               || (do_msg  && !partial && total_new >= hdr_len)
               || (do_skip && skip_new == 16'd0 && total >= hdr_len);

    // ---------------- timestamp queue (end position, ts) per inserted word -----------
    reg [6:0]  q_end [0:15];
    reg [63:0] q_ts  [0:15];
    reg [4:0]  q_head = 0, q_tail = 0;
    wire [4:0] q_count = q_tail - q_head;
    wire       q_room  = (q_count < 5'd14);
    reg  [15:0] rel_consumed, rel_complete;
    reg  [4:0]  pop;
    reg  [3:0]  recv_rel;
    reg  [3:0]  qi;
    reg         found_pop, found_rel;
    integer i;
    always @* begin
        for (i = 0; i < 16; i = i + 1) begin
            qi = q_head[3:0] + i[3:0];
            rel_consumed[i] = (i < q_count) && (q_end[qi] <= c);
            rel_complete[i] = (i < q_count) && (q_end[qi] >= c);
        end
        pop = 5'd16; found_pop = 0;
        for (i = 0; i < 16; i = i + 1)
            if (!found_pop && !rel_consumed[i]) begin pop = i; found_pop = 1; end
        recv_rel = 4'd0; found_rel = 0;
        for (i = 0; i < 16; i = i + 1)
            if (!found_rel && rel_complete[i]) begin recv_rel = i; found_rel = 1; end
    end
    wire [3:0]  recv_idx = q_head[3:0] + recv_rel;
    wire [63:0] recv_ts  = q_ts[recv_idx];

    // ---------------- insertion ----------------
    // something at the head still has to be consumed (possibly stalled by cmd_afull):
    // a frame start must wait for it instead of clearing the window
    wire pending = (state == S_HDR  && L >= 7'd8)
                || (state == S_MSG  && L != 7'd0 && b0 != 8'd0 && (b0 > 8'd56 || L >= b0[6:0]))
                || (state == S_SKIP && L != 7'd0);
    wire sof_clear  = in_valid && in_sof && !pending;
    wire clear_junk = bad_len && !sof_clear;
    wire ins = in_valid && (in_sof ? !pending
                                   : (!drop && !bad_len && !finish && (L <= 7'd56) && q_room));
    assign in_ready = ins || (in_valid && !in_sof && (drop || clear_junk));
    wire        clear   = sof_clear || clear_junk || finish;
    wire [6:0]  ins_pos = sof_clear ? 7'd0 : (L - c);
    wire [6:0]  L_next  = (clear && !sof_clear) ? 7'd0 : (ins_pos + (ins ? {3'd0, in_nbytes} : 7'd0));
    reg  [63:0] in_masked;
    integer j;
    always @* for (j = 0; j < 8; j = j + 1) in_masked[8*j +: 8] = (j < in_nbytes) ? in_data[8*j +: 8] : 8'd0;
    wire [511:0] W_shift = clear ? 512'd0 : (W >> {c, 3'b000});
    wire [511:0] W_ins   = {448'd0, in_masked} << {ins_pos, 3'b000};

    // ---------------- stage B: one consumed unit per cycle, decoded next cycle --------
    reg         m_v = 0, m_hdr = 0, m_partial = 0;
    reg [383:0] m_bytes = 0;
    reg [7:0]   m_len = 0, m_type = 0;
    reg [63:0]  m_ts = 0;
    reg [6:0]   m_L = 0;
    reg [15:0]  m_hlen = 0;
    reg         rst_d = 1;

    always @(posedge clk) begin
        rst_d <= rst;
        if (rst) begin
            state <= S_HDR; W <= 0; L <= 0; hdr_len <= 0; total <= 0; skip_rem <= 0; drop <= 0;
            q_head <= 0; q_tail <= 0; m_v <= 0;
        end else begin
            // window
            W <= ins ? (W_shift | W_ins) : W_shift;
            L <= L_next;
            // state
            if (sof_clear) begin
                state <= S_HDR; total <= 0; skip_rem <= 0; drop <= 1'b0;
            end else if (clear_junk) begin
                state <= S_HDR; drop <= 1'b1;
            end else if (do_hdr) begin
                hdr_len <= hdr_len_new; total <= 16'd8;
                if (finish) begin state <= S_HDR; drop <= 1'b1; end else state <= S_MSG;
            end else if (do_msg) begin
                total <= total_new;
                if (partial) begin state <= S_SKIP; skip_rem <= {8'd0, b0} - {9'd0, L}; end
                else if (finish) begin state <= S_HDR; drop <= 1'b1; end
                else state <= S_MSG;
            end else if (do_skip) begin
                skip_rem <= skip_new;
                if (skip_new == 16'd0) begin
                    if (finish) begin state <= S_HDR; drop <= 1'b1; end else state <= S_MSG;
                end
            end
            // timestamp queue
            if (clear) begin
                q_head <= 0; q_tail <= 0;
                if (ins) begin q_end[0] <= {3'd0, in_nbytes}; q_ts[0] <= in_ts; q_tail <= 5'd1; end
            end else begin
                if (c != 7'd0) begin
                    q_head <= q_head + pop;
                    for (i = 0; i < 16; i = i + 1) q_end[i] <= q_end[i] - c;
                end
                if (ins) begin
                    q_end[q_tail[3:0]] <= ins_pos + {3'd0, in_nbytes};
                    q_ts[q_tail[3:0]]  <= in_ts;
                    q_tail <= q_tail + 5'd1;
                end
            end
            // hand the consumed unit to the decode stage
            m_v <= do_hdr || do_msg;
            m_hdr <= do_hdr;
            m_partial <= partial;
            m_bytes <= W[383:0];
            m_len <= b0; m_type <= b1; m_L <= L; m_hlen <= hdr_len_new;
            m_ts <= recv_ts;
        end
    end


`ifdef PARSER_TRACE
    always @(posedge clk) if (!rst && (in_valid || c != 0 || m_v))
        $display("P st=%0d L=%0d c=%0d b0=%0d b1=%02x ins=%b sof=%b n=%0d rdy=%b drop=%b afull=%b fin=%b dh=%b dm=%b mv=%b qh=%0d qt=%0d pop=%0d room=%b W0=%016x",
                 state, L, c, b0, b1, ins, in_sof, in_nbytes, in_ready, drop, cmd_afull, finish, do_hdr, do_msg, m_v, q_head, q_tail, pop, q_room, W[63:0]);
    always @(posedge clk) if (!rst && ins)
        $display("I pos=%0d n=%0d data=%016x masked=%016x W_ins[127:64]=%016x W_ins[63:0]=%016x", ins_pos, in_nbytes, in_data, in_masked, W_ins[127:64], W_ins[63:0]);
    always @(posedge clk) if (!rst && do_msg)
        $display("X W1=%016x W2=%016x W3=%016x W4=%016x W5=%016x", W[127:64], W[191:128], W[255:192], W[319:256], W[383:320]);
`endif
    // ---------------- decode ----------------
    function [63:0] bswap64; input [63:0] x; integer k;
        begin for (k = 0; k < 8; k = k + 1) bswap64[8*k +: 8] = x[8*(7-k) +: 8]; end
    endfunction
    // the message bytes are an explicit argument: Verilog-2001 @* does not see signals read
    // inside a function, so a function reading m_bytes directly would make the block stale
    function [63:0] le16;  input [383:0] b; input [5:0] o; begin le16  = {48'd0, b[8*o +: 16]}; end endfunction
    function [63:0] le32;  input [383:0] b; input [5:0] o; begin le32  = {32'd0, b[8*o +: 32]}; end endfunction
    function [63:0] le64;  input [383:0] b; input [5:0] o; begin le64  = b[8*o +: 64]; end endfunction
    function [63:0] sym6;  input [383:0] b; input [5:0] o; begin sym6  = {16'h2020, b[8*o +: 48]}; end endfunction
    function [63:0] byte8; input [383:0] b; input [5:0] o; begin byte8 = {56'd0, b[8*o +: 8]}; end endfunction
    function [63:0] px100; input [383:0] b; input [5:0] o; reg [63:0] v;   // short prices: 2 -> 4 implied decimals
        begin v = {48'd0, b[8*o +: 16]}; px100 = (v << 6) + (v << 5) + (v << 2); end
    endfunction

    reg [63:0] r_type, r_side, r_oid, r_qty, r_sym, r_price, r_exec, r_canc, r_rem, r_sec, r_ns, r_flags;
    always @* begin
        r_type = 64'd11; r_side = 0; r_oid = 0; r_qty = 0; r_sym = 0; r_price = 0; r_exec = 0;
        r_canc = 0; r_rem = 0; r_sec = 0; r_ns = 0; r_flags = 0;
        if (!m_partial) case (m_type)
            8'h20: begin r_type = 0;  r_sec = le32(m_bytes, 2); end
            8'h21: begin r_type = 1;  r_flags = 1; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le32(m_bytes, 15); r_sym = sym6(m_bytes, 19); r_price = le64(m_bytes, 25); end
            8'h22: begin r_type = 1;  r_flags = 1; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le16(m_bytes, 15); r_sym = sym6(m_bytes, 17); r_price = px100(m_bytes, 23); end
            8'h2F: begin r_type = 1;  r_flags = 1; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le32(m_bytes, 15); r_sym = le64(m_bytes, 19); r_price = le64(m_bytes, 27); end
            8'h23: begin r_type = 2;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_exec = le32(m_bytes, 14); end
            8'h24: begin r_type = 3;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_exec = le32(m_bytes, 14); r_rem = le32(m_bytes, 18); r_price = le64(m_bytes, 30); end
            8'h25: begin r_type = 4;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_canc = le32(m_bytes, 14); end
            8'h26: begin r_type = 4;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_canc = le16(m_bytes, 14); end
            8'h27: begin r_type = 5;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_qty = le32(m_bytes, 14); r_price = le64(m_bytes, 18); end
            8'h28: begin r_type = 5;  r_flags = 2; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_qty = le16(m_bytes, 14); r_price = px100(m_bytes, 16); end
            8'h29: begin r_type = 6;  r_flags = 4; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); end
            8'h2A: begin r_type = 10; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le32(m_bytes, 15); r_sym = sym6(m_bytes, 19); r_price = le64(m_bytes, 25); end
            8'h2B: begin r_type = 10; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le16(m_bytes, 15); r_sym = sym6(m_bytes, 17); r_price = px100(m_bytes, 23); end
            8'h30: begin r_type = 10; r_ns = le32(m_bytes, 2); r_oid = le64(m_bytes, 6); r_side = byte8(m_bytes, 14); r_qty = le32(m_bytes, 15); r_sym = le64(m_bytes, 19); r_price = le64(m_bytes, 27); end
            default: ;
        endcase
    end

    wire [63:0] first8 = bswap64(m_bytes[63:0]);     // stream byte 0 in the MSB, as the LabVIEW DEBUG records
    wire        push_msg = m_v && !m_hdr;
    wire        push_hdr = m_v && m_hdr;
    wire        rst_release = rst_d && !rst;

    always @(posedge clk) begin
        cmd_wen  <= push_msg;
        mdbg_wen <= push_msg;
        dbg_wen  <= push_msg || push_hdr || rst_release;
        if (rst) seq <= 32'd0; else if (push_msg) seq <= seq + 32'd1;
        cmd_rec <= {64'h00000000DEADBEEF, time_now, m_ts, {32'd0, seq + 32'd1}, r_flags, r_ns, r_sec,
                    r_rem, r_canc, r_exec, r_price, r_sym, r_qty, r_oid, r_side, r_type};
        mdbg_rec <= {{57'd0, m_L}, {56'd0, m_type}, {56'd0, m_len}, time_now};
        if (rst_release)  dbg_rec <= {64'd2, 64'd1, 64'd0, 64'h000000000000AAAB};
        else if (push_hdr) dbg_rec <= {64'd0, first8, {48'd0, m_hlen}, {24'd0, 8'hDE, 16'd0, m_hlen}};
        else               dbg_rec <= {64'h99, 64'd0, 64'd0, first8};
    end
endmodule
