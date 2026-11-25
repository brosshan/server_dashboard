@echo off
@setlocal EnableExtensions
title Datacenter Monitor Launcher

cd /d "%~dp0"

echo ============================================================
echo   Starting Datacenter Infrastructure Monitor...
echo ============================================================

REM 1. Check if Python is installed in system
python --version >nul 2>&1
if errorlevel 1 (
    echo [Error] Python is not installed or not in system PATH!
    echo Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

REM 2. Check .env configuration
if not exist ".env" (
    if exist ".env.example" (
        echo [Creating .env from .env.example...]
        copy .env.example .env >nul
    )
)

REM Clean legacy active_url file to avoid opening stale port
if exist ".active_url" del /f /q ".active_url" >nul 2>&1

REM 3. Verify virtual environment
set "VENV_OK=1"
if not exist ".venv\Scripts\python.exe" (
    set "VENV_OK=0"
) else (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 set "VENV_OK=0"
)

if "%VENV_OK%"=="0" (
    echo [.venv is missing or invalid. Initializing virtual environment...]
    python -m venv --clear .venv
    if errorlevel 1 (
        echo [Error] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [Installing required packages, please wait...]
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r server\requirements.txt -r agent\requirements.txt
    if errorlevel 1 (
        echo [Error] Failed to install dependencies!
        pause
        exit /b 1
    )
    echo [Environment setup complete.]
)

echo [1/2] Launching Monitor Server...
start "Server Monitor" cmd /k "call start_server.bat"

REM Wait 3 seconds for server initialization
powershell -Command "Start-Sleep -Seconds 3" >nul 2>&1

echo [2/2] Launching Local Agent...
start "Server Monitor Agent" cmd /k "call start_agent.bat"

echo.
echo [Done] All services started in separate windows.

REM Read active URL written by server, wait up to 5 seconds for server to write .active_url
set "OPEN_URL="
for /L %%i in (1,1,10) do (
    if exist ".active_url" (
        set /p OPEN_URL=<.active_url
        goto :got_url
    )
    powershell -Command "Start-Sleep -Milliseconds 500" >nul 2>&1
)

:got_url
if "%OPEN_URL%"=="" set "OPEN_URL=https://127.0.0.1"

echo Opening Dashboard at %OPEN_URL% ...
powershell -Command "Start-Sleep -Seconds 1" >nul 2>&1
start %OPEN_URL%

exit
