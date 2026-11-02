$t = [System.__ComObject]; $P = [Reflection.BindingFlags]::GetProperty; $M = [Reflection.BindingFlags]::InvokeMethod
$lv = New-Object -ComObject LabVIEW.Application
"bound to LabVIEW " + $t.InvokeMember("Version", $P, $null, $lv, $null)
$root = "C:\work\fpganow\lvgen\exp"
$vi = $t.InvokeMember("GetVIReference", $M, $null, $lv, @("$root\lv2020\helper\fifo_experiment2.vi", "", $false, 0))
"helper ExecState=" + $t.InvokeMember("ExecState", $P, $null, $vi, $null)
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("project path", [object]"$root\tree\Market.Data.PoC.lvproj")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("target name", [object]"FPGA Target")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("vi name", [object]"fifo_scratch.vi")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("fifo name", [object]"EXP-Fifo")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("depth", [object]([UInt32]1024))) | Out-Null
$sw = [Diagnostics.Stopwatch]::StartNew()
$t.InvokeMember("Run", $M, $null, $vi, @($false)) | Out-Null
"run took " + $sw.ElapsedMilliseconds + " ms"
foreach ($n in @("item count","target index","vi index","fifo item name","succeeded")) { "$n=" + $t.InvokeMember("GetControlValue", $M, $null, $vi, @($n)) }
"name read errors=" + ($t.InvokeMember("GetControlValue", $M, $null, $vi, @("name read errors")) -join " | ")
"error out=" + ($t.InvokeMember("GetControlValue", $M, $null, $vi, @("error out")) -join " | ")
