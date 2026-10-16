# scripts/status-local-telegram.ps1
# Status check for local BooStudy Telegram dev environment

$ErrorActionPreference = 'SilentlyContinue'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   BooStudy Telegram Dev Environment - Status Check       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# Run python diagnostic helper
$diagJson = python scripts/check_telegram_status.py 2>$null
if ($diagJson) {
    try {
        $diag = $diagJson | ConvertFrom-Json
    } catch {
        $diag = $null
    }
}

if ($diag) {
    # 1. Bot token & identity
    $botUser = if ($diag.bot.username) { "@$($diag.bot.username)" } else { "Unknown" }
    $tokenType = if ($diag.is_dev_token) { "DEV (Isolated)" } else { "SHARED WITH PRODUCTION" }
    
    if ($diag.is_dev_token) {
        Write-Host "[OK] Bot Identity:            $botUser ($($diag.masked_token), $tokenType)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Bot Identity:          $botUser ($($diag.masked_token), $tokenType)" -ForegroundColor Yellow
        Write-Host "                              Using production bot token locally causes 409 Conflict." -ForegroundColor DarkYellow
    }

    # 2. Local SQLite DB
    if ($diag.db_exists) {
        Write-Host "[OK] Local SQLite DB:         $($diag.db_path) ($($diag.db_size_kb) KB, Users: $($diag.users_count), Pending Codes: $($diag.pending_codes_count))" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Local SQLite DB:       Not found at $($diag.db_path)" -ForegroundColor Yellow
    }

    # 3. Backend status
    if ($diag.backend_running) {
        Write-Host "[OK] Web Backend (port 5000): RUNNING on http://127.0.0.1:5000" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Web Backend (port 5000): STOPPED (deep-link linking requires backend)" -ForegroundColor Gray
    }

    # 4. Conflict detection
    if ($diag.conflict_detected) {
        Write-Host "[ALERT] Telegram Polling:     409 CONFLICT DETECTED! Another process holds getUpdates." -ForegroundColor Red
    } else {
        Write-Host "[OK] Telegram API:            Accessible without active conflict probe" -ForegroundColor Green
    }
} else {
    Write-Host "[WARN] Unable to run diagnostic inspector (python scripts/check_telegram_status.py)" -ForegroundColor Yellow
}

# 5. Local Bot Polling Process
$botProcesses = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' AND CommandLine LIKE '%run_bot.py%'" | Where-Object { $_.ProcessId -ne $PID }
$pidFile = "$rootDir\instance\telegram_bot.pid"

if ($botProcesses) {
    foreach ($p in $botProcesses) {
        Write-Host "[OK] Local Bot Poller:        RUNNING (PID: $($p.ProcessId))" -ForegroundColor Green
    }
} elseif (Test-Path $pidFile) {
    $storedPid = (Get-Content $pidFile -Raw).Trim()
    Write-Host "[WARN] Local Bot Poller:      PID file exists ($storedPid) but process is not active" -ForegroundColor Yellow
} else {
    Write-Host "[INFO] Local Bot Poller:      STOPPED" -ForegroundColor Gray
}

# 6. Show recent logs if available
$logFile = "$rootDir\instance\telegram_bot_err.log"
if (Test-Path $logFile) {
    Write-Host "`nRecent bot logs ($logFile):" -ForegroundColor DarkGray
    Get-Content $logFile -Tail 6 | ForEach-Object { Write-Host "   $_" -ForegroundColor DarkGray }
}

Write-Host ""
