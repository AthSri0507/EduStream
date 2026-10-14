# Compile and run bench\java\M2StreamsChecks.java against the local Kafka 4.3.1 jars
# (no Maven needed). Output goes to bench\results\m2_java_checks.txt.
#   powershell -ExecutionPolicy Bypass -File bench\run_java_checks.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$KafkaHome = if ($env:KAFKA_HOME) { $env:KAFKA_HOME } else { "C:\kafka_2.13-4.3.1" }
$ClassPath = "$KafkaHome\libs\*"
$Out = Join-Path $Root "run\java-classes"
$Results = Join-Path $Root "bench\results"
New-Item -ItemType Directory -Force $Out, $Results | Out-Null

# Same keys as bench\verify_kafka_python.py (J1 vs K3 comparison)
$Keys = @("python_l1","python_l2","algorithms_l1","algorithms_l2","lecture_01","lecture_02","lecture_03",
          "demo_a","demo_b","demo_c") + (0..9 | ForEach-Object { "video_{0:D2}" -f $_ })

& javac --release 17 -cp "$ClassPath" -d "$Out" (Join-Path $Root "bench\java\M2StreamsChecks.java")
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

$Lines = & java -cp "$Out;$ClassPath" M2StreamsChecks @Keys 2>&1 |
    ForEach-Object { "$_" } |
    Where-Object { $_ -match '^\[(PASS|FAIL)\]|^JAVA_PARTITIONS|CHECK' }
$Code = $LASTEXITCODE
# Plain UTF-8 (PowerShell 5.1's Tee-Object would write UTF-16)
[System.IO.File]::WriteAllLines((Join-Path $Results "m2_java_checks.txt"), [string[]]$Lines, (New-Object System.Text.UTF8Encoding($false)))
$Lines
exit $Code
