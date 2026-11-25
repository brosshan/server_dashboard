from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_key: str = "change-me"  # Agent 遙測上報專用 Key
    admin_api_key: str = "change-admin-key"  # 管理者金鑰 (嚴格隔離，禁止與 api_key 相同)
    snmp_community: str = "public"  # 預設 SNMP 社群名稱

    redis_url: str = "redis://redis:6379/0"
    sqlite_path: str = "./data/metrics.db"
    heartbeat_timeout_seconds: int = 30

    # 伺服器監聽與通訊埠配置 (支援 Port 80 與 443)
    host: str = "0.0.0.0"
    port_http: int = 80
    port_https: int = 443
    enable_http: bool = True
    enable_https: bool = True
    ssl_cert_path: str = "./certs/cert.pem"
    ssl_key_path: str = "./certs/key.pem"

    @property
    def effective_admin_key(self) -> str:
        # 嚴格要求管理者金鑰獨立
        return self.admin_api_key

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
