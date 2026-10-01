$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot "docs\FloodGuard_Backend_Technical_Overview.html"
$outputPath = Join-Path $projectRoot "docs\FloodGuard_Backend_Technical_Overview.pdf"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if (-not (Test-Path -LiteralPath $edgePath)) {
    $edgePath = "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
}
if (-not (Test-Path -LiteralPath $edgePath)) {
    throw "Microsoft Edge was not found. Install Edge or update edgePath in this script."
}
if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "Documentation source not found: $sourcePath"
}

$profilePath = Join-Path ([System.IO.Path]::GetTempPath()) ("floodguard-pdf-" + [guid]::NewGuid())
$sourceUri = [uri]::new($sourcePath)

try {
    New-Item -ItemType Directory -Path $profilePath | Out-Null
    & $edgePath `
        --headless `
        --disable-gpu `
        --disable-breakpad `
        --disable-crash-reporter `
        --no-first-run `
        --no-pdf-header-footer `
        "--user-data-dir=$profilePath" `
        "--print-to-pdf=$outputPath" `
        $sourceUri.AbsoluteUri 2>$null

    if (-not (Test-Path -LiteralPath $outputPath)) {
        throw "PDF generation did not create: $outputPath"
    }
    Write-Output "Generated $outputPath"
}
finally {
    if (Test-Path -LiteralPath $profilePath) {
        $removed = $false
        for ($attempt = 0; $attempt -lt 40 -and -not $removed; $attempt++) {
            try {
                Remove-Item -LiteralPath $profilePath -Recurse -Force -ErrorAction Stop
                $removed = $true
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        if (-not $removed) {
            Write-Warning "Temporary Edge profile is still in use and will remain at $profilePath"
        }
    }
}
