# Re-run implementation only, with a timing-driven strategy, and re-export the XSA.
# Use after `make xsa` finishes with "Timing constraints are not met" on a design that
# is known to be marginal (the NI parser loop at 100 MHz closes with < 0.1 ns to spare):
#   vivado -mode batch -source reimpl.tcl -tclargs 8 [Strategy]
# Synthesis results are kept; only impl_1 is reset.
set jobs 8
set strategy "Performance_ExplorePostRoutePhysOpt"
if {$argc > 0} { set jobs [lindex $argv 0] }
if {$argc > 1} { set strategy [lindex $argv 1] }

set proj_name "mktdata_poc"
open_project ${proj_name}/${proj_name}.xpr
set_property strategy $strategy [get_runs impl_1]
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "ERROR: Implementation failed"
}
open_run impl_1
set wns [get_property STATS.WNS [get_runs impl_1]]
puts "INFO: impl_1 strategy $strategy routed WNS = $wns ns"
write_hw_platform -fixed -force -include_bit -file ${proj_name}.xsa
puts "INFO: XSA written to ${proj_name}.xsa"
