# Run as Administrator: overlay = built-in shell32 blank icon resource
# 29 = "C:\Windows\System32\shell32.dll,-50" (negative = resource ID, system blank icon)
$siKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (-not (Test-Path $siKey)) { New-Item -Path $siKey -Force | Out-Null }

New-ItemProperty -Path $siKey -Name '29' -Value 'C:\Windows\System32\shell32.dll,-50' `
    -PropertyType String -Force | Out-Null
"Step 1 OK: Shell Icons\29 = C:\Windows\System32\shell32.dll,-50"

# clean icon cache + restart explorer
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache*" -Force -ErrorAction SilentlyContinue
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
"=== Done. Check desktop: arrow replaced by blank, icons intact? ==="
Read-Host 'Press Enter to exit'
