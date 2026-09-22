@echo off
setlocal
cd /d "%~dp0"
title FB Video Watcher - Console and Log Viewer

echo ======================================================================
echo           FB VIDEO WATCHER - REALTIME LOG VIEWER
echo ======================================================================
echo.

REM Kiem tra moi truong ao .fbwenv
if not exist "%~dp0.fbwenv\Scripts\python.exe" (
    echo [ERROR] Khong tim thay moi truong ao .fbwenv tai thu muc nay!
    echo Thu muc hien tai: %~dp0
    echo.
    pause
    exit /b 1
)

echo [INFO] Dang khoi dong FB Video Watcher tu .fbwenv...
echo [INFO] Moi thong tin log, luong stream va loi se xuat hien ben duoi.
echo ----------------------------------------------------------------------
echo.

"%~dp0.fbwenv\Scripts\python.exe" -u main.py

echo.
echo ----------------------------------------------------------------------
echo [INFO] Ung dung da dong.
pause
endlocal
