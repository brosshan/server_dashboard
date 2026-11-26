import asyncio
import platform
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .api import database, router
from .config import settings
from .scheduler import run_device_probes

# Windows asyncio Proactor 關閉非預期 RST 產生的 WinError 10054 雜訊處理
if platform.system() == "Windows":
    # 設置自定義例外處理器以過濾 Windows 管道連線重置的噪音
    def _silence_proactor_winerror(loop, context):
        msg = context.get("message", "")
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError) or "10054" in str(context):
            return
        loop.default_exception_handler(context)

    try:
        asyncio.get_event_loop_policy().get_event_loop().set_exception_handler(_silence_proactor_winerror)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    placeholder_keys = {
        "change-me",
        "change-this-secret-key",
        "change-this-metrics-key",
        "change-admin-key",
        "change-this-admin-key",
    }
    if (
        not settings.api_key
        or not settings.admin_api_key
        or settings.api_key in placeholder_keys
        or settings.admin_api_key in placeholder_keys
    ):
        raise RuntimeError("API_KEY and ADMIN_API_KEY must be configured with distinct non-placeholder values")
    if settings.admin_api_key == settings.api_key:
        raise RuntimeError("ADMIN_API_KEY and API_KEY must be different")

    await database.connect()
    probe_task = asyncio.create_task(run_device_probes(database))
    try:
        yield
    finally:
        probe_task.cancel()
        try:
            await probe_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Datacenter Server Monitor",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """注入 HTTP 安全防護標頭 (包含 CSP, HSTS, X-Frame-Options 等)"""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss: http: https:; "
        "font-src 'self'; "
        "frame-ancestors 'none';"
    )
    # 若為 HTTPS 請求注入 HSTS 強制傳輸安全標頭
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(router)
static_directory = Path(__file__).resolve().parents[1] / "static"
app.mount("/", StaticFiles(directory=static_directory, html=True), name="dashboard")

