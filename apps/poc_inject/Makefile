# Cross-compile poc_inject for the KR260 (Ubuntu, aarch64). Same toolchain
# conventions as apps/poc_server (sudo apt install gcc-aarch64-linux-gnu).
TARGET := poc_inject
STATS  := xxv_stats
MON    := poc_mon
CC = aarch64-linux-gnu-gcc
CFLAGS ?= -O2 -Wall -Wextra -std=gnu11

REMOTE_HOST ?= kr260u
REMOTE_PATH ?= /home/ubuntu/
FRAME ?= generated_2025_05_02.hex

.PHONY: all clean deploy run

all: $(TARGET) $(STATS) $(MON)

$(TARGET): main.c
	$(CC) $(CFLAGS) -o $@ $<
	@file $@

# MAC frame counters since the previous tick (used by scripts/rate_sweep.py).
$(STATS): xxv_stats.c
	$(CC) $(CFLAGS) -o $@ $<

# axis_mon counters / sink mode via axi_gpio_mon (scripts/rate_sweep.py --sink).
$(MON): poc_mon.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET) $(STATS) $(MON)

deploy: $(TARGET) $(STATS) $(MON)
	scp $(TARGET) $(STATS) $(MON) $(FRAME) $(REMOTE_HOST):$(REMOTE_PATH)

# Inject one frame through the 10G TX -> PCS local loopback -> RX -> NI IP.
run: deploy
	ssh $(REMOTE_HOST) "sudo $(REMOTE_PATH)$(TARGET) $(REMOTE_PATH)$(FRAME)"
