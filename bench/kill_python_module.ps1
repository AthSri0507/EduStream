# Hard-kill the Python process(es) running one module, WITHOUT stopping its run_component.ps1 window,
# so the component is restarted the way a real crash would be (fault tests N-3, I-2).
#   powershell -ExecutionPolicy Bypass -File bench\kill_python_module.ps1 -Module agents.note_agent
#
# On Windows the venv's python.exe is a launcher that starts the real interpreter as a child, and both
# carry the module name on their command line; every match is killed with its tree, or an orphaned child
# would keep running (and, for the Note Agent, keep holding its lock).

param([Parameter(Mandatory = $true)][string]$Module)

$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "-m\s+$([regex]::Escape($Module))(\s|$)" }
if (-not $procs) { Write-Host "no python process runs $Module"; exit 1 }
foreach ($p in $procs) {
    & taskkill /PID $p.ProcessId /T /F *> $null
}
Write-Host ("killed {0} at {1}" -f (($procs | ForEach-Object { $_.ProcessId }) -join ","), (Get-Date -Format HH:mm:ss.fff))
