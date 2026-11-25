import ipaddress
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


BLOCKED_HOST_TARGETS = {
    "169.254.169.254",  # AWS/GCP/Azure IMDS 雲端元數據
    "0.0.0.0",
    "metadata.google.internal",
}


def validate_host_target(value: str) -> str:
    val = value.strip().lower()
    if not val:
        raise ValueError("主機位址不得為空")

    if val in BLOCKED_HOST_TARGETS:
        raise ValueError("禁止探測雲端中繼服務或受保護位址")
    
    # 1. 嘗試驗證是否為合法 IPv4 或 IPv6
    try:
        ip_obj = ipaddress.ip_address(val)
        if ip_obj.is_link_local:
            raise ValueError("禁止探測 Link-local 連結本地保留位址 (169.254.0.0/16)")
        return val
    except ValueError as e:
        if "Link-local" in str(e):
            raise e
        pass

    # 2. 驗證是否為合法 FQDN / Domain (不允許注入破折號旗標、空白、換行、引號等)
    # RFC 1123 / RFC 952 規則
    domain_regex = r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})*$"
    if re.match(domain_regex, val):
        return val

    raise ValueError("無效的 IP 位址或主機名稱格式，請輸入標準 IP 或網域名稱")


class DiskMetric(BaseModel):
    mount: str
    total_gb: float
    used_gb: float
    percent: float


class NetworkMetric(BaseModel):
    bytes_sent: int = 0
    bytes_recv: int = 0


class MetricsPayload(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    ip_address: str = "unknown"
    platform: str = "unknown"
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    memory_used_gb: float = Field(ge=0)
    memory_total_gb: float = Field(ge=0)
    disk: list[DiskMetric] = Field(default_factory=list)
    network: NetworkMetric = Field(default_factory=NetworkMetric)
    service_status: dict[str, Literal["online", "offline", "warning"]] = Field(
        default_factory=dict
    )


class ServerView(BaseModel):
    hostname: str
    ip_address: str
    platform: str
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk: list[DiskMetric]
    network: NetworkMetric
    service_status: dict[str, Literal["online", "offline", "warning"]]
    status: Literal["online", "warning", "offline"]
    last_seen: datetime


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    device_type: Literal["server", "nas", "firewall", "ups"] = "server"
    location: str = Field(default="總部機房", max_length=100)
    ip_address: str = Field(min_length=1, max_length=255)
    check_method: Literal["ping", "tcp", "agent", "web", "snmp"] = "ping"
    check_port: int | None = Field(default=None, ge=1, le=65535)
    notes: str = ""
    is_active: bool = True

    @field_validator("ip_address")
    @classmethod
    def check_valid_host(cls, v: str) -> str:
        return validate_host_target(v)


class DeviceUpdate(BaseModel):
    name: str | None = None
    device_type: Literal["server", "nas", "firewall", "ups"] | None = None
    location: str | None = None
    ip_address: str | None = None
    check_method: Literal["ping", "tcp", "agent", "web", "snmp"] | None = None
    check_port: int | None = Field(default=None, ge=1, le=65535)
    notes: str | None = None
    is_active: bool | None = None

    @field_validator("ip_address")
    @classmethod
    def check_valid_host(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_host_target(v)
        return v


class DeviceView(BaseModel):
    id: int
    name: str
    device_type: Literal["server", "nas", "firewall", "ups"]
    location: str
    ip_address: str
    check_method: Literal["ping", "tcp", "agent", "web", "snmp"]
    check_port: int | None = None
    notes: str = ""
    is_active: bool = True
    status: Literal["online", "warning", "offline", "unknown"] = "unknown"
    latency_ms: float | None = None
    last_checked: str | None = None
    status_detail: str | None = None
    snmp: dict | None = None


