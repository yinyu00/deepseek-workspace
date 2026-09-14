# Run as Administrator: rebuild blank.ico with CORRECT transparent AND mask
# Fix: previous ico had all-zero AND mask (= opaque). Must be 0xFF (= transparent).
$ErrorActionPreference = 'Continue'

$icoPath = 'C:\Windows\blank.ico'
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($ms)

# ICONDIR: reserved=0, type=1(icon), count=2
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]2)

# ICONDIRENTRY helper
function Entry([int]$size, [uint32]$offset) {
    $bw.Write([byte]$size); $bw.Write([byte]$size); $bw.Write([byte]0)
    $bw.Write([byte]0); $bw.Write([uint16]1); $bw.Write([uint16]32)
    $len = 40 + ($size*$size*4) + ($size*4)
    $bw.Write([uint32]$len); $bw.Write([uint32]$offset)
}
Entry 16 22
Entry 32 (22 + 40 + 1024 + 64)

# frame writer: 32bpp pixels with alpha=0, AND mask all 0xFF (transparent)
function Frame([int]$size) {
    $bw.Write([uint32]40); $bw.Write([int32]$size); $bw.Write([int32]($size*2))
    $bw.Write([uint16]1); $bw.Write([uint16]32)
    for ($i=0; $i -lt 12; $i++) { $bw.Write([uint32]0) }
    $px = New-Object byte[] ($size*$size*4)
    for ($i=3; $i -lt $px.Length; $i+=4) { $px[$i] = 0 }    # alpha=0
    $bw.Write($px)
    $mask = New-Object byte[] ($size*4)
    for ($i=0; $i -lt $mask.Length; $i++) { $mask[$i] = 0xFF }  # all transparent
    $bw.Write($mask)
}
Frame 16
Frame 32
$bw.Flush()
[System.IO.File]::WriteAllBytes($icoPath, $ms.ToArray())
$bw.Close()
"Step 1 OK: rebuilt $icoPath ($((Get-Item $icoPath).Length) bytes), AND mask = 0xFF transparent"

# Shell Icons\29 should still point there; re-assert to be safe
$siKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons'
if (-not (Test-Path $siKey)) { New-Item -Path $siKey -Force | Out-Null }
New-ItemProperty -Path $siKey -Name '29' -Value $icoPath -PropertyType String -Force | Out-Null
"Step 2 OK: Shell Icons\29 -> $icoPath"

# purge icon cache to force re-read
"Step 3: purging icon cache & restarting Explorer..."
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache*" -Force -ErrorAction SilentlyContinue
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
"=== Done. Check: no arrow, no white block, icons intact ==="
"=== If still bad: delete Shell Icons\29 + restart Explorer to get arrows back ==="
Read-Host 'Press Enter to exit'
