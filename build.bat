@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo   Dong goi ung dung FB Video Watcher thanh file .exe
echo ========================================================

if exist ".fbwenv\Scripts\python.exe" (
    set "PYTHON_EXE=.fbwenv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [1/2] Dang kiem tra thu vien va don dep thu muc cu...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"

echo [2/2] Dang chay PyInstaller de dong goi file .exe doc lap...
"%PYTHON_EXE%" -m PyInstaller --clean fb_video_watcher.spec

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================================
    echo   THANH CONG! File .exe da duoc tao tai:
    echo   dist\FB-Video-Watcher.exe
    echo ========================================================
) else (
    echo.
    echo [LOI] Qua trinh dong goi that bai. Ma loi: %ERRORLEVEL%
)

pause
