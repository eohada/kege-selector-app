param(
  [string]$TailwindExe = "tools/tailwindcss/tailwindcss.exe",
  [string]$InputCss = "static/src/input.css",
  [string]$OutputCss = "static/dist/boostudy.css"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $TailwindExe)) {
  Write-Host "Tailwind CLI not found. Downloading..."
  powershell -ExecutionPolicy Bypass -File scripts/get_tailwind.ps1 -OutPath $TailwindExe
}

if (-not (Test-Path $InputCss)) { throw "Input CSS not found: $InputCss" }

$outDir = Split-Path -Parent $OutputCss
if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

Write-Host "Building Tailwind CSS..."
& $TailwindExe -c tailwind.config.js -i $InputCss -o $OutputCss --minify

Write-Host "Done:"
Write-Host "  $OutputCss"

