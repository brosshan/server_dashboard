# Datacenter Server Monitor

本專案依規劃書提供 FastAPI 監控後端、Redis 即時快取、SQLite 歷史紀錄、WebSocket 儀表板與跨平台資源 Agent。

## 快速啟動（Windows）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r server\requirements.txt -r agent\requirements.txt
Copy-Item .env.example .env

$env:API_KEY="replace-with-a-random-agent-key"
$env:ADMIN_API_KEY="replace-with-a-different-random-admin-key"
$env:REQUIRE_READ_AUTH="true"
$env:SQLITE_PATH="./data/metrics.db"
python -m uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000 --reload
```

預設僅本機可連線，開啟 http://127.0.0.1:8000。正式部署請使用 HTTPS，並在防火牆限制來源。

另開終端機執行 Agent：

```powershell
.\.venv\Scripts\Activate.ps1
$env:MONITOR_API_KEY="same agent-only key configured on the server"
python agent\agent.py
```

Agent 金鑰只透過 `MONITOR_API_KEY` 環境變數提供；請勿把金鑰寫入 `agent_config.json`。讀取 API 與 WebSocket 需要 API 金鑰或管理金鑰，管理操作另需管理金鑰。

## Docker 啟動

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose 預設只在本機發布 `127.0.0.1:8000`。若需區網存取，請明確設定 `DASHBOARD_BIND_ADDRESS` 並以主機防火牆限制至核准網段；容器內監聽位址會維持 `0.0.0.0`。

SNMP 探測採 SNMPv3 authPriv。請以秘密管理機制設定 `SNMP_V3_USERNAME`、`SNMP_V3_AUTH_PASSWORD` 及 `SNMP_V3_PRIV_PASSWORD`，並在設備端配置相符的唯讀 SNMPv3 使用者；未配置時探測會失敗關閉，不會退回 v2c 或 `public` 社群字串。

## 主要端點

- `GET /api/servers`
- `GET /api/history/{hostname}?hours=24`
- `POST /api/metrics`
- `WS /ws`
- `GET /docs`
