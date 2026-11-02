$t = [System.__ComObject]; $P = [Reflection.BindingFlags]::GetProperty; $M = [Reflection.BindingFlags]::InvokeMethod
$lv = New-Object -ComObject LabVIEW.Application
"bound to LabVIEW " + $t.InvokeMember("Version", $P, $null, $lv, $null)
$root = "C:\work\fpganow\lvgen\exp"
$vi = $t.InvokeMember("GetVIReference", $M, $null, $lv, @("$root\lv2020\helper\print_bd.vi", "", $false, 0))
"print_bd ExecState=" + $t.InvokeMember("ExecState", $P, $null, $vi, $null)
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("project path", [object]"$root\tree\Market.Data.PoC.lvproj")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("vi name", [object]"fifo_scratch.vi")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("html path", [object]"$root\print\fifo_scratch.html")) | Out-Null
$t.InvokeMember("SetControlValue", $M, $null, $vi, @("image dir", [object]"$root\print")) | Out-Null
$t.InvokeMember("Run", $M, $null, $vi, @($false)) | Out-Null
"vi index=" + $t.InvokeMember("GetControlValue", $M, $null, $vi, @("vi index"))
"scratch VI exec state=" + $t.InvokeMember("GetControlValue", $M, $null, $vi, @("exec state"))
"error out=" + ($t.InvokeMember("GetControlValue", $M, $null, $vi, @("error out")) -join " | ")
Get-ChildItem "$root\print" | Select-Object Name, Length | Format-Table -AutoSize
