import asyncio
import ipaddress
import logging
from typing import Any, Dict, Optional

from UPS狀態.web_client import fetch_ups_web_data
from UPS狀態.snmp_client import fetch_ups_data as fetch_ups_snmp_data

from .config import settings

logger = logging.getLogger("ups_prober")


def is_safe_private_ip(ip_str: str) -> bool:
    """防範 SSRF：限制 UPS 探測僅限內部私有區域網路或本地迴路"""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


async def probe_ups_status(ip: str, check_method: str = "web") -> Optional[Dict[str, Any]]:
    """
    非同步調用 UPS 遙測 (Web XML 或 SNMP)
    嚴格限制僅探測合法之私有網路 IP，防範 SSRF 與外網偽冒探測
    """
    clean_ip = ip.strip()
    if not is_safe_private_ip(clean_ip):
        logger.warning(f"拒絕探測非私有區域網路之 UPS 目標: {clean_ip}")
        return None

    cfg = {
        "host": clean_ip,
        "ups_url": f"https://{clean_ip}/webpages/home.html",
        "verify_ssl": True,
        "ca_cert_path": settings.ups_ssl_ca_path or None,
        "web_timeout": 4.0,
        "timeout": 3,
        "version": "v3",
        "username": settings.snmp_v3_username,
        "auth_password": settings.snmp_v3_auth_password.get_secret_value(),
        "priv_password": settings.snmp_v3_priv_password.get_secret_value(),
        "auth_protocol": settings.snmp_v3_auth_protocol,
        "priv_protocol": settings.snmp_v3_priv_protocol,
    }

    loop = asyncio.get_running_loop()

    def _sync_fetch():
        if check_method == "snmp":
            return fetch_ups_snmp_data(cfg)
        return fetch_ups_web_data(cfg)

    try:
        res = await loop.run_in_executor(None, _sync_fetch)
        if not res or not res.get("ok"):
            return None

        data = res.get("data", {})
        battery = data.get("battery", {})
        output = data.get("output", {})
        input_data = data.get("input", {})
        identity = data.get("identity", {})

        capacity = battery.get("capacity_percent")
        if capacity is None:
            capacity = battery.get("charge_percent", 100)

        return {
            "model": identity.get("model", "Delta UPS"),
            "manufacturer": identity.get("manufacturer", "Delta"),
            "ups_type": identity.get("type", "On-line"),
            "comm_status": identity.get("comm_status", "Normal"),
            "battery_percent": capacity,
            "battery_status": battery.get("status", "Normal"),
            "charge_status": battery.get("charge_status", "Resting"),
            "minutes_remaining": battery.get("minutes_remaining"),
            "battery_voltage": battery.get("voltage_v"),
            "temperature_c": battery.get("temperature_c"),
            "input_voltage": input_data.get("voltage_v"),
            "input_freq": input_data.get("frequency_hz"),
            "output_voltage": output.get("voltage_v"),
            "output_freq": output.get("frequency_hz"),
            "percent_load": output.get("percent_load", 0),
            "output_source": output.get("source", "Normal"),
            "raw_time": res.get("timestamp"),
        }
    except Exception as e:
        logger.error(f"Error probing UPS {ip}: {e}")
        return None
