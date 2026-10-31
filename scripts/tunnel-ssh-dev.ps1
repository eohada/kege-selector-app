# scripts/tunnel-ssh-dev.ps1
# Manages secure reverse SSH tunnel from local PC to dedicated dev-VPS for Telegram Mini App V2.
#
# Direct Russian-accessible HTTPS endpoint:
# Local Gateway (127.0.0.1:5050) <- SSH Tunnel -> Dev VPS (127.0.0.1:5055) <- Caddy/Nginx -> https://dev-tg.boostudy.ru

param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Restart,
    [switch]$Status,
    [switch]$StartGateway,
    [switch]$TestConnection,
    [switch]$TestAuth,
    [string]$RemoteHost = "",
    [string]$RemoteUser = "boostudy-tunnel",
    [string]$KeyPath = "$HOME\.ssh\boostudy_codex_20261014",
    [int]$RemotePort = 5055,
    [int]$LocalPort = 5050,
    [string]$PublicDomain = "dev-tg.boostudy.ru",
    [string]$AllowlistChatIds = "854161398"
)

$ErrorActionPreference = 'Stop'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

$instanceDir = "$rootDir\instance"
if (!(Test-Path $instanceDir)) {
    New-Item -ItemType Directory -Path $instanceDir -Force | Out-Null
}

$sshPidFile = "$instanceDir\ssh_tunnel.pid"
$sshLogFile = "$instanceDir\ssh_tunnel.log"
$sshStopFlag = "$instanceDir\ssh_tunnel_stop.flag"
$gatewayPidFile = "$instanceDir\mini_app_gateway.pid"
$gatewayLogFile = "$instanceDir\mini_app_gateway.log"
$tunnelConfigFile = "$instanceDir\mini_app_tunnel_env.json"

function Ensure-LocalGateway {
    Write-Host "[*] Checking Local Isolated Gateway (127.0.0.1:$LocalPort)..." -ForegroundColor Cyan
    $gwRunning = $false
    try {
        $gwCheck = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/healthz" -Method Get -TimeoutSec 2
        if ($gwCheck.status -eq "healthy") { $gwRunning = $true }
    } catch {}

    if ($gwRunning) {
        Write-Host "    [OK] Gateway is already running and healthy." -ForegroundColor Green
        return
    }

    Write-Host "    Starting mini_app_gateway.py on 127.0.0.1:$LocalPort..." -ForegroundColor Yellow
    $createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = "cmd.exe /c python -u scripts/mini_app_gateway.py --port $LocalPort > instance\mini_app_gateway.log 2> instance\mini_app_gateway_err.log"
        CurrentDirectory = $rootDir
    }
    $gwPid = $createResult.ProcessId
    $gwPid | Out-File -FilePath $gatewayPidFile -Encoding ascii -Force

    Start-Sleep -Seconds 2
    try {
        $gwCheck = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/healthz" -Method Get -TimeoutSec 3
        if ($gwCheck.status -eq "healthy") {
            Write-Host "    [OK] Gateway started successfully (PID: $gwPid)." -ForegroundColor Green
        } else {
            Write-Host "    [WARN] Gateway responded but status is unexpected." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "    [ERROR] Gateway failed to respond. Check instance\mini_app_gateway.log." -ForegroundColor Red
        exit 1
    }
}

function Stop-SSHTunnel {
    Write-Host "`n[1/3] Stopping Reverse SSH Tunnel..." -ForegroundColor Cyan
    
    # 1. Set stop flag to instruct supervisor to exit
    "stop" | Out-File -FilePath $sshStopFlag -Encoding ascii -Force

    # 2. Terminate supervisor process
    if (Test-Path $sshPidFile) {
        $rawPid = (Get-Content $sshPidFile -Raw -ErrorAction SilentlyContinue)
        if ($rawPid -and $rawPid.Trim() -match '^\d+$') {
            $procId = [int]$rawPid.Trim()
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Host "      Stopped SSH supervisor PID $procId." -ForegroundColor Yellow
            }
        }
        Remove-Item $sshPidFile -Force -ErrorAction SilentlyContinue
    }

    # 3. Terminate any remaining ssh.exe with the reverse port forwarding
    $sshProcesses = Get-CimInstance Win32_Process -Filter "Name LIKE 'ssh%'" -ErrorAction SilentlyContinue
    foreach ($p in $sshProcesses) {
        if ($p.CommandLine -like "*$RemotePort:127.0.0.1:$LocalPort*") {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "      Stopped orphaned SSH child PID $($p.ProcessId)." -ForegroundColor Yellow
        }
    }

    if (Test-Path $sshStopFlag) {
        Remove-Item $sshStopFlag -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path $tunnelConfigFile) {
        Remove-Item $tunnelConfigFile -Force -ErrorAction SilentlyContinue
    }
    Write-Host "      [OK] SSH Tunnel stopped." -ForegroundColor Green
}

function Show-Status {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "   BooStudy Mini App V2 - Direct VPS Tunnel Status        " -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    # 1. Local Flask Backend
    try {
        $backend = Invoke-RestMethod -Uri "http://127.0.0.1:5000/ready" -Method Get -TimeoutSec 2
        Write-Host "`n[OK] Flask Backend:      RUNNING on http://127.0.0.1:5000 (status: $($backend.status))" -ForegroundColor Green
    } catch {
        Write-Host "`n[WARN] Flask Backend:    NOT reachable on 127.0.0.1:5000." -ForegroundColor Yellow
    }

    # 2. Local Gateway
    try {
        $gw = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/healthz" -Method Get -TimeoutSec 2
        Write-Host "[OK] Local Gateway:      RUNNING on http://127.0.0.1:$LocalPort (status: $($gw.status))" -ForegroundColor Green
    } catch {
        Write-Host "[WARN] Local Gateway:    NOT running on port $LocalPort." -ForegroundColor Yellow
    }

    # 3. SSH Tunnel Supervisor
    $sshProc = $null
    if (Test-Path $sshPidFile) {
        $rawPid = (Get-Content $sshPidFile -Raw -ErrorAction SilentlyContinue)
        if ($rawPid -and $rawPid.Trim() -match '^\d+$') {
            $parsedPid = [int]($rawPid.Trim())
            $sshProc = Get-Process -Id $parsedPid -ErrorAction SilentlyContinue
        }
    }
    if ($sshProc) {
        Write-Host "[OK] SSH Supervisor:     RUNNING (PID: $($sshProc.Id))" -ForegroundColor Green
    } else {
        $activeSsh = Get-CimInstance Win32_Process -Filter "Name LIKE 'ssh%'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*$RemotePort:127.0.0.1:$LocalPort*" }
        if ($activeSsh) {
            Write-Host "[OK] Active SSH Tunnel:  RUNNING (PID: $($activeSsh.ProcessId))" -ForegroundColor Green
        } else {
            Write-Host "[INFO] Reverse SSH Tunnel: NOT running." -ForegroundColor Gray
        }
    }

    # 4. Tunnel Configuration
    if (Test-Path $tunnelConfigFile) {
        $cfg = Get-Content $tunnelConfigFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        Write-Host "[OK] Active Endpoint:    $($cfg.public_url)" -ForegroundColor Yellow
        Write-Host "     Allowed Chat IDs:   $($cfg.allowlist_chat_ids)" -ForegroundColor Gray
        Write-Host "     Tunnel Type:        $($cfg.tunnel_type)" -ForegroundColor Gray
    } else {
        Write-Host "[INFO] Active Endpoint:   Local Dev Mode (no public endpoint)." -ForegroundColor Gray
    }
    Write-Host ""
}

function Test-AllConnections {
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "   BooStudy Mini App V2 - Verification Probe              " -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan

    # 1. Local Flask /ready
    try {
        $res = Invoke-RestMethod -Uri "http://127.0.0.1:5000/ready" -Method Get -TimeoutSec 3
        Write-Host "[PASS] Local Flask /ready: HTTP 200 (status: $($res.status))" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] Local Flask /ready: NOT reachable ($($_.Exception.Message))" -ForegroundColor Red
    }

    # 2. Local Gateway /healthz
    try {
        $res = Invoke-RestMethod -Uri "http://127.0.0.1:$LocalPort/healthz" -Method Get -TimeoutSec 3
        Write-Host "[PASS] Local Gateway /healthz: HTTP 200 (upstream: $($res.upstream))" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] Local Gateway /healthz: NOT reachable ($($_.Exception.Message))" -ForegroundColor Red
    }

    # 3. Local Gateway static vendor script
    try {
        $code = (Invoke-WebRequest "http://127.0.0.1:$LocalPort/static/js/vendor/telegram-web-app.js" -UseBasicParsing -TimeoutSec 3).StatusCode
        if ($code -eq 200) {
            Write-Host "[PASS] Local Gateway vendor telegram-web-app.js: HTTP 200" -ForegroundColor Green
        }
    } catch {
        Write-Host "[FAIL] Local Gateway vendor script blocked: $($_.Exception.Message)" -ForegroundColor Red
    }

    # 4. Local Gateway route isolation (/admin must be 403)
    try {
        $code = (Invoke-WebRequest "http://127.0.0.1:$LocalPort/admin" -UseBasicParsing -TimeoutSec 3).StatusCode
        Write-Host "[FAIL] Gateway /admin: Unexpectedly returned HTTP $code (must be 403)" -ForegroundColor Red
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 403) {
            Write-Host "[PASS] Gateway /admin: Strictly blocked with HTTP 403 Forbidden" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Gateway /admin: Returned HTTP $statusCode" -ForegroundColor Yellow
        }
    }

    # 5. Public Domain Checks (if configured)
    if ($PublicDomain -and $PublicDomain -ne "localhost") {
        Write-Host "`n[*] Probing Public Endpoint: https://$PublicDomain..." -ForegroundColor Cyan
        
        # DNS Resolution
        try {
            $dns = Resolve-DnsName -Name $PublicDomain -Type A -ErrorAction Stop
            Write-Host "    [PASS] DNS A Record: $($dns.IPAddress -join ', ')" -ForegroundColor Green
        } catch {
            Write-Host "    [WARN] DNS resolution failed for $PublicDomain (record not created yet or propagated)." -ForegroundColor Yellow
        }

        # Public HTTPS Health
        try {
            $pubRes = Invoke-RestMethod -Uri "https://$PublicDomain/healthz" -Method Get -TimeoutSec 5
            Write-Host "    [PASS] Public Gateway /healthz: HTTP 200 (healthy)" -ForegroundColor Green
        } catch {
            Write-Host "    [INFO] Public Gateway /healthz not responding yet: $($_.Exception.Message)" -ForegroundColor Gray
        }

        # Public HTTPS Mini App Root
        try {
            $pubHtml = Invoke-WebRequest -Uri "https://$PublicDomain/tg-app/" -UseBasicParsing -TimeoutSec 5
            if ($pubHtml.StatusCode -eq 200) {
                Write-Host "    [PASS] Public Mini App /tg-app/: HTTP 200 (Shell delivered)" -ForegroundColor Green
            }
        } catch {
            Write-Host "    [INFO] Public Mini App /tg-app/ not reachable: $($_.Exception.Message)" -ForegroundColor Gray
        }
    }
}

# --- Action Dispatch ---

if ($StartGateway) {
    Ensure-LocalGateway
    exit 0
}

if ($TestConnection) {
    Test-AllConnections
    exit 0
}

if ($TestAuth) {
    Write-Host "`n[*] Running Mini App E2E Security & Auth Verification Suite..." -ForegroundColor Cyan
    python tests/verify_public_tunnel_e2e.py
    exit $LASTEXITCODE
}

if ($Stop) {
    Stop-SSHTunnel
    Write-Host "`n[2/3] Restoring local Telegram bot to local mode..." -ForegroundColor Cyan
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_URL', $null, 'Process')
    [System.Environment]::SetEnvironmentVariable('TELEGRAM_MINI_APP_ALLOWLIST_ONLY', $null, 'Process')
    & "$PSScriptRoot\restart-local-telegram.ps1" -Background
    Write-Host "`n[3/3] [COMPLETE] Reverted to local mode." -ForegroundColor Green
    exit 0
}

if ($Restart) {
    Stop-SSHTunnel
    Start-Sleep -Seconds 2
    # Fall through to Start if RemoteHost is supplied or saved
    if (!$RemoteHost -and (Test-Path $tunnelConfigFile)) {
        try {
            $savedCfg = Get-Content $tunnelConfigFile -Raw | ConvertFrom-Json
            $RemoteHost = $savedCfg.remote_host
        } catch {}
    }
    $Start = $true
}

if ($Status -or (!$Start -and !$Stop -and !$Restart)) {
    Show-Status
    exit 0
}

if ($Start) {
    if (!$RemoteHost) {
        Write-Host "[ERROR] -RemoteHost parameter is required (IP or domain of dev-VPS)." -ForegroundColor Red
        Write-Host "Example: .\scripts\tunnel-ssh-dev.ps1 -Start -RemoteHost 185.xxx.xxx.xxx -PublicDomain dev-tg.boostudy.ru" -ForegroundColor Yellow
        exit 1
    }

    # 1. Stop any existing SSH tunnel
    Stop-SSHTunnel

    # 2. Verify SSH Key
    $expandedKeyPath = [System.Environment]::ExpandEnvironmentVariables($KeyPath)
    if (!(Test-Path $expandedKeyPath)) {
        Write-Host "[ERROR] SSH private key not found at: $expandedKeyPath" -ForegroundColor Red
        exit 1
    }

    # 3. Ensure local isolated gateway is running
    Ensure-LocalGateway

    # 4. Launch Background Reverse SSH Tunnel Supervisor
    Write-Host "`n[2/4] Starting Reverse SSH Tunnel Supervisor to $RemoteHost..." -ForegroundColor Cyan
    $supervisorCmd = "cmd.exe /c python -u scripts/run_ssh_tunnel.py --remote-host `"$RemoteHost`" --remote-user `"$RemoteUser`" --key-path `"$expandedKeyPath`" --remote-port $RemotePort --local-port $LocalPort --pid-file `"$sshPidFile`" --log-file `"$sshLogFile`" --stop-file `"$sshStopFlag`" > nul 2>&1"
    
    $createResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $supervisorCmd
        CurrentDirectory = $rootDir
    }
    $supervisorPid = $createResult.ProcessId
    Start-Sleep -Seconds 3

    # Check if process is still alive
    $liveProc = Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue
    if (!$liveProc) {
        Write-Host "      [ERROR] Supervisor failed to start. Logs:" -ForegroundColor Red
        if (Test-Path $sshLogFile) { Get-Content $sshLogFile -Tail 10 }
        exit 1
    }
    Write-Host "      [OK] Supervisor active (PID: $supervisorPid). Reverse port: $RemotePort -> 127.0.0.1:$LocalPort." -ForegroundColor Green

    # 5. Apply Public Configuration
    $httpsUrl = "https://$PublicDomain/tg-app"
    Write-Host "`n[3/4] Applying Direct HTTPS Endpoint: $httpsUrl" -ForegroundColor Cyan

    $tunnelMeta = @{
        public_url = $httpsUrl
        gateway_port = $LocalPort
        remote_port = $RemotePort
        remote_host = $RemoteHost
        allowlist_chat_ids = $AllowlistChatIds
        started_at = (Get-Date).ToString("o")
        tunnel_type = "reverse_ssh_vps"
    } | ConvertTo-Json

    [System.IO.File]::WriteAllText($tunnelConfigFile, $tunnelMeta, (New-Object System.Text.UTF8Encoding $false))

    # 6. Restart Dev Bot
    Write-Host "`n[4/4] Restarting Telegram Dev Bot with WebAppInfo pointing to $httpsUrl..." -ForegroundColor Cyan
    & "$PSScriptRoot\restart-local-telegram.ps1" -Background

    Write-Host "`n[COMPLETE] Mini App V2 is now connected via direct reverse SSH VPS tunnel!" -ForegroundColor Green
    Write-Host "           Endpoint: $httpsUrl" -ForegroundColor Yellow
}
