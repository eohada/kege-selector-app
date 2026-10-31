# scripts/tunnel-mini-app.ps1
# Safe Isolated Reverse Proxy & Tunnel Manager for BooStudy Telegram Mini App V2.
#
# Ensures:
# 1. Reverse proxy (scripts/mini_app_gateway.py) binds to 127.0.0.1:5050.
# 2. Only /tg-app, /tg-app/api/*, /static/*, /healthz are exposed.
# 3. All other BooStudy routes (/admin, /login, /api, etc.) are strictly blocked.
# 4. Telegram bot is updated with the public HTTPS URL without touching Flask or git files.

param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [string]$PublicUrl = "",
    [int]$GatewayPort = 5050,
    [string]$AllowlistChatIds = "854161398"
)

$ErrorActionPreference = 'Stop'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

$instanceDir = "$rootDir\instance"
if (!(Test-Path $instanceDir)) {
    New-Item -ItemType Directory -Path $instanceDir -Force | Out-Null
}

$gatewayPidFile = "$instanceDir\mini_app_gateway.pid"
$tunnelConfigFile = "$instanceDir\mini_app_tunnel_env.json"
$cfPidFile = "$instanceDir\cloudflared.pid"
$cfLogFile = "$instanceDir\cloudflared.log"

function Find-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    if (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe") {
        return "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    }
    if (Test-Path "C:\Program Files\cloudflared\cloudflared.exe") {
        return "C:\Program Files\cloudflared\cloudflared.exe"
    }
    return $null
}

function Stop-Gateway {
    Write-Host "`n[1/3] Stopping Mini App Isolated Gateway & Tunnel..." -ForegroundColor Cyan

    # 1. Stop Cloudflare tunnel if running
    if (Test-Path $cfPidFile) {
        $rawCfPid = (Get-Content $cfPidFile -Raw).Trim()
        if ($rawCfPid -match '^\d+$') {
            $cfPidInt = [int]$rawCfPid
            $cfProc = Get-Process -Id $cfPidInt -ErrorAction SilentlyContinue
            if ($cfProc) {
                Stop-Process -Id $cfPidInt -Force -ErrorAction SilentlyContinue
                Write-Host "      Stopped cloudflared runner PID $rawCfPid." -ForegroundColor Yellow
            }
        }
        Remove-Item $cfPidFile -Force -ErrorAction SilentlyContinue
    }
    $cfProcesses = Get-CimInstance Win32_Process -Filter "Name LIKE 'cloudflared%'" -ErrorAction SilentlyContinue
    foreach ($p in $cfProcesses) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "      Stopped orphaned cloudflared PID $($p.ProcessId)." -ForegroundColor Yellow
    }
    $runnerProcesses = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%run_cloudflared_tunnel.cmd%'" -ErrorAction SilentlyContinue
    foreach ($p in $runnerProcesses) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }

    # 2. Stop Gateway
    if (Test-Path $gatewayPidFile) {
        $rawPid = (Get-Content $gatewayPidFile -Raw).Trim()
        if ($rawPid -match '^\d+$') {
            $gwPidInt = [int]$rawPid
            $proc = Get-Process -Id $gwPidInt -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $gwPidInt -Force -ErrorAction SilentlyContinue
                Write-Host "      Stopped gateway process PID $rawPid." -ForegroundColor Yellow
            }
        }
        Remove-Item $gatewayPidFile -Force -ErrorAction SilentlyContinue
    }

    # Terminate any remaining mini_app_gateway.py
    $gwProcesses = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%mini_app_gateway.py%'" | Where-Object { $_.ProcessId -ne $PID }
    foreach ($p in $gwProcesses) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "      Stopped orphaned gateway PID $($p.ProcessId)." -ForegroundColor Yellow
    }

    if (Test-Path $tunnelConfigFile) {
        Remove-Item $tunnelConfigFile -Force -ErrorAction SilentlyContinue
    }
    Write-Host "      [OK] Gateway & Tunnel stopped." -ForegroundColor Green
}

function Show-Status {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "   BooStudy Mini App V2 - Isolated Gateway & Tunnel Status " -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    # 1. Gateway Status
    $gwRunning = $false
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/healthz" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($health.status -eq "healthy") {
            $gwRunning = $true
            Write-Host "`n[OK] Mini App Gateway:  RUNNING on http://127.0.0.1:$GatewayPort" -ForegroundColor Green
            Write-Host "     Upstream:          $($health.upstream)" -ForegroundColor Gray
            Write-Host "     Exposed routes:    $($health.exposed_endpoints -join ', ')" -ForegroundColor Gray
        }
    } catch {
        Write-Host "`n[INFO] Mini App Gateway: NOT running on port $GatewayPort." -ForegroundColor Gray
    }

    # 2. Configuration & Tunnel Status
    $cfRunning = Get-CimInstance Win32_Process -Filter "Name LIKE 'cloudflared%'" -ErrorAction SilentlyContinue
    if ($cfRunning) {
        $pids = ($cfRunning | ForEach-Object { $_.ProcessId }) -join ', '
        Write-Host "[OK] Cloudflare Tunnel: RUNNING (PID: $pids)" -ForegroundColor Green
    } else {
        Write-Host "[INFO] Cloudflare Tunnel: NOT running." -ForegroundColor Gray
    }

    if (Test-Path $tunnelConfigFile) {
        $cfg = Get-Content $tunnelConfigFile -Raw | ConvertFrom-Json
        Write-Host "[OK] Tunnel Config:     Active" -ForegroundColor Green
        Write-Host "     Public HTTPS:      $($cfg.public_url)" -ForegroundColor Yellow
        Write-Host "     Allowed Chat IDs:  $($cfg.allowlist_chat_ids)" -ForegroundColor Gray
    } else {
        Write-Host "[INFO] Tunnel Config:   No active tunnel configured (Local Dev Mode)." -ForegroundColor Gray
    }

    # 3. Security Boundary Verification
    if ($gwRunning) {
        Write-Host "`n--- Security Boundary Probe ---" -ForegroundColor DarkCyan
        try {
            $probe = Invoke-WebRequest -Uri "http://127.0.0.1:$GatewayPort/admin" -Method Get -SkipHttpErrorCheck -TimeoutSec 2
            if ($probe.StatusCode -eq 403) {
                Write-Host "  * /admin access:      BLOCKED (HTTP 403) [PASS]" -ForegroundColor Green
            } else {
                Write-Host "  * /admin access:      UNEXPECTED (HTTP $($probe.StatusCode)) [FAIL]" -ForegroundColor Red
            }
        } catch {
            Write-Host "  * /admin access:      BLOCKED [PASS]" -ForegroundColor Green
        }
    }
    Write-Host ""
}

# --- Action Dispatch ---

if ($Stop) {
    Stop-Gateway
    Write-Host "`n[2/3] Restoring local Telegram bot to local mode..." -ForegroundColor Cyan
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_URL', $null, 'Process')
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_ALLOWLIST_ONLY', $null, 'Process')
    & "$PSScriptRoot\restart-local-telegram.ps1" -Background
    Write-Host "`n[3/3] [COMPLETE] Isolated Gateway and Tunnel deactivated." -ForegroundColor Green
    exit 0
}

if ($Status -or (!$Start -and !$Stop)) {
    Show-Status
    exit 0
}

if ($Start) {
    # 1. Stop any existing gateway
    Stop-Gateway

    # 2. Start Gateway
    Write-Host "`n[1/3] Starting Mini App Isolated Reverse Proxy Gateway on 127.0.0.1:$GatewayPort..." -ForegroundColor Cyan
    $createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "cmd.exe /c python -u scripts/mini_app_gateway.py --port $GatewayPort > instance\mini_app_gateway.log 2> instance\mini_app_gateway_err.log"
        CurrentDirectory = $rootDir
    }
    $gwPid = $createResult.ProcessId
    $gwPid | Out-File -FilePath $gatewayPidFile -Encoding ascii -Force
    Start-Sleep -Seconds 2

    # Verify Gateway Health
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$GatewayPort/healthz" -Method Get -TimeoutSec 3
        if ($health.status -ne "healthy") {
            throw "Gateway health check returned: $($health.status)"
        }
        Write-Host "      [OK] Gateway active (PID: $gwPid) on http://127.0.0.1:$GatewayPort" -ForegroundColor Green
    } catch {
        Write-Host "      [ERROR] Gateway failed to respond on http://127.0.0.1:${GatewayPort}: $_" -ForegroundColor Red
        Stop-Gateway
        exit 1
    }

    # 3. Cloudflare Tunnel Auto-Discovery (if PublicUrl not provided)
    if (!$PublicUrl) {
        $cfBin = Find-Cloudflared
        if ($cfBin) {
            Write-Host "`n[2/3] Launching Cloudflare Tunnel (detached process)..." -ForegroundColor Cyan
            if (Test-Path $cfLogFile) { Remove-Item $cfLogFile -Force -ErrorAction SilentlyContinue }
            
            $cmdRunner = "$rootDir\scripts\run_cloudflared_tunnel.cmd"
            $cfCreate = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
                CommandLine = "cmd.exe /c `"$cmdRunner`""
                CurrentDirectory = $rootDir
            }
            $cfPid = $cfCreate.ProcessId
            $cfPid | Out-File -FilePath $cfPidFile -Encoding ascii -Force
            Write-Host "      Cloudflare Tunnel started (PID: $cfPid). Waiting for HTTPS URL..." -ForegroundColor Gray

            $discoveredUrl = $null
            for ($i = 0; $i -lt 30; $i++) {
                Start-Sleep -Seconds 1
                $allLogs = ""
                if (Test-Path $cfLogFile) {
                    $allLogs = (Get-Content $cfLogFile -Raw -ErrorAction SilentlyContinue)
                }
                if ($allLogs -match 'Registered tunnel connection' -and $allLogs -match 'https://[a-zA-Z0-9-]+\.trycloudflare\.com') {
                    $matchObj = [regex]::Match($allLogs, 'https://[a-zA-Z0-9-]+\.trycloudflare\.com')
                    if ($matchObj.Success) {
                        $discoveredUrl = $matchObj.Value
                        break
                    }
                }
            }
            if ($discoveredUrl) {
                Write-Host "      [OK] Cloudflare Tunnel established: $discoveredUrl" -ForegroundColor Green
                $PublicUrl = $discoveredUrl
            } else {
                Write-Host "      [WARN] Could not automatically detect trycloudflare.com URL from logs." -ForegroundColor Yellow
                Write-Host "      Check $cfLogFile for details." -ForegroundColor Gray
            }
        }
    }

    # 4. Configure Public HTTPS URL if available
    if ($PublicUrl) {
        $normalizedUrl = $PublicUrl.TrimEnd('/')
        if (!$normalizedUrl.EndsWith("/tg-app")) {
            $normalizedUrl = "$normalizedUrl/tg-app"
        }

        Write-Host "`n[3/3] Applying Public HTTPS Configuration..." -ForegroundColor Cyan
        Write-Host "      Public WebApp URL: $normalizedUrl" -ForegroundColor Yellow
        Write-Host "      Allowed Chat IDs:  $AllowlistChatIds" -ForegroundColor Gray

        $tunnelMeta = @{
            public_url = $normalizedUrl
            gateway_port = $GatewayPort
            allowlist_chat_ids = $AllowlistChatIds
            started_at = (Get-Date).ToString("o")
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText($tunnelConfigFile, $tunnelMeta, (New-Object System.Text.UTF8Encoding $false))

        # Set environment variables for this process and bot launcher
        [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_URL', $normalizedUrl, 'Process')
        [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_ALLOWLIST_ONLY', '1', 'Process')
        [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_ALLOWLIST_CHAT_IDS', $AllowlistChatIds, 'Process')

        Write-Host "`n[3/3] Restarting Dev Bot with new WebAppInfo..." -ForegroundColor Cyan
        & "$PSScriptRoot\restart-local-telegram.ps1" -Background
        Write-Host "`n[COMPLETE] Mini App is now ready for Telegram WebView testing!" -ForegroundColor Green
        Write-Host "           Open @BooStudy_local_bot and send /start or /menu to view the WebApp button." -ForegroundColor Green
    } else {
        Write-Host "`n[2/3] Gateway is ready. Point your Cloudflare Tunnel to: http://127.0.0.1:$GatewayPort" -ForegroundColor Yellow
        Write-Host "      Example: cloudflared tunnel --url http://127.0.0.1:$GatewayPort" -ForegroundColor Gray
        Write-Host "      Then activate with: .\scripts\tunnel-mini-app.ps1 -Start -PublicUrl https://<your-subdomain>.trycloudflare.com" -ForegroundColor Gray
    }
}
