# Shared settings for the FloodGuard production copy (dot-sourced by the other scripts).
#
# Production is a git worktree of this repository, checked out on the "production"
# branch, in a sibling folder. It has its own .env, database, Python environment and
# frontend packages, and runs on its own ports, so development never affects it.
$ErrorActionPreference = "Continue"

$DevRoot  = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ProdRoot = Join-Path (Split-Path $DevRoot -Parent) "floodguard-production"
$ProdBackendPort  = 8100
$ProdFrontendPort = 4100
$ProdPython = Join-Path $ProdRoot ".venv\Scripts\python.exe"
$ProdLogs   = Join-Path $ProdRoot ".local-logs"
$ProdPids   = Join-Path $ProdLogs "production-pids.json"

function Assert-ProductionFolder {
  if (-not (Test-Path (Join-Path $ProdRoot ".git"))) {
    throw "Production folder not found at $ProdRoot. It is created once with: git worktree add `"$ProdRoot`" production"
  }
}

function Test-PortOpen([int]$Port) {
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Url([string]$Url, [int]$Seconds = 120) {
  for ($i = 0; $i -lt $Seconds; $i += 2) {
    try { if ((Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5).StatusCode -lt 500) { return $true } } catch {}
    Start-Sleep 2
  }
  return $false
}

function Write-Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }
