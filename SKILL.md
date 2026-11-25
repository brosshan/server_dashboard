---
name: code-backup-standard
description: Standard operating procedure for pre-modification source code backup with dated snapshots in server_dashboard
---

# 程式碼修改前備份作業規範 (Code Pre-Modification Backup Standard)

當在本專案（`server_dashboard`）進行任何功能新增、結構重構或程式碼修改前，**必須強制執行修改前原始程式碼備份**，並以**當天日期（格式：YYYYMMDD）**命名備份目錄或備份檔名。

---

## 1. 備份時機 (When to Backup)
- **任何功能修改前**：包含後端 API (`server/app/*.py`)、排程 (`scheduler.py`)、前端介面 (`server/static/*`) 等。
- **引入新模組或第三方整合前**：如新增 UPS 監控、SNMP 協議擴展、防火牆規則介面等。
- **資料庫 Schema 異動前**：修改 SQLite 資料表或資料遷移前。

---

## 2. 備份命名規則 (Naming Convention)
- **備份目錄名稱**：`backup_YYYYMMDD`（例如今日日期：`backup_20261124`）。
- **存放位置**：專案根目錄 `D:\gemini\server_dashboard\backup_YYYYMMDD/`。
- 若同一天內進行多次重大里程碑修改，可使用流水號後綴，例如：`backup_20261124_v2`。

---

## 3. 備份操作方式 (How to Backup)

### 方式 A：使用 Python 一鍵備份腳本 (推薦，跨平台最穩定)
在專案根目錄執行：
```bash
python -c "import shutil, os, datetime; date_str=datetime.datetime.now().strftime('%Y%m%d'); backup_dir=f'D:/gemini/server_dashboard/backup_{date_str}'; os.makedirs(backup_dir, exist_ok=True); targets=['server/app/models.py', 'server/app/api.py', 'server/app/prober.py', 'server/app/scheduler.py', 'server/app/database.py', 'server/static/index.html', 'server/static/app.js']; [shutil.copy(t, os.path.join(backup_dir, os.path.basename(t))) for t in targets if os.path.exists(t)]; print(f'Backup completed to {backup_dir}:', os.listdir(backup_dir))"
```

### 方式 B：使用 PowerShell 腳本
```powershell
$today = (Get-Date).ToString("yyyyMMdd")
$backupDir = "D:\gemini\server_dashboard\backup_$today"
New-Item -ItemType Directory -Force -Path $backupDir

$filesToBackup = @(
    "server\app\models.py",
    "server\app\api.py",
    "server\app\prober.py",
    "server\app\scheduler.py",
    "server\app\database.py",
    "server\static\index.html",
    "server\static\app.js"
)

foreach ($f in $filesToBackup) {
    if (Test-Path $f) {
        Copy-Item -Path $f -Destination $backupDir -Force
    }
}
Get-ChildItem -Path $backupDir | Select-Object Name, Length
```

---

## 4. 還原作業流程 (Rollback / Restore)
若修改後發生異常需要立即還原至指定日期版本：
```bash
python -c "import shutil, os; src_dir='D:/gemini/server_dashboard/backup_20261124'; shutil.copy(f'{src_dir}/models.py', 'server/app/models.py'); shutil.copy(f'{src_dir}/api.py', 'server/app/api.py'); shutil.copy(f'{src_dir}/prober.py', 'server/app/prober.py'); shutil.copy(f'{src_dir}/scheduler.py', 'server/app/scheduler.py'); shutil.copy(f'{src_dir}/database.py', 'server/app/database.py'); shutil.copy(f'{src_dir}/index.html', 'server/static/index.html'); shutil.copy(f'{src_dir}/app.js', 'server/static/app.js'); print('Restore successful!')"
```

---

## 5. 檢核清單 (Checklist)
每次執行任務時確認：
1. [x] 是否已建立 `backup_YYYYMMDD` 目錄？
2. [x] 即將更動的所有既有檔案是否已完整拷貝？
3. [x] 備份檔案大小是否皆大於 0 bytes？
4. [x] 修改後測試若有失敗，是否有指定備份可供快速比對或還原？
