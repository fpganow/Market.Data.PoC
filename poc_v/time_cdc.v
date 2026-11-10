// Carries the 156.25 MHz free-running tick counter into the 100 MHz domain.
// A req/ack toggle handshake snapshots the counter; between snapshots the 100 MHz
// side extrapolates by 25/16 ticks per cycle (156.25 / 100). CORR compensates the
// handshake latency (measured in xsim: a snapshot is ~5 ticks old when it lands).
module time_cdc #(
    parameter [7:0] CORR = 8'd5
) (
    input         clk156,
    input         rst156,
    input  [63:0] ts156,
    input         clk100,
    input         rst100,
    output [63:0] time100
);
    // 100 MHz side
    reg        req = 0, busy = 0;
    reg        ack_s1 = 0, ack_s2 = 0, ack_prev = 0;
    reg [63:0] snap = 0;
    reg [15:0] age16 = 0;              // elapsed since snapshot, in 1/16 tick
    // 156 MHz side
    reg        req_s1 = 0, req_s2 = 0, req_prev = 0;
    reg [63:0] cap = 0;
    reg        ack = 0;

    always @(posedge clk156) begin
        if (rst156) begin
            req_s1 <= 0; req_s2 <= 0; req_prev <= 0; ack <= 0; cap <= 0;
        end else begin
            req_s1 <= req; req_s2 <= req_s1; req_prev <= req_s2;
            if (req_s2 != req_prev) begin
                cap <= ts156;
                ack <= ~ack;
            end
        end
    end

    always @(posedge clk100) begin
        if (rst100) begin
            req <= 0; busy <= 0; ack_s1 <= 0; ack_s2 <= 0; ack_prev <= 0;
            snap <= 0; age16 <= 0;
        end else begin
            ack_s1 <= ack; ack_s2 <= ack_s1; ack_prev <= ack_s2;
            if (!busy) begin
                req  <= ~req;
                busy <= 1'b1;
            end
            if (ack_s2 != ack_prev) begin
                snap  <= cap;
                age16 <= 16'd0;
                busy  <= 1'b0;
            end else begin
                age16 <= age16 + 16'd25;
            end
        end
    end

    assign time100 = snap + {52'd0, age16[15:4]} + {56'd0, CORR};
endmodule
