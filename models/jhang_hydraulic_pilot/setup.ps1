$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$basePython = Join-Path $projectRoot '.venv/Scripts/python.exe'
$pilotPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
# Refresh interpreter paths even when a transferred environment already exists.
& $basePython -m venv (Join-Path $PSScriptRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Could not create the hydraulic trial environment' }
# Read existing application libraries without installing into that environment.
$sharedPackages = Join-Path $projectRoot '.venv/Lib/site-packages'
$pathFile = Join-Path $PSScriptRoot '.venv/Lib/site-packages/floodguard_existing_environment.pth'
[System.IO.File]::WriteAllText($pathFile, $sharedPackages + [Environment]::NewLine)
& $pilotPython -m pip install --only-binary=:all: -r (Join-Path $PSScriptRoot 'requirements-serial.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the serial numerical dependencies' }
# PyMetis has no matching Windows wheel in the tested environment. This trial
# uses a regular mesh and a single CPU process, with no MPI partitioning calls.
& $pilotPython -m pip install --no-deps anuga==4.0.1
if ($LASTEXITCODE -ne 0) { throw 'Could not install the ANUGA solver wheel' }
& $pilotPython -c "import anuga; print('ANUGA', anuga.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'ANUGA import check failed' }
