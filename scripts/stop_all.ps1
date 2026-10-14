# Stop every component started by start_all.ps1 (whole process trees), broker last.
#   powershell -ExecutionPolicy Bypass -File scripts\stop_all.ps1 [-KeepBroker]

param([switch]$KeepBroker)

. "$PSScriptRoot\_common.ps1"
if (-not (Test-Path $PidDir)) { Write-Host "Nothing running (no run\pids)"; exit 0 }

Get-ChildItem $PidDir -Filter *.pid | Where-Object { $_.BaseName -ne "broker" } | ForEach-Object {
    if (Stop-EduProcess $_.BaseName) { Write-Host "stopped $($_.BaseName)" }
}
if (-not $KeepBroker) {
    if (Stop-EduProcess "broker") { Write-Host "stopped broker" }
}
