import asyncio
import base64
import ssl
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from UPS狀態 import snmp_client, web_client
from puresnmp import PyWrapper, V3

from server.app import main
from server.app.config import Settings, settings
from server.app.database import Database
from server.app.snmp import create_snmpv3_credentials


@pytest.fixture
def dashboard_client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-agent-key")
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    monkeypatch.setattr(settings, "require_read_auth", True)

    async def no_op_connect():
        return None

    async def wait_for_shutdown(_database):
        await asyncio.Event().wait()

    monkeypatch.setattr(main.database, "connect", no_op_connect)
    monkeypatch.setattr(main.database, "list_servers", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.database, "list_devices", AsyncMock(return_value=[]))
    monkeypatch.setattr(main, "run_device_probes", wait_for_shutdown)

    with TestClient(main.app) as client:
        yield client


def test_read_api_requires_a_valid_key(dashboard_client):
    assert dashboard_client.get("/api/servers").status_code == 401
    response = dashboard_client.get(
        "/api/servers",
        headers={"X-API-Key": "test-agent-key"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_websocket_uses_authenticated_subprotocol_not_query_key(dashboard_client):
    with pytest.raises(WebSocketDisconnect) as disconnect:
        dashboard_client.websocket_connect("/ws?api_key=test-agent-key").__enter__()
    assert disconnect.value.code == 1008

    token = base64.urlsafe_b64encode(b"test-agent-key").decode().rstrip("=")
    with dashboard_client.websocket_connect(
        "/ws",
        subprotocols=["monitor.v1", f"auth.{token}"],
    ) as websocket:
        assert websocket.accepted_subprotocol == "monitor.v1"
        assert websocket.receive_json()["type"] == "servers"


def test_authentication_and_bind_defaults_are_secure():
    defaults = Settings(_env_file=None)
    assert defaults.require_read_auth is True
    assert defaults.host == "127.0.0.1"


def test_snmp_requires_v3_auth_priv_and_bounded_timeout():
    credentials = create_snmpv3_credentials(
        "monitor",
        "test-auth-passphrase",
        "test-priv-passphrase",
    )
    assert isinstance(credentials, V3)
    with pytest.raises(ValueError):
        create_snmpv3_credentials("monitor", "short", "test-priv-passphrase")

    with pytest.raises(ValueError, match="SNMPv1/v2c is disabled"):
        snmp_client._make_client(
            {
                "version": "v2c",
                "username": "monitor",
                "auth_password": "test-auth-passphrase",
                "priv_password": "test-priv-passphrase",
            }
        )
    with pytest.raises(ValueError, match="retries must be"):
        snmp_client._make_client(
            {
                "version": "v3",
                "username": "monitor",
                "auth_password": "test-auth-passphrase",
                "priv_password": "test-priv-passphrase",
                "retries": 6,
            }
        )

    wrapped = snmp_client._make_client(
        {
            "version": "v3",
            "username": "monitor",
            "auth_password": "test-auth-passphrase",
            "priv_password": "test-priv-passphrase",
            "timeout": 2,
            "retries": 1,
        }
    )
    assert isinstance(wrapped, PyWrapper)


def test_ups_tls_cannot_be_disabled_or_bypassed_with_http():
    context = web_client._make_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    with pytest.raises(ValueError, match="cannot be disabled"):
        web_client._make_ssl_context(False)

    root, error = web_client._fetch_xml("http://127.0.0.1/status.xml")
    assert root is None
    assert error is not None and "require HTTPS" in error


def test_database_uses_configured_sqlite_timeout(monkeypatch):
    import server.app.database as database_module

    monkeypatch.setattr(settings, "sqlite_timeout_seconds", 7.5)
    connection = object()
    connect = Mock(return_value=connection)
    monkeypatch.setattr(database_module.sqlite3, "connect", connect)
    database = Database.__new__(Database)
    database.db_path = "test.db"

    assert database._connect() is connection
    connect.assert_called_once_with("test.db", timeout=7.5)
