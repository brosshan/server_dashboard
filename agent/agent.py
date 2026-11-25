import json
import platform
import socket
import time
from pathlib import Path

import psutil
import requests


CONFIG_PATH = Path(__file__).with_name("agent_config.json")


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def collect_metrics(config: dict = None) -> dict:
    config = config or {}
    memory = psutil.virtual_memory()
    disks = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append(
                {
                    "mount": partition.mountpoint,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "percent": usage.percent,
                }
            )
        except (PermissionError, OSError):
            continue

    network = psutil.net_io_counters()
    return {
        "hostname": config.get("custom_hostname") or socket.gethostname(),
        "ip_address": get_ip_address(),
        "platform": f"{platform.system()} {platform.release()}",
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": memory.percent,
        "memory_used_gb": round(memory.used / (1024 ** 3), 2),
        "memory_total_gb": round(memory.total / (1024 ** 3), 2),
        "disk": disks,
        "network": {
            "bytes_sent": network.bytes_sent,
            "bytes_recv": network.bytes_recv,
        },
        "service_status": {},
    }


import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_target_url(config: dict) -> str:
    active_file = Path(__file__).resolve().parents[1] / ".active_url"
    if active_file.exists():
        try:
            active = active_file.read_text(encoding="utf-8").strip().rstrip("/")
            if active:
                return f"{active}/api/metrics"
        except Exception:
            pass
    return config.get("server_url") or config.get("api_url") or "http://127.0.0.1:8000/api/metrics"


def main() -> None:
    config = load_config()
    target_url = get_target_url(config)
    api_key = config.get("api_key", "")
    session = requests.Session()
    cert_file = Path(__file__).with_name("cert.pem")
    if cert_file.exists():
        session.verify = str(cert_file)
    else:
        session.verify = False
    while True:
        try:
            response = session.post(
                target_url,
                headers={"X-API-Key": api_key},
                json=collect_metrics(config),
                timeout=10,
            )
            response.raise_for_status()
            print("Metrics sent successfully")
        except requests.RequestException as error:
            print(f"Failed to send metrics: {error}")
        time.sleep(max(1, int(config.get("interval_seconds", 5))))


if __name__ == "__main__":
    main()
