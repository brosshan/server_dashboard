# Datacenter Server Monitor

本專案依規劃書提供 FastAPI 監控後端、Redis 即時快取、SQLite 歷史紀錄、WebSocket 儀表板與跨平台資源 Agent。

## 快速啟動（Windows）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r server\requirements.txt -r agent\requirements.txt
Copy-Item .env.example .env

$env:API_KEY="change-this-secret-key"
$env:SQLITE_PATH="./data/metrics.db"
python -m uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000 --reload
```

開啟 http://127.0.0.1:8000。

另開終端機執行 Agent：

```powershell
.\.venv\Scripts\Activate.ps1
python agent\agent.py
```

正式環境請修改 `.env` 與 `agent_config.json` 的相同 API Key。

## Docker 啟動

```powershell
Copy-Item .env.example .env
docker compose up --build
```

## 主要端點

- `GET /api/servers`
- `GET /api/history/{hostname}?hours=24`
- `POST /api/metrics`
- `WS /ws`
- `GET /docs`
