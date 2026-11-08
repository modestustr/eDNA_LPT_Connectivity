@echo off
REM Quick launcher for eDNA LPT Simulation API Server on Windows
REM Double-click to start with default settings
REM
REM For more control, use PowerShell:
REM   powershell -ExecutionPolicy Bypass -File Start-APIServer.ps1 -Port 9000

setlocal enabledelayedexpansion

echo.
echo ========================================================================
echo   eDNA LPT Simulation API Server Launcher
echo ========================================================================
echo.

REM Check if PowerShell is available
where powershell >nul 2>nul
if errorlevel 1 (
    echo ERROR: PowerShell not found. This script requires PowerShell.
    pause
    exit /b 1
)

REM Get script directory
set SCRIPT_DIR=%~dp0

REM Allow customization via arguments
set PORT=%1
set HOST=%2

if not defined PORT set PORT=8000
if not defined HOST set HOST=127.0.0.1

echo Configuration:
echo   Port: %PORT%
echo   Host: %HOST%
echo.

REM Launch PowerShell launcher script
echo Starting API server...
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%Start-APIServer.ps1" -Port %PORT% -Host %HOST%

pause
