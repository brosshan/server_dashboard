@echo off
@setlocal EnableExtensions
title Server Monitor

cd /d "%~dp0"

echo ============================================================
echo   Starting Datacenter Monitor Server...
echo ============================================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [Error] Python is not installed or not in system PATH!
    pause
    exit /b 1
)

REM Check virtualenv
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
    echo [Installing dependencies...]
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r server\requirements.txt -r agent\requirements.txt
    if errorlevel 1 (
        echo [Error] Failed to install dependencies!
        pause
        exit /b 1
    )
)

REM Check .env
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    )
)

echo [Server is starting...]
echo Dashboard URL: https://127.0.0.1 (Port 443) / http://127.0.0.1 (Port 80)
echo ============================================================

.\.venv\Scripts\python.exe server\run.py

pause
