# Install SignalRGB-MagicHome Bridge as a Windows Scheduled Task.
#
# Usage (run as Administrator):
#   powershell -ExecutionPolicy Bypass -File install-task.ps1 --ip 192.168.1.100 --leds 300
#
# All arguments after the script name are passed through to bridge.py.

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$BridgeArgs
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Find pythonw.exe (Python without console window)
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $pythonw = (Get-Command python).Source -replace 'python\.exe$','pythonw.exe'
}
Write-Host "Using: $pythonw"
Write-Host "Bridge dir: $scriptDir"

$argString = "tray.py $($BridgeArgs -join ' ')"
Write-Host "Arguments: $argString"

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $argString `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName "SignalRGB-MagicHome Bridge" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force

Write-Host ""
Write-Host "Task 'SignalRGB-MagicHome Bridge' registered!" -ForegroundColor Green
Write-Host "It runs as a system tray icon at logon (no CMD window)."
Write-Host ""
Write-Host "To start now:  Start-ScheduledTask -TaskName 'SignalRGB-MagicHome Bridge'"
Write-Host "To remove:     Unregister-ScheduledTask -TaskName 'SignalRGB-MagicHome Bridge' -Confirm:`$false"
