# ShotHub installer: copy exe to a stable location + create Start Menu shortcut
# Note: keep this file ASCII-only (or UTF-8 with BOM) so Windows PowerShell 5.1 parses it.
$ErrorActionPreference = "Stop"

$src = Join-Path $PSScriptRoot "..\dist\ShotHub.exe"
$binDir = Join-Path $env:LOCALAPPDATA "ShotHub\bin"
$exe = Join-Path $binDir "ShotHub.exe"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Copy-Item $src $exe -Force
Write-Output "installed: $exe"

# Start Menu shortcut
$lnkPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ShotHub.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = $exe
$sc.IconLocation = "$exe,0"
$sc.WorkingDirectory = $binDir
$sc.Description = "ShotHub - Screenshot staging hub"
$sc.Save()
Write-Output "shortcut: $lnkPath"
