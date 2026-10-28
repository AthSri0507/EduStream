# Stop ONE component for good (its window and everything in it), so it stays down: the live failover demo (F1).
# Unlike bench\kill_python_module.ps1 (a crash: run_component.ps1 restarts the process), nothing restarts it, so
# Kafka moves its partitions to the other members of its group.
#   powershell -ExecutionPolicy Bypass -File scripts\kill.ps1 -Name w2
# Bring it back with scripts\start_all.ps1 (with the same -Workers): it starts only the components that are missing.

param([Parameter(Mandatory = $true)][string]$Name)

. "$PSScriptRoot\_common.ps1"
$windows = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match "run_component\.ps1" -and
    $_.CommandLine -match "-Name\s+$([regex]::Escape($Name))(\s|$)"
}
if (-not $windows) {
    Write-Host "no running component named $Name"
    exit 1
}
foreach ($w in $windows) {
    & taskkill /PID $w.ProcessId /T /F *> $null
}
Remove-Item -ErrorAction SilentlyContinue (Join-Path $PidDir "$Name.pid")
Write-Host ("stopped {0} (window {1}) at {2}; restart it with scripts\start_all.ps1" -f $Name,
            (($windows | ForEach-Object { $_.ProcessId }) -join ","), (Get-Date -Format HH:mm:ss))
