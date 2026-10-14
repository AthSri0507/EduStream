# Run one EduStream component in the current window, optionally restarting it when it exits
# with an error (e.g. EXIT_PRODUCE_FAILED = 3: a fresh process means a fresh producer,
# re-reading from the last committed offset; ARCHITECTURE §6.3).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_component.ps1 -Name w1 -Module summarizer.transcription.transcription_worker -EnvVars "WORKER_ID=w1" -Restart
#   powershell -ExecutionPolicy Bypass -File scripts\run_component.ps1 -Name streams-legacy -JavaClass com.educationalstream.StreamProcessor -ClassPath "<dir>"

param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Module,
    [string]$JavaClass,
    [string]$ClassPath,
    [string]$EnvVars = "",
    [switch]$Restart
)

. "$PSScriptRoot\_common.ps1"
$host.UI.RawUI.WindowTitle = "edustream-$Name"
Set-Location $Root
foreach ($pair in ($EnvVars -split ";" | Where-Object { $_ })) {
    $key, $value = $pair -split "=", 2
    [Environment]::SetEnvironmentVariable($key, $value)
}

while ($true) {
    $started = Get-Date
    if ($Module) {
        & $VenvPy -u -m $Module
    } else {
        & java -Xmx512m -cp "$ClassPath;$KafkaHome\libs\*" $JavaClass
    }
    $code = $LASTEXITCODE
    Write-Host "[$Name] exited with code $code at $(Get-Date -Format HH:mm:ss)"
    if (-not $Restart -or $code -eq 0) { break }
    # Avoid a tight crash loop if it dies immediately (e.g. broker down)
    $delay = if (((Get-Date) - $started).TotalSeconds -lt 10) { 10 } else { 3 }
    Write-Host "[$Name] restarting in $delay s (fresh process, fresh producer)"
    Start-Sleep -Seconds $delay
}
exit $code
