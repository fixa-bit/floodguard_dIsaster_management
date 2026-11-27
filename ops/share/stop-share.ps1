# Stop sharing: closes the tunnel and gateway, and the backend only if start-share.ps1 started it.
#   powershell -ExecutionPolicy Bypass -File ops\share\stop-share.ps1
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$pidFile = Join-Path $root ".local-logs\share-pids.json"
if (-not (Test-Path $pidFile)) { Write-Host "Nothing to stop (no share-pids.json)"; return }
$state = Get-Content $pidFile -Raw | ConvertFrom-Json
# Only the program each id was saved for: after a restart Windows reuses ids for other programs.
$programs = @{ tunnel = "cloudflared"; gateway = "node"; floodsim = "python"; api = "python" }
foreach ($name in "tunnel", "gateway", "floodsim", "api") {
  $id = $state.$name
  $process = if ($id) { Get-Process -Id $id -ErrorAction SilentlyContinue }
  if ($process -and $process.ProcessName -eq $programs[$name]) {
    taskkill /PID $id /T /F | Out-Null
    Write-Host "Stopped $name (pid $id)"
  }
}
Remove-Item $pidFile
Remove-Item (Join-Path $PSScriptRoot ".share-url") -ErrorAction SilentlyContinue
Write-Host "Sharing stopped. The public link no longer works."
