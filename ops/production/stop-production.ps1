# Stops the FloodGuard production copy started by start-production.ps1.
#
#   powershell -ExecutionPolicy Bypass -File ops\production\stop-production.ps1
. (Join-Path $PSScriptRoot "common.ps1")

$stopped = @()
if (Test-Path $ProdPids) {
  $pids = Get-Content $ProdPids -Raw | ConvertFrom-Json
  foreach ($name in "backend", "frontend") {
    $id = $pids.$name
    if ($id -and (Get-Process -Id $id -ErrorAction SilentlyContinue)) { taskkill /PID $id /T /F | Out-Null; $stopped += $name }
  }
  Remove-Item $ProdPids -ErrorAction SilentlyContinue
}
# Anything still holding the production ports (e.g. started by hand) is stopped too.
foreach ($port in $ProdBackendPort, $ProdFrontendPort) {
  Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | ForEach-Object {
    taskkill /PID $_.OwningProcess /T /F | Out-Null; $stopped += "port $port"
  }
}
if ($stopped.Count) { Write-Host "Production stopped ($($stopped -join ', '))." } else { Write-Host "Production was not running." }
