@echo off
title Download AI Models - Local 4K Upscaler
cd /d "%~dp0"

echo ===================================================
echo   Download Pretrained Models (Real-ESRGAN / GFPGAN)
echo   Author: Raliq Hidayat BM3
echo ===================================================
echo.

if exist ".venv\Scripts\python.exe" (
    call .venv\Scripts\activate.bat
    python download_models.py %*
) else (
    python download_models.py %*
)

pause
