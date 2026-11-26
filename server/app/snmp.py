import asyncio
import logging
from typing import Any

from puresnmp import Auth, Client, Priv, PyWrapper, V3

from .config import settings

logger = logging.getLogger(__name__)

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
CPU_IDLE = "1.3.6.1.4.1.2021.11.11.0"
MEM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"
MEM_AVAIL = "1.3.6.1.4.1.2021.4.6.0"
SYNOLOGY_TEMP = "1.3.6.1.4.1.6574.1.2.0"
STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
STORAGE_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"


def create_snmpv3_credentials(
    username: str,
    auth_password: str,
    priv_password: str,
    auth_protocol: str = "sha1",
    priv_protocol: str = "aes",
) -> V3:
    if not username.strip() or len(auth_password) < 8 or len(priv_password) < 8:
        raise ValueError("SNMPv3 authPriv requires a username and passphrases of at least 8 characters")
    if auth_protocol.lower() != "sha1" or priv_protocol.lower() != "aes":
        raise ValueError("Only SNMPv3 SHA-1 authentication with AES privacy is enabled")
    return V3(
        username.strip(),
        auth=Auth(auth_password.encode("utf-8"), "sha1"),
        priv=Priv(priv_password.encode("utf-8"), "aes"),
    )


def _client(ip: str) -> PyWrapper:
    credentials = create_snmpv3_credentials(
        settings.snmp_v3_username,
        settings.snmp_v3_auth_password.get_secret_value(),
        settings.snmp_v3_priv_password.get_secret_value(),
        settings.snmp_v3_auth_protocol,
        settings.snmp_v3_priv_protocol,
    )
    client = Client(ip, credentials)
    client.configure(
        timeout=settings.snmp_timeout_seconds,
        retries=settings.snmp_retries,
    )
    return PyWrapper(client)


def _plain(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError:
            return value.hex()
    return value


async def _get(client: PyWrapper, oid: str) -> Any:
    try:
        return _plain(await client.get(oid))
    except Exception:
        return None


async def _walk(client: PyWrapper, base_oid: str, max_steps: int = 40) -> list[tuple[str, Any]]:
    result = []
    prefix = base_oid.lstrip(".")
    async for item in client.bulkwalk([base_oid]):
        oid = item.oid.lstrip(".")
        if not oid.startswith(prefix):
            break
        result.append((oid, _plain(item.value)))
        if len(result) >= max_steps:
            break
    return result


async def _probe_synology(ip: str) -> dict | None:
    client = _client(ip)
    if await _get(client, SYS_DESCR) is None:
        return None

    cpu_idle, mem_total, mem_avail, temp_c = await asyncio.gather(
        _get(client, CPU_IDLE),
        _get(client, MEM_TOTAL),
        _get(client, MEM_AVAIL),
        _get(client, SYNOLOGY_TEMP),
    )
    cpu_percent = round(max(0.0, min(100.0, 100.0 - float(cpu_idle or 100))), 1)

    total_kb = int(mem_total or 0)
    available_kb = int(mem_avail or 0)
    used_kb = max(0, total_kb - available_kb)
    memory_percent = round(used_kb / total_kb * 100.0, 1) if total_kb else 0.0

    descrs, units, sizes, useds = await asyncio.gather(
        _walk(client, STORAGE_DESCR, max_steps=100),
        _walk(client, STORAGE_UNITS, max_steps=100),
        _walk(client, STORAGE_SIZE, max_steps=100),
        _walk(client, STORAGE_USED, max_steps=100),
    )
    units_map = {oid.split(".")[-1]: value for oid, value in units}
    sizes_map = {oid.split(".")[-1]: value for oid, value in sizes}
    useds_map = {oid.split(".")[-1]: value for oid, value in useds}
    volumes = []
    for oid, value in descrs:
        name = str(value)
        if not name.startswith("/volume") or "@" in name:
            continue
        index = oid.split(".")[-1]
        unit = int(units_map.get(index, 4096) or 4096)
        size = int(sizes_map.get(index, 0) or 0)
        used = int(useds_map.get(index, 0) or 0)
        if size:
            volumes.append(
                {
                    "mount": name,
                    "total_tb": round(size * unit / (1024**4), 2),
                    "used_tb": round(used * unit / (1024**4), 2),
                    "percent": round(used / size * 100.0, 1),
                }
            )

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_gb": round(used_kb / (1024 * 1024), 2),
        "memory_total_gb": round(total_kb / (1024 * 1024), 2),
        "temp_c": temp_c,
        "volumes": volumes,
    }


def _probe_synology_sync(ip: str) -> dict | None:
    return asyncio.run(_probe_synology(ip))


async def probe_synology_snmp(ip: str) -> dict | None:
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _probe_synology_sync, ip)
    except ValueError as error:
        logger.warning("SNMPv3 credentials are not configured: %s", error)
        return None
    except Exception as error:
        logger.warning("SNMPv3 probe failed for %s (%s)", ip, type(error).__name__)
        return None
