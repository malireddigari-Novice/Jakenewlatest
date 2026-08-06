# Registers the Jakenew_DailyRun scheduled task: starts the Attention Engine at 08:10 CST
# every weekday. Idempotent — re-run to update. No admin required (runs as the current user
# when logged on). Remove with:  Unregister-ScheduledTask -TaskName Jakenew_DailyRun -Confirm:$false
$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = 'Jakenew_DailyRun'
$bat      = Join-Path $root 'run_scheduled.bat'

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$bat`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 8:10AM
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -WakeToRun `
    -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'Jakenew MAG-7 Attention Engine - starts main.py each trading morning (08:10 CST).' | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Output "Registered '$taskName' (state: $($t.State))"
Write-Output "Next run: $($info.NextRunTime)"
