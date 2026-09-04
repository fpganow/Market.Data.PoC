## KR260 has an issue where you need

https://xilinx.github.io/kria-apps-docs/creating_applications/2022.1/build/html/docs/bootmodes.html

From SDK/XSCT Console:
```
connect

# Switch to JTAG boot mode #
targets -set -filter {name =~ "PSU"}

# update multiboot to ZERO
mwr 0xffca0010 0x0

# change boot mode to JTAG
mwr 0xff5e0200 0x0100

# reset
rst -system
```

## To Restore Project from Vivado

This project was exported using Vivado v2024.1 (64-bit), to restore it do the following:

1. Open Vivado 2024.1
1. From the 'TCL Console' windows inside Vivado, navigate to this directory:

```
cd C:/work/fpganow/Market.Data.PoC/vivado/kr260/poc_kr260/
```

1. Source the TCL script ```poc_kr260.tcl```:

```
source ./poc_kr260.tcl
```

Ignore any error about importing ```design_1_wrapper.dcp```, I don't know why Vivado includes this file when exporting.

## Current Project Status

Project has a mini-Ethernet MAC copied from NetFPGA, see the ```my_hdl``` directory.

A Vitis SDK project will read raw Ethernet Packets if you read the Axi DMA channel #0.

## Todo:

[] Import LabVIEW
[] Dump Normalized Market Data Messages to console
