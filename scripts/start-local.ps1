$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (!$node -and (Test-Path 'C:\Program Files\nodejs\node.exe')) {
    $env:Path = "C:\Program Files\nodejs;$env:Path"
    $node = Get-Command node.exe
}
if (!(Test-Path $python) -or !$node) {
    throw 'Install the Python virtual environment and Node.js before starting.'
}
$logDir = Join-Path $projectRoot '.local-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$backend = Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput "$logDir\backend.log" -RedirectStandardError "$logDir\backend-error.log" -PassThru
$frontend = Start-Process -FilePath $node.Source -ArgumentList 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '3000', '--strictPort' -WorkingDirectory "$projectRoot\frontend" -WindowStyle Hidden -RedirectStandardOutput "$logDir\frontend.log" -RedirectStandardError "$logDir\frontend-error.log" -PassThru
Write-Host "Frontend: http://127.0.0.1:3000 (PID $($frontend.Id))"
Write-Host "API docs: http://127.0.0.1:8000/docs (PID $($backend.Id))"
Write-Host "Logs: $logDir"
