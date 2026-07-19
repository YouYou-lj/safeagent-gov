$ErrorActionPreference = "Stop"
$DesktopDir = Split-Path -Parent $PSScriptRoot
if (-not $IsWindows) { throw "Windows x64 native runner required" }
Set-Location $DesktopDir
npm run sidecar:build
npm run sidecar:verify
npm run tauri -- build --config windows/tauri.windows.conf.json --bundles msi,nsis --ci
& "$PSScriptRoot/package-msi.ps1"
