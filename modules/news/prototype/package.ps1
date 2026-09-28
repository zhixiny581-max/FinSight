$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$outputName = 'FinSight-news-prototype-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip'
$outputPath = Join-Path (Split-Path -Parent $projectRoot) $outputName
$files = @(
    '.env.example', 'README.md', 'package.json', 'index.html', 'server.js',
    'ifind_client.js', 'start.ps1', 'package.ps1'
)
$files += @(Get-ChildItem -LiteralPath $projectRoot -Filter '*.cmd' -File | Select-Object -ExpandProperty Name)

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::Open($outputPath, 'Create')
try {
    foreach ($name in $files) {
        $source = Join-Path $projectRoot $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Missing package file: $name"
        }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, $source, ('prototype/' + $name),
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
} catch {
    $archive.Dispose()
    Remove-Item -LiteralPath $outputPath -Force
    throw
} finally {
    $archive.Dispose()
}
Write-Host "Created: $outputPath"
Write-Host 'The archive excludes .env, data, local credentials, and Git files.'
