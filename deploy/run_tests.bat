@echo off
REM eDNA LPT API Tests - Automated Test Runner
REM
REM Purpose: Run comprehensive test suite for API infrastructure
REM Usage: run_tests.bat [option]
REM
REM Options:
REM   (no args)  - Run all tests
REM   unit       - Run unit tests only
REM   service    - Test api_service.py
REM   client     - Test api_client.py
REM   server     - Test api_server.py
REM   coverage   - Run with coverage report
REM   watch      - Run tests on file changes

setlocal enabledelayedexpansion

color 0A
title eDNA LPT API Tests

REM Set venv python path
set PYTHON=.\.venv\Scripts\python.exe

REM Check if Python available
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found in .\.venv
    echo.
    echo Please ensure virtual environment is activated:
    echo   .\.venv\Scripts\activate
    echo.
    pause
    exit /b 1
)

REM Check if pytest installed
%PYTHON% -m pytest --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARNING] pytest not installed
    echo [INFO] Installing pytest...
    %PYTHON% -m pip install pytest pytest-asyncio -q
    if errorlevel 1 (
        echo [ERROR] Failed to install pytest
        pause
        exit /b 1
    )
)

echo.
echo ════════════════════════════════════════════════════════════
echo   eDNA LPT API Testing Suite
echo ════════════════════════════════════════════════════════════
echo.

REM Determine test option
set TEST_OPTION=%1

if "%TEST_OPTION%"=="" (
    echo [INFO] Running all tests...
    echo.
    %PYTHON% -m pytest tests/ -v --tb=short
    goto end_tests
)

if "%TEST_OPTION%"=="unit" (
    echo [INFO] Running unit tests...
    echo.
    %PYTHON% -m pytest tests/ -v -k "not integration"
    goto end_tests
)

if "%TEST_OPTION%"=="service" (
    echo [INFO] Running api_service tests...
    echo.
    %PYTHON% -m pytest tests/test_api_service.py -v
    goto end_tests
)

if "%TEST_OPTION%"=="client" (
    echo [INFO] Running api_client tests...
    echo.
    %PYTHON% -m pytest tests/test_api_client.py -v
    goto end_tests
)

if "%TEST_OPTION%"=="server" (
    echo [INFO] Running api_server tests...
    echo.
    %PYTHON% -m pytest tests/test_api_server.py -v
    goto end_tests
)

if "%TEST_OPTION%"=="coverage" (
    echo [INFO] Running tests with coverage report...
    echo.
    %PYTHON% -m pip install pytest-cov -q
    %PYTHON% -m pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing
    echo.
    echo [INFO] Coverage report generated: htmlcov\index.html
    goto end_tests
)

if "%TEST_OPTION%"=="watch" (
    echo [INFO] Running tests in watch mode...
    echo [INFO] Tests will re-run when files change...
    echo.
    %PYTHON% -m pip install pytest-watch -q
    %PYTHON% -m ptw tests/ -- -v --tb=short
    goto end_tests
)

echo.
echo [ERROR] Unknown option: %TEST_OPTION%
echo.
echo Usage: run_tests.bat [option]
echo.
echo Options:
echo   (no args)  - Run all tests
echo   unit       - Run unit tests only
echo   service    - Test api_service.py
echo   client     - Test api_client.py
echo   server     - Test api_server.py
echo   coverage   - Run with coverage report
echo   watch      - Run tests on file changes
echo.
pause
exit /b 1

:end_tests
set TEST_EXIT_CODE=%ERRORLEVEL%

echo.
echo ════════════════════════════════════════════════════════════

if %TEST_EXIT_CODE% equ 0 (
    echo   Test Results: ✓ ALL TESTS PASSED
) else (
    echo   Test Results: ✗ SOME TESTS FAILED (Exit code: %TEST_EXIT_CODE%)
)

echo ════════════════════════════════════════════════════════════
echo.

if "%TEST_OPTION%"=="coverage" (
    echo [INFO] To view coverage report:
    echo   Open: htmlcov\index.html
    echo.
)

pause
exit /b %TEST_EXIT_CODE%
