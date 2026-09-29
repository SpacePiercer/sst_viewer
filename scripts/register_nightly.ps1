# Register (or re-register) the nightly sst_viewer job in Task Scheduler.
# Run once:  powershell -File "scripts\register_nightly.ps1"
# Remove:    Unregister-ScheduledTask -TaskPath "\AgenticOS\" -TaskName "sst_viewer_nightly" -Confirm:$false
#
# PowerShell 5.1 here: no ternary, no ??, no && chaining.

$root   = Split-Path -Parent $PSScriptRoot
$py     = "C:\Users\Georgii\miniconda3\envs\mfa_env\python.exe"
$script = Join-Path $root "scripts\nightly.py"
$log    = Join-Path $root "cache\nightly.log"

if (-not (Test-Path $py))     { Write-Error "python not found: $py";     exit 1 }
if (-not (Test-Path $script)) { Write-Error "script not found: $script"; exit 1 }

# Invoke python.exe DIRECTLY. The old cmd.exe wrapper (used only to redirect
# into a log) died with 0xC0000142 when the task fired on wake instead of at
# 03:30, so the job did nothing and logged nothing. nightly.py now tees its own
# output into $log, so nothing is lost. --hours 6 keeps retrying a dark ERDDAP.
$args = "`"$script`" --yes --hours 6 --every 15"

$action  = New-ScheduledTaskAction -Execute $py -Argument $args -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 3:30am
$set     = New-ScheduledTaskSettingsSet -StartWhenAvailable `
             -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
             -ExecutionTimeLimit (New-TimeSpan -Hours 8)

Register-ScheduledTask -TaskPath "\AgenticOS\" -TaskName "sst_viewer_nightly" `
  -Action $action -Trigger $trigger -Settings $set -Force `
  -Description "Wipe sst_viewer derived caches, then re-download today's MUR Okhotsk tiles and global OISST." | Out-Null

Write-Host "registered \AgenticOS\sst_viewer_nightly - daily 03:30, log: $log"
Get-ScheduledTask -TaskPath "\AgenticOS\" -TaskName "sst_viewer_nightly" |
  Select-Object TaskName, State
