from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PixelSave API"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://pixelsave:pixelsave@localhost:5432/pixelsave"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "downloads"

    storage_endpoint: str = "localhost:9000"
    storage_access_key: str = "minioadmin"
    storage_secret_key: str = "minioadmin"
    storage_bucket: str = "pixelsave-downloads"
    storage_secure: bool = False

    cors_origins: str = Field(default="http://localhost:3000")

    max_job_age_hours: int = 24
    yt_dlp_cookies_file: str | None = None
    yt_dlp_cookies_text: str | None = None
    yt_dlp_cookies_base64: str | None = None
    yt_dlp_proxy: str | None = None
    browser_timeout_seconds: int = 90
    browser_wait_after_load_ms: int = 4000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
