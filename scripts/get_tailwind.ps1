param(
  [string]$OutPath = "tools/tailwindcss/tailwindcss.exe",
  [string]$Version = "v3.4.17"
)

$ErrorActionPreference = "Stop"

function Ensure-Dir([string]$path) {
  $dir = Split-Path -Parent $path
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir | Out-Null
  }
}

Ensure-Dir $OutPath

# Tailwind official releases (standalone binary)
# Pinned to v3.x to match our Tailwind directives/@apply usage.
$url = "https://github.com/tailwindlabs/tailwindcss/releases/download/$Version/tailwindcss-windows-x64.exe"

Write-Host "Downloading Tailwind CLI..."
Write-Host "  URL: $url"
Write-Host "  OUT: $OutPath"

Invoke-WebRequest -Uri $url -OutFile $OutPath

Write-Host "Done. Tailwind CLI saved."

