# scripts/restart-backend.ps1
# Restarts the local BooStudy Flask backend
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
Set-Location $rootDir

Write-Host "Restarting local BooStudy Flask backend..." -ForegroundColor Cyan

& "$PSScriptRoot\stop-backend.ps1"
Start-Sleep -Seconds 1
& "$PSScriptRoot\start-backend.ps1"
