@echo off
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo Error: .venv not found. Create venv in project root.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install pyinstaller -q

echo Building OGE Math Review...
.venv\Scripts\pyinstaller.exe --noconfirm --name OGE_Math_Review --onefile --console scripts/review_oge_math.py
if errorlevel 1 ( echo OGE build failed & pause & exit /b 1 )

echo Building EGE Math Review...
.venv\Scripts\pyinstaller.exe --noconfirm --name EGE_Math_Review --onefile --console scripts/review_ege_math.py
if errorlevel 1 ( echo EGE build failed & pause & exit /b 1 )

mkdir dist\OGE_Math_portable 2>nul
mkdir dist\EGE_Math_portable 2>nul
move /Y dist\OGE_Math_Review.exe dist\OGE_Math_portable\ 2>nul
move /Y dist\EGE_Math_Review.exe dist\EGE_Math_portable\ 2>nul
copy /Y "scripts\README_math_review.txt" "dist\OGE_Math_portable\README.txt"
copy /Y "scripts\README_math_review.txt" "dist\EGE_Math_portable\README.txt"

echo.
echo Done.
echo   OGE Math: dist\OGE_Math_portable\OGE_Math_Review.exe  (put oge_math_tasks.json there)
echo   EGE Math: dist\EGE_Math_portable\EGE_Math_Review.exe  (put ege_math_tasks.json there)
pause
