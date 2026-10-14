# EduStream preflight checks (read-only; changes nothing).
#   powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1
#
# Exit code 0 = all required checks passed, 1 = at least one failed.
# Checks still to be added in later milestones (docs/ARCHITECTURE.md §11):
#   M2: LLM providers answer a 1-token call (when LLM_ENABLED=true)
#   M3: config invariants (S5, CHUNK_SECONDS <= 15, partition counts)

$Root = Split-Path -Parent $PSScriptRoot
$Failures = 0

function Report([string]$Name, [bool]$Ok, [string]$Detail, [switch]$WarnOnly) {
    if ($Ok) {
        Write-Host ("[ OK ] {0} - {1}" -f $Name, $Detail)
    } elseif ($WarnOnly) {
        Write-Host ("[WARN] {0} - {1}" -f $Name, $Detail)
    } else {
        Write-Host ("[FAIL] {0} - {1}" -f $Name, $Detail)
        $script:Failures++
    }
}

# --------------------------------------------------
# Read .env (simple KEY=VALUE lines) without exporting it
# --------------------------------------------------

$Config = @{}
$EnvFile = Join-Path $Root ".env"
$Example = Join-Path $Root ".env.example"
$Source = $Example
if (Test-Path $EnvFile) { $Source = $EnvFile }
foreach ($Line in Get-Content $Source) {
    if ($Line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $Config[$Matches[1]] = $Matches[2].Trim() }
}
Report ".env" (Test-Path $EnvFile) $(if (Test-Path $EnvFile) { "found" } else { "missing - using .env.example defaults (run setup.ps1)" }) -WarnOnly

# --------------------------------------------------
# Python environment
# --------------------------------------------------

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    $PyVer = (& "$VenvPy" -c "import sys; print('%d.%d.%d' % sys.version_info[:3])").Trim()
    Report "Python (.venv)" ($PyVer -like "3.10.*") $PyVer
    $Imports = "kafka,faster_whisper,jsonschema,requests,dotenv,streamlit,pandas,matplotlib,jiwer,pytest"
    $Out = & "$VenvPy" -c "import importlib.util,sys; bad=[m for m in sys.argv[1].split(',') if importlib.util.find_spec(m) is None]; print(','.join(bad))" $Imports
    Report "Python packages" ([string]::IsNullOrWhiteSpace($Out)) $(if ($Out) { "missing: $Out" } else { "all importable" })
    $KafkaPy = (& "$VenvPy" -c "import kafka; print(kafka.__version__)").Trim()
    Report "kafka-python" ($KafkaPy -eq "3.0.11") $KafkaPy
} else {
    Report "Python (.venv)" $false "not found - run scripts\setup.ps1"
}

# --------------------------------------------------
# Java (Kafka Streams needs JDK 17+)
# --------------------------------------------------

$Javac = Get-Command javac -ErrorAction SilentlyContinue
if ($Javac) {
    $JavacOut = (& javac -version 2>&1 | Out-String).Trim()
    $Major = 0
    if ($JavacOut -match 'javac (\d+)') { $Major = [int]$Matches[1] }
    Report "JDK" ($Major -ge 17) $JavacOut
} else {
    Report "JDK" $false "javac not on PATH"
}

# --------------------------------------------------
# Kafka installation
# --------------------------------------------------

$KafkaHome = $Config["KAFKA_HOME"]
if ($KafkaHome -and (Test-Path $KafkaHome)) {
    $ClientsJar = Get-ChildItem (Join-Path $KafkaHome "libs") -Filter "kafka-clients-*.jar" -ErrorAction SilentlyContinue | Select-Object -First 1
    $KVer = "unknown"
    if ($ClientsJar -and $ClientsJar.Name -match 'kafka-clients-(.+)\.jar') { $KVer = $Matches[1] }
    Report "Kafka install" ($KVer -eq "4.3.1") "$KafkaHome (version $KVer)"
    Report "Kafka path has no spaces" (-not $KafkaHome.Contains(" ")) $KafkaHome
} else {
    Report "Kafka install" $false "KAFKA_HOME not found: $KafkaHome"
}

# --------------------------------------------------
# Ports (must be free before start_all.ps1)
# --------------------------------------------------

foreach ($Port in @(9092, 9093, 8501)) {
    $Busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    Report "Port $Port" (-not $Busy) $(if ($Busy) { "in use by PID $($Busy[0].OwningProcess)" } else { "free" }) -WarnOnly
}

# --------------------------------------------------
# Disk and memory
# --------------------------------------------------

$FreeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Report "Free disk on C:" ($FreeGB -ge 15) "$FreeGB GB (need >= 15 GB for dataset, models, Kafka logs)"
$FreeRamGB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
Report "Free RAM" ($FreeRamGB -ge 5) "$FreeRamGB GB free (close browsers before running the pipeline)" -WarnOnly

# --------------------------------------------------
# Whisper models (downloaded by setup.ps1)
# --------------------------------------------------

foreach ($Model in @("base.en", "small.en")) {
    $Present = Test-Path (Join-Path $Root "models\$Model\model.bin")
    Report "Whisper model $Model" $Present $(if ($Present) { "present" } else { "not downloaded yet (setup.ps1 without -SkipModels)" }) -WarnOnly
}

Write-Host ""
if ($Failures -gt 0) {
    Write-Host "Preflight: $Failures required check(s) failed."
    exit 1
}
Write-Host "Preflight: all required checks passed."
exit 0
