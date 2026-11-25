import hmac
import time
from collections import defaultdict
from urllib.parse import urlparse
from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .config import settings
from .database import Database
from .models import DeviceCreate, DeviceUpdate, MetricsPayload
from .notifier import broadcast, connections
from .prober import check_device_health

router = APIRouter()
database = Database()

# 遙測上報頻率限制 (Rate Limiting) 防止 DoS 與資料庫寫入耗盡
_metrics_timestamps: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 1.0  # 1 秒滑動窗口
MAX_REQ_PER_WINDOW = 3   # 限制單一主機每秒最多允許 3 次上報 (正常 agent 為 5 秒 1 次)


def is_trusted_websocket_origin(origin: str | None, host_header: str | None) -> bool:
    """校驗 WebSocket 來源 Origin，阻斷跨站 WebSocket 劫持 (CSWSH)"""
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
        origin_host = (parsed.hostname or "").lower()
        if origin_host in ("localhost", "127.0.0.1", "192.168.0.100", settings.host.lower()):
            return True
        if host_header:
            req_host = host_header.split(":")[0].lower()
            if origin_host == req_host:
                return True
        # 允許常見區域網路私有網段
        if origin_host.startswith("192.168.") or origin_host.startswith("10."):
            return True
        return False
    except Exception:
        return False


def verify_admin_auth(x_admin_key: str | None = Header(default=None)):
    """驗證管理權限（防止時序攻擊與未授權寫入）"""
    expected = settings.effective_admin_key
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(
            status_code=401,
            detail="需要管理者授權 (Invalid or Missing X-Admin-Key)",
            headers={"WWW-Authenticate": "ApiKey"},
        )


@router.post("/api/metrics")
async def ingest_metrics(
    payload: MetricsPayload,
    x_api_key: str | None = Header(default=None),
):
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 頻率限制防護 (Rate Limiter)
    now_ts = time.time()
    client_id = f"{payload.hostname}:{payload.ip_address}"
    timestamps = _metrics_timestamps[client_id]
    _metrics_timestamps[client_id] = [t for t in timestamps if now_ts - t < RATE_LIMIT_WINDOW]
    if len(_metrics_timestamps[client_id]) >= MAX_REQ_PER_WINDOW:
        raise HTTPException(status_code=429, detail="上報頻率過高 (Rate limit exceeded)")
    _metrics_timestamps[client_id].append(now_ts)

    data = await database.save(payload)
    await broadcast({"type": "metric", "data": data})
    return JSONResponse({"ok": True})


@router.get("/api/servers")
async def list_servers():
    return await database.list_servers()


@router.get("/api/history/{hostname}")
async def server_history(hostname: str, hours: int = 24):
    if hours < 1 or hours > 168:
        raise HTTPException(status_code=400, detail="hours must be between 1 and 168")
    return await database.history(hostname, hours)


# === 設備管理相關 API (Server / NAS / 防火牆) ===


@router.get("/api/devices")
async def list_devices():
    return await database.list_devices()


@router.post("/api/devices")
async def create_device(payload: DeviceCreate, x_admin_key: str | None = Header(default=None)):
    verify_admin_auth(x_admin_key)
    new_device = await database.create_device(payload.model_dump())
    # 立即觸發一次檢測
    res = await check_device_health(new_device)
    await database.update_device_status(new_device["id"], res["status"], res["latency_ms"], res["status_detail"], res.get("snmp"))
    new_device["status"] = res["status"]
    new_device["latency_ms"] = res["latency_ms"]
    new_device["status_detail"] = res["status_detail"]
    await broadcast({"type": "devices_status", "data": await database.list_devices()})
    return new_device


@router.put("/api/devices/{device_id}")
async def update_device(device_id: int, payload: DeviceUpdate, x_admin_key: str | None = Header(default=None)):
    verify_admin_auth(x_admin_key)
    updated = await database.update_device(device_id, payload.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Device not found")
    res = await check_device_health(updated)
    await database.update_device_status(device_id, res["status"], res["latency_ms"], res["status_detail"], res.get("snmp"))
    await broadcast({"type": "devices_status", "data": await database.list_devices()})
    return await database.get_device(device_id)


@router.delete("/api/devices/{device_id}")
async def delete_device(device_id: int, x_admin_key: str | None = Header(default=None)):
    verify_admin_auth(x_admin_key)
    ok = await database.delete_device(device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    await broadcast({"type": "devices_status", "data": await database.list_devices()})
    return {"ok": True}


@router.post("/api/devices/{device_id}/test")
async def test_existing_device(device_id: int, x_admin_key: str | None = Header(default=None)):
    verify_admin_auth(x_admin_key)
    dev = await database.get_device(device_id)
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found")
    res = await check_device_health(dev)
    await database.update_device_status(device_id, res["status"], res["latency_ms"], res["status_detail"], res.get("snmp"))
    dev["status"] = res["status"]
    dev["latency_ms"] = res["latency_ms"]
    dev["status_detail"] = res["status_detail"]
    await broadcast({"type": "devices_status", "data": await database.list_devices()})
    return res


@router.post("/api/devices/test-probe")
async def test_probe_temp(payload: DeviceCreate, x_admin_key: str | None = Header(default=None)):
    """測試未儲存前的連線（需管理授權防止 SSRF 內網掃描）"""
    verify_admin_auth(x_admin_key)
    res = await check_device_health(payload.model_dump())
    return res


# === WebSocket 端點 ===


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    host_header = websocket.headers.get("host")
    if not is_trusted_websocket_origin(origin, host_header):
        await websocket.close(code=1008)  # Policy Violation
        return

    await websocket.accept()
    connections.add(websocket)
    try:
        await websocket.send_json({"type": "servers", "data": await database.list_servers()})
        await websocket.send_json({"type": "devices_status", "data": await database.list_devices()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.discard(websocket)


