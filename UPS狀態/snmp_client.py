import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from puresnmp import Auth, Client, Priv, PyWrapper, V3


CONFIG_PATH = Path(__file__).with_name("config.json")

# Standard UPS-MIB (RFC 1628) OIDs
OID_MAP = {
    "ident_manufacturer": "1.3.6.1.2.1.33.1.1.1.0",
    "ident_model": "1.3.6.1.2.1.33.1.1.2.0",
    "ident_ups_software_version": "1.3.6.1.2.1.33.1.1.3.0",
    "ident_agent_software_version": "1.3.6.1.2.1.33.1.1.4.0",
    "ident_name": "1.3.6.1.2.1.33.1.1.5.0",
    "battery_status": "1.3.6.1.2.1.33.1.2.1.0",
    "battery_seconds_on_battery": "1.3.6.1.2.1.33.1.2.2.0",
    "battery_estimated_minutes_remaining": "1.3.6.1.2.1.33.1.2.3.0",
    "battery_estimated_charge_remaining": "1.3.6.1.2.1.33.1.2.4.0",
    "battery_voltage": "1.3.6.1.2.1.33.1.2.5.0",
    "battery_temperature": "1.3.6.1.2.1.33.1.2.7.0",
    "input_line_bads": "1.3.6.1.2.1.33.1.3.1.0",
    "input_num_lines": "1.3.6.1.2.1.33.1.3.2.0",
    "input_frequency_1": "1.3.6.1.2.1.33.1.3.3.1.2.1",
    "input_voltage_1": "1.3.6.1.2.1.33.1.3.3.1.3.1",
    "input_current_1": "1.3.6.1.2.1.33.1.3.3.1.4.1",
    "input_true_power_1": "1.3.6.1.2.1.33.1.3.3.1.5.1",
    "output_source": "1.3.6.1.2.1.33.1.4.1.0",
    "output_frequency_1": "1.3.6.1.2.1.33.1.4.4.1.2.1",
    "output_num_lines": "1.3.6.1.2.1.33.1.4.3.0",
    "output_voltage_1": "1.3.6.1.2.1.33.1.4.4.1.2.1",  # some devices; corrected below via table logic
    "output_current_1": "1.3.6.1.2.1.33.1.4.4.1.3.1",
    "output_power_1": "1.3.6.1.2.1.33.1.4.4.1.4.1",
    "output_percent_load_1": "1.3.6.1.2.1.33.1.4.4.1.5.1",
    "bypass_frequency_1": "1.3.6.1.2.1.33.1.5.3.1.2.1",
    "bypass_num_lines": "1.3.6.1.2.1.33.1.5.2.0",
    "bypass_voltage_1": "1.3.6.1.2.1.33.1.5.3.1.3.1",
    "alarms_present": "1.3.6.1.2.1.33.1.6.1.0",
}

# Correct output table OIDs (RFC1628): upsOutputVoltage/frequency/current/power/percentLoad
OID_MAP.update(
    {
        "output_frequency_1": "1.3.6.1.2.1.33.1.4.4.1.2.1",
        "output_voltage_1": "1.3.6.1.2.1.33.1.4.4.1.3.1",
        "output_current_1": "1.3.6.1.2.1.33.1.4.4.1.4.1",
        "output_power_1": "1.3.6.1.2.1.33.1.4.4.1.5.1",
        "output_percent_load_1": "1.3.6.1.2.1.33.1.4.4.1.6.1",
    }
)

BATTERY_STATUS = {
    1: "unknown",
    2: "normal",
    3: "low",
    4: "depleted",
}

OUTPUT_SOURCE = {
    1: "other",
    2: "none",
    3: "normal",
    4: "bypass",
    5: "battery",
    6: "booster",
    7: "reducer",
}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    cfg_path = path or CONFIG_PATH
    defaults = {
        "host": "192.168.0.7",
        "port": 161,
        "version": "v3",
        "username": "",
        "auth_password": "",
        "priv_password": "",
        "auth_protocol": "sha1",
        "priv_protocol": "aes",
        "timeout": 2,
        "retries": 1,
    }
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                defaults.update(data)
            else:
                raise ValueError(f"UPS configuration must be a JSON object: {cfg_path}")
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read UPS configuration {cfg_path}: {error}") from error
    for field, env_name in (
        ("username", "SNMP_V3_USERNAME"),
        ("auth_password", "SNMP_V3_AUTH_PASSWORD"),
        ("priv_password", "SNMP_V3_PRIV_PASSWORD"),
        ("auth_protocol", "SNMP_V3_AUTH_PROTOCOL"),
        ("priv_protocol", "SNMP_V3_PRIV_PROTOCOL"),
    ):
        if os.getenv(env_name):
            defaults[field] = os.environ[env_name]
    return defaults


def _make_client(config: Dict[str, Any]):
    host = str(config.get("host", "127.0.0.1"))
    port = int(config.get("port", 161))
    version = str(config.get("version", "v2c")).lower()
    if version != "v3":
        raise ValueError("SNMPv1/v2c is disabled; configure SNMPv3 authPriv")

    username = str(config.get("username", "")).strip()
    auth_password = str(config.get("auth_password", ""))
    priv_password = str(config.get("priv_password", ""))
    auth_protocol = str(config.get("auth_protocol", "sha1")).lower()
    priv_protocol = str(config.get("priv_protocol", "aes")).lower()
    if not username or len(auth_password) < 8 or len(priv_password) < 8:
        raise ValueError("SNMPv3 username and authPriv passphrases of at least 8 characters are required")
    if auth_protocol != "sha1" or priv_protocol != "aes":
        raise ValueError("Only SNMPv3 SHA-1 authentication with AES privacy is enabled")
    timeout = int(config.get("timeout", 2))
    retries = int(config.get("retries", 1))
    if not 1 <= timeout <= 30 or not 0 <= retries <= 5:
        raise ValueError("SNMP timeout must be 1-30 seconds and retries must be 0-5")

    credentials = V3(
        username,
        auth=Auth(auth_password.encode("utf-8"), auth_protocol),
        priv=Priv(priv_password.encode("utf-8"), priv_protocol),
    )
    client = Client(host, credentials, port=port)
    client.configure(timeout=timeout, retries=retries)
    return PyWrapper(client)


def _to_plain(value: Any) -> Any:
    if value is None:
        return None
    # bytes -> try decode, else hex
    if isinstance(value, (bytes, bytearray)):
        try:
            s = value.decode("utf-8").strip()
            if s:
                return s
        except Exception:
            pass
        return value.hex()
    # puresnmp/x690 types often have .value or string repr
    if hasattr(value, "value"):
        try:
            return _to_plain(value.value)
        except Exception:
            pass
    # ints/bools/strings/floats pass through
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.lstrip("-").isdigit():
            try:
                return int(s)
            except Exception:
                pass
        return s
    # fallback to string, try numeric
    try:
        s = str(value).strip()
        if s.lstrip("-").isdigit():
            return int(s)
        return s
    except Exception:
        return value


def _oid_str(oid: Any) -> str:
    try:
        s = str(oid)
        return s.lstrip(".")
    except Exception:
        return str(oid)


async def _snmp_get_async(oids: List[str], config: Dict[str, Any]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    if not oids:
        return results
    client = _make_client(config)
    try:
        values = await client.multiget(oids)
        return {_oid_str(oid): _to_plain(value) for oid, value in zip(oids, values)}
    except Exception as e:
        for oid in oids:
            try:
                results[_oid_str(oid)] = _to_plain(await client.get(oid))
            except Exception:
                continue
        if not results:
            raise e
    return results


def snmp_get(oids: List[str], config: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        return asyncio.run(_snmp_get_async(oids, config)), None
    except Exception as error:
        return {}, str(error)


async def _snmp_walk_async(base_oid: str, config: Dict[str, Any], max_rows: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    client = _make_client(config)
    async for item in client.bulkwalk([base_oid]):
        rows.append({"oid": _oid_str(item.oid), "value": _to_plain(item.value)})
        if len(rows) >= max_rows:
            break
    return rows


def snmp_walk(base_oid: str, config: Dict[str, Any], max_rows: int = 300) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        return asyncio.run(_snmp_walk_async(base_oid, config, max_rows)), None
    except Exception as error:
        return [], str(error)


def _lookup_by_oid(fetched: Dict[str, Any], oid: str) -> Any:
    # Exact match first
    if oid in fetched:
        return fetched[oid]
    # Fallback: prefix/normalize match
    for k, v in fetched.items():
        if k == oid or k.startswith(oid):
            return v
    return None


def _scale_tenths(value: Any) -> Any:
    if isinstance(value, int):
        return value / 10.0
    return value


def fetch_ups_data(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = config or load_config()
    version = str(cfg.get("version", "v2c")).lower()
    if version != "v3":
        return {
            "ok": False,
            "error": "SNMPv1/v2c is disabled; configure SNMPv3 authPriv.",
            "config": {k: v for k, v in cfg.items() if "pass" not in k.lower() and "community" not in k.lower()},
            "data": {},
            "raw": {},
        }

    oids = list(dict.fromkeys(OID_MAP.values()))
    fetched, err = snmp_get(oids, cfg)
    raw_walk, walk_err = snmp_walk("1.3.6.1.2.1.33", cfg, max_rows=400)

    # Merge walk results so table indexes other than .1 can still be found
    for row in raw_walk:
        fetched.setdefault(row["oid"], row["value"])

    def get(key: str) -> Any:
        return _lookup_by_oid(fetched, OID_MAP[key])

    battery_status_val = get("battery_status")
    output_source_val = get("output_source")

    data = {
        "identity": {
            "manufacturer": get("ident_manufacturer"),
            "model": get("ident_model"),
            "name": get("ident_name"),
            "ups_software_version": get("ident_ups_software_version"),
            "agent_software_version": get("ident_agent_software_version"),
        },
        "battery": {
            "status_code": battery_status_val,
            "status": BATTERY_STATUS.get(battery_status_val, str(battery_status_val) if battery_status_val is not None else None),
            "charge_percent": get("battery_estimated_charge_remaining"),
            "minutes_remaining": get("battery_estimated_minutes_remaining"),
            "voltage_0_1vdc": get("battery_voltage"),
            "temperature_c": get("battery_temperature"),
            "seconds_on_battery": get("battery_seconds_on_battery"),
        },
        "input": {
            "num_lines": get("input_num_lines"),
            "voltage_v": get("input_voltage_1"),
            "frequency_hz": _scale_tenths(get("input_frequency_1")),
            "current_0_1a": get("input_current_1"),
            "line_bads": get("input_line_bads"),
        },
        "output": {
            "source_code": output_source_val,
            "source": OUTPUT_SOURCE.get(output_source_val, str(output_source_val) if output_source_val is not None else None),
            "num_lines": get("output_num_lines"),
            "voltage_v": get("output_voltage_1"),
            "frequency_hz": _scale_tenths(get("output_frequency_1")),
            "current_0_1a": get("output_current_1"),
            "power_w": get("output_power_1"),
            "percent_load": get("output_percent_load_1"),
        },
        "bypass": {
            "num_lines": get("bypass_num_lines"),
            "voltage_v": get("bypass_voltage_1"),
            "frequency_hz": _scale_tenths(get("bypass_frequency_1")),
        },
        "alarms_present": get("alarms_present"),
    }

    ok = err is None and (len(fetched) > 0 or len(raw_walk) > 0)
    error_msg = err or walk_err
    if not ok and not error_msg:
        error_msg = "未取得任何 SNMP 資料，請確認 IP/Community/版本與網路連線。"

    safe_cfg = dict(cfg)
    for key in list(safe_cfg):
        if "password" in key.lower() or "community" in key.lower():
            safe_cfg.pop(key)

    return {
        "ok": ok,
        "error": error_msg if not ok or (error_msg and len(fetched) == 0) else None,
        "warning": walk_err if err is None and walk_err else None,
        "config": safe_cfg,
        "data": data,
        "raw_count": len(raw_walk),
        "raw": raw_walk,
    }
