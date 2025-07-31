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
