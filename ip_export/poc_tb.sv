`timescale 1ns / 1ps

`include "./sim/pysv_pkg.sv"
import pysv::*;

//////////////////////////////////////////////////////////////////////////////////
// 
// Create Date: 03/16/2021 09:23:26 PM
// Module Name: poc_tb
// Description: 
// 
// 
//////////////////////////////////////////////////////////////////////////////////

module poc_tb();

    // 10ns = 100 MHz
    // 20ns = 50 MHz
    // 25ns = 40MHz
    // duration for each bit = 20 * timescale = 20 * 1 ns = 20 ns
    localparam period = 25;
    localparam duty_cycle = period / 2;

    reg clk;

    // Generate 40MHz Clock
    always
    begin
        clk = 1'b0;
        #duty_cycle;

        clk = 1'b1;
        #duty_cycle;
    end

    longint unsigned my_fifo_array[][4];
    int my_fifo_len = 0;
    int index = 0;
    longint unsigned debug_data[4];

    // Poll DEBUG FIFO
    always @(posedge clk)
    begin
        if (out_debug_fifo_tvalid == 1)
        begin
            debug_data[index] = out_debug_fifo_tdata;
            if (index == 3)
            begin
                my_fifo_array = new[my_fifo_array.size() + 1](my_fifo_array);
                my_fifo_array[my_fifo_len] = debug_data;
                my_fifo_len += 1;
                index = 0;
                $display("%6d\tDEBUG\t0x%x 0x%x 0x%x 0x%x",
                            $time,
                            debug_data[0],
                            debug_data[1],
                            debug_data[2],
                            debug_data[3]);
            end
            else
            begin
                index += 1;
            end
            //$display("%6d\tDEBUG\t0x%x",
            //                $time,
            //                out_debug_fifo_tdata);
        end
    end

    // Poll CMD FIFO
    always @(posedge clk)
    begin
        if (out_cmd_fifo_tvalid == 1)
        begin
            $display("%6d\tCMD\t0x%x",
                            $time,
                            out_cmd_fifo_tdata);
        end
    end

    // Variables for NiFpgaIPWrapper_bats_parser_ip
    // reset: asynchronous reset (active high)
    // enable_in: Must be synchronous to base clock.  Assert to
    //            start running the IP, must remain asserted
    //            when the IP is running.  Deassert when resetting
    //            the IP.
    // enable_out: Ignore this for free running IP. Otherwise it is
    //             asserted when the IP has stopped.
    // enable_clr: Assert for one cycle to prepare IP for a single shot.
    // AUTO_GENERATED_CODE_START: parse.py ['./NiFpgaIPWrapper_bats_parser_ip.vhd']
    // Source file: ./NiFpgaIPWrapper_bats_parser_ip.vhd
    // Variables for NiFpgaIPWrapper_bats_parser_ip
    reg              reset;
    reg              enable_in;
    wire             enable_out;
    reg              enable_clr;
    // CMD_FIFO
    reg    [ 0:0]    out_cmd_fifo_tvalid;
    reg    [ 0:0]    out_cmd_fifo_tlast;
    reg    [ 7:0]    out_cmd_fifo_tkeep;
    reg    [63:0]    out_cmd_fifo_tdata;
    // DEBUG_FIFO
    reg    [ 0:0]    out_debug_fifo_tvalid;
    reg    [ 0:0]    out_debug_fifo_tlast;
    reg    [ 7:0]    out_debug_fifo_tkeep;
    reg    [63:0]    out_debug_fifo_tdata;
    // Input
    reg    [ 0:0]    in_data_tuser;
    reg    [ 0:0]    in_data_tlast;
    reg    [ 0:0]    in_data_tvalid;
    reg    [ 7:0]    in_data_tkeep;
    reg    [63:0]    in_data_tdata;
    // IP Reset
    reg    [ 0:0]    in_ip_reset;

	NiFpgaAG_poc_ip UUT (
        .reset(reset),
        .enable_in(enable_in),
        .enable_out(enable_out),
        .enable_clr(enable_clr),
        // Outputs
        .ctrlind_00_CMD_TVALID(out_cmd_fifo_tvalid),
        .ctrlind_01_CMD_TLAST(out_cmd_fifo_tlast),
        .ctrlind_02_CMD_TKEEP(out_cmd_fifo_tkeep),
        .ctrlind_03_CMD_TDATA(out_cmd_fifo_tdata),
        .ctrlind_04_DEBUG_TVALID(out_debug_fifo_tvalid),
        .ctrlind_05_DEBUG_TLAST(out_debug_fifo_tlast),
        .ctrlind_06_DEBUG_TKEEP(out_debug_fifo_tkeep),
        .ctrlind_07_DEBUG_TDATA(out_debug_fifo_tdata),
        // Inputs
        .ctrlind_08_TUSER(in_data_tuser),
        .ctrlind_09_TLAST(in_data_tlast),
        .ctrlind_10_TVALID(in_data_tvalid),
        .ctrlind_11_TKEEP(in_data_tkeep),
        .ctrlind_12_TDATA(in_data_tdata),
        // Clocks & Reset & Enable
        .ctrlind_13_ip_reset(in_ip_reset),
        .Clk40Derived168x43B56_28MHz(clk),
        .tDiagramEnableOut(1)
    );

    // Main Thread
    initial
    begin
        MyList my_list;
        Pcap pcap;
        EthernetFrame eth_frame = new();

        // Set default control signal values
        reset = 0;
        enable_in = 1;
        enable_clr = 0;
        in_ip_reset = 0;
        // Default values for Data
        in_data_tlast = 0;
        in_data_tvalid = 0;
        in_data_tkeep = 0;
        in_data_tdata = 0;

        // Reset IP
        reset = 1;
        #(period*10);
        $display("Reset IP");
        // reset : Reset port. Minimum assertion length: 8 base clock cycles.
        //         Minimum de-assertion length: 40 base clock cycles.
        // enable_in : Enable in port. Minimum re-initialization 
        //             length: 7 base clock cycles.

        // De-assertion of Reset IP
        reset = 0;
        #(period*45);

        // Enable IP
        reset = 0;
        //#enable_in = 1;
        #(period*10);

        // Reset IP - User
        in_ip_reset = 1;
        #(period*2);
        in_ip_reset = 0;

        // Configure IP

        // Send Pcap data in
        $display("+---------------------------------------------------------------------------------+");
        $display("|  Pcap Section                                                                   |");
        $display("+---------------------------------------------------------------------------------+");
        pcap = new("../../../../tests/data/generated_2025_05_02.pcap",
                "MAC", "IP", 8000);
        $display("|  # of Ethernet Frames: %2d", pcap.get_frame_count());

        #(duty_cycle*1);
        for (int i=0; i < pcap.get_frame_count(); i++)
        begin
            $display("| - Sending Ethernet Frame #%2d", (i+1));

            pcap.get_frame(eth_frame, i);
            $display("|    Length (bytes) %4d", eth_frame.get_length_bytes());
            $display("|    Details: %s", eth_frame.get_short());
            $display("|    # of Words: %d", eth_frame.get_number_of_words());
            for (int j=0; j < eth_frame.get_number_of_words(); j++)
            begin
                $display("%6d\tSEND\t0x%x\t0x%x",
                                  $time,
                                  eth_frame.get_word(j, 0),
                                  eth_frame.get_word_tkeep(j, 0));
                in_data_tuser = 1;
                if (j+1 == eth_frame.get_number_of_words())
                begin
                    in_data_tlast = 1;
                end
                else
                begin
                    in_data_tlast = 0;
                end

                in_data_tvalid = 1;
                in_data_tkeep = eth_frame.get_word_tkeep(j, 0);
                in_data_tdata = eth_frame.get_word(j, 0);

                // Keep values for 1 clock cycle
                #(period*1);
            end
        end

        // Reset values
        in_data_tlast = 0;
        in_data_tvalid = 0;
        in_data_tkeep = 0;
        in_data_tdata = 0;

        // Wait for CMD and DEBUG FIFOs to drain
        $display("Dumping FIFO Array");
        $display("my_fifo_len=%d", my_fifo_len);

        pysv_finalize();
        $display("+---------------------------------------------------------------------------------+");
        $display("|  Finished Testing PYSV                                                          |");
        $display("+---------------------------------------------------------------------------------+");

        $display("----------------------------------------------------------------");
        $display("  End of TEST BENCH  ");
        $display("----------------------------------------------------------------");
        // */

        $finish;
    end
endmodule
