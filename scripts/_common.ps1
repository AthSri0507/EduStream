# Shared helpers for the EduStream scripts (dot-sourced: . "$PSScriptRoot\_common.ps1").

$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$PidDir = Join-Path $Root "run\pids"
$LogDir = Join-Path $Root "run\logs"
$BrokerConfig = Join-Path $Root "infra\kafka\single.properties"
$BrokerData = "C:\edustream-kafka\single"

# .env values as defaults; real environment variables win (same rule as common/config.py)
function Get-EduSetting([string]$Name, [string]$Default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$Name\s*=\s*(.*)$") {
                $value = $Matches[1].Trim()
                if ($value) { return $value }
            }
        }
    }
    return $Default
}

$KafkaHome = Get-EduSetting "KAFKA_HOME" "C:\kafka_2.13-4.3.1"
$KafkaBin = Join-Path $KafkaHome "bin\windows"

function Test-Port([int]$Port) {
    [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# Kill a recorded process TREE. Killing only the top process orphans children:
# e.g. Oracle's javapath "java" shim leaves the real JVM running (M2 finding).
function Stop-EduProcess([string]$Name) {
    $pidFile = Join-Path $PidDir "$Name.pid"
    if (-not (Test-Path $pidFile)) { return $false }
    $procId = (Get-Content $pidFile -Raw).Trim()
    & taskkill /PID $procId /T /F *> $null
    Remove-Item $pidFile -Force
    return $true
}
