# Run as Administrator: remove shortcut arrow - IsShortcut rename method
# Step 0: revert the blank icon overlay (previous attempt)
# Step 1: rename HKCR\lnkfile\IsShortcut -> IsShortcut.bak

$ErrorActionPreference = 'Continue'

# ---- 0. Revert Shell Icons\29 ----
$siKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (Test-Path $siKey) {
    Remove-ItemProperty -Path $siKey -Name '29' -ErrorAction SilentlyContinue
    "Step 0 OK: Shell Icons\\29 removed"
}
Remove-Item 'C:\Windows\blank.ico' -Force -ErrorAction SilentlyContinue

# ---- 1. Rename IsShortcut in lnkfile class ----
$lnkKey = 'Registry::HKEY_CLASSES_ROOT\lnkfile'
if (Get-ItemProperty -Path $lnkKey -Name IsShortcut -ErrorAction SilentlyContinue) {
    Rename-ItemProperty -Path $lnkKey -Name 'IsShortcut' -NewName 'IsShortcut.bak'
    "Step 1 OK: IsShortcut renamed to IsShortcut.bak"
} elseif (Get-ItemProperty -Path $lnkKey -Name 'IsShortcut.bak' -ErrorAction SilentlyContinue) {
    "Step 1 skip: IsShortcut already renamed"
} else {
    "Step 1 WARN: IsShortcut not found in lnkfile"
}

# ---- 2. Restart Explorer ----
"Step 2: restarting Explorer..."
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
"=== Done. Arrows should be gone with icons intact. ==="
"=== To revert: rename IsShortcut.bak back to IsShortcut ==="
Read-Host 'Press Enter to exit'
