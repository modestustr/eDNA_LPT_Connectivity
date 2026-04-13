@echo off
REM eDNA LPT Simulation Service - Quick Launcher
REM This batch script installs and starts the Windows Service automatically
REM
REM Usage: Double-click start_service.bat to install and start the service
REM Administrator privileges required

setlocal enabledelayedexpansion

color 0A
title eDNA LPT Simulation Service - Launcher

REM Check if running as admin
openfiles >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] This script requires administrator privileges!
    echo.
    echo Please right-click this file and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   eDNA LPT Simulation Service
echo   Windows Service Launcher
echo ==========================================
echo.

REM Find the exe location
set EXE_PATH=
if exist "dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe" (
    set "EXE_PATH=!CD!\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe"
) else if exist "..\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe" (
    set "EXE_PATH=!CD!\..\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe"
) else (
    echo.
    echo [ERROR] Cannot find eDNA_LPT_SimService.exe
    echo.
    echo Expected locations:
    echo   - .\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe
    echo   - ..\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe
    echo.
    echo Please run build_exe.bat first to build the executable.
    echo.
    pause
    exit /b 1
)

echo [INFO] Found executable: %EXE_PATH%
echo.

REM Configuration
set SERVICE_NAME=eDNALPTSim
set PORT=8000
set HOST=127.0.0.1
set WORKERS=4
set LOG_LEVEL=info

REM Check if service already exists
sc query %SERVICE_NAME% >nul 2>&1
if errorlevel 1 (
    echo [INFO] Service '%SERVICE_NAME%' does not exist yet.
    echo [INFO] Installing service...
    echo.
    
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "& '.\service_manager.ps1' -Action Install -ServiceName %SERVICE_NAME% ^
        -ExePath '%EXE_PATH%' -Port %PORT% -Host %HOST% -Workers %WORKERS% -LogLevel %LOG_LEVEL%"
    
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install service
        pause
        exit /b 1
    )
) else (
    echo [INFO] Service '%SERVICE_NAME%' already installed.
    echo.
)

REM Check service status
sc query %SERVICE_NAME% | findstr "RUNNING" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Service is not running. Starting it now...
    echo.
    
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "& '.\service_manager.ps1' -Action Start -ServiceName %SERVICE_NAME%"
    
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to start service
        pause
        exit /b 1
    )
) else (
    echo [INFO] Service is already running!
    echo.
)

REM Get service status
echo [INFO] Current service status:
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "& '.\service_manager.ps1' -Action Status -ServiceName %SERVICE_NAME%"

echo.
echo ==========================================
echo   Service Information
echo ==========================================
echo.
echo Service Name:      %SERVICE_NAME%
echo API URL:           http://%HOST%:%PORT%
echo API Docs:          http://%HOST%:%PORT%/docs
echo Health Check:      http://%HOST%:%PORT%/health
echo.
echo ==========================================
echo   Next Steps
echo ==========================================
echo.
echo 1. Test API health:
echo    curl http://%HOST%:%PORT%/health
echo.
echo 2. View API documentation:
echo    Open browser to http://%HOST%:%PORT%/docs
echo.
echo 3. Configure app to use this server:
echo    - Uncomment or set http_server_url parameter
echo    - Run: streamlit run ..\src\ui\app.py
echo.
echo 4. Manage service:
echo    - Stop:   powershell -Command "& '.\service_manager.ps1' -Action Stop -ServiceName %SERVICE_NAME%"
echo    - Remove: powershell -Command "& '.\service_manager.ps1' -Action Remove -ServiceName %SERVICE_NAME%"
echo.
echo ==========================================
echo.

pause
