from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEMANTIC_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- DB connection ----
    mssql_server: str
    mssql_user: Optional[str] = None
    mssql_password: Optional[str] = None
    mssql_database: str
    mssql_port: int = 1433
    mssql_windows_auth: bool = False
    mssql_encrypt: bool = False

    # ---- Cache ----
    cache_path: str = "./cache/semantic_mcp.db"
    cache_enabled: bool = True
    background_batch_size: int = Field(default=5, ge=1)
    background_interval_ms: int = Field(default=500, ge=0)

    # ---- Policy ----
    policy_file: Optional[str] = None
    policy_profile: Optional[str] = None

    # ---- Policy overrides ----
    max_rows_returned: int = Field(default=1000, ge=1)
    max_rows_affected: int = Field(default=100, ge=1)
    query_timeout: int = Field(default=30, ge=1)

    # ---- Tool surface ----
    tool_profile: str = "all"

    # ---- Metrics ----
    metrics_enabled: bool = True


_config: Optional[Config] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Test helper only."""
    global _config
    _config = None
