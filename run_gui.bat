@echo off
title ReelFrame - Local 4K AI Upscaler (by Raliq Hidayat BM3)
cd /d "%~dp0"

echo =======================================================
echo   ReelFrame - Local 4K AI Video & Image Upscaler
echo   Author: Raliq Hidayat BM3
echo =======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Running setup first...
    call setup.bat
)

echo [*] Launching ReelFrame Web Dashboard at http://127.0.0.1:7860 ...
call .venv\Scripts\activate.bat
python gui.py
pause
