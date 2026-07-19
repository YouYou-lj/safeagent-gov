$ErrorActionPreference = "Stop"
$DesktopDir = Split-Path -Parent $PSScriptRoot
$ReleaseDir = Join-Path (Split-Path -Parent $DesktopDir) "release/windows"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Get-ChildItem "$DesktopDir/src-tauri/target/release/bundle" -Recurse -File |
  Where-Object { $_.Extension -eq ".msi" -or $_.Name -match "setup.*\.exe$" } |
  Copy-Item -Destination $ReleaseDir
if (-not (Get-ChildItem $ReleaseDir -Filter "*.msi" -File)) { throw "Windows MSI was not produced" }
if (-not (Get-ChildItem $ReleaseDir -Filter "*setup*.exe" -File)) { throw "Windows NSIS installer was not produced" }
Write-Host "Windows release artifacts: $ReleaseDir"
