# Start the EduStream foundation on one laptop (ARCHITECTURE §11, baseline profile).
#   powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 [-Workers 3] [-Minimized]
#
# 1. checks the configuration
# 2. starts the single Kafka broker (formats its storage on first use)
# 3. creates/verifies the topics
# 4. builds the Kafka Streams jar if needed (Maven Wrapper; -Rebuild forces it), then starts
#    the Streams app, N transcription workers, the interim note generator (until M6), the
#    db-sink (SQLite + lag monitor) and the dashboard (http://localhost:8501), each in its own
#    titled window, restarted on error exits.
# The lecture source is NOT started here: run it when you want lectures to play:
#   .venv\Scripts\python -m producer.lecture_source --demo
# PIDs go to run\pids\ so stop_all.ps1 / kill.ps1 can stop whole process trees.

param(
    [int]$Workers = 3,
    [switch]$Minimized,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\_common.ps1"
New-Item -ItemType Directory -Force $PidDir, $LogDir | Out-Null
$style = if ($Minimized) { "Minimized" } else { "Normal" }

function Start-Window([string]$Name, [string]$Arguments) {
    if (Test-Path (Join-Path $PidDir "$Name.pid")) {
        Write-Host "  $Name already running (pid file exists) - skipped"
        return
    }
    $proc = Start-Process powershell.exe -WindowStyle $style -PassThru -ArgumentList (
        "-NoExit -ExecutionPolicy Bypass -File `"$PSScriptRoot\run_component.ps1`" -Name $Name $Arguments")
    Set-Content -Path (Join-Path $PidDir "$Name.pid") -Value $proc.Id
    Write-Host "  started $Name (pid $($proc.Id))"
}

# 1. Configuration ------------------------------------------------------------
& $VenvPy -m common.config --check
if ($LASTEXITCODE -ne 0) { throw "configuration invalid (see above)" }

# 2. Broker -------------------------------------------------------------------
if (Test-Port 9092) {
    Write-Host "Broker already listening on 9092"
} else {
    if (-not (Test-Path (Join-Path $BrokerData "meta.properties"))) {
        Write-Host "Formatting broker storage in $BrokerData"
        $uuid = (& "$KafkaBin\kafka-storage.bat" random-uuid 2>$null | Select-Object -Last 1).Trim()
        & "$KafkaBin\kafka-storage.bat" format --standalone -t $uuid -c "$BrokerConfig" 2>$null | Out-Null
    }
    $log = Join-Path $LogDir "broker-single.log"
    $cmd = "`$env:KAFKA_HEAP_OPTS='-Xmx512M -Xms512M'; `$host.UI.RawUI.WindowTitle='edustream-broker'; " +
           "& '$KafkaBin\kafka-server-start.bat' '$BrokerConfig' *>&1 | Tee-Object -FilePath '$log'"
    $proc = Start-Process powershell.exe -WindowStyle $style -PassThru -ArgumentList "-NoExit", "-Command", $cmd
    Set-Content -Path (Join-Path $PidDir "broker.pid") -Value $proc.Id
    Write-Host "Starting broker (pid $($proc.Id)) ..."
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Port 9092)) {
        if ((Get-Date) -gt $deadline) { throw "broker did not open port 9092 within 60 s; see $log" }
        Start-Sleep -Seconds 1
    }
    Write-Host "Broker up"
}

# 3. Topics -------------------------------------------------------------------
& $VenvPy -m tools.create_topics
if ($LASTEXITCODE -ne 0) { throw "topic setup failed" }

# 4. Components -----------------------------------------------------------------
$streamsDir = Join-Path $Root "stream_processor"
$jar = Join-Path $streamsDir "target\edustream-streams.jar"
if ($Rebuild -or -not (Test-Path $jar)) {
    Write-Host "Building the Kafka Streams app (Maven Wrapper) ..."
    Push-Location $streamsDir
    & .\mvnw.cmd -B -q package -DskipTests
    $built = $LASTEXITCODE -eq 0
    Pop-Location
    if (-not $built) { throw "Streams build failed (run stream_processor\mvnw.cmd package to see why)" }
}

$stateDir = Join-Path $Root "run\state\streams"
Write-Host "Starting components:"
Start-Window "streams" "-Jar `"$jar`" -EnvVars `"STATE_DIR=$stateDir`" -Restart"
for ($i = 1; $i -le $Workers; $i++) {
    Start-Window "w$i" "-Module summarizer.transcription.transcription_worker -EnvVars `"WORKER_ID=w$i`" -Restart"
}
Start-Window "note-generator" "-Module summarizer.notes.note_generator -Restart"
Start-Window "db-sink" "-Module storage.db_sink -Restart"
Start-Window "dashboard" "-Module streamlit -ModuleArgs `"run dashboard/app.py --server.headless true --server.port 8501`" -Restart"

Write-Host ""
Write-Host "Foundation running. Play the demo lectures with:"
Write-Host "  .venv\Scripts\python -m producer.lecture_source --demo"
Write-Host "  (or, without audio/Whisper:  .venv\Scripts\python -m tools.replay_fixtures --demo)"
Write-Host "Dashboard: http://localhost:8501"
