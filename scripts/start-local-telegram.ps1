# scripts/start-local-telegram.ps1
# Starts the local BooStudy Telegram bot for Windows development.
# Fully isolated from production: connects to local SQLite DB (instance/boostudy_dev.db)
# and local BooStudy backend (http://127.0.0.1:5000).

param(
    [switch]$Background,
    [switch]$WithBackend,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   BooStudy Telegram Dev Environment - Launcher           " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verify Python
try {
    $pythonVer = python --version 2>&1
    Write-Host "[OK] Python: $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found in PATH! Please ensure Python is installed." -ForegroundColor Red
    exit 1
}

# 2. Ensure instance directory exists
$instanceDir = "$rootDir\instance"
if (!(Test-Path $instanceDir)) {
    New-Item -ItemType Directory -Path $instanceDir -Force | Out-Null
}

# 3. Single-Instance Check
if ($Force) {
    & "$PSScriptRoot\stop-local-telegram.ps1"
} else {
    $existing = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' AND CommandLine LIKE '%run_bot.py%'" | Where-Object { $_.ProcessId -ne $PID }
    if ($existing) {
        Write-Host "[WARN] Local bot poller is already running (PID: $($existing[0].ProcessId))." -ForegroundColor Yellow
        Write-Host "       Use -Force to restart or run scripts\restart-local-telegram.ps1" -ForegroundColor Yellow
        exit 0
    }
}

# 4. Diagnostic check via check_telegram_status.py
$diagJson = python scripts/check_telegram_status.py 2>$null
if ($diagJson) {
    try {
        $diag = $diagJson | ConvertFrom-Json
    } catch {
        $diag = $null
    }
}

if ($diag) {
    if (!$diag.bot.id) {
        Write-Host "[!] ATTENTION: Telegram Bot Token not found or invalid!" -ForegroundColor Red
        Write-Host "    Add TELEGRAM_DEV_BOT_TOKEN=... to your .env file." -ForegroundColor Red
        exit 1
    }

    $botUser = if ($diag.bot.username) { "@$($diag.bot.username)" } else { "Bot" }
    
    if ($diag.is_dev_token) {
        Write-Host "[OK] Bot Identity:            $botUser ($($diag.masked_token), Isolated Dev Bot)" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Bot Identity:          $botUser ($($diag.masked_token), SHARED WITH PRODUCTION)" -ForegroundColor Yellow
        Write-Host "                              Warning: If the production server is running, you will experience" -ForegroundColor DarkYellow
        Write-Host "                              Telegram 409 Conflict. For full isolation, define TELEGRAM_DEV_BOT_TOKEN in .env." -ForegroundColor DarkYellow
    }

    if ($diag.db_exists) {
        Write-Host "[OK] Local Database:          SQLite ($($diag.db_path), $($diag.users_count) users)" -ForegroundColor Green
    }

    if ($diag.backend_running) {
        Write-Host "[OK] Web Backend:             Listening on http://127.0.0.1:5000" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Web Backend:           Not running on http://127.0.0.1:5000" -ForegroundColor Gray
        if ($WithBackend) {
            Write-Host "Starting local Flask backend in background..." -ForegroundColor Cyan
            $backendOut = "$instanceDir\backend_dev.log"
            $backendErr = "$instanceDir\backend_dev_err.log"
            $backendProc = Start-Process -FilePath "python" -ArgumentList "scripts/run_local.py" -WorkingDirectory $rootDir -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru -WindowStyle Hidden
            Start-Sleep -Seconds 2
            Write-Host "[OK] Local backend started (PID: $($backendProc.Id))" -ForegroundColor Green
        } else {
            Write-Host "[TIP] To test deep-link account linking (/start <token>), run with -WithBackend flag." -ForegroundColor DarkYellow
        }
    }
}

$pidFile = "$instanceDir\telegram_bot.pid"

if ($Background) {
    Write-Host "`nStarting Telegram bot in detached background process..." -ForegroundColor Cyan
    $createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "cmd.exe /c python -u run_bot.py > instance\telegram_bot.log 2> instance\telegram_bot_err.log"
        CurrentDirectory = $rootDir
    }
    $botPid = $createResult.ProcessId
    $botPid | Out-File -FilePath $pidFile -Encoding ascii -Force
    Start-Sleep -Seconds 3
    Write-Host "[OK] Telegram bot started in background (PID: $botPid)." -ForegroundColor Green
    Write-Host "     Status:   scripts\status-local-telegram.ps1" -ForegroundColor DarkGray
    Write-Host "     Stop:     scripts\stop-local-telegram.ps1" -ForegroundColor DarkGray
} else {
    Write-Host "`nStarting Telegram bot in interactive mode (Press Ctrl+C to stop)..." -ForegroundColor Cyan
    Write-Host "----------------------------------------------------------" -ForegroundColor DarkGray
    python run_bot.py
}
