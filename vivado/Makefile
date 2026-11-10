VIVADO    ?= /tools/Xilinx/Vivado/2024.1/bin/vivado
PROJ_NAME  = mktdata_poc
XPR        = $(PROJ_NAME)/$(PROJ_NAME).xpr
XSA        = $(PROJ_NAME).xsa
JOBS      ?= 4
# impl_1 strategy (build.tcl default: Performance_ExplorePostRoutePhysOpt; the NI parser
# loop fails 100 MHz by ~0.3 ns under Vivado's default strategy since axis_mon was added).
STRATEGY  ?=

.PHONY: project gui xsa xsa-clean help

help:
	@echo "Targets:"
	@echo "  project   - Recreate the Vivado project from mktdata_poc.tcl (no build), to inspect it"
	@echo "  gui       - Create the project if needed and open it in the Vivado GUI"
	@echo "  xsa       - Create project, run synthesis/implementation, export XSA with bitstream"
	@echo "  xsa-clean - Remove all generated build artifacts (project dir, XSA, logs)"
	@echo ""
	@echo "Variables:"
	@echo "  JOBS=N    - Number of parallel jobs for synthesis/implementation (default: 4)"
	@echo "  STRATEGY= - impl_1 strategy name (default in build.tcl: Performance_ExplorePostRoutePhysOpt)"
	@echo "  reimpl.tcl - re-run implementation only on an existing project: vivado -mode batch -source reimpl.tcl -tclargs 8 [Strategy]"
	@echo "  VIVADO=   - Path to Vivado executable (default: $(VIVADO))"

project: $(XPR)

gui: $(XPR)
	$(VIVADO) $(XPR) &

xsa: $(XSA)

$(XSA): $(XPR)
	$(VIVADO) -mode batch -log build.log -journal build.jou \
		-source build.tcl -tclargs $(JOBS) $(STRATEGY)

$(XPR):
	$(VIVADO) -mode batch -source $(PROJ_NAME).tcl \
		-log create_project.log -journal create_project.jou

xsa-clean:
	rm -rf $(PROJ_NAME) $(XSA) *.log *.jou .Xil
