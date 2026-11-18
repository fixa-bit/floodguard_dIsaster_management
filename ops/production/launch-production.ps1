# One-click launcher for the FloodGuard production copy (used by the desktop shortcut).
# Starts production if it is not already running (or is only half running), then opens it
# in the default browser.
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ProductionFolder
$url = "http://127.0.0.1:$ProdFrontendPort"

$backendUp  = Test-PortOpen $ProdBackendPort
$frontendUp = Test-PortOpen $ProdFrontendPort
if ($backendUp -and $frontendUp) {
  Write-Host "FloodGuard production is already running."
} else {
  if ($backendUp -or $frontendUp) {
    Write-Host "Production was only partly running; restarting it."
    & (Join-Path $PSScriptRoot "stop-production.ps1")
  }
  Write-Host "Starting FloodGuard production (this takes up to a minute)..."
  & (Join-Path $PSScriptRoot "start-production.ps1")
  if (-not ((Test-PortOpen $ProdBackendPort) -and (Test-PortOpen $ProdFrontendPort))) {
    Write-Host "`nProduction could not start. Logs: $ProdLogs" -ForegroundColor Red
    exit 1
  }
}
Start-Process $url
Write-Host "Opened $url"
