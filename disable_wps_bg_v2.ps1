# ============================================================
# Disable WPS background autostart v2 (self-check + fallbacks)
# Usage (MUST be elevated): powershell -ExecutionPolicy Bypass -File disable_wps_bg_v2.ps1
# Fallback chain:
#   tasks   : Disable-ScheduledTask -> schtasks /Change /DISABLE
#   service : Set-Service -> registry direct write (Start=4, DoSvc-style bypass)
# ============================================================

# --- 0. Elevation self-check ---
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ("ELEVATED = " + $isAdmin)
if (-not $isAdmin) {
    Write-Host "NOT elevated. Right-click Start -> Terminal (Admin) and rerun this script."
    exit 1
}

# --- 1. Disable 3 WPS tasks (cmdlet -> schtasks fallback) ---
$tasks = @('WpsUpdateLogonTask_jinwei', 'WpsUpdateTask_jinwei', 'WpsWakeWnsLogonTask')
foreach ($t in $tasks) {
    $done = $false
    try {
        Disable-ScheduledTask -TaskName $t -TaskPath '\' -ErrorAction Stop | Out-Null
        Write-Host "OK  task (cmdlet): $t"; $done = $true
    } catch { }
    if (-not $done) {
        $out = schtasks /Change /TN $t /DISABLE 2>&1
        if ($LASTEXITCODE -eq 0) { Write-Host "OK  task (schtasks): $t" }
        else { Write-Host "ERR task ${t}: $out" }
    }
}

# --- 2. Disable cloud service (Set-Service -> registry fallback) ---
$done = $false
try {
    Set-Service -Name wpscloudsvr -StartupType Disabled -ErrorAction Stop
    Write-Host "OK  service (Set-Service): wpscloudsvr -> Disabled"; $done = $true
} catch { }
if (-not $done) {
    $reg = 'HKLM:\SYSTEM\CurrentControlSet\Services\wpscloudsvr'
    try {
        Set-ItemProperty -Path $reg -Name Start -Value 4 -ErrorAction Stop
        Write-Host "OK  service (registry): Start=4 (Disabled). Takes effect on next boot."
    } catch {
        Write-Host "ERR service registry: $($_.Exception.Message)"
    }
}

# --- 3. Kill WPS background processes (again, after sources disabled) ---
Get-Process | Where-Object { $_.ProcessName -match '^wps' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$left = Get-Process | Where-Object { $_.ProcessName -match '^wps' }
if ($left) { Write-Host ("WARN respawned: " + (($left | ForEach-Object { $_.ProcessName + '(' + $_.Id + ')' }) -join ', ')) }
else { Write-Host "OK  all WPS background processes stopped (no respawn)" }

Write-Host ""
Write-Host "Verify later anytime:"
Write-Host "  Get-Process wps* ; Get-ScheduledTask *Wps* ; Get-Service wpscloudsvr"
