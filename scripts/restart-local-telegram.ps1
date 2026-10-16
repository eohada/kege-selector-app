# scripts/restart-local-telegram.ps1
# Restarts the local BooStudy Telegram bot (Windows PowerShell)

param(
    [switch]$Background
)

$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "Restarting local BooStudy Telegram bot..." -ForegroundColor Cyan

& "$PSScriptRoot\stop-local-telegram.ps1"
Start-Sleep -Seconds 1

if ($Background) {
    & "$PSScriptRoot\start-local-telegram.ps1" -Background
} else {
    & "$PSScriptRoot\start-local-telegram.ps1"
}
