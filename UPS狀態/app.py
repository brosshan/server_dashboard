from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from snmp_client import CONFIG_PATH, fetch_ups_data, load_config
from web_client import fetch_ups_web_data

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="UPS Monitor Dashboard", description="InsightPower G3 Mini SNMP Card Web/SNMP dashboard")

static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fetch_by_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    source = str(cfg.get("source") or "web").lower()
    if source == "snmp":
        result = fetch_ups_data(cfg)
        result["source"] = "snmp"
        return result
    result = fetch_ups_web_data(cfg)
    result["config"] = _public_config(cfg)
    return result


def _public_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    secret_markers = ("password", "community", "api_key", "token", "secret")
    return {
        key: value
        for key, value in cfg.items()
        if not any(marker in key.lower() for marker in secret_markers)
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "config": _public_config(cfg),
            "host": cfg.get("host", ""),
            "ups_url": cfg.get("ups_url", ""),
            "source": cfg.get("source", "web"),
        },
    )


@app.get("/api/ups")
async def api_ups():
    cfg = load_config()
    result = _fetch_by_config(cfg)
    result["timestamp"] = datetime.now().astimezone().isoformat()
    return JSONResponse(content=result)


@app.get("/api/battery")
async def api_battery():
    cfg = load_config()
    result = _fetch_by_config(cfg)
    battery = (result.get("data") or {}).get("battery") or {}
    capacity = battery.get("capacity_percent")
    if capacity is None:
        capacity = battery.get("charge_percent")
    payload = {
        "ok": bool(result.get("ok")),
        "source": result.get("source", "web"),
        "source_url": result.get("source_url") or cfg.get("ups_url", ""),
        "battery_capacity_percent": capacity,
        "battery_status": battery.get("status"),
        "battery": battery,
        "error": result.get("error"),
        "timestamp": datetime.now().astimezone().isoformat(),
    }
    return JSONResponse(content=payload)


@app.get("/api/config")
async def api_config():
    cfg = load_config()
    return JSONResponse(content=_public_config(cfg))


@app.get("/api/health")
async def api_health():
    return {"status": "ok", "config_path": str(CONFIG_PATH)}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("UPS_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("UPS_DASHBOARD_PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
