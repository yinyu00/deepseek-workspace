# Run as Administrator: fix broken shortcuts + hide arrow properly
# 1) Restore IsShortcut (fixes "no app associated" error on ALL shortcuts)
# 2) Apply multi-size transparent overlay icon (16x16 + 32x32, no stretching)
$ErrorActionPreference = 'Continue'

# ---- 1. Restore IsShortcut ----
$lnkKey = 'Registry::HKEY_CLASSES_ROOT\lnkfile'
if (Get-ItemProperty -Path $lnkKey -Name 'IsShortcut.bak' -ErrorAction SilentlyContinue) {
    Rename-ItemProperty -Path $lnkKey -Name 'IsShortcut.bak' -NewName 'IsShortcut'
    "Step 1 OK: IsShortcut restored (shortcuts will launch again)"
}

# ---- 2. Build a 2-frame (16x16 + 32x32) fully transparent .ico ----
$icoPath = 'C:\Windows\blank.ico'
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($ms)
function Write-IconFrame([System.IO.BinaryWriter]$bw, [int]$size, [uint32]$offset) {
    # ICONDIRENTRY
    $bw.Write([byte]$size); $bw.Write([byte]$size); $bw.Write([byte]0)
    $bw.Write([byte]0); $bw.Write([uint16]1); $bw.Write([uint16]32)
    $dataLen = 40 + ($size*$size*4) + ($size*4)   # header + XOR + AND(aligned)
    $bw.Write([uint32]$dataLen); $bw.Write([uint32]$offset)
}
# ICONDIR: reserved=0, type=1(icon), count=2
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]2)
Write-IconFrame $bw 16 22
Write-IconFrame $bw 32 (22 + 40 + 1024 + 64)
# frame 1: 16x16
$bw.Write([uint32]40); $bw.Write([int32]16); $bw.Write([int32]32)
$bw.Write([uint16]1); $bw.Write([uint16]32)
for ($i=0; $i -lt 12; $i++) { $bw.Write([uint32]0) }
$bw.Write((New-Object byte[] (16*16*4)))   # transparent pixels
$bw.Write((New-Object byte[] (16*4)))      # AND mask (16 rows x 2B, padded to 4)
# frame 2: 32x32
$bw.Write([uint32]40); $bw.Write([int32]32); $bw.Write([int32]64)
$bw.Write([uint16]1); $bw.Write([uint16]32)
for ($i=0; $i -lt 12; $i++) { $bw.Write([uint32]0) }
$bw.Write((New-Object byte[] (32*32*4)))
$bw.Write((New-Object byte[] (32*4)))
$bw.Flush()
[System.IO.File]::WriteAllBytes($icoPath, $ms.ToArray())
$bw.Close()
"Step 2 OK: 2-frame transparent icon at $icoPath ($((Get-Item $icoPath).Length) bytes)"

# ---- 3. Register overlay ----
$siKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (-not (Test-Path $siKey)) { New-Item -Path $siKey -Force | Out-Null }
New-ItemProperty -Path $siKey -Name '29' -Value $icoPath -PropertyType String -Force | Out-Null
"Step 3 OK: Shell Icons\29 -> $icoPath"

# ---- 4. Restart Explorer ----
"Step 4: restarting Explorer..."
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
"=== Done: shortcuts fixed, arrow hidden with correct-size overlay ==="
"=== Revert arrow: delete Shell Icons\29 and restart Explorer ==="
Read-Host 'Press Enter to exit'
