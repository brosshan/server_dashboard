@echo off
@setlocal EnableExtensions
title Datacenter Monitor Agent

cd /d "%~dp0"

echo ============================================================
echo   Starting Datacenter Monitor Agent...
echo ============================================================

REM 1. If standalone agent.exe exists, run it directly (No Python required!)
if exist "agent.exe" (
    echo [免安裝模式] 偵測到獨立執行檔 agent.exe，無需安裝 Python，直接啟動...
    echo.
    agent.exe
    if errorlevel 1 (
        echo [異常結束] agent.exe 已停止。
        pause
    )
    exit /b 0
)

REM 2. If agent.exe is not present, search Python in PATH and common locations
set "PY_CMD="

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_found
)

py --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py"
    goto :python_found
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PY_CMD=%%D\python.exe"
        goto :python_found
    )
)

for /d %%D in ("C:\Program Files\Python*") do (
    if exist "%%D\python.exe" (
        set "PY_CMD=%%D\python.exe"
        goto :python_found
    )
)

for /d %%D in ("C:\Python*") do (
    if exist "%%D\python.exe" (
        set "PY_CMD=%%D\python.exe"
        goto :python_found
    )
)

:python_not_found
echo.
echo [錯誤] 找不到 Python 執行環境，且資料夾中無 agent.exe！
echo.
echo ============================================================
echo  您可以選擇以下兩種方式之一來監控此台伺服器：
echo ============================================================
echo.
echo  【方案 A】在此台主機安裝 Python (以回報 CPU/RAM/磁碟詳細資源)：
echo    1. 請至 https://www.python.org 下載 Python 3.8+ 安裝檔。
echo    2. 安裝時務必勾選「Add python.exe to PATH」！
echo    3. 安裝完成後重新執行本 run_agent.bat 即可。
echo.
echo  【方案 B】免裝 Python！直接由監控中心進行探測 (最推薦／最簡便)：
echo    - 您不需要在此台伺服器安裝任何軟體。
echo    - 請直接回到監控中心儀表板 (http://192.168.0.100:8000)
echo    - 進入「設備與站點設定」-^> 點擊「新增設備」
echo    - 填入此台伺服器的 IP 與檢測方式 (Ping 或 TCP Port) 即可立即監控在線狀態！
echo ============================================================
echo.
pause
exit /b 1

:python_found
echo [已找到 Python: %PY_CMD%]

REM 3. Check virtualenv validity
set "VENV_OK=1"
if not exist ".venv\Scripts\python.exe" (
    set "VENV_OK=0"
) else (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if errorlevel 1 set "VENV_OK=0"
)

if "%VENV_OK%"=="0" (
    echo [建立專屬虛擬環境中...]
    if exist ".venv" rd /s /q ".venv"
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [錯誤] 虛擬環境建立失敗！
        pause
        exit /b 1
    )
    echo [安裝監控相依套件中...]
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [錯誤] 套件安裝失敗！請確認網路是否可連線至 PyPI。
        pause
        exit /b 1
    )
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo [啟動監控 Agent...]
python agent.py

pause
