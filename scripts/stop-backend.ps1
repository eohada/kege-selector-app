# scripts/stop-backend.ps1
# Stops the local BooStudy Flask backend
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "Stopping local BooStudy Flask backend..." -ForegroundColor Cyan

$stopped = 0
$pidFile = Join-Path $rootDir "instance\backend_dev.pid"
if (Test-Path $pidFile) {
    try {
        $pidVal = Get-Content $pidFile -Raw
        $pId = [int]$pidVal.Trim()
        Stop-Process -Id $pId -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        $stopped++
    } catch {
        # ignore
    }
}

$processes = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' AND (CommandLine LIKE '%run_local.py%' OR CommandLine LIKE '%wsgi.py%')" | Where-Object { $_.ProcessId -ne $PID }

foreach ($proc in $processes) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped++
    } catch {
        # ignore
    }
}

Write-Host "[OK] Stopped $stopped backend process(es)." -ForegroundColor Green
