@echo off
rem scripts/run_cloudflared_tunnel.cmd
rem Dedicated detached runner for Cloudflare Tunnel to Mini App Gateway (5050)

set "CF_BIN=C:\Program Files (x86)\cloudflared\cloudflared.exe"
if not exist "%CF_BIN%" (
    for /f "tokens=*" %%i in ('where cloudflared 2^>nul') do set "CF_BIN=%%i"
)

"%CF_BIN%" tunnel --protocol http2 --url http://127.0.0.1:5050 > "%~dp0..\instance\cloudflared.log" 2>&1
