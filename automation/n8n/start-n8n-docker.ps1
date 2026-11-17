# Starts FloodGuard n8n in Docker at http://localhost:5678 (see docker-compose.yml).
#
#   powershell -ExecutionPolicy Bypass -File automation\n8n\start-n8n-docker.ps1
#
# The first time, it copies the native install's data (%USERPROFILE%\.floodguard-n8n\data\.n8n:
# account, workflows, data tables, encryption key) into the floodguard_n8n_data volume, so
# nothing has to be set up again. The native folder is left as it was, as a backup.
# "Continue": docker writes normal progress to stderr, which Windows PowerShell would
# otherwise treat as fatal. Failures are caught through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$compose = Join-Path $PSScriptRoot "docker-compose.yml"
$volume = "floodguard_n8n_data"
$native = Join-Path $env:USERPROFILE ".floodguard-n8n\data\.n8n"

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running. Start Docker Desktop and try again." }

# Port 5678 must be free: the native n8n or another n8n container may hold it.
$ours = docker ps --filter "name=^floodguard-n8n$" --format "{{.Names}}"
if (-not $ours) {
  $busy = Get-NetTCPConnection -State Listen -LocalPort 5678 -ErrorAction SilentlyContinue
  if ($busy) {
    $others = docker ps --filter "publish=5678" --format "{{.Names}}"
    if ($others) { throw "Container '$others' already uses port 5678. Stop it first: docker stop $others" }
    throw "Port 5678 is in use (probably the native n8n from start-n8n.ps1). Stop it with Ctrl+C in its window, then run this again."
  }
}

docker volume inspect $volume *> $null
if ($LASTEXITCODE -ne 0) {
  docker volume create $volume | Out-Null
  if (Test-Path (Join-Path $native "database.sqlite")) {
    Write-Host "First run: copying the native n8n data into the Docker volume..."
    docker run --rm -v "${volume}:/to" -v "${native}:/from:ro" alpine sh -c "cp -a /from/. /to/ && chown -R 1000:1000 /to"
    if ($LASTEXITCODE -ne 0) { docker volume rm $volume | Out-Null; throw "Copying the data failed; nothing was changed." }
  } else {
    Write-Host "No native n8n data found: starting a fresh n8n (you will create an owner account)."
  }
}

docker compose -f $compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose failed" }
Write-Host "Waiting for n8n..."
for ($i = 0; $i -lt 90; $i++) {
  try { if ((Invoke-WebRequest -UseBasicParsing http://localhost:5678/healthz -TimeoutSec 2).StatusCode -eq 200) { break } } catch {}
  Start-Sleep 2
}
Write-Host "n8n is running at http://localhost:5678 (it restarts by itself with Docker Desktop)."
Write-Host "Logs: docker logs -f floodguard-n8n    Stop: docker compose -f `"$compose`" stop"
