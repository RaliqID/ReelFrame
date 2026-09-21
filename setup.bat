@echo off
title Setup ReelFrame (by Raliq Hidayat BM3)
cd /d "%~dp0"

echo =======================================================
echo   ReelFrame - AI Environment Setup
echo   Author: Raliq Hidayat BM3
echo =======================================================
echo.

if not exist ".venv" (
    echo [*] Creating Python virtual environment in .venv ...
    python -m venv .venv
)

echo [*] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip

echo [*] Installing PyTorch with CUDA 12.4 support...
.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

echo [*] Installing dependencies from requirements.txt...
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [*] Downloading default AI models...
.venv\Scripts\python.exe download_models.py default

echo.
echo =======================================================
echo   ReelFrame Setup Complete!
echo   Double click 'run_gui.bat' to launch the dashboard.
echo =======================================================
pause
