# Run as Administrator: stop + disable the agreed bloat services
# Generated for jinwei 2026-09-14
$services = @(
    'MuMuRemoteService',   # MuMu emulator remote service
    'NahimicService',      # Nahimic audio bloat
    'lfsvc',               # Geolocation
    'TrkWks',              # Distributed Link Tracking
    'lmhosts',             # NetBIOS helper
    'SharedAccess',        # ICS
    'InstallService',      # Store install
    'PcaSvc',              # Program Compat Assistant
    'whesvc',              # Health & optimization telemetry
    'InventorySvc',        # Inventory & compat telemetry
    'DusmSvc',             # Data usage metering
    'WSAIFabricSvc'        # Windows AI / Copilot pipeline
)

"=== Stop & disable services $(Get-Date) ==="
foreach ($s in $services) {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if (-not $svc) { "[$s] NOT FOUND, skip"; continue }

    # stop first
    if ($svc.Status -ne 'Stopped') {
        Stop-Service -Name $s -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    # disable via registry (bypasses SCM protection like DoSvc)
    try {
        Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$s" `
            -Name Start -Value 4 -ErrorAction Stop
        $regOK = $true
    } catch {
        # fallback to sc
        sc.exe config $s start= disabled | Out-Null
        $regOK = $?
    }

    $now = Get-Service -Name $s
    "[{0}] Status={1} StartType={2} (registry write: {3})" -f $s, $now.Status, $now.StartType, $regOK
}

"=== Done, you can close this window ==="
Read-Host 'Press Enter to exit'
