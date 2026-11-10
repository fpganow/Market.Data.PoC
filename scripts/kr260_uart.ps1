# KR260 PS-UART console from the Windows side (the board's FT4232H is not visible in WSL).
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/kr260_uart.ps1 [-Port COM6] [-Send "uptime"] [-WaitMs 2500]
# Opens the port at 115200 8N1, discards pending input, writes -Send followed by Enter, collects output for -WaitMs
# milliseconds and prints it; -Quiet sends nothing (watch a boot without interrupting U-Boot). Channel B of the FT4232H (VID 0403 PID 6011, "USB Serial Port") is
# the console; find the COM number with: Get-PnpDevice -PresentOnly | ? FriendlyName -match 'USB Serial Port'
param([string]$Port = "COM6", [string]$Send = "", [int]$WaitMs = 2500, [switch]$Quiet)
$p = New-Object System.IO.Ports.SerialPort $Port, 115200, 'None', 8, 'One'
$p.ReadTimeout = 500; $p.NewLine = "`n"; $p.DtrEnable = $false; $p.RtsEnable = $false
$p.Open()
Start-Sleep -Milliseconds 200
try { $p.ReadExisting() | Out-Null } catch {}
if (-not $Quiet) { $p.Write($Send + "`r") }   # -Quiet: listen only (a keystroke during U-Boot autoboot stops the boot)
$sw = [Diagnostics.Stopwatch]::StartNew(); $out = ""
while ($sw.ElapsedMilliseconds -lt $WaitMs) { Start-Sleep -Milliseconds 100; try { $out += $p.ReadExisting() } catch {} }
$p.Close()
$out
