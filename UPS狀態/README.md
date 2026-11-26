# UPS 電池容量與狀態 Web Dashboard

以 Python + FastAPI 建立的簡易 Web 儀表板，直接從 Delta InsightPower G3 Mini SNMP Card 的網頁介面（預設 `https://192.168.0.7/webpages/home.html`）抓取即時電池容量與 UPS 狀態，並提供 JSON API（亦保留原有的 SNMP 讀取模式）。

## 專案結構

- `app.py`：FastAPI Web 服務（儀表板首頁、`/api/battery`、`/api/ups`）
- `web_client.py`：從 UPS 網頁對應的 XML 端點（`/webpages/xml/ups/index_ups.xml` 與 `/webpages/xml/ups/info_battery.xml`）抓取並解析電池容量與各項狀態
- `snmp_client.py`：原有的 SNMP（UPS-MIB RFC 1628）讀取模組
- `templates/index.html`：前端儀表板頁面（醒目顯示電池容量百分比與進度條，自動每 10 秒更新）
- `config.json`：連線設定（`source`、`ups_url`、`verify_ssl` 等）
- `requirements.txt`：Python 相依套件

## 安裝與啟動

在專案目錄（`D:\gemini\UPS狀態`）執行：

```powershell
# 啟動虛擬環境（若尚未建立可先執行 python -m venv .venv）
.\.venv\Scripts\Activate.ps1

# 安裝套件
pip install -r requirements.txt

# 啟動 Web 服務
python app.py
```

啟動後開啟瀏覽器：<http://localhost:8000>

服務預設僅監聽 `127.0.0.1`。若需透過反向代理存取，請使用 `UPS_DASHBOARD_HOST`／`UPS_DASHBOARD_PORT` 明確設定，並在代理層加上認證與網路存取限制；勿直接公開此服務。

## 設定（`config.json`）

```json
{
  "source": "web",
  "ups_url": "https://192.168.0.7/webpages/home.html",
  "verify_ssl": true,
  "ca_cert_path": "",
  "web_timeout": 5,
  "host": "192.168.0.7",
  "port": 161,
  "version": "v3",
  "username": "",
  "auth_protocol": "sha1",
  "priv_protocol": "aes",
  "timeout": 2,
  "retries": 1
}
```

- `source`：`web`（預設，從 UPS 網頁 XML 抓取）或 `snmp`（從 SNMP UDP 161 抓取）
- `ups_url`：UPS 管理網頁網址（程式會自動解析主機並抓取其 XML 資料）
- `verify_ssl`：必須為 `true`；如使用私有 CA，設定 `ca_cert_path` 指向 CA 憑證檔
- `web_timeout`：HTTP/HTTPS 請求逾時秒數
- SNMP 僅支援 SNMPv3 authPriv。請以 `SNMP_V3_USERNAME`、`SNMP_V3_AUTH_PASSWORD`、`SNMP_V3_PRIV_PASSWORD` 環境變數提供憑證（兩組密語至少 8 字元）；不支援 v1/v2c 或 `public` 社群字串。
- UPS 網頁資料僅接受 HTTPS，且預設驗證伺服器憑證；不得以停用驗證或改用 HTTP 繞過憑證問題。

## API

- `GET /`：電池容量與 UPS 狀態儀表板頁面
- `GET /api/battery`：專抓電池容量與狀態的精簡 JSON（含 `battery_capacity_percent`、`battery_status`、`battery`）
- `GET /api/ups`：即時抓取並回傳完整 UPS 資訊 JSON（含輸入、輸出、電池、排程與原始 XML 欄位）
- `GET /api/config`：回傳目前設定
- `GET /api/health`：服務健康檢查
