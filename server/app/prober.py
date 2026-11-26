import asyncio
import platform
import socket
import time


async def ping_host(host: str, timeout: float = 2.0) -> tuple[bool, float | None, str]:
    """
    執行系統 ping 檢查，支援 Windows 與 Linux
    返回 (is_online, latency_ms, detail)
    嚴格防範命令引數注入 (CWE-88) 與非法目標格式
    """
    clean_host = host.strip()
    # 嚴格禁止以破折號開頭之引數或包含空白/非預期字元
    if not clean_host or clean_host.startswith("-") or "/" in clean_host or "\\" in clean_host or " " in clean_host:
        return False, None, "探測目標位址格式不合法"

    param = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_param = "-w" if platform.system().lower() == "windows" else "-W"
    timeout_val = str(int(timeout * 1000)) if platform.system().lower() == "windows" else str(int(timeout))

    # Windows 與 Linux 嚴格以列表分離傳遞參數，禁止 shell 注入
    cmd = ["ping", param, "1", timeout_param, timeout_val, clean_host]
    start_time = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 1.0)
        duration_ms = round((time.time() - start_time) * 1000, 1)

        if proc.returncode == 0:
            out_str = stdout.decode("cp950", errors="ignore") if platform.system().lower() == "windows" else stdout.decode("utf-8", errors="ignore")
            # 嘗試解析時間 (例如: 時間=12ms 或 time=12ms)
            import re
            match = re.search(r"(?:time|時間)[=<](\d+(?:\.\d+)?)ms", out_str, re.IGNORECASE)
            latency = float(match.group(1)) if match else duration_ms
            return True, latency, f"Ping 回應正常 ({latency}ms)"
        else:
            return False, None, "主機無回應 (Ping Timeout)"
    except asyncio.TimeoutError:
        return False, None, "探測逾時 (Timeout)"
    except Exception as e:
        return False, None, f"探測異常: {str(e)}"


async def tcp_ping(host: str, port: int, timeout: float = 2.0) -> tuple[bool, float | None, str]:
    """
    嘗試連線指定 TCP Port，返回 (is_open, latency_ms, detail)
    使用底層 socket 連線並安全關閉，避免 Windows ProactorEventLoop 出現 WinError 10054
    """
    start_time = time.time()
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)

    try:
        await asyncio.wait_for(loop.sock_connect(sock, (host, port)), timeout=timeout)
        duration_ms = round((time.time() - start_time) * 1000, 1)
        return True, duration_ms, f"Port {port} 通暢 ({duration_ms}ms)"
    except asyncio.TimeoutError:
        return False, None, f"Port {port} 連線逾時 (Timeout)"
    except ConnectionRefusedError:
        return False, None, f"Port {port} 連線被拒絕 (Refused)"
    except Exception as e:
        return False, None, f"Port {port} 異常: {str(e)}"
    finally:
        try:
            sock.close()
        except Exception:
            pass


from .snmp import probe_synology_snmp
from .ups_prober import probe_ups_status


async def check_device_health(device: dict) -> dict:
    """
    檢測單一設備健康狀態，支援 TCP/Ping 連線與 Synology SNMP / UPS 遙測指標採集
    """
    method = device.get("check_method", "ping")
    ip = device.get("ip_address", "").strip()
    port = device.get("check_port")
    device_type = device.get("device_type", "server")

    if not ip:
        return {
            "status": "offline",
            "latency_ms": None,
            "status_detail": "無效的 IP 位址",
            "snmp": None,
        }

    # 1. 執行基礎連線檢測
    if method == "tcp" and port:
        online, latency, detail = await tcp_ping(ip, int(port))
    elif method == "ping":
        online, latency, detail = await ping_host(ip)
    elif method == "agent":
        online, latency, detail = await ping_host(ip)
    elif method in ("web", "snmp"):
        online, latency, detail = await ping_host(ip)
    else:
        online, latency, detail = await ping_host(ip)

    # 2. 若為 NAS 設備或指定 SNMP，嘗試採集 SNMP 硬體數據 (CPU/RAM/Volume/Temp)
    snmp_data = None
    if device_type == "nas" or (device_type != "ups" and method == "snmp"):
        snmp_data = await probe_synology_snmp(ip)
        if snmp_data:
            online = True
            vol_str = ""
            if snmp_data.get("volumes"):
                v0 = snmp_data["volumes"][0]
                vol_str = f" · 儲存空間 {v0['percent']}% ({v0['used_tb']}T/{v0['total_tb']}T)"
            temp_str = f" · 溫度 {snmp_data['temp_c']}°C" if snmp_data.get("temp_c") is not None else ""
            detail = f"SNMP 正常{temp_str}{vol_str}"

    # 3. 若為 UPS 設備，採集電池電量、備援時間、負載率與溫度
    if device_type == "ups":
        ups_data = await probe_ups_status(ip, check_method=method)
        if ups_data:
            online = True
            snmp_data = ups_data
            min_str = f" · 備援 {ups_data['minutes_remaining']}分" if ups_data.get("minutes_remaining") is not None else ""
            load_str = f" · 負載 {ups_data['percent_load']}%" if ups_data.get("percent_load") is not None else ""
            temp_str = f" · {ups_data['temperature_c']}°C" if ups_data.get("temperature_c") is not None else ""
            detail = f"UPS 正常 · 電量 {ups_data['battery_percent']}%{min_str}{load_str}{temp_str}"
        elif online:
            detail = "網路通暢 (UPS 監控介面等待回應)"
        else:
            detail = "UPS 斷線無回應"

    status = "offline"
    if online:
        if latency is not None and latency > 150:
            status = "warning"
        else:
            status = "online"

    return {
        "status": status,
        "latency_ms": latency,
        "status_detail": detail,
        "snmp": snmp_data,
    }
