param(
    [Parameter(Mandatory = $true)]
    [string]$SafeDbPath,
    [int]$Port = 5185,
    [string]$SyntheticUserIds = '1,2,3,4,10,12,19,9311001,9313001',
    [string]$SyntheticActorIds = '1',
    [string]$SyntheticCourseIds = '1',
    [string]$SyntheticCourseCopyIds = '9312004,9313004'
)

$ErrorActionPreference = 'Stop'
$rootDir = (Get-Item $PSScriptRoot).Parent.FullName
$safeDb = (Resolve-Path -LiteralPath $SafeDbPath).Path
$dbFile = Get-Item -LiteralPath $safeDb

if ($dbFile.Name -ne 'adaptive_learning_synthetic.sqlite' -or
    $dbFile.Directory.Name -notmatch '^BooStudy_Adaptive_Lab_Synthetic_' -or
    ($dbFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Укажите обычный файл adaptive_learning_synthetic.sqlite внутри BooStudy_Adaptive_Lab_Synthetic_*. Обычная dev-база здесь не поддерживается.'
}

if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Порт $Port уже занят. Скрипт не будет останавливать существующий процесс."
}

$python = (Get-Command python -ErrorAction Stop).Source
$identity = (& $python -c 'import os,sys; s=os.stat(sys.argv[1]); print(f"{s.st_dev}:{s.st_ino}")' $safeDb).Trim()
if ($LASTEXITCODE -ne 0 -or $identity -notmatch '^\d+:\d+$') {
    throw 'Не удалось вычислить identity синтетической базы.'
}

$databaseUri = 'sqlite:///' + ($safeDb -replace '\\', '/')
$env:PYTHON_DOTENV_DISABLED = '1'
$env:ENVIRONMENT = 'local'
$env:AI_LAB_ENABLED = '1'
$env:AI_LAB_COURSE_ADAPTER_ENABLED = '1'
$env:AI_LAB_SAFE_DB_MODE = '1'
$env:AI_LAB_SAFE_DB_PATH = $safeDb
$env:AI_LAB_SAFE_DB_FILE_ID = $identity
$env:AI_LAB_SYNTHETIC_COURSE_IDS = $SyntheticCourseIds
$env:AI_LAB_SYNTHETIC_COURSE_COPY_IDS = $SyntheticCourseCopyIds
$env:AI_LAB_PLATFORM_TEST_USER_IDS = $SyntheticUserIds
$env:AI_LAB_PLATFORM_TEST_ACTOR_IDS = $SyntheticActorIds
$env:AI_LAB_PLATFORM_HOMEWORK_ENABLED = '1'
$env:DATABASE_URL = $databaseUri
$env:SQLALCHEMY_DATABASE_URI = $databaseUri
$env:SQLITE_DB_PATH = $safeDb
$env:BOOSTUDY_SKIP_DATABASE_BOOTSTRAP = '1'
$env:BOOSTUDY_BACKGROUND_WORKERS_ENABLED = '0'
$env:DISABLE_BACKGROUND_WORKERS = '1'

Set-Location $rootDir
Write-Host "AI Lab safe mode: $safeDb"
Write-Host "Serving only on http://127.0.0.1:$Port. Press Ctrl+C to stop."
& $python -u -c "from app import create_app; app=create_app(); app.run(host='127.0.0.1', port=$Port, use_reloader=False)"
