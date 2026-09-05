# Cross-compile poc_server for the KR260 (Ubuntu, aarch64).
#
# Default toolchain is Debian/Ubuntu's g++-aarch64-linux-gnu package:
#   sudo apt install g++-aarch64-linux-gnu
# main.cpp uses only the C++ stdlib + standard Linux syscalls, so no Xilinx
# sysroot is needed. Override CXX=... if you want a different cross-g++
# (e.g. the PetaLinux SDK's aarch64-xilinx-linux-g++).

TARGET := poc_server

# CXX must be `=`, not `?=` -- make defines CXX=g++ as a built-in, so `?=`
# would silently keep the host x86_64 compiler and fail on the ARM64 inline
# asm (dsb) in main.cpp. `=` still allows `make CXX=...` from the command
# line, because command-line assignments outrank Makefile ones.
CXX = aarch64-linux-gnu-g++
CXXFLAGS ?= -O2 -Wall -Wextra -std=gnu++17

REMOTE_HOST ?= kr260u
REMOTE_PATH ?= /home/ubuntu/

.PHONY: all clean deploy run

all: $(TARGET)

$(TARGET): main.cpp
	$(CXX) $(CXXFLAGS) -pthread -o $@ $<
	@file $@

clean:
	rm -f $(TARGET)

deploy: $(TARGET)
	scp $(TARGET) $(REMOTE_HOST):$(REMOTE_PATH)

# Poll all three market-data FIFOs until Ctrl-C.
run: deploy
	ssh -t $(REMOTE_HOST) "sudo $(REMOTE_PATH)$(TARGET) poll"
