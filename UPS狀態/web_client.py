import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


UPS_TYPE_MAP = {
    0: "On-line",
    1: "Off-line",
    2: "Line-Interactive",
    3: "3-Phase",
    4: "Split-Phase",
}

UPS_COMM_MAP = {
    0: "Normal",
    1: "Warning",
    2: "Warning",
    3: "Critical",
}

UPS_SOURCE_MAP = {
    0: "Normal",
    1: "Battery",
    2: "Bypass/Reserve",
    3: "Reducing",
    4: "Boosting",
    5: "Manual Bypass",
    6: "Other",
    7: "No output",
    8: "On ECO",
}

BATT_STATUS_MAP = {
    0: "Normal",
    1: "Weak",
    2: "Low",
    3: "Depleted",
    4: "Replace",
}

BATT_CHARGE_STATUS_MAP = {
    0: "Charging",
    1: "Resting",
    2: "Discharging",
}


def _build_base_url(config: Dict[str, Any]) -> str:
    ups_url = str(config.get("ups_url") or "").strip()
    if ups_url:
        parsed = urlparse(ups_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    host = str(config.get("host") or "192.168.0.7").strip()
    scheme = str(config.get("web_scheme") or "https").strip()
    return f"{scheme}://{host}"


def _make_ssl_context(verify_ssl: bool) -> ssl.SSLContext:
    if verify_ssl:
        return ssl.create_default_context()
    ctx = ssl._create_unverified_context()
    return ctx


def _fetch_xml(url: str, timeout: float = 5.0, verify_ssl: bool = False) -> Tuple[Optional[ET.Element], Optional[str]]:
    ts = int(time.time() * 1000)
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}_t={ts}"
    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "UPS-Dashboard/1.0",
            "Accept": "application/xml, text/xml, */*",
            "Cache-Control": "no-cache",
        },
    )
    ctx = _make_ssl_context(verify_ssl) if full_url.lower().startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
        if not raw:
            return None, f"Empty XML response from {url}"
        root = ET.fromstring(raw)
        return root, None
    except urllib.error.URLError as e:
        return None, f"無法連線至 {url}: {e.reason if hasattr(e, 'reason') else e}"
    except ET.ParseError as e:
        return None, f"XML 解析失敗 ({url}): {e}"
    except Exception as e:
        return None, f"讀取失敗 ({url}): {e}"


def _parse_number(val: Optional[str]) -> Any:
    if val is None:
        return None
    s = val.strip()
    if not s or s == "-":
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _parse_text(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = val.strip()
    return s if s else None


def _get_value(parent: Optional[ET.Element], value_id: str, index: int = 0) -> Optional[str]:
    if parent is None:
        return None
    matches = parent.findall(f"Value[@id='{value_id}']")
    if len(matches) > index and matches[index].text is not None:
        return matches[index].text.strip()
    return None


def _collect_raw_items(root: Optional[ET.Element], source_name: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if root is None:
        return items
    for section in root:
        if len(section) == 0:
            val = _parse_text(section.text)
            if val is not None:
                items.append({"key": f"{source_name}.{section.tag}", "value": val})
        else:
            for child in section:
                if child.tag == "Value":
                    vid = child.attrib.get("id", "unknown")
                    items.append({"key": f"{source_name}.{section.tag}.{vid}", "value": _parse_text(child.text) or "-"})
                elif len(child) == 0 and child.tag != "Class":
                    val = _parse_text(child.text)
                    if val is not None:
                        items.append({"key": f"{source_name}.{section.tag}.{child.tag}", "value": val})
    return items


def fetch_ups_web_data(config: Dict[str, Any]) -> Dict[str, Any]:
    base_url = _build_base_url(config)
    timeout = float(config.get("web_timeout", config.get("timeout", 5)))
    verify_ssl = bool(config.get("verify_ssl", False))

    index_url = f"{base_url}/webpages/xml/ups/index_ups.xml"
    battery_url = f"{base_url}/webpages/xml/ups/info_battery.xml"

    index_root, index_err = _fetch_xml(index_url, timeout=timeout, verify_ssl=verify_ssl)
    batt_root, batt_err = _fetch_xml(battery_url, timeout=timeout, verify_ssl=verify_ssl)

    if index_root is None and batt_root is None:
        return {
            "ok": False,
            "source": "web",
            "source_url": config.get("ups_url") or f"{base_url}/webpages/home.html",
            "xml_urls": [index_url, battery_url],
            "error": index_err or batt_err or "無法從 UPS 網頁抓取資料",
            "warning": None,
            "data": {},
            "raw_count": 0,
            "raw": [],
        }

    # Parse index_ups.xml
    inp_el = index_root.find("input") if index_root is not None else None
    status_el = index_root.find("status") if index_root is not None else None
    out_el = index_root.find("output") if index_root is not None else None
    sche_el = index_root.find("schedule") if index_root is not None else None
    idx_batt_el = index_root.find("batt") if index_root is not None else None
    cd_el = index_root.find("countDown") if index_root is not None else None

    # Parse info_battery.xml
    det_batt_el = batt_root.find("batt") if batt_root is not None else None

    ups_type_code = _parse_number(_get_value(status_el, "Type"))
    comm_code = _parse_number(_get_value(status_el, "Comm"))
    source_code = _parse_number(_get_value(status_el, "Source", 0))

    batt_status_code = _parse_number(
        _get_value(idx_batt_el, "battStatus") or _get_value(det_batt_el, "battStatus")
    )
    batt_capacity = _parse_number(
        _get_value(idx_batt_el, "battCapacity") or _get_value(det_batt_el, "battCapacity")
    )
    batt_charge_code = _parse_number(_get_value(det_batt_el, "battStatusCharge"))

    product_name = _parse_text(index_root.findtext("LIN_PRODUCT_NAME") if index_root is not None else None)

    data = {
        "identity": {
            "manufacturer": "Delta",
            "model": _parse_text(_get_value(status_el, "Model")),
            "name": product_name or "InsightPower G3 Mini SNMP Card",
            "type": UPS_TYPE_MAP.get(ups_type_code, str(ups_type_code) if ups_type_code is not None else None),
            "rating_kva": _parse_number(_get_value(status_el, "Rating")),
            "comm_status": UPS_COMM_MAP.get(comm_code, str(comm_code) if comm_code is not None else None),
        },
        "battery": {
            "status_code": batt_status_code,
            "status": BATT_STATUS_MAP.get(batt_status_code, str(batt_status_code) if batt_status_code is not None else None),
            "charge_status_code": batt_charge_code,
            "charge_status": BATT_CHARGE_STATUS_MAP.get(batt_charge_code, str(batt_charge_code) if batt_charge_code is not None else None),
            "charge_percent": batt_capacity,
            "capacity_percent": batt_capacity,
            "minutes_remaining": _parse_number(_get_value(det_batt_el, "battRemainingTime")),
            "voltage_v": _parse_number(_get_value(det_batt_el, "battVolt")),
            "current_a": _parse_number(_get_value(det_batt_el, "battCurr")),
            "temperature_c": _parse_number(_get_value(det_batt_el, "battTemp")),
            "seconds_on_battery": _parse_number(_get_value(det_batt_el, "onBattTime")),
            "replace_date_last": _parse_text(_get_value(det_batt_el, "replaceDateLast")),
            "replace_date_next": _parse_text(_get_value(det_batt_el, "replaceDateNext")),
        },
        "input": {
            "num_lines": _parse_number(inp_el.findtext("inputPhases") if inp_el is not None else None),
            "voltage_v": _parse_number(_get_value(inp_el, "inVolt")),
            "frequency_hz": _parse_number(_get_value(inp_el, "inFreq")),
        },
        "output": {
            "source_code": source_code,
            "source": UPS_SOURCE_MAP.get(source_code, str(source_code) if source_code is not None else None),
            "num_lines": _parse_number(out_el.findtext("outputPhases") if out_el is not None else None),
            "voltage_v": _parse_number(_get_value(out_el, "outVolt")),
            "frequency_hz": _parse_number(_get_value(out_el, "outFreq")),
            "percent_load": _parse_number(_get_value(out_el, "outLoad")),
        },
        "schedule": {
            "next_power_off": _parse_text(_get_value(sche_el, "NextPowerOff")) or "None",
            "next_power_on": _parse_text(_get_value(sche_el, "NextPowerOn")) or "None",
            "next_test": _parse_text(_get_value(sche_el, "NextTest")) or "None",
            "next_deep_batt_test": _parse_text(_get_value(sche_el, "NextDeepBattTest")) or "None",
        },
        "countdown": {
            "time_to_power_off": _parse_text(_get_value(cd_el, "time2PowerOff")) or "--:--",
            "estimated_os_delay": _parse_text(_get_value(cd_el, "estimatedOsDelay")) or "--:--",
        },
    }

    raw_items = _collect_raw_items(index_root, "index_ups") + _collect_raw_items(batt_root, "info_battery")
    warning = batt_err if index_root is not None and batt_err else (index_err if batt_root is not None and index_err else None)

    return {
        "ok": True,
        "source": "web",
        "source_url": config.get("ups_url") or f"{base_url}/webpages/home.html",
        "xml_urls": [index_url, battery_url],
        "error": None,
        "warning": warning,
        "data": data,
        "raw_count": len(raw_items),
        "raw": raw_items,
    }
