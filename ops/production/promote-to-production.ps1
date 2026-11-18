# Promotes the tested development version to production.
#
#   powershell -ExecutionPolicy Bypass -File ops\production\promote-to-production.ps1
#
# Production only changes when every step passes:
#   1. the development folder has no uncommitted changes (the commit is what you tested);
#   2. the backend tests pass;
#   3. the frontend type-checks and builds;
#   4. you confirm each feature in feature-checklist.txt was tested by hand.
# Then the commit is tagged release-YYYY-MM-DD-N, the production branch moves to it,
# production's dependencies are updated if they changed, and production restarts.
# Undo with rollback-production.ps1.
. (Join-Path $PSScriptRoot "common.ps1")
Assert-ProductionFolder

function Stop-Promotion([string]$Why) {
  Write-Host "`nPromotion stopped: $Why`nProduction was not changed." -ForegroundColor Red
  exit 1
}

Write-Step "1/4 Development state"
$dirty = git -C $DevRoot status --porcelain
if ($dirty) { Stop-Promotion "the development folder has uncommitted changes. Commit the version you tested first." }
$commit = (git -C $DevRoot rev-parse HEAD).Trim()
$current = (git -C $ProdRoot rev-parse HEAD).Trim()
if ($commit -eq $current) { Write-Host "Production already runs this commit ($($commit.Substring(0,8)))."; exit 0 }
git -C $DevRoot merge-base --is-ancestor $current $commit
if ($LASTEXITCODE -ne 0) { Stop-Promotion "this commit does not build on the current production version (different history). Merge production into your branch first." }
Write-Host "Promoting $($commit.Substring(0,8)): $(git -C $DevRoot log -1 --format=%s $commit)"
Write-Host "Production now runs $($current.Substring(0,8)) ($(git -C $ProdRoot describe --tags --always))."

Write-Step "2/4 Backend tests"
Push-Location $DevRoot
& (Join-Path $DevRoot ".venv\Scripts\python.exe") -m pytest -q -p no:warnings
$testsOk = $LASTEXITCODE -eq 0
Pop-Location
if (-not $testsOk) { Stop-Promotion "backend tests failed." }

Write-Step "3/4 Frontend type-check and build"
Push-Location (Join-Path $DevRoot "frontend")
npm run build
$buildOk = $LASTEXITCODE -eq 0
Pop-Location
if (-not $buildOk) { Stop-Promotion "the frontend did not type-check or build." }

Write-Step "4/4 Features tested by hand (in development, http://localhost:3000)"
$items = Get-Content (Join-Path $PSScriptRoot "feature-checklist.txt") | Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith("#") }
foreach ($item in $items) {
  $answer = Read-Host "Tested and working: $item ? (y/n)"
  if ($answer -notmatch "^(y|yes)$") { Stop-Promotion "not confirmed: $item" }
}

Write-Step "Releasing"
$day = Get-Date -Format "yyyy-MM-dd"
$n = 1; while (git -C $DevRoot tag -l "release-$day-$n") { $n++ }
$tag = "release-$day-$n"
git -C $DevRoot tag -a $tag $commit -m "Promoted to production $((Get-Date).ToString('s')): tests, build and $($items.Count) hand-tested features passed"
git -C $ProdRoot merge --ff-only $tag
if ($LASTEXITCODE -ne 0) { Stop-Promotion "could not move the production folder to $tag." }

# Dependencies: only reinstalled in production when they changed.
git -C $DevRoot diff --quiet $current $commit -- requirements.txt
if ($LASTEXITCODE -ne 0) {
  Write-Step "Python requirements changed: updating production's environment"
  & $ProdPython -m pip install -r (Join-Path $ProdRoot "requirements.txt")
}
git -C $DevRoot diff --quiet $current $commit -- frontend/package-lock.json frontend/package.json
if ($LASTEXITCODE -ne 0) {
  Write-Step "Frontend packages changed: updating production's packages"
  Push-Location (Join-Path $ProdRoot "frontend"); npm ci; Pop-Location
}

Write-Step "Restarting production"
& (Join-Path $PSScriptRoot "stop-production.ps1")
& (Join-Path $PSScriptRoot "start-production.ps1") -Rebuild
New-Item -ItemType Directory -Force $ProdLogs | Out-Null
Add-Content (Join-Path $ProdLogs "promotions.log") "$((Get-Date).ToString('s'))  $tag  $commit  (was $current)"
Write-Host "`nProduction now runs $tag. To undo: ops\production\rollback-production.ps1" -ForegroundColor Green
