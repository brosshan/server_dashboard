@echo off
@setlocal EnableExtensions
title Stop Server Monitor
cd /d "%~dp0"

echo ============================================================
echo   Stopping Datacenter Monitor Processes...
echo ============================================================

REM 1. 終止執行 server/run.py 與 agent/agent.py 之 Python 行程
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server\run.py*' -or $_.CommandLine -like '*agent\agent.py*' -or $_.CommandLine -like '*server_dashboard*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('[Terminated] PID ' + $_.ProcessId + ': ' + $_.CommandLine) }"

REM 2. 清除殘留的暫存 active_url
if exist ".active_url" del /f /q ".active_url" >nul 2>&1

echo ============================================================
echo [Done] All Server Dashboard processes and sessions stopped.
echo ============================================================
pause
