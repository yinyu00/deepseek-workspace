# ============================================================
# Disable WPS background autostart (run in ELEVATED PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File disable_wps_bg.ps1
# What it does:
#   1. Disable 3 WPS scheduled tasks (cloud wake + update checks)
#   2. Disable "WPS Office Cloud Service" (wpscloudsvr)
#   3. Kill all user-mode WPS background processes
# WPS itself still works when you open it manually.
# To revert: Enable-ScheduledTask -TaskName <name>; Set-Service wpscloudsvr -StartupType Manual
# ============================================================

$tasks = @('WpsUpdateLogonTask_jinwei', 'WpsUpdateTask_jinwei', 'WpsWakeWnsLogonTask')
foreach ($t in $tasks) {
    try {
        Disable-ScheduledTask -TaskName $t -TaskPath '\' -ErrorAction Stop | Out-Null
        Write-Host "OK  task disabled: $t"
    } catch {
        Write-Host "ERR task ${t}: $($_.Exception.Message)"
    }
}

try {
    Set-Service -Name wpscloudsvr -StartupType Disabled -ErrorAction Stop
    Write-Host "OK  service wpscloudsvr -> Disabled"
} catch {
    Write-Host "ERR service: $($_.Exception.Message)"
}

Get-Process | Where-Object { $_.ProcessName -match '^wps' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$left = Get-Process | Where-Object { $_.ProcessName -match '^wps' }
if ($left) {
    Write-Host ("WARN still running: " + ($left.ProcessName -join ', '))
} else {
    Write-Host "OK  all WPS background processes stopped"
}
