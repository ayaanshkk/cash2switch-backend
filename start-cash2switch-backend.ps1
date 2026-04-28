# Business Gas / Cash2Switch API — includes CRM leads, renewals, energy-clients, dashboard.
# Do NOT use c2s-backend on the same port for this frontend; it does not expose those routes.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pids = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ })
foreach ($p in $pids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
}

$env:PYTHONPATH = (Get-Location).Path
$py = Join-Path $root ".venv-new\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Missing $py - create the venv or install dependencies first."
    exit 1
}

Write-Host "Starting Cash2Switch backend on http://127.0.0.1:5000"
Write-Host "PYTHONPATH=$($env:PYTHONPATH)"
& $py backend/app.py
