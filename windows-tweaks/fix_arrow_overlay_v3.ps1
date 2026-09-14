# Run as Administrator: last attempt - empty string overlay (Win11 path)
# Empty 29 value tells Explorer to draw NO overlay instead of validating an icon file
$siKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (-not (Test-Path $siKey)) { New-Item -Path $siKey -Force | Out-Null }

# empty string, not removed - removed would fall back to default arrow
New-ItemProperty -Path $siKey -Name '29' -Value '' -PropertyType String -Force | Out-Null
"Step 1 OK: Shell Icons\29 = '' (empty string)"

# clean icon cache + restart explorer
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache*" -Force -ErrorAction SilentlyContinue
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
"=== Done. Check desktop: arrow gone? icons intact? ==="
Read-Host 'Press Enter to exit'
