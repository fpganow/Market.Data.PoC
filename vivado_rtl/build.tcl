set jobs 4
if {$argc > 0} { set jobs [lindex $argv 0] }

set proj_name "mktdata_rtl"
open_project ${proj_name}/${proj_name}.xpr

launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
    error "ERROR: Synthesis failed"
}

# Same strategy as vivado/build.tcl so the two bitstreams are comparable; the RTL
# parser has no 100 MHz critical loop, the tight paths are its 156.25 MHz byte muxes.
set strategy "Performance_ExplorePostRoutePhysOpt"
if {$argc > 1 && [string index [lindex $argv 1] 0] ne "-"} { set strategy [lindex $argv 1] }
set_property strategy $strategy [get_runs impl_1]
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "ERROR: Implementation failed"
}

open_run impl_1
set wns [get_property STATS.WNS [get_runs impl_1]]
puts "INFO: routed WNS = $wns ns"
write_hw_platform -fixed -force -include_bit -file ${proj_name}.xsa
puts "INFO: XSA written to ${proj_name}.xsa"
