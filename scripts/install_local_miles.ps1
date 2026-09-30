$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source
$windowlessPython = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (Test-Path -LiteralPath $windowlessPython) { $pythonPath = $windowlessPython }
$scriptPath = Join-Path $PSScriptRoot 'local_miles.py'
$userIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $scriptPath + '" --scheduled') -WorkingDirectory $workspacePath
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At '08:00'),
    (New-ScheduledTaskTrigger -Daily -At '14:00'),
    (New-ScheduledTaskTrigger -Daily -At '20:00'),
    (New-ScheduledTaskTrigger -AtLogOn -User $userIdentity)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $userIdentity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'FlightAlert-Milhas' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description 'Coleta local de milhas às 08h, 14h e 20h; recupera horários perdidos ao entrar no Windows.' -Force | Out-Null
Write-Output 'Agendamento local instalado: 08h, 14h, 20h e ao entrar no Windows.'
