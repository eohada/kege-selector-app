# scripts/stop-local-telegram.ps1
# Stops the local BooStudy Telegram bot process (Windows PowerShell)

$ErrorActionPreference = 'SilentlyContinue'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "Stopping local BooStudy Telegram bot..." -ForegroundColor Cyan

$pidFile = "$rootDir\instance\telegram_bot.pid"
$stoppedCount = 0

# 1. Terminate by stored PID
if (Test-Path $pidFile) {
    $rawPid = (Get-Content $pidFile -Raw).Trim()
    if ($rawPid -match '^\d+$') {
        $targetPid = [int]$rawPid
        $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Terminating bot process by PID: $targetPid..." -ForegroundColor Yellow
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
            $stoppedCount++
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. Terminate any remaining run_bot.py processes
$botProcesses = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%run_bot.py%'" | Where-Object { $_.ProcessId -ne $PID }
foreach ($p in $botProcesses) {
    Write-Host "Terminating run_bot.py process (PID: $($p.ProcessId))..." -ForegroundColor Yellow
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    $stoppedCount++
}

if ($stoppedCount -gt 0) {
    Write-Host "[OK] Local Telegram bot stopped (terminated $stoppedCount process(es))." -ForegroundColor Green
} else {
    Write-Host "[INFO] No active local Telegram bot processes found." -ForegroundColor Gray
}
