import asyncio
import socket
from typing import Any


def _encode_oid(oid_str: str) -> bytes:
    parts = [int(p) for p in oid_str.strip(".").split(".")]
    res = bytearray()
    res.append(parts[0] * 40 + parts[1])
    for p in parts[2:]:
        if p < 128:
            res.append(p)
        else:
            buf = []
            while p > 0:
                buf.append(p & 0x7F)
                p >>= 7
            buf.reverse()
            for i in range(len(buf) - 1):
                buf[i] |= 0x80
            res.extend(buf)
    return bytes(res)


def _decode_oid(data: bytes) -> str:
    if not data:
        return ""
    parts = [data[0] // 40, data[0] % 40]
    val = 0
    for b in data[1:]:
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            parts.append(val)
            val = 0
    return "." + ".".join(str(p) for p in parts)


def _encode_length(l: int) -> bytes:
    if l < 128:
        return bytes([l])
    elif l < 256:
        return bytes([0x81, l])
    else:
        return bytes([0x82, (l >> 8) & 0xFF, l & 0xFF])


def _decode_tlv(data: bytes, offset: int = 0) -> tuple[int, int, bytes, int]:
    tag = data[offset]
    offset += 1
    l = data[offset]
    offset += 1
    if l & 0x80:
        n = l & 0x7F
        l = 0
        for _ in range(n):
            l = (l << 8) | data[offset]
            offset += 1
    val = data[offset:offset + l]
    return tag, l, val, offset + l


def _snmp_request_sync(ip: str, community: str, oids: list[str], pdu_type: int = 0xA0, req_id: int = 1, timeout: float = 1.5) -> bytes | None:
    comm_bytes = community.encode("utf-8")
    vblist_inner = bytearray()
    for o in oids:
        eb = _encode_oid(o)
        vb = bytes([0x06]) + _encode_length(len(eb)) + eb + bytes([0x05, 0x00])
        vblist_inner.extend(bytes([0x30]) + _encode_length(len(vb)) + vb)

    vblist = bytes([0x30]) + _encode_length(len(vblist_inner)) + bytes(vblist_inner)

    pdu_inner = bytearray()
    pdu_inner.extend(bytes([0x02, 0x04, (req_id >> 24) & 0xFF, (req_id >> 16) & 0xFF, (req_id >> 8) & 0xFF, req_id & 0xFF]))
    pdu_inner.extend(bytes([0x02, 0x01, 0x00]))
    pdu_inner.extend(bytes([0x02, 0x01, 0x00]))
    pdu_inner.extend(vblist)

    pdu = bytes([pdu_type]) + _encode_length(len(pdu_inner)) + bytes(pdu_inner)

    msg_inner = bytearray()
    msg_inner.extend(bytes([0x02, 0x01, 0x01]))  # SNMPv2c
    msg_inner.extend(bytes([0x04]) + _encode_length(len(comm_bytes)) + comm_bytes)
    msg_inner.extend(pdu)

    packet = bytes([0x30]) + _encode_length(len(msg_inner)) + bytes(msg_inner)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(packet, (ip, 161))
        resp, _ = s.recvfrom(65535)
        return resp
    except Exception:
        return None
    finally:
        s.close()


def _parse_snmp_response(resp: bytes | None) -> list[tuple[str, int, Any]]:
    if not resp:
        return []
    results = []
    try:
        _, _, msg_val, _ = _decode_tlv(resp, 0)
        _, _, _, off = _decode_tlv(msg_val, 0)
        _, _, _, off = _decode_tlv(msg_val, off)
        _, _, pdu_val, _ = _decode_tlv(msg_val, off)
        _, _, _, off = _decode_tlv(pdu_val, 0)
        _, _, _, off = _decode_tlv(pdu_val, off)
        _, _, _, off = _decode_tlv(pdu_val, off)
        _, _, vb_val, _ = _decode_tlv(pdu_val, off)

        off = 0
        while off < len(vb_val):
            _, _, vb_entry, off = _decode_tlv(vb_val, off)
            e_off = 0
            _, _, oid_raw, e_off = _decode_tlv(vb_entry, e_off)
            tag_val, _, val_raw, _ = _decode_tlv(vb_entry, e_off)
            oid_str = _decode_oid(oid_raw)

            if tag_val in (0x02, 0x41, 0x42, 0x46):
                v = int.from_bytes(val_raw, byteorder="big", signed=(tag_val == 0x02))
            elif tag_val == 0x04:
                try:
                    v = val_raw.decode("utf-8")
                except Exception:
                    v = val_raw.hex()
            elif tag_val == 0x06:
                v = _decode_oid(val_raw)
            else:
                v = val_raw.hex()
            results.append((oid_str, tag_val, v))
    except Exception:
        pass
    return results


def _snmp_walk_sync(ip: str, community: str, base_oid: str, max_steps: int = 40, timeout: float = 1.0) -> list[tuple[str, int, Any]]:
    cur_oid = base_oid
    results = []
    target_prefix = base_oid if base_oid.startswith(".") else "." + base_oid
    for _ in range(max_steps):
        raw = _snmp_request_sync(ip, community, [cur_oid], pdu_type=0xA1, timeout=timeout)
        items = _parse_snmp_response(raw)
        if not items:
            break
        oid, tag, val = items[0]
        if not oid.startswith(target_prefix):
            break
        results.append((oid, tag, val))
        cur_oid = oid.lstrip(".")
    return results


def _probe_synology_sync(ip: str, communities: list[str]) -> dict | None:
    matched_comm = None
    for comm in communities:
        raw_test = _snmp_request_sync(ip, comm, ["1.3.6.1.2.1.1.1.0"], timeout=1.0)
        res = _parse_snmp_response(raw_test)
        if res:
            matched_comm = comm
            break

    if not matched_comm:
        return None

    # 1. 採集 CPU 與 實體記憶體
    # 1.3.6.1.4.1.2021.11.11.0: ssCpuIdle
    # 1.3.6.1.4.1.2021.4.5.0: memTotalReal (KB)
    # 1.3.6.1.4.1.2021.4.6.0: memAvailReal (KB)
    # 1.3.6.1.4.1.6574.1.2.0: Synology Temperature (°C)
    raw_status = _snmp_request_sync(
        ip,
        matched_comm,
        [
            "1.3.6.1.4.1.2021.11.11.0",
            "1.3.6.1.4.1.2021.4.5.0",
            "1.3.6.1.4.1.2021.4.6.0",
            "1.3.6.1.4.1.6574.1.2.0",
        ],
        timeout=1.5,
    )
    status_items = _parse_snmp_response(raw_status)
    status_map = {item[0].lstrip("."): item[2] for item in status_items}

    cpu_idle = status_map.get("1.3.6.1.4.1.2021.11.11.0", 100)
    cpu_percent = round(max(0.0, min(100.0, 100.0 - float(cpu_idle))), 1)

    mem_tot_kb = status_map.get("1.3.6.1.4.1.2021.4.5.0", 0)
    mem_avail_kb = status_map.get("1.3.6.1.4.1.2021.4.6.0", 0)
    if mem_tot_kb > 0:
        mem_used_kb = max(0, mem_tot_kb - mem_avail_kb)
        mem_percent = round(mem_used_kb / mem_tot_kb * 100.0, 1)
        mem_used_gb = round(mem_used_kb / (1024 * 1024), 2)
        mem_tot_gb = round(mem_tot_kb / (1024 * 1024), 2)
    else:
        mem_percent = 0.0
        mem_used_gb = 0.0
        mem_tot_gb = 0.0

    temp_c = status_map.get("1.3.6.1.4.1.6574.1.2.0", None)

    # 2. 採集儲存空間 (Volumes)
    descrs = _snmp_walk_sync(ip, matched_comm, "1.3.6.1.2.1.25.2.3.1.3", max_steps=25, timeout=1.0)
    units = _snmp_walk_sync(ip, matched_comm, "1.3.6.1.2.1.25.2.3.1.4", max_steps=25, timeout=1.0)
    sizes = _snmp_walk_sync(ip, matched_comm, "1.3.6.1.2.1.25.2.3.1.5", max_steps=25, timeout=1.0)
    useds = _snmp_walk_sync(ip, matched_comm, "1.3.6.1.2.1.25.2.3.1.6", max_steps=25, timeout=1.0)

    units_map = {u[0].split(".")[-1]: u[2] for u in units}
    sizes_map = {s[0].split(".")[-1]: s[2] for s in sizes}
    useds_map = {u[0].split(".")[-1]: u[2] for u in useds}

    volumes = []
    for d in descrs:
        idx = d[0].split(".")[-1]
        name = str(d[2])
        if name.startswith("/volume") and "@" not in name:
            unit = units_map.get(idx, 4096)
            size_blocks = sizes_map.get(idx, 0)
            used_blocks = useds_map.get(idx, 0)
            if size_blocks > 0:
                tot_tb = round(size_blocks * unit / (1024**4), 2)
                used_tb = round(used_blocks * unit / (1024**4), 2)
                pct = round(used_blocks / size_blocks * 100.0, 1)
                volumes.append({
                    "mount": name,
                    "total_tb": tot_tb,
                    "used_tb": used_tb,
                    "percent": pct,
                })

    return {
        "community": matched_comm,
        "cpu_percent": cpu_percent,
        "memory_percent": mem_percent,
        "memory_used_gb": mem_used_gb,
        "memory_total_gb": mem_tot_gb,
        "temp_c": temp_c,
        "volumes": volumes,
    }


async def probe_synology_snmp(ip: str, custom_community: str | None = None) -> dict | None:
    from .config import settings
    communities = []
    # 1. 優先採用設備備註或自訂之社群名稱
    if custom_community and custom_community.strip():
        # 若備註含有 snmp=xxx 格式則解析，否則若純字串亦可使用
        comm_val = custom_community.strip()
        for part in comm_val.split():
            if part.lower().startswith("snmp="):
                comm_val = part.split("=", 1)[1].strip()
                break
        if comm_val:
            communities.append(comm_val)

    # 2. 其次採用 .env 設定之預設社群名稱
    if settings.snmp_community and settings.snmp_community not in communities:
        communities.append(settings.snmp_community.strip())

    # 3. 備援標準 public
    if "public" not in communities:
        communities.append("public")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _probe_synology_sync, ip, communities)
