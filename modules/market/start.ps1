param(
    [string]$IfindConfigPath = $env:IFIND_MCP_CONFIG,
    [ValidateRange(1024, 65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$pythonPath = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install modules/market/requirements.txt first. See modules/market/README.md.'
}
if ($IfindConfigPath) {
    $env:IFIND_MCP_CONFIG = (Resolve-Path -LiteralPath $IfindConfigPath).Path
}
Push-Location -LiteralPath $repoRoot
try {
    & $pythonPath -m uvicorn modules.market.app:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
