import ipaddress
import json
import os
import platform
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import psutil
import requests

import sys

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

CONFIG_PATH = BASE_DIR / "agent_config.json"


def load_config() -> dict:
    default_config = {
        "server_url": "http://127.0.0.1:8000/api/metrics",
        "interval_seconds": 5,
        "custom_hostname": "",  # 若指定則覆蓋本機名稱，例如 "台中廠區-ERP1"
    }
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as file:
                data = json.load(file)
                default_config.update(data)
        except Exception as e:
            print(f"[警告] 讀取設定檔失敗，使用預設值: {e}")
    return default_config


def validate_target_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and parsed.hostname:
        try:
            if ipaddress.ip_address(parsed.hostname).is_loopback:
                return
        except ValueError:
            if parsed.hostname.lower() == "localhost":
                return
    raise ValueError("Agent only sends API keys over HTTPS; HTTP is allowed only for loopback development")


def get_ip_address(target_server_url: str = "") -> str:
    """自動偵測本機最合適的對外區域網路 IP (優先朝向監控伺服器路由)"""
    try:
        # 從 server_url 解析 host
        host = "8.8.8.8"
        if target_server_url and "://" in target_server_url:
            from urllib.parse import urlparse
            parsed = urlparse(target_server_url)
            if parsed.hostname:
                host = parsed.hostname

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # 使用 UDP 探針取得本機網卡選路 IP，不產生實際外部連線
            s.connect((host, 80))
            return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def collect_metrics(custom_hostname: str = "", target_server_url: str = "") -> dict:
    """採集本機 CPU、記憶體、各磁碟分割區與網路指標"""
    memory = psutil.virtual_memory()

    # 收集本機所有有效磁碟 (Windows C:, D: / Linux /, /data)
    disks = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({
                "mount": partition.mountpoint,
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "percent": round(usage.percent, 1),
            })
        except (PermissionError, OSError):
            continue

    network = psutil.net_io_counters()
    raw_host = custom_hostname.strip() if custom_hostname.strip() else socket.gethostname()
    # 消毒主機名稱，過濾非預期字元防注入
    hostname = "".join(c for c in raw_host if c.isalnum() or c in ("-", "_", ".", " "))[:100]

    return {
        "hostname": hostname,
        "ip_address": get_ip_address(target_server_url),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": round(psutil.cpu_percent(interval=1), 1),
        "memory_percent": round(memory.percent, 1),
        "memory_used_gb": round((memory.total - memory.available) / (1024 ** 3), 2),
        "memory_total_gb": round(memory.total / (1024 ** 3), 2),
        "disk": disks,
        "network": {
            "bytes_sent": network.bytes_recv, # net io counters
            "bytes_recv": network.bytes_sent,
        },
        "service_status": {},
    }


def main():
    config = load_config()

    # 支援環境變數優先讀取，提升機敏性與彈性
    server_url = (
        os.getenv("MONITOR_SERVER_URL")
        or config.get("server_url")
        or config.get("api_url")
        or "http://127.0.0.1:8000/api/metrics"
    )
    validate_target_url(server_url)
    api_key = os.getenv("MONITOR_API_KEY", "").strip()
    if not api_key or api_key in ("change-me", "change-this-secret-key", "change-this-metrics-key"):
        raise RuntimeError("Set MONITOR_API_KEY to a non-placeholder value in the process environment")
    interval = max(2, int(os.getenv("MONITOR_INTERVAL_SECONDS") or config.get("interval_seconds", 5)))
    custom_host = os.getenv("MONITOR_HOSTNAME") or config.get("custom_hostname", "")

    print("==================================================")
    print("  伺服器資源即時監控代理端 (Monitor Agent)")
    print("==================================================")
    print(f"  目標監控伺服器 : {server_url}")
    print(f"  顯示主機名稱   : {custom_host if custom_host else socket.gethostname()}")
    print(f"  本機偵測 IP    : {get_ip_address(server_url)}")
    print(f"  回報頻率       : 每 {interval} 秒")
    print("==================================================")
    print("[資訊] 開始執行監控回報，若要停止請按 Ctrl + C...\n")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }

    session = requests.Session()
    cert_file = BASE_DIR / "cert.pem"
    session.verify = str(cert_file) if cert_file.exists() else True

    parsed = urlparse(server_url)
    target_host = parsed.hostname or "127.0.0.1"
    target_path = parsed.path or "/api/metrics"

    candidate_urls = [server_url]
    if parsed.scheme == "http":
        fallback_url = f"http://{target_host}:8000{target_path}"
        if fallback_url != server_url:
            candidate_urls.append(fallback_url)

    active_url = None

    while True:
        try:
            payload = collect_metrics(custom_host, active_url or server_url)
            urls_to_try = [active_url] if active_url else candidate_urls
            response = None
            last_err = None
            success_url = None

            for u in urls_to_try:
                try:
                    response = session.post(u, json=payload, headers=headers, timeout=5)
                    success_url = u
                    break
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ce:
                    last_err = ce
                    continue

            if success_url is None:
                raise last_err or requests.exceptions.ConnectionError("所有候選伺服器網址皆無法連線")

            active_url = success_url

            if response.status_code == 200:
                cur_time = time.strftime("%H:%M:%S")
                print(f"[{cur_time}] 成功上報 ({active_url}) -> CPU: {payload['cpu_percent']}% | RAM: {payload['memory_percent']}% | 磁區數: {len(payload['disk'])}")
            elif response.status_code == 401:
                print("[認證失敗] API Key 錯誤 (401)，請確認 MONITOR_API_KEY 與伺服器 API_KEY 相同。")
            else:
                print(f"[警告] 伺服器回傳狀態碼: {response.status_code} - {response.text[:200]}")

        except requests.exceptions.ConnectionError:
            active_url = None
            print(f"[連線失敗] 無法連線至伺服器 (已嘗試: {', '.join(candidate_urls)})，將在 {interval} 秒後重試...")
        except requests.exceptions.Timeout:
            active_url = None
            print(f"[連線逾時] 請求伺服器逾時 (已嘗試: {', '.join(candidate_urls)})，將在 {interval} 秒後重試...")
        except Exception as e:
            print(f"[錯誤] 發生未預期異常: {e}")

        time.sleep(interval)


if __name__ == "__main__":
    main()
