#
# Usage:
# 1 - Install Python dependencies
#   make install_deps
#
# 3 - Build
#   make simulate
#
# Troubleshooting:
#   If you get any errors related to missing versions of GLIBC or libstdc++,
# please see:
#   - https://fpganow.com/index.php/2024/01/03/error-while-running-vivado-simulation-on-ubuntu-22-04/
#

# +---------------------------------------------------------------------------+
# |  New Idea                                                                 |
# +---------------------------------------------------------------------------+
help:
	@echo "+------+"
	@echo "| Help |"
	@echo "+------+"
	@echo
	@echo "---------"
	@echo "IP Export"
	@echo "---------"
	@echo
	@echo "ip-export-list"
	@echo "    Lists all directories in /mnt/c/NIFPGA/compilation"
	@echo
	@echo "ip-export-copy-%"
	@echo "    Copies .dcp and .vhd files from export by index as per"
	@echo "    the output of 'make ip-export-list'"
	@echo
	@echo "-------------"
	@echo "IP Management"
	@echo "-------------"
	@echo "local-list"
	@echo "    List all local IP Exports"
	@echo
	@echo "local-gen-%"
	@echo "    Generate Verilog wrapper for IP Export by Vi Name"
	@echo
	@echo "----------------"
	@echo "Local Simulation"
	@echo "----------------"
	@echo

define AWK_EXPORT_LIST
BEGIN { \
	print "+-------+-------------+--------------------------------------------------------+"; \
	print "| Index | Date        | Name                                                   |"; \
	print "+-------+-------------+--------------------------------------------------------+"; \
} \
{ \
	print "|     " NR " | " $$6 " " $$7 " " $$8 " | " $$9; \
} \
END { \
	print "+-------+-------------+--------------------------------------------------------+"; \
}
endef

ip-export-list:
	@echo "+---------------------+"
	@echo "| Listing all exports |"
	@ls -l /mnt/c/NIFPGA/compilation | tail -n +2 | awk '$(AWK_EXPORT_LIST)'


ip-export-copy-%: IMP_BASE=$(shell ls -l /mnt/c/NIFPGA/compilation | tail -n +$* | head -n 2 | tail -n 1 \
		| awk '{print "/mnt/c/NIFPGA/compilation/" $$9 "/source_files/"}')
ip-export-copy-%: export dcp_file=$(shell ls ${IMP_BASE} | grep dcp)
ip-export-copy-%: export vhd_wrapper=$(shell ls ${IMP_BASE} | grep vhd)
ip-export-copy-%: export v_file=$(shell ls ${IMP_BASE} | grep dcp | cut -d'.' -f1)".v"
ip-export-copy-%:
	@echo "+---------------------------------+"
	@echo "| Importing #$*                    |"
	@echo "+---------------------------------+"
	@echo "From:"
	@echo " - ${IMP_BASE}"
	@echo
	@echo "Copying DCP_FILE:"
	@echo "  - ${dcp_file}"
	@cp ${IMP_BASE}/${dcp_file} .
	@echo
	@echo "Copying VHD_WRAPPER:"
	@echo "  - ${vhd_wrapper}"
	@cp ${IMP_BASE}/${vhd_wrapper} .


# ** <Switch to another computer> **
define AWK_LOCAL_LIST
@load "filefuncs"; \
BEGIN { \
	FS=" ";  \
	print "+-------------+----------------------------------------------+";\
	print "| Date        | Vi Name                                      |"; \
	print "|             | DCP File                                     |"; \
	print "|             | VHD File                                     |"; \
	print "+-------------+----------------------------------------------+";\
} \
{ \
	date_time = $$6 " " $$7 " " $$8; \
	dcp_file = $$9; \
	vi_name = dcp_file; \
	gsub("[.].*$$", "", vi_name); \
	gsub("NiFpgaAG_", "", vi_name); \
	vhd_wrapper = "NiFpgaIPWrapper_" vi_name ".vhd"; \
	v_file = dcp_file; \
	gsub("dcp", "v", v_file); \
	v_file_size = "Size: "; \
	if(stat(v_file, info)) { \
	    v_file_size = "<Missing>"; \
	} else { \
		v_file_size = info["size"] / 1024 " KB"; \
		v_file_size = v_file_size " (" strftime("%b%e %H:%M", info["mtime"]) ")"; \
	} \
	print "- " date_time " - " vi_name; \
	print "                DCP: " dcp_file; \
	print "                VHD: " vhd_wrapper; \
	print "                V: " v_file " - " v_file_size; \
} \
END { \
}
endef
#  - list all copied exports present in current directory
local-list:
local-list:
	@echo "+---------------------------+"
	@echo "| Listing all local Exports |"
	@ls -l NiFpgaAG*.dcp | awk '$(AWK_LOCAL_LIST)'
	@echo
	@echo "Generate local via 'make local-gen-<Vi Name>"
	@echo

#  - generate verilog version of local version
local-gen-%: export dcp_file=$(shell ls  *$*.dcp)
local-gen-%: export v_file=$(shell ls  *$*.dcp | sed 's/dcp/v/g')
local-gen-%:
	@echo "+-----------------------------------------+"
	@echo "| Writing Verilog for Vivado Block Design |"
	@echo "+-----------------------------------------+"
	@echo "Using:"
	@echo "  - ${dcp_file}"
	@echo "to generate:"
	@echo "  - ${v_file}"
	@powershell.exe "C:\\NIFPGA\\programs\\Vivado2021_1\\bin\\vivado.bat \
		-nolog -nojournal -notrace -mode batch \
		-source ${PWD_WIN3}\\gen.tcl" \
		-tclargs "${PWD_WIN3}\\${dcp_file}"


py-codegen-%:
	@echo "+----------------------------+"
	@echo "| Generating Python Bindings |"
	@echo "+----------------------------+"
	@echo "Using:"

######  OLD  #######
# make ip-export-list
# - lists all available exports by date descending
# - -t : sort by time, newest first

# make compile-%
# make elaborate-%
# make simulate-%
# make wave-%
#
# With defaults selecting last modified
# make compile-%
# make elaborate-%
# make simulate-%
# make wave-%




# 1 - Install cboe_pitch
#   SETUPTOOLS_USE_DISTUTILS=stdlib python3 -m pip install -e .

SHELL       :=  /bin/bash
VIVADO_VER  :=  2024.1
VIVADO_BIN  :=  /tools/Xilinx/Vivado/${VIVADO_VER}/tps/lnx64/python-3.8.3/bin/
VIVADO_LIB  :=  /tools/Xilinx/Vivado/2024.1/tps/lnx64/python-3.8.3/lib/
SRC_XIL      =  source /tools/Xilinx/Vivado/${VIVADO_VER}/settings64.sh
SIM_DIR     ?=  sim/synth/func
PYTHON      ?=  python3.8

PWD         ?=  ${pwd}
PWD_WIN2    ?=  $(shell pwd | tr "/" "\\\\")
OLD_PATH    :=  ${PATH}

# User Parameters
DCP_FILE    ?=  NiFpgaAG_poc_ip.dcp

#DCP_FILE_2=$(shell cat .dcp_file)
#VHD_WRAPPER_2=$(shell cat .vhd_wrapper)
#V_FILE_2=$(shell cat .v_file)

# IDEA
# There can only exist 1 dcp and 1 vhd wrapper
#
# list-exports
#   Lists all exports in /mnt/C/NIFPGA/compilation
#
# import-export-0
#   Delete current dcp and vhd wrapper
#   Copy new dcp and vhd files from NIFPGA compilation directory
#
# generate-verilog
#
#
#
#
#
OS=$(shell lsb_release -r | awk '{print $$2}')
PWD_WIN     ?=  "\\\\wsl.localhost\\Ubuntu-${OS}"${PWD_WIN2}
PWD_WIN3    ?=  $(shell wslpath -w ${PWD})

.EXPORT_ALL_VARIABLES:

export MY_VAR=TEST
export PATH=$(VIVADO_BIN):$(OLD_PATH)
export LD_LIBRARY_PATH :=  /tools/Xilinx/Vivado/2024.1/tps/lnx64/python-3.8.3/lib:/tools/Xilinx/Vivado/2024.1/lib/lnx64.o/Ubuntu/22/:$(LD_LIBRARY_PATH)



run-%:
	@echo "RUN-$*"
	@echo "FILE=${FILE}"

run: export FILE=JJJ
run: run-john
	@echo "RUN"


#import-%: IMP_BASE=$(shell ls -l /mnt/c/NIFPGA/compilation | tail -n +$* | head -n 2 | tail -n 1 \
#		| awk '{print "/mnt/c/NIFPGA/compilation/" $$9 "/source_files/"}')
#import-%: export dcp_file=$(shell ls ${IMP_BASE} | grep dcp)
#import-%: export vhd_wrapper=$(shell ls ${IMP_BASE} | grep vhd)
#import-%: export v_file=$(shell ls ${IMP_BASE} | grep dcp | cut -d'.' -f1)".v"
#import-%:
#	@echo "+---------------------------------+"
#	@echo "| Importing #$*                    |"
#	@echo "+---------------------------------+"
#	@echo "From:"
#	@echo " - ${IMP_BASE}"
#	@echo
#	@echo "Copying DCP_FILE"
#	@cp ${IMP_BASE}/${dcp_file} .
#	@echo " - setting .dcp_file to ${dcp_file}"
#	@echo ${dcp_file} > ./.dcp_file
#	@echo " - setting .v_file to ${v_file}"
#	@echo ${v_file} > ./.v_file
#	@echo "Copying VHD_WRAPPER"
#	@cp ${IMP_BASE}/${vhd_wrapper} .
#	@echo " - setting .vhd_wrapper to ${vhd_wrapper}"
#	@echo ${vhd_wrapper} > ./.vhd_wrapper
#
#show-current:
#	@echo "+---------------------------------+"
#	@echo "| Currently Selected Design       |"
#	@echo "+---------------------------------+"
#	@echo "  DCP_FILE     =  ${DCP_FILE_2}"
#	@echo "  VHD_WRAPPER  =  ${VHD_WRAPPER_2}"
#	@echo "  V_FILE       =  ${V_FILE_2}"

gen-verilog: export dcp_file=$(shell cat .dcp_file)
gen-verilog: export v_file=$(shell cat .v_file)
gen-verilog:
	@echo "+---------------------------------+"
	@echo "| Generating Synthesis as Verilog |"
	@echo "+---------------------------------+"
	@echo " - dcp_file=${dcp_file}"
	@echo " - v_file=${v_file}"
	@echo "Invoking gen.tcl to generate ${v_file}"
	@echo "PWD = ${PWD}"
	@echo "SIM_DIR  = ${SIM_DIR}"
	@echo "WIN_DCP  = ${WIN_DCP}"
	@echo "PWD_WIN  = ${PWD_WIN}"
	@echo "PWD_WIN3 = ${PWD_WIN3}"
	@echo "dcp_file= ${dcp_file}"
	@powershell.exe "C:\\NIFPGA\\programs\\Vivado2021_1\\bin\\vivado.bat \
		-nolog -nojournal -notrace -mode batch \
		-source ${PWD_WIN3}\\gen.tcl" \
		-tclargs "${PWD_WIN3}\\${dcp_file}"

gen-custom-%:
	@echo
	@echo "CUSTOM GEN: $*"

help2:
	@echo
	@echo "Help"
	@echo "  clean"
	@echo
	@echo "Python Related"
	@echo "  install_deps"
	@echo "  pytest"
	@echo "  py_codegen"
	@echo "  v_codegen"
	@echo "  py_shell"
	@echo "  use_vivado_cmake arg=--version"
	@echo "  use_vivado_py arg=--version"
	@echo
	@echo "Vivado Related"
	@echo "  compile"
	@echo "  elaborate"
	@echo "  simulate"
	@echo "  waveform"
	@echo
	@echo "Message Generator Related"
	@echo "  display_short"
	@echo "  display_long"
	@echo "  regenerate"
	@echo
	@echo "To Run a simulation for a specific configuration use:"
	@echo "  SIM_DIR=sim/synth/func make simulate (default)"
	@echo "  SIM_DIR=sim/synth/timing make simulate"
	@echo "  SIM_DIR=sim/impl/func make simulate"
	@echo "  SIM_DIR=sim/imply/timing make simulate"

sandbox:
	@echo "Listing all NIFPGA Compilations"
	@ls -dl /mnt/c/NIFPGA/compilation/*

clean_%: export build_type=$(shell echo "$*" | awk -F'_' '{ print $$1 }')
clean_%: export sim_type=$(shell echo "$*" | awk -F'_' '{ print $$2 }')
clean_%:
	@echo "Cleaning:"
	@echo -e "\t - Build type: ${build_type}"
	@echo -e "\t - Simulation type: ${sim_type}"
	@cd sim/${build_type}/${sim_type} && rm -rf xsim.dir *.log *.pb *.jou *.wdb
	@rm -f sim/libpysv.so sim/pysv_pkg.sv


clean: clean_synth_func clean_synth_timing clean_impl_func clean_impl_timing
	@echo "Cleaning"
	@rm -rf build/
	@rm -rf __pycache__
	@rm -rf .pytest_cache
	@rm -f *.jou *.log

# make use_vivado_cmake --arg=--version
use_vivado_cmake:
	cmake $(arg)

# make use_vivado_py arg=--version
use_vivado_py:
	$(PYTHON) $(arg)

py_shell:
	$(PYTHON)

install_deps:
	${PYTHON} -m pip install --user -r ./requirements-test.txt

pytest:
	@echo
	@echo " - Running Python Tests"
	${PYTHON} -m pytest --disable-warnings tests_poc_gen.py

py_codegen:
	${PYTHON} ./poc_gen.py
	mv pysv_pkg.sv ./sim
	mv ./build/libpysv.so ./sim


#v_codegen:
#	@echo "  - Generating Synth"
#	@echo "PWD = ${PWD}"
#	@echo "SIM_DIR = ${SIM_DIR}"
#	@echo "WIN_DCP = ${WIN_DCP}"
#	@echo "PWD_WIN = ${PWD_WIN}"
#	@powershell.exe "C:\\NIFPGA\\programs\\Vivado2021_1\\bin\\vivado.bat \
#		-nolog -nojournal -notrace -mode batch \
#		-source ${PWD_WIN}\\sim\\synth\\func\\gen.tcl" \
#		-tclargs "${PWD_WIN}\\${DCP_FILE}"

# Message Generator Section
display_short:
	@echo "Displaying short"

display_long:
	@echo "Displaying long"

regenerate:
	@echo "Regenerate"


compile: py_codegen v_codegen
	@echo "  - Compiling"
	${SRC_XIL} && cd ${SIM_DIR} && ./compile.sh

elaborate: compile
	@echo "  - Elaborating"
	${SRC_XIL} && cd ${SIM_DIR} && ./elaborate.sh

simulate: elaborate
	@echo "  - Simulating"
	${SRC_XIL} && cd ${SIM_DIR} && ./simulate.sh

waveform:
	@echo
	@echo " - Displaying waveform"
	@echo " xsim --gui ${SIM_DIR}/autogenerated_tb_synth_fun.wdb"
	${SRC_XIL} && cd ${SIM_DIR} && \
		xsim --gui autogenerated_tb_synth_func.wdb \
		     --view ./${SIM_DIR}/autogenerated_tb_synth_func.wcfg

wave: waveform
