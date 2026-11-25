@echo off
@setlocal EnableExtensions
title Server Monitor Agent

cd /d "%~dp0"

echo ============================================================
echo   Starting Datacenter Monitor Agent...
echo ============================================================

set "VENV_OK=1"
if not exist ".venv\Scripts\python.exe" (
    set "VENV_OK=0"
) else (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 set "VENV_OK=0"
)

if "%VENV_OK%"=="0" (
    echo [Error: .venv not found or invalid. Please run start_server.bat or start_all.bat first.]
    pause
    exit /b 1
)

echo [Agent is running and sending metrics...]
echo Press Ctrl + C to stop.
echo ============================================================

.\.venv\Scripts\python.exe agent\agent.py

pause
