# Starts the FloodGuard production copy:
#   backend   http://127.0.0.1:8100   (no auto-reload: code edits never restart it)
#   frontend  http://127.0.0.1:4100   (a fixed build, served by "vite preview")
#
#   powershell -ExecutionPolicy Bypass -File ops\production\start-production.ps1
#
# Both run in the background; logs go to floodguard-production\.local-logs.
# Stop with ops\production\stop-production.ps1.
param([switch]$Rebuild)
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ProductionFolder
New-Item -ItemType Directory -Force $ProdLogs | Out-Null

if ((Test-PortOpen $ProdBackendPort) -or (Test-PortOpen $ProdFrontendPort)) {
  Write-Host "Production is already running (port $ProdBackendPort or $ProdFrontendPort in use). Stop it first: ops\production\stop-production.ps1" -ForegroundColor Yellow
  exit 1
}

$frontend = Join-Path $ProdRoot "frontend"
# A byte-order mark at the start of an .env file hides its first setting; strip it if present.
foreach ($envFile in (Join-Path $ProdRoot ".env"), (Join-Path $frontend ".env")) {
  if (Test-Path $envFile) {
    $bytes = [IO.File]::ReadAllBytes($envFile)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
      [IO.File]::WriteAllBytes($envFile, $bytes[3..($bytes.Length - 1)])
    }
  }
}
$apiSetting = Select-String -Path (Join-Path $frontend ".env") -Pattern "^VITE_API_BASE_URL=.*:$ProdBackendPort/" -Quiet
if (-not $apiSetting) { throw "frontend\.env in production must set VITE_API_BASE_URL to the production backend (port $ProdBackendPort)." }
if ($Rebuild -or -not (Test-Path (Join-Path $frontend "dist\index.html"))) {
  Write-Step "Building the production frontend"
  Push-Location $frontend
  npm run build
  $ok = $LASTEXITCODE -eq 0
  Pop-Location
  if (-not $ok) { throw "Frontend build failed; production not started." }
}

Write-Step "Starting the production backend on port $ProdBackendPort"
$backend = Start-Process -FilePath $ProdPython -WorkingDirectory $ProdRoot -WindowStyle Hidden -PassThru `
  -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ProdBackendPort" `
  -RedirectStandardOutput (Join-Path $ProdLogs "backend.out.log") -RedirectStandardError (Join-Path $ProdLogs "backend.err.log")

Write-Step "Starting the production frontend on port $ProdFrontendPort"
$vite = Join-Path $frontend "node_modules\vite\bin\vite.js"
$web = Start-Process -FilePath "node" -WorkingDirectory $frontend -WindowStyle Hidden -PassThru `
  -ArgumentList "`"$vite`"", "preview", "--host", "127.0.0.1", "--port", "$ProdFrontendPort", "--strictPort" `
  -RedirectStandardOutput (Join-Path $ProdLogs "frontend.out.log") -RedirectStandardError (Join-Path $ProdLogs "frontend.err.log")

@{ backend = $backend.Id; frontend = $web.Id; started = (Get-Date).ToString("s") } | ConvertTo-Json | Set-Content $ProdPids

$apiUp = Wait-Url "http://127.0.0.1:$ProdBackendPort/api/v1/health"
$webUp = Wait-Url "http://127.0.0.1:$ProdFrontendPort/"
$release = (git -C $ProdRoot describe --tags --always 2>$null)
if ($apiUp -and $webUp) {
  Write-Host "`nProduction is running: http://127.0.0.1:$ProdFrontendPort  (release $release)" -ForegroundColor Green
} else {
  Write-Host "`nProduction did not come up (backend: $apiUp, frontend: $webUp). See $ProdLogs" -ForegroundColor Red
  exit 1
}
