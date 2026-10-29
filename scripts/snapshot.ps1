# The demo's safety net (PLAN §3): save a known-good copy of the databases, put it back in seconds
# (storage/snapshot.py). Nothing has to be stopped; restore with the lecture source stopped.
#   powershell -ExecutionPolicy Bypass -File scripts\snapshot.ps1 save demo-ok [-Overwrite]
#   powershell -ExecutionPolicy Bypass -File scripts\snapshot.ps1 list
#   powershell -ExecutionPolicy Bypass -File scripts\snapshot.ps1 restore demo-ok
# A restore first saves the data that was there as before-restore-<time>: restore that to undo.

param(
    [Parameter(Mandatory = $true, Position = 0)][ValidateSet("save", "restore", "list")][string]$Command,
    [Parameter(Position = 1)][string]$Name,
    [switch]$Overwrite
)

. "$PSScriptRoot\_common.ps1"
$argv = @($Command)
if ($Name) { $argv += $Name }
if ($Overwrite) { $argv += "--overwrite" }
Push-Location $Root
try { & $VenvPy -m storage.snapshot @argv } finally { Pop-Location }
exit $LASTEXITCODE
