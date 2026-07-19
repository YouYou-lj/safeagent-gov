$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
python "$ProjectRoot/scripts/setup_uv_env.py"
