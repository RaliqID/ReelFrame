@echo off
title Build ReelFrame Windows Installer (by Raliq Hidayat BM3)
cd /d "%~dp0"

echo =======================================================
echo   ReelFrame - Build Windows App + Installer
echo   Author: Raliq Hidayat BM3
echo =======================================================
echo.

where ISCC.exe >nul 2>nul
set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC=C:\Program Files\Inno Setup 6\ISCC.exe

echo [1/4] Building portable app (dist\ReelFrame\ReelFrame.exe)...
call build_desktop.bat
if errorlevel 1 ( echo [X] Portable build failed. & pause & exit /b 1 )

if "%ISCC%"=="" (
    echo.
    echo [!] Inno Setup not found - skipping installer.
    echo     Install it with:  winget install JRSoftware.InnoSetup
    echo     Then re-run this script to get ReelFrame-Setup.exe
    pause
    exit /b 0
)

echo [2/4] Building Windows installer...
"%ISCC%" "installer\ReelFrame.iss"
if errorlevel 1 ( echo [X] Installer build failed. & pause & exit /b 1 )

echo.
echo =======================================================
echo   DONE
echo   Portable app : dist\ReelFrame\ReelFrame.exe
echo   Installer    : installer\output\ReelFrame-Setup-2.0.0.exe
echo =======================================================
pause
