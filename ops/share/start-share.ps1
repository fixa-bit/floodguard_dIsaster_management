# Share the full FloodGuard app (development copy) through a password-protected public link.
#
#   powershell -ExecutionPolicy Bypass -File ops\share\start-share.ps1            # start (builds the app if needed)
#   powershell -ExecutionPolicy Bypass -File ops\share\start-share.ps1 -Rebuild   # rebuild the app first, to include new changes
#   powershell -ExecutionPolicy Bypass -File ops\share\start-share.ps1 -NoPassword  # no password: anyone with the link gets in
#   powershell -ExecutionPolicy Bypass -File ops\share\stop-share.ps1             # stop
#
# Starts, each only if not already running:
#   backend  : FastAPI on 127.0.0.1:8300, the share's own (ports 3000 and 8000 are kept for `npm run dev`).
#              Its background jobs (daily report, flood-event watcher) are off, so they never run twice;
#              `npm run dev` runs them.
#   gateway  : ops/share/gateway.mjs on 127.0.0.1:4300 (password + serves frontend/dist + forwards /api)
#   tunnel   : Cloudflare quick tunnel -> https://<random>.trycloudflare.com
# The link works only while this PC is on and these keep running. A quick tunnel gets a new
# address each time it starts; the current one is saved in ops/share/.share-url.
param([switch]$Rebuild, [switch]$NoPassword)
$ErrorActionPreference = "Stop"

$share = $PSScriptRoot
$root = Resolve-Path (Join-Path $share "..\..")
$logs = Join-Path $root ".local-logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$pidFile = Join-Path $logs "share-pids.json"
$state = @{}
if (Test-Path $pidFile) { (Get-Content $pidFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $state[$_.Name] = $_.Value } }

function Test-Port([int]$port) {
  $client = New-Object Net.Sockets.TcpClient
  try { $client.Connect("127.0.0.1", $port); return $true } catch { return $false } finally { $client.Dispose() }
}
# A saved process id counts only if it is still that program: after a restart Windows reuses ids.
function Test-Alive($id, [string]$name) {
  if (-not $id) { return $false }
  $process = Get-Process -Id $id -ErrorAction SilentlyContinue
  return [bool]($process -and (-not $name -or $process.ProcessName -eq $name))
}

# 1. Backend: the share's own, on 8300
$apiPort = 8300
# An older share backend on 8000 (before 8000 was kept for npm run dev) is stopped.
if ($state.api -and $state.apiPort -ne $apiPort -and (Test-Alive $state.api "python")) {
  taskkill /PID $state.api /T /F | Out-Null
  Write-Host "Stopped the share's old backend on port 8000 (pid $($state.api))"
  $state.Remove("api")
}
if (Test-Port $apiPort) {
  Write-Host "Backend already running on port $apiPort"
} else {
  $python = Join-Path $root ".venv\Scripts\python.exe"
  # Read by the backend's settings (app/core/config.py); inherited by the process started below.
  $env:FLOOD_EVENT_REPORTS_ENABLED = "false"
  $env:DAILY_REPORT_SCHEDULE_ENABLED = "false"
  $env:REPORT_API_BASE = "http://127.0.0.1:$apiPort/api/v1"
  $env:REPORT_FRONTEND_URL = "http://127.0.0.1:4300"
  try {
    $p = Start-Process -FilePath $python -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$apiPort" `
      -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "share-api.log") -RedirectStandardError (Join-Path $logs "share-api.err.log")
  } finally {
    Remove-Item Env:FLOOD_EVENT_REPORTS_ENABLED, Env:DAILY_REPORT_SCHEDULE_ENABLED, Env:REPORT_API_BASE, Env:REPORT_FRONTEND_URL -ErrorAction SilentlyContinue
  }
  $state.api = $p.Id
  $state.apiPort = $apiPort
  Write-Host "Starting backend on port $apiPort (pid $($p.Id))"
  for ($i = 0; $i -lt 60 -and -not (Test-Port $apiPort); $i++) { Start-Sleep -Seconds 1 }
  if (-not (Test-Port $apiPort)) { throw "Backend did not start; see $logs\share-api.err.log" }
}

# 1b. Flood Simulation app (Simulation -> Flood simulation lab): its data service on 8010 and its portal build
$simDir = if ($env:FLOOD_SIM_DIR) { $env:FLOOD_SIM_DIR } else { Join-Path (Split-Path -Parent (Split-Path -Parent $root)) "flood sim cursor\flood sim cursor" }
$simPython = Join-Path $simDir ".venv\Scripts\python.exe"
if (Test-Path $simPython) {
  if (Test-Port 8010) {
    Write-Host "Flood simulation data service already running on port 8010"
  } else {
    $p = Start-Process -FilePath $simPython -ArgumentList "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8010" `
      -WorkingDirectory $simDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "share-floodsim.log") -RedirectStandardError (Join-Path $logs "share-floodsim.err.log")
    $state.floodsim = $p.Id
    Write-Host "Starting flood simulation data service (pid $($p.Id))"
  }
  if ($Rebuild -or -not (Test-Path (Join-Path $simDir "dist-portal\index.html"))) {
    Write-Host "Building the flood simulation app for the portal..."
    node (Join-Path $root "scripts\build-flood-sim.mjs") | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Flood simulation build failed" }
  }
} else {
  Write-Host "Flood simulation app not found at $simDir; the Flood simulation lab tab will show how to start it."
}

# 2. Frontend build
$dist = Join-Path $root "frontend\dist\index.html"
if ($Rebuild -or -not (Test-Path $dist)) {
  Write-Host "Building the app (frontend\dist)..."
  Push-Location (Join-Path $root "frontend")
  try { npx vite build | Out-Host; if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" } } finally { Pop-Location }
}

# 3. Gateway (restarted when the password setting or backend port changes; the tunnel and its link stay the same)
$mode = "$(if ($NoPassword) { 'open' } else { 'password' })@$apiPort"
if ((Test-Port 4300) -and $state.gatewayMode -ne $mode -and (Test-Alive $state.gateway "node")) {
  taskkill /PID $state.gateway /T /F | Out-Null
  for ($i = 0; $i -lt 20 -and (Test-Port 4300); $i++) { Start-Sleep -Milliseconds 250 }
  Write-Host "Restarting the gateway ($mode)"
}
if (Test-Port 4300) {
  Write-Host "Gateway already running on port 4300"
} else {
  $gatewayArgs = @("`"$(Join-Path $share 'gateway.mjs')`"", "--api", "http://127.0.0.1:$apiPort") + $(if ($NoPassword) { @("--open") } else { @() })
  $p = Start-Process -FilePath "node" -ArgumentList $gatewayArgs -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs "share-gateway.log") -RedirectStandardError (Join-Path $logs "share-gateway.err.log")
  $state.gateway = $p.Id
  $state.gatewayMode = $mode
  for ($i = 0; $i -lt 20 -and -not (Test-Port 4300); $i++) { Start-Sleep -Milliseconds 500 }
  if (-not (Test-Port 4300)) { throw "Gateway did not start; see $logs\share-gateway.err.log" }
  Write-Host "Gateway started (pid $($p.Id))"
}

# 4. Tunnel
$urlFile = Join-Path $share ".share-url"
if (Test-Alive $state.tunnel "cloudflared") {
  Write-Host "Tunnel already running"
} else {
  $exe = Join-Path $share "bin\cloudflared.exe"
  if (-not (Test-Path $exe)) { throw "cloudflared.exe is missing from $share\bin (download cloudflared-windows-amd64.exe from https://github.com/cloudflare/cloudflared/releases)" }
  $tunnelLog = Join-Path $logs "share-tunnel.log"
  if (Test-Path $tunnelLog) { Remove-Item $tunnelLog }
  $p = Start-Process -FilePath $exe -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:4300", "--logfile", "`"$tunnelLog`"" `
    -WindowStyle Hidden -PassThru
  $state.tunnel = $p.Id
  $url = $null
  for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $tunnelLog) { $m = Select-String -Path $tunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1; if ($m) { $url = $m.Matches[0].Value } }
  }
  if (-not $url) { throw "The tunnel did not report an address; see $tunnelLog" }
  [IO.File]::WriteAllText($urlFile, $url)  # no byte-order mark, so other tools can read it
}

$state | ConvertTo-Json | Set-Content -Path $pidFile -Encoding utf8
Write-Host ""
Write-Host "FloodGuard is shared at: $((Get-Content $urlFile -Raw).Trim())"
if ($state.gatewayMode -like "open*") { Write-Host "No password: anyone with the link can open the app." }
else { Write-Host "Username: floodguard   Password: in ops\share\.share-password" }
Write-Host "Keep this PC on. Stop sharing with ops\share\stop-share.ps1"
