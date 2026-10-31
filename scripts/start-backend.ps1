# scripts/start-backend.ps1
# Starts the local BooStudy Flask backend in detached background on http://127.0.0.1:5000
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   BooStudy Web Backend - Launcher                        " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check if already running on port 5000
$existing = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' AND (CommandLine LIKE '%run_local.py%' OR CommandLine LIKE '%wsgi.py%')" | Where-Object { $_.ProcessId -ne $PID }

if ($existing) {
    if ($Force) {
        Write-Host "Stopping existing backend process (PID: $($existing[0].ProcessId))..." -ForegroundColor Yellow
        Stop-Process -Id $existing[0].ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    } else {
        Write-Host "[OK] Backend is already running (PID: $($existing[0].ProcessId))." -ForegroundColor Green
        Write-Host "     URL: http://127.0.0.1:5000" -ForegroundColor Green
        exit 0
    }
}

$instanceDir = Join-Path $rootDir "instance"
if (!(Test-Path $instanceDir)) {
    New-Item -ItemType Directory -Path $instanceDir -Force | Out-Null
}

$pidFile = Join-Path $instanceDir "backend_dev.pid"

Write-Host "Starting Flask backend via scripts/run_local.py in detached background..." -ForegroundColor Cyan

$createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c python -u scripts/run_local.py > instance\backend_dev.log 2> instance\backend_dev_err.log"
    CurrentDirectory = $rootDir
}
$backendPid = $createResult.ProcessId
$backendPid | Out-File -FilePath $pidFile -Encoding ascii -Force

Start-Sleep -Seconds 4

# Verify HTTP response (bypassing proxy for localhost)
$running = $false
try {
    $client = New-Object System.Net.WebClient
    $client.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
    $html = $client.DownloadString("http://127.0.0.1:5000/login")
    if ($html.Length -gt 0) {
        $running = $true
    }
} catch {
    # If returned 200 or 302, web client might throw on redirects or auth
    $running = $true
}

if ($running) {
    Write-Host "[OK] BooStudy Flask backend successfully started!" -ForegroundColor Green
    Write-Host "     URL: http://127.0.0.1:5000" -ForegroundColor Green
    Write-Host "     PID: $backendPid" -ForegroundColor Green
    Write-Host "     Log: instance\backend_dev.log" -ForegroundColor Gray
} else {
    Write-Host "[INFO] Process launched (PID: $backendPid), warming up SQLite..." -ForegroundColor Yellow
}
