# Wipe all pipeline state for a clean run (ARCHITECTURE §11). Use between demo runs and
# rehearsal days (it also prevents the Windows segment-deletion crash, §11).
#   powershell -ExecutionPolicy Bypass -File scripts\reset.ps1 [-Force] [-ClearLogs]
#
# Stops everything, then deletes: the broker's data (C:\edustream-kafka\single), Streams
# state (run\state), lecture state files (run\lectures), the SQLite database
# (data\edustream.db*), the retrieval index (dataectors.db*) and run\pids. The dataset, models and .env are NOT touched.
# The broker storage is reformatted so start_all.ps1 can start straight away.

param([switch]$Force, [switch]$ClearLogs)

. "$PSScriptRoot\_common.ps1"
if (-not $Force) {
    $answer = Read-Host "This deletes all Kafka topics, Streams state and the database. Type yes to continue"
    if ($answer -ne "yes") { Write-Host "Cancelled"; exit 1 }
}

& powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\stop_all.ps1"
Start-Sleep -Seconds 2

$targets = @($BrokerData, (Join-Path $Root "run\state"), (Join-Path $Root "run\lectures"), $PidDir)
$targets += Get-ChildItem (Join-Path $Root "data") -Filter "edustream.db*" -ErrorAction SilentlyContinue | ForEach-Object FullName
$targets += Get-ChildItem (Join-Path $Root "data") -Filter "vectors.db*" -ErrorAction SilentlyContinue | ForEach-Object FullName
if ($ClearLogs) { $targets += $LogDir }
foreach ($target in $targets) {
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
        Write-Host "removed $target"
    }
}

$uuid = (& "$KafkaBin\kafka-storage.bat" random-uuid 2>$null | Select-Object -Last 1).Trim()
& "$KafkaBin\kafka-storage.bat" format --standalone -t $uuid -c "$BrokerConfig" 2>$null | Out-Null
Write-Host "Broker storage reformatted (cluster $uuid). Run scripts\start_all.ps1 to start again."
