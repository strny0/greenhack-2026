<#
.SYNOPSIS
    Reproducible local launch for Grid Pulse (dev mode). Windows/PowerShell port
    of run.sh.

    One command that:
      1. checks the dataset is present (points you to download_dataset.ps1),
      2. checks/install backend deps (uv preferred, falls back to python + pip),
      3. validates backend\.env (creates it from .env.example on first run),
      4. checks/install frontend deps (npm),
      5. starts the backend (uvicorn :8099) and the frontend (vite :5173).

    Open http://127.0.0.1:5173  (Vite proxies /api to the backend).
    Ctrl-C stops both processes.

.PARAMETER Port
    Backend port (default 8099).
.PARAMETER SkipInstall
    Skip dependency checks/installs.
#>
[CmdletBinding()]
param(
    [int]$Port = 8099,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$backend  = Join-Path $repoRoot 'src\backend'
$frontend = Join-Path $repoRoot 'src\frontend'
$venv     = Join-Path $backend '.venv'
$venvPy   = Join-Path $venv 'Scripts\python.exe'

function Cyan($m)  { Write-Host "==> $m"  -ForegroundColor Cyan }
function Green($m) { Write-Host "    $m"   -ForegroundColor Green }
function Red($m)   { Write-Host "!!  $m"   -ForegroundColor Red }

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

# --- 1. dataset --------------------------------------------------------------
if (-not (Test-Path (Join-Path $repoRoot 'dataset\data\snapshots'))) {
    Red "Dataset not found at dataset\data\snapshots"
    Red "Download it first:  .\scripts\download_dataset.ps1"
    exit 1
}
Green "dataset present (dataset\data)"

# --- 2. tooling --------------------------------------------------------------
$missing = @()

if (Have 'uv')            { $pyTool = 'uv' }
elseif (Have 'python')    { $pyTool = 'python' }
elseif (Have 'py')        { $pyTool = 'py' }
else { $missing += "Python 3.12 (install Python, or 'uv' from https://docs.astral.sh/uv/)"; $pyTool = $null }

if (-not (Have 'node') -or -not (Have 'npm')) { $missing += "Node.js + npm (https://nodejs.org/)" }

if ($missing.Count -gt 0) {
    Red "Missing dependencies:"
    foreach ($m in $missing) { Red "  - $m" }
    exit 1
}

# --- 3. backend venv + deps --------------------------------------------------
if (-not $SkipInstall) {
    if (-not (Test-Path $venvPy)) {
        Cyan "creating backend venv ($pyTool)"
        if ($pyTool -eq 'uv') { & uv venv --python 3.12 $venv }
        elseif ($pyTool -eq 'py') { & py -3.12 -m venv $venv }
        else { & python -m venv $venv }
    }
    $stamp = Join-Path $venv '.deps-stamp'
    $reqs  = Join-Path $backend 'requirements.txt'
    $needInstall = (-not (Test-Path $stamp)) -or `
        ((Get-Item $reqs).LastWriteTime -gt (Get-Item $stamp).LastWriteTime)
    if ($needInstall) {
        Cyan "installing backend deps"
        if ($pyTool -eq 'uv') {
            & uv pip install --python $venvPy -r $reqs
        } else {
            & $venvPy -m pip install --quiet --upgrade pip
            & $venvPy -m pip install -r $reqs
        }
        New-Item -ItemType File -Force -Path $stamp | Out-Null
    } else {
        Green "backend deps up to date"
    }
}

# --- 4. backend .env ---------------------------------------------------------
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) {
    Cyan "creating backend\.env from .env.example"
    Copy-Item (Join-Path $backend '.env.example') $envFile
    Green "edit src\backend\.env and set AI_API_KEY to enable the dispatcher chatbot"
    Green "(the app runs fine without it; the chat just returns its grounded context)"
} else {
    Green "backend\.env present"
}

# --- 5. gridstats bundle (built once via `python -m app.gridstats.build`) -----
# Precomputed historical/statistical bundle the dispatcher agent serves from.
# The build scans all 8760 snapshots, so do it once; presence of metrics.parquet
# (what the runtime loader checks) means it's already built.
$bundle = Join-Path $backend 'app\gridstats\target\metrics.parquet'
if (-not (Test-Path $bundle)) {
    Cyan "building gridstats bundle (one-time; scans all snapshots — may take a few minutes)"
    Push-Location $backend; try { & $venvPy -m app.gridstats.build } finally { Pop-Location }
} else {
    Green "gridstats bundle present"
}

# --- 6. frontend deps --------------------------------------------------------
if (-not $SkipInstall) {
    $nodeModules = Join-Path $frontend 'node_modules'
    $lock = Join-Path $frontend 'package-lock.json'
    $needNpm = (-not (Test-Path $nodeModules)) -or `
        ((Get-Item $lock).LastWriteTime -gt (Get-Item $nodeModules).LastWriteTime)
    if ($needNpm) {
        Cyan "installing frontend deps (npm install)"
        Push-Location $frontend; try { & npm install } finally { Pop-Location }
    } else {
        Green "frontend deps up to date"
    }
}

# --- 7. launch both ----------------------------------------------------------
$procs = @()
try {
    Cyan "starting backend  (uvicorn :$Port)"
    $procs += Start-Process -PassThru -WorkingDirectory $backend `
        -FilePath $venvPy `
        -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port")

    Cyan "starting frontend (vite :5173)"
    $procs += Start-Process -PassThru -WorkingDirectory $frontend `
        -FilePath 'npm.cmd' -ArgumentList @('run', 'dev')

    Green "open  http://127.0.0.1:5173   (Ctrl-C to stop)"

    # Exit as soon as either process dies.
    while ($true) {
        Start-Sleep -Seconds 1
        if ($procs | Where-Object { $_.HasExited }) { break }
    }
}
finally {
    Cyan "stopping..."
    foreach ($p in $procs) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
}
