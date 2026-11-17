# Starts the local FloodGuard n8n at http://localhost:5678.
#
#   powershell -ExecutionPolicy Bypass -File automation\n8n\start-n8n.ps1
#
# n8n and its data (your account, workflows, data tables, executions) live in
# %USERPROFILE%\.floodguard-n8n, outside the repo, so they survive reboots and
# are never committed. The first run installs n8n there if it is missing.
# Stop it with Ctrl+C in the window it runs in.
param(
  [int]$Port = 5678,
  [string]$Home_ = "$env:USERPROFILE\.floodguard-n8n",
  [string]$Version = "2.47.7"
)
$ErrorActionPreference = "Stop"
$app = Join-Path $Home_ "app"
$n8n = Join-Path $app "node_modules\n8n\bin\n8n"

if (-not (Test-Path $n8n)) {
  Write-Host "Installing n8n $Version into $app (one time, a few minutes)..."
  New-Item -ItemType Directory -Force $app | Out-Null
  npm install "n8n@$Version" --prefix $app --no-audit --no-fund
  if (-not (Test-Path $n8n)) { throw "n8n install failed" }
}

$env:N8N_USER_FOLDER = Join-Path $Home_ "data"   # n8n keeps everything in data\.n8n
$env:N8N_PORT = "$Port"
$env:N8N_SECURE_COOKIE = "false"                   # plain http on localhost
$env:N8N_DIAGNOSTICS_ENABLED = "false"
$env:N8N_PERSONALIZATION_ENABLED = "false"
$env:GENERIC_TIMEZONE = "Asia/Karachi"
$env:N8N_RUNNERS_BROKER_PORT = "$($Port + 1)"

Write-Host "Starting n8n on http://localhost:$Port (data: $env:N8N_USER_FOLDER)"
node $n8n start
