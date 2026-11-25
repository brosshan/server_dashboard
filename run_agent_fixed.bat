@echo off
@setlocal EnableExtensions
title ERP Monitor Agent

cd /d "%~dp0"

echo ============================================================
echo   Starting Datacenter Monitor Agent for Remote Server...
echo ============================================================

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python is not installed or not in PATH!
    echo Please install Python 3.8+ on this server.
    pause
    exit /b 1
)

REM Check if config template exists, prompt user to create agent_config.json
if not exist "agent_config.json" (
    echo [Warning] agent_config.json not found!
    echo Please copy agent_config.json.template to agent_config.json
    echo and fill in your server_url and api_key before running.
    pause
    exit /b 1
)

REM Install required packages (pinned versions, verbose output)
echo [Checking Dependencies...]
python -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo [Error] Failed to install dependencies!
    pause
    exit /b 1
)

echo.
echo [Starting Agent...]
python agent.py

pause