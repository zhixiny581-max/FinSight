param(
    [switch]$Check,
    [switch]$NoOpen,
    [ValidateRange(0, 65535)][int]$PortOverride = 0
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$envFile = Join-Path $projectRoot '.env'
$templateFile = Join-Path $projectRoot '.env.example'
$dataDir = Join-Path $projectRoot 'data'

function Stop-WithMessage([string]$message) {
    Write-Host "[Error] $message" -ForegroundColor Red
    exit 1
}

function Read-LocalSettings([string]$filePath) {
    $settings = @{}
    foreach ($line in Get-Content -LiteralPath $filePath -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) { continue }
        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim().Trim('"', "'")
        if ($name -match '^[A-Z][A-Z0-9_]*$') { $settings[$name] = $value }
    }
    return $settings
}

function Is-Placeholder([string]$value) {
    return [string]::IsNullOrWhiteSpace($value) -or $value -match '(?i)your.*(key|token)'
}

function Get-RunningService([int]$port) {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/status" -TimeoutSec 2
    } catch {
        return $null
    }
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Stop-WithMessage 'Node.js is missing. Install Node.js 18 or newer.' }
$versionText = (& $node.Source --version).TrimStart('v')
try { $nodeVersion = [version]$versionText } catch { Stop-WithMessage 'Cannot read the Node.js version.' }
if ($nodeVersion.Major -lt 18) { Stop-WithMessage 'Node.js 18 or newer is required.' }

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath $templateFile -Destination $envFile
    Write-Host 'Created .env. Enter your iFinD MCP authorization and DeepSeek API key, save, then double-click again.'
    if (-not $Check) { Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $envFile + '"') }
    exit 2
}

$settings = Read-LocalSettings $envFile
if (Is-Placeholder $settings['DEEPSEEK_API_KEY']) {
    Write-Host 'Enter DEEPSEEK_API_KEY in .env.'
    if (-not $Check) { Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $envFile + '"') }
    exit 3
}

$directIfindKey = $settings['IFIND_MCP_AUTHORIZATION']
if (Is-Placeholder $directIfindKey) { $directIfindKey = $settings['IFIND_API_KEY'] }
if (Is-Placeholder $directIfindKey) {
    $directIfindKey = [Environment]::GetEnvironmentVariable('IFIND_API_KEY', 'User')
    if (-not (Is-Placeholder $directIfindKey)) { $env:IFIND_API_KEY = $directIfindKey }
}
$skillDir = if ($settings['IFIND_SKILL_DIR']) { $settings['IFIND_SKILL_DIR'] } else { Join-Path $env:USERPROFILE '.codex\skills\ifind-finance-data' }
$skillConfig = Join-Path $skillDir 'mcp_config.json'
$skillClient = Join-Path $skillDir 'call-node.js'
$skillReady = $false
if ((Test-Path -LiteralPath $skillConfig) -and (Test-Path -LiteralPath $skillClient)) {
    try {
        $skillSettings = Get-Content -LiteralPath $skillConfig -Encoding UTF8 -Raw | ConvertFrom-Json
        $skillReady = -not (Is-Placeholder $skillSettings.auth_token)
    } catch { $skillReady = $false }
}
if ((Is-Placeholder $directIfindKey) -and -not $skillReady) {
    Write-Host 'Enter IFIND_MCP_AUTHORIZATION in .env, or configure the ifind-finance-data Skill.'
    if (-not $Check) { Start-Process -FilePath 'notepad.exe' -ArgumentList ('"' + $envFile + '"') }
    exit 4
}

$port = 3000
if ($settings['PORT']) {
    if (-not [int]::TryParse($settings['PORT'], [ref]$port) -or $port -lt 1024 -or $port -gt 65535) {
        Stop-WithMessage 'PORT must be an integer from 1024 to 65535.'
    }
}
if ($PortOverride -ne 0) { $port = $PortOverride }
$env:PORT = [string]$port

if ($Check) {
    Write-Host "Configuration found. Node.js $nodeVersion; iFinD and DeepSeek configured; port $port."
    exit 0
}

$existing = Get-RunningService $port
$isExistingPrototype = $existing -and (
    $existing.app -eq 'finsight-news-prototype' -or
    ($existing.mode -in @('live_ready', 'mock_only') -and $null -ne $existing.deepseek -and $null -ne $existing.skillInstalled)
)
$expectedAnalysisSchemaVersion = 6
if ($isExistingPrototype -and [int]$existing.analysisSchemaVersion -ne $expectedAnalysisSchemaVersion) {
    $listenerProcessId = $null
    $listenerPattern = "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $listenerLine = netstat -ano -p TCP | Where-Object { $_ -match $listenerPattern } | Select-Object -First 1
    if ($listenerLine -and $listenerLine -match $listenerPattern) { $listenerProcessId = [int]$Matches[1] }
    $listenerProcess = if ($listenerProcessId) { Get-Process -Id $listenerProcessId -ErrorAction SilentlyContinue } else { $null }
    if (-not $listenerProcess -or $listenerProcess.ProcessName -ne 'node') {
        Stop-WithMessage "An outdated FinSight service is running on port $port, but its Node.js process could not be identified. Stop that process and run this launcher again."
    }
    Write-Host "Restarting outdated FinSight analysis service on port $port..."
    Stop-Process -Id $listenerProcessId -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 100
        if (-not (Get-RunningService $port)) { break }
    }
    if (Get-RunningService $port) {
        Stop-WithMessage "The outdated FinSight service on port $port did not stop. End Node.js process $listenerProcessId and run this launcher again."
    }
    $existing = $null
    $isExistingPrototype = $false
}
if ($existing -and -not $isExistingPrototype) {
    Stop-WithMessage "Port $port is used by another service. Change PORT in .env."
}

if (-not $existing) {
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    $stdout = Join-Path $dataDir 'server.log'
    $stderr = Join-Path $dataDir 'server-error.log'
    # Some Windows hosts expose both Path and PATH; Start-Process rejects that pair.
    $savedPath = $env:Path
    Remove-Item Env:PATH -ErrorAction SilentlyContinue
    if (-not $env:Path -and $savedPath) { $env:Path = $savedPath }
    Start-Process -FilePath $node.Source -ArgumentList @('server.js', "--port=$port") -WorkingDirectory $projectRoot `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $existing = Get-RunningService $port
        if ($existing) { break }
    }
    if (-not $existing -or $existing.app -ne 'finsight-news-prototype') {
        Stop-WithMessage 'The server did not start. See data\server-error.log.'
    }
}

$siteUrl = "http://127.0.0.1:$port/"
Write-Host "FinSight is ready: $siteUrl"
if (-not $NoOpen) { Start-Process -FilePath $siteUrl }
