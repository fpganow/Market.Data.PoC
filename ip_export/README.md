# IP Export

LabVIEW PoC
- Export to Netlist
 -> /mnt/c/NIFPGA/compilation/.../source_files/
   NiFpgaAG_poc_ip.dcp
   NiFpgaIPWrapper_poc_ip.vhd
- Generate verilog from dcp file
- Copy to Xilin Vivado Project Directory
- Add:
  NiFpgaIPWrapper_poc_ip.vhd
  NiFpgaAG_poc_ip.v
- Add to Block Design

Vivado Block Design

xxv_ethernet_0
 tx_fifo -
         - axis2xgmii
 xgmii2axis -
            - rx_fifo_0
            - NiFpgaIPWrapper_poc_ip.vhd -
                                         - rx_fifo_1
                                         - rx_fifo_2

- GPIO_0 channel 0 -> Reset
- GPIO_0 channel 1 -> Enable
- 


# To run the LabVIEW FPGA IP, one needs to:


# [Hard coded] Set MAC Address
# [Hard coded] Set IP Address
# [Hard coded] Set Port
# Implement and use TREADY
# [Filter] Set Watchlist

## For now, just have to start sending Ethernet Frames

Simulation will load a Pcap file and load all ethernet frames meant for a specific target will be sent in to the Simulation

## Running on Hardware

There is a python script that can be used to transmit data directly to the target interface.

For actual runs, the UDP payload data will be read from a Pcap file and will be sent directly to the target interface with one UDP segment per Ethernet Frame.


Call BATS Pcap Message Generator with config file

Use Generated Pcap to run Simulation.
Use same file to run on live hardware.
Use utility to display the messages in the Pcap file in short and detailed form.

Makefile rule to regenerate the pcap file using associated config file
Makefile rule to display the short and detailed versions of the associated pcap file
