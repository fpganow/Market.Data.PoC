set jobs 4
if {$argc > 0} { set jobs [lindex $argv 0] }

set proj_name "mktdata_poc"
open_project ${proj_name}/${proj_name}.xpr

launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "ERROR: Synthesis failed"
}

# The NI parser loop closes 100 MHz with < 0.1 ns to spare; the default strategy
# failed by 0.28 ns once axis_mon was added (2026-11-08) and this one gave +0.13 ns.
# Override with: vivado ... -tclargs <jobs> <Strategy>; reimpl.tcl re-runs impl only.
set strategy "Performance_ExplorePostRoutePhysOpt"
if {$argc > 1 && [string index [lindex $argv 1] 0] ne "-"} { set strategy [lindex $argv 1] }
set_property strategy $strategy [get_runs impl_1]
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "ERROR: Implementation failed"
}

open_run impl_1
write_hw_platform -fixed -force -include_bit -file ${proj_name}.xsa
puts "INFO: XSA written to ${proj_name}.xsa"
