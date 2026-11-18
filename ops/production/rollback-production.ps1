# Puts production back on an earlier release.
#
#   powershell -ExecutionPolicy Bypass -File ops\production\rollback-production.ps1            (the release before the current one)
#   powershell -ExecutionPolicy Bypass -File ops\production\rollback-production.ps1 -To release-2026-11-18-1
#
# Only code changes: production's database, .env and reports are kept.
param([string]$To)
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ProductionFolder

$releases = @(git -C $DevRoot tag -l "release-*" --sort=creatordate)
if (-not $releases.Count) { throw "No release tags found." }
$current = (git -C $ProdRoot rev-parse HEAD).Trim()
$currentTag = git -C $DevRoot tag --points-at $current -l "release-*" | Select-Object -Last 1
if (-not $To) {
  $index = [array]::IndexOf($releases, $currentTag)
  if ($index -le 0) { throw "No earlier release than $currentTag. Releases: $($releases -join ', ')" }
  $To = $releases[$index - 1]
}
if ($releases -notcontains $To) { throw "Unknown release $To. Releases: $($releases -join ', ')" }

Write-Host "Production runs $currentTag ($($current.Substring(0,8))). Roll back to $To ?"
if ((Read-Host "Type yes to roll back") -ne "yes") { Write-Host "Nothing changed."; exit 0 }

$target = (git -C $DevRoot rev-list -n 1 $To).Trim()
git -C $ProdRoot reset --hard $target
git -C $DevRoot diff --quiet $current $target -- requirements.txt
if ($LASTEXITCODE -ne 0) { & $ProdPython -m pip install -r (Join-Path $ProdRoot "requirements.txt") }
git -C $DevRoot diff --quiet $current $target -- frontend/package-lock.json frontend/package.json
if ($LASTEXITCODE -ne 0) { Push-Location (Join-Path $ProdRoot "frontend"); npm ci; Pop-Location }

& (Join-Path $PSScriptRoot "stop-production.ps1")
& (Join-Path $PSScriptRoot "start-production.ps1") -Rebuild
New-Item -ItemType Directory -Force $ProdLogs | Out-Null
Add-Content (Join-Path $ProdLogs "promotions.log") "$((Get-Date).ToString('s'))  ROLLBACK to $To  $target  (was $current)"
Write-Host "`nProduction is back on $To." -ForegroundColor Green
