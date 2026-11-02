$t = [System.__ComObject]; $P = [Reflection.BindingFlags]::GetProperty; $M = [Reflection.BindingFlags]::InvokeMethod
$lv = New-Object -ComObject LabVIEW.Application
"bound to LabVIEW " + $t.InvokeMember("Version", $P, $null, $lv, $null)
$src = "C:\work\fpganow\lvgen\exp\helper\fifo_experiment2.vi"; $dst = "C:\work\fpganow\lvgen\exp\lv2020\helper\fifo_experiment2.vi"
$vi = $t.InvokeMember("GetVIReference", $M, $null, $lv, @($src, "", $false, 0))
"ExecState=" + $t.InvokeMember("ExecState", $P, $null, $vi, $null)
$t.InvokeMember("SaveForPrevious", $M, $null, $vi, @($dst, "", "20.0")) | Out-Null
"saved " + (Get-Item $dst).Length + " bytes"
