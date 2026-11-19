# Script to register a Windows Scheduled Task running the news aggregator every 30 minutes
$TaskName = "DylanNewsAggregator30Min"
$ScriptPath = Join-Path $PSScriptRoot "deploy.ps1"

Write-Host "Configuring Windows Scheduled Task: $TaskName" -ForegroundColor Cyan

# Action: Launch PowerShell with deploy.ps1
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Trigger: Start now, repeat every 30 minutes indefinitely
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)

# Settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Register or update task
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs News & Intelligence Aggregator ingestion and S3 deployment every 30 minutes" -Force

Write-Host "[+] Task '$TaskName' registered successfully to trigger every 30 minutes." -ForegroundColor Green
Write-Host "    To verify: Get-ScheduledTask -TaskName $TaskName" -ForegroundColor Gray
Write-Host "    To unregister: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false" -ForegroundColor Gray
