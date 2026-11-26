import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from redis.asyncio import Redis

from .config import settings
from .models import MetricsPayload


class Database:
    def __init__(self) -> None:
        path = Path(settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self.redis: Redis | None = None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(
            self.db_path,
            timeout=settings.sqlite_timeout_seconds,
        )

    async def connect(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hostname TEXT NOT NULL,
                    ip_address TEXT,
                    platform TEXT,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    memory_used_gb REAL NOT NULL,
                    memory_total_gb REAL NOT NULL,
                    disk_json TEXT NOT NULL,
                    network_json TEXT NOT NULL,
                    service_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_metrics_hostname_time "
                "ON metrics_history(hostname, recorded_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    location TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    check_method TEXT NOT NULL,
                    check_port INTEGER,
                    notes TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'unknown',
                    latency_ms REAL,
                    last_checked TEXT,
                    status_detail TEXT DEFAULT '',
                    snmp_json TEXT DEFAULT ''
                )
                """
            )
            try:
                connection.execute("ALTER TABLE devices ADD COLUMN snmp_json TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass

        try:
            self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
            await self.redis.ping()
        except Exception:
            self.redis = None

    async def save(self, payload: MetricsPayload) -> dict:
        now = datetime.now(timezone.utc)
        data = payload.model_dump(mode="json")
        data["status"] = "online"
        data["last_seen"] = now.isoformat()

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            matched = connection.execute(
                "SELECT id, name, location, notes FROM devices WHERE ip_address = ? OR name = ? LIMIT 1",
                (payload.ip_address, payload.hostname),
            ).fetchone()
            if matched:
                data["display_name"] = matched["name"]
                data["location"] = matched["location"]
                data["notes"] = matched["notes"] or ""
                data["device_id"] = matched["id"]
            else:
                data["display_name"] = payload.hostname
                data["location"] = "本機" if payload.ip_address in ("127.0.0.1", "192.168.0.100") else "總部機房"
                data["notes"] = ""
                data["device_id"] = None

            connection.execute(
                """
                INSERT INTO metrics_history (
                    hostname, ip_address, platform, cpu_percent, memory_percent,
                    memory_used_gb, memory_total_gb, disk_json, network_json,
                    service_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.hostname,
                    payload.ip_address,
                    payload.platform,
                    payload.cpu_percent,
                    payload.memory_percent,
                    payload.memory_used_gb,
                    payload.memory_total_gb,
                    json.dumps(payload.disk, default=lambda value: value.model_dump()),
                    json.dumps(payload.network.model_dump()),
                    json.dumps(payload.service_status),
                    now.isoformat(),
                ),
            )

        if self.redis is not None:
            await self.redis.set(
                f"server:status:{payload.hostname}",
                json.dumps(data),
                ex=settings.heartbeat_timeout_seconds,
            )

        return data

    async def list_servers(self) -> list[dict]:
        servers: dict[str, dict] = {}

        if self.redis is not None:
            keys = await self.redis.keys("server:status:*")
            for key in keys:
                raw = await self.redis.get(key)
                if raw:
                    servers[key.removeprefix("server:status:")] = json.loads(raw)

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            dev_rows = connection.execute(
                "SELECT id, name, device_type, location, ip_address, notes, check_method FROM devices WHERE is_active = 1"
            ).fetchall()
            dev_by_ip = {d["ip_address"]: dict(d) for d in dev_rows}
            dev_by_name = {d["name"]: dict(d) for d in dev_rows}

            rows = connection.execute(
                """
                SELECT hostname, ip_address, platform, cpu_percent, memory_percent,
                       memory_used_gb, memory_total_gb, disk_json, network_json,
                       service_json, recorded_at
                FROM metrics_history AS current
                WHERE id = (
                    SELECT id FROM metrics_history
                    WHERE hostname = current.hostname
                    ORDER BY id DESC LIMIT 1
                )
                """
            ).fetchall()
            for row in rows:
                if row["hostname"] not in servers:
                    last_seen = datetime.fromisoformat(row["recorded_at"])
                    age = (datetime.now(timezone.utc) - last_seen).total_seconds()
                    servers[row["hostname"]] = {
                        "hostname": row["hostname"],
                        "ip_address": row["ip_address"],
                        "platform": row["platform"],
                        "cpu_percent": row["cpu_percent"],
                        "memory_percent": row["memory_percent"],
                        "memory_used_gb": row["memory_used_gb"],
                        "memory_total_gb": row["memory_total_gb"],
                        "disk": json.loads(row["disk_json"]),
                        "network": json.loads(row["network_json"]),
                        "service_status": json.loads(row["service_json"]),
                        "status": "offline" if age > settings.heartbeat_timeout_seconds else "online",
                        "last_seen": row["recorded_at"],
                    }

            for s in servers.values():
                matched = dev_by_ip.get(s.get("ip_address")) or dev_by_name.get(s.get("hostname"))
                if matched:
                    s["display_name"] = matched["name"]
                    s["location"] = matched["location"]
                    s["notes"] = matched.get("notes") or ""
                    s["device_id"] = matched["id"]
                else:
                    s["display_name"] = s["hostname"]
                    s["location"] = "本機" if s.get("ip_address") in ("127.0.0.1", "192.168.0.100") else "總部機房"
                    s["notes"] = ""
                    s["device_id"] = None

        return list(servers.values())

    async def history(self, hostname: str, hours: int = 24) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        cutoff_text = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT cpu_percent, memory_percent, recorded_at
                FROM metrics_history
                WHERE hostname = ? AND recorded_at >= ?
                ORDER BY recorded_at ASC
                LIMIT 5000
                """,
                (
                    hostname,
                    cutoff_text,
                ),
            ).fetchall()

        cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
        return [
            {
                "cpu_percent": row["cpu_percent"],
                "memory_percent": row["memory_percent"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
            if datetime.fromisoformat(row["recorded_at"]).timestamp() >= cutoff
        ]

    async def list_devices(self) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, name, device_type, location, ip_address,
                       check_method, check_port, notes, is_active,
                       status, latency_ms, last_checked, status_detail,
                       snmp_json
                FROM devices
                ORDER BY location ASC, device_type ASC, id ASC
                """
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "device_type": row["device_type"],
                    "location": row["location"],
                    "ip_address": row["ip_address"],
                    "check_method": row["check_method"],
                    "check_port": row["check_port"],
                    "notes": row["notes"] or "",
                    "is_active": bool(row["is_active"]),
                    "status": row["status"] or "unknown",
                    "latency_ms": row["latency_ms"],
                    "last_checked": row["last_checked"],
                    "status_detail": row["status_detail"] or "",
                    "snmp": json.loads(row["snmp_json"]) if ("snmp_json" in row.keys() and row["snmp_json"]) else None,
                }
                for row in rows
            ]

    async def get_device(self, device_id: int) -> dict | None:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, name, device_type, location, ip_address,
                       check_method, check_port, notes, is_active,
                       status, latency_ms, last_checked, status_detail
                FROM devices
                WHERE id = ?
                """,
                (device_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "device_type": row["device_type"],
                "location": row["location"],
                "ip_address": row["ip_address"],
                "check_method": row["check_method"],
                "check_port": row["check_port"],
                "notes": row["notes"] or "",
                "is_active": bool(row["is_active"]),
                "status": row["status"] or "unknown",
                "latency_ms": row["latency_ms"],
                "last_checked": row["last_checked"],
                "status_detail": row["status_detail"] or "",
            }

    async def create_device(self, data: dict) -> dict:
        with self._connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO devices (
                    name, device_type, location, ip_address,
                    check_method, check_port, notes, is_active,
                    status, status_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unknown', '尚未檢測')
                """,
                (
                    data["name"],
                    data["device_type"],
                    data.get("location", "總部機房"),
                    data["ip_address"],
                    data.get("check_method", "ping"),
                    data.get("check_port"),
                    data.get("notes", ""),
                    1 if data.get("is_active", True) else 0,
                ),
            )
            device_id = cursor.lastrowid
        return await self.get_device(device_id)

    async def update_device(self, device_id: int, data: dict) -> dict | None:
        fields = []
        params = []
        for key in ["name", "device_type", "location", "ip_address", "check_method", "check_port", "notes", "is_active"]:
            if key in data and data[key] is not None:
                fields.append(f"{key} = ?")
                val = 1 if (key == "is_active" and data[key]) else (0 if key == "is_active" else data[key])
                params.append(val)
        if not fields:
            return await self.get_device(device_id)
        params.append(device_id)

        with self._connect() as connection:
            connection.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        return await self.get_device(device_id)

    async def update_device_status(
        self,
        device_id: int,
        status: str,
        latency_ms: float | None,
        detail: str,
        snmp_data: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        snmp_str = json.dumps(snmp_data) if snmp_data else ""
        with self._connect() as connection:
            if snmp_data is not None:
                connection.execute(
                    """
                    UPDATE devices
                    SET status = ?, latency_ms = ?, last_checked = ?, status_detail = ?, snmp_json = ?
                    WHERE id = ?
                    """,
                    (status, latency_ms, now, detail, snmp_str, device_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE devices
                    SET status = ?, latency_ms = ?, last_checked = ?, status_detail = ?
                    WHERE id = ?
                    """,
                    (status, latency_ms, now, detail, device_id),
                )

    async def delete_device(self, device_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM devices WHERE id = ?", (device_id,))
            return cursor.rowcount > 0

