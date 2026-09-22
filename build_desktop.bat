@echo off
title Build ReelFrame Desktop App (by Raliq Hidayat BM3)
cd /d "%~dp0"

echo =======================================================
echo   ReelFrame - Build Windows Desktop App
echo   Author: Raliq Hidayat BM3
echo =======================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Running setup first...
    call setup.bat
)

echo [*] Ensuring PyInstaller is installed...
.venv\Scripts\python.exe -m pip install --upgrade pyinstaller >nul

echo [*] Generating app icon...
.venv\Scripts\python.exe make_icon.py

echo [*] Building ReelFrame.exe (this can take a few minutes)...
.venv\Scripts\python.exe -m PyInstaller ReelFrame.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [X] Build failed. See the output above for details.
    pause
    exit /b 1
)

echo.
echo =======================================================
echo   Build complete!
echo   Your app: dist\ReelFrame\ReelFrame.exe
echo   Double-click it to launch the native window.
echo =======================================================
pause
