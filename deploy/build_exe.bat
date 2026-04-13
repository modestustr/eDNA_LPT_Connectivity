@echo off
REM eDNA LPT Simulation Service - Build Executable
REM Creates standalone exe using PyInstaller
REM
REM Prerequisites:
REM   - Python 3.10+
REM   - PyInstaller installed: pip install pyinstaller
REM   - All dependencies installed: pip install -r requirements.txt
REM
REM Usage: build_exe.bat

setlocal enabledelayedexpansion

color 0A
title eDNA LPT Simulation Service - Build

echo.
echo ==========================================
echo   eDNA LPT SimService - Build Process
echo ==========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo.
    echo Please install Python 3.10+ from https://www.python.org/
    echo and add it to your system PATH
    echo.
    pause
    exit /b 1
)

echo [INFO] Checking Python version...
python --version

REM Check if PyInstaller is installed
echo [INFO] Checking PyInstaller installation...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] PyInstaller not installed
    echo [INFO] Installing PyInstaller...
    python -m pip install pyinstaller --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller
        pause
        exit /b 1
    )
)

REM Check if build directory exists
if exist "build" (
    echo [INFO] Cleaning previous build...
    rmdir /s /q "build" >nul 2>&1
)

if exist "__pycache__" (
    rmdir /s /q "__pycache__" >nul 2>&1
)

echo.
echo [INFO] Building executable using PyInstaller...
echo [INFO] This may take 1-3 minutes...
echo.

REM Run PyInstaller (note: do NOT use --onedir/--onefile with .spec file)
pyinstaller build_exe.spec

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo.
    echo Troubleshooting:
    echo   1. Check that all dependencies are installed:
    echo      pip install -r requirements.txt
    echo.
    echo   2. Check for missing modules in build_exe.spec hiddenimports
    echo.
    echo   3. Run with verbose output:
    echo      pyinstaller --debug=imports build_exe.spec
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   Build Complete!
echo ==========================================
echo.
echo Executable location:
echo   .\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe
echo.
echo Next steps:
echo.
echo 1. Install as Windows Service:
echo    .\start_service.bat
echo.
echo 2. Or run directly:
echo    .\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe --help
echo.
echo 3. Manual service installation:
echo    powershell -Command ^
echo    "& '.\service_manager.ps1' -Action Install -ServiceName eDNALPTSim -ExePath '.\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe'"
echo.
echo ==========================================
echo.

pause
