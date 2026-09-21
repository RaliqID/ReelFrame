@echo off
title ReelFrame — Desktop App (by Raliq Hidayat BM3)
cd /d "%~dp0"

echo =======================================================
echo   ReelFrame - Native Desktop Application
echo   Author: Raliq Hidayat BM3
echo   Runs as: Windows Desktop App (WebView2)
echo =======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Running setup first...
    call setup.bat
)

echo [*] Launching ReelFrame Desktop App...
call .venv\Scripts\activate.bat
python desktop_app.py
pause
