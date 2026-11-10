VIVADO    ?= /tools/Xilinx/Vivado/2024.1/bin/vivado
PROJ_NAME  = mktdata_rtl
XPR        = $(PROJ_NAME)/$(PROJ_NAME).xpr
XSA        = $(PROJ_NAME).xsa
JOBS      ?= 4
STRATEGY  ?=

.PHONY: project xsa xsa-clean gui sim help

help:
	@echo "Pure-RTL bitstream (vivado_rtl/, project $(PROJ_NAME)):"
	@echo "  make project   - Recreate the Vivado project from mktdata_rtl.tcl (no build)"
	@echo "  make gui       - Create the project if needed and open it in the Vivado GUI"
	@echo "  make xsa       - project + synthesis + implementation + XSA with bitstream (~12 min, run detached)"
	@echo "  make xsa-clean - Remove the project dir, XSA and logs"
	@echo "  make sim       - xsim the parser on tests/data/generated_2026_09_17_multi.pcap and score it"
	@echo "Variables: JOBS=N  STRATEGY=<impl strategy>  VIVADO=<path>"

project: $(XPR)

$(XPR):
	$(VIVADO) -mode batch -source $(PROJ_NAME).tcl \
		-log create_project.log -journal create_project.jou

xsa: $(XSA)

$(XSA): $(XPR)
	$(VIVADO) -mode batch -log build.log -journal build.jou \
		-source build.tcl -tclargs $(JOBS) $(STRATEGY)

gui: $(XPR)
	$(VIVADO) $(XPR) &

sim:
	./sim/run.sh

xsa-clean:
	rm -rf $(PROJ_NAME) $(XSA) *.log *.jou .Xil
