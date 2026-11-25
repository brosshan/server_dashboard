import asyncio
import ipaddress
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 將 server 目錄加入 sys.path
SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import uvicorn
from app.config import settings
from app.main import app


def is_port_available(host: str, port: int) -> bool:
    """測試特定主機與連接埠是否可供綁定監聽"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def ensure_ssl_certs():
    """自動建立本機自簽署 SSL 憑證 (若憑證不存在)"""
    cert_path = Path(settings.ssl_cert_path)
    key_path = Path(settings.ssl_key_path)

    if not cert_path.is_absolute():
        cert_path = (SERVER_DIR.parent / cert_path).resolve()
    if not key_path.is_absolute():
        key_path = (SERVER_DIR.parent / key_path).resolve()

    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    print("[資訊] 未偵測到 SSL 憑證，自動生成自簽 SSL 憑證 (支援 HTTPS 443)...")
    cert_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "Datacenter Monitor"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Datacenter Infrastructure"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv4Address("192.168.0.100")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print(f"[成功] 憑證已建立：\n  憑證檔: {cert_path}\n  私鑰檔: {key_path}")
    except Exception as e:
        print(f"[警告] 自動建立 SSL 憑證失敗: {e}")

    return str(cert_path), str(key_path)


def write_active_url(url: str):
    """寫入當前啟用的網址供批次檔自動開啟"""
    try:
        url_file = SERVER_DIR.parent / ".active_url"
        url_file.write_text(url, encoding="utf-8")
    except Exception:
        pass


async def main():
    servers = []
    active_urls = []

    print("============================================================")
    print("  Starting Datacenter Monitor Server...")
    print("============================================================")

    # 檢測 Port 80 與 443 是否被占用 (例如本機既有的 Node.js ExamSystem)
    port_80_free = is_port_available(settings.host, settings.port_http)
    port_443_free = is_port_available(settings.host, settings.port_https)

    # 1. 嘗試啟動 HTTPS (Port 443)
    if settings.enable_https and port_443_free:
        cert_file, key_file = ensure_ssl_certs()
        if Path(cert_file).exists() and Path(key_file).exists():
            https_config = uvicorn.Config(
                app,
                host=settings.host,
                port=settings.port_https,
                ssl_certfile=cert_file,
                ssl_keyfile=key_file,
                log_level="info",
            )
            https_server = uvicorn.Server(https_config)
            servers.append(https_server.serve())
            url_https = f"https://127.0.0.1:{settings.port_https}" if settings.port_https != 443 else "https://127.0.0.1"
            active_urls.append(url_https)
            print(f"  [HTTPS 在線] {url_https} (局域網: https://192.168.0.100)")
    elif settings.enable_https and not port_443_free:
        print(f"  ⚠️ [連接埠占用] Port {settings.port_https} (HTTPS) 目前已被其他程式占用！")

    # 2. 嘗試啟動 HTTP (Port 80)
    if settings.enable_http and port_80_free:
        http_config = uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port_http,
            log_level="info",
        )
        http_server = uvicorn.Server(http_config)
        servers.append(http_server.serve())
        url_http = f"http://127.0.0.1:{settings.port_http}" if settings.port_http != 80 else "http://127.0.0.1"
        active_urls.append(url_http)
        print(f"  [HTTP  在線] {url_http} (局域網: http://192.168.0.100)")
    elif settings.enable_http and not port_80_free:
        print(f"  ⚠️ [連接埠占用] Port {settings.port_http} (HTTP) 目前已被其他程式占用！")

    # 3. 備援啟動：若 Port 80 與 443 皆被占用，自動啟用備援連接埠 (Port 8000)
    if not servers:
        fallback_port = 8000
        print("\n" + "=" * 60)
        print("  ⚠️ [注意] 由於 Port 80 與 443 目前被本機其他服務 (如 Node.js) 占用，")
        print(f"  為確保監控系統能正常運作，自動切換至備援連接埠: Port {fallback_port}！")
        print("=" * 60)

        fallback_config = uvicorn.Config(
            app,
            host=settings.host,
            port=fallback_port,
            log_level="info",
        )
        fallback_server = uvicorn.Server(fallback_config)
        servers.append(fallback_server.serve())
        url_fallback = f"http://127.0.0.1:{fallback_port}"
        active_urls.append(url_fallback)
        print(f"  [備援 HTTP 在線] {url_fallback} (局域網: http://192.168.0.100:{fallback_port})")

    print("============================================================")

    # 記錄主網址供腳本自動呼叫瀏覽器
    if active_urls:
        write_active_url(active_urls[0])

    await asyncio.gather(*servers)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"\n[錯誤] 伺服器異常中斷: {e}")
