@echo off
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo Error: .venv not found
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install pyinstaller -q
.venv\Scripts\pyinstaller.exe --noconfirm --name EGE_Review --onefile --console scripts/review_tasks.py

if errorlevel 1 (
    echo Build failed
    pause
    exit /b 1
)

mkdir dist\EGE_Review_portable 2>nul
move /Y dist\EGE_Review.exe dist\EGE_Review_portable\
copy /Y "scripts\README_EGE_Review.txt" "dist\EGE_Review_portable\README.txt"
echo Done. Copy dist\EGE_Review_portable\ - only exe + tasks_export.json needed
pause
