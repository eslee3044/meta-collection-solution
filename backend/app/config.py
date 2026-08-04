from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MetaVault"
    database_url: str = "sqlite:///./metavault.db"
    secret_key: str = "dev-only-change-me"
    admin_email: str = "admin@example.com"
    admin_password: str = "Admin123!"
    cors_origins: str = "http://localhost:5173"
    deployment_mode: str = "local"
    token_minutes: int = 480
    collection_workers: int = 8

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).parents[2] / ".env", Path.cwd() / ".env"),
        env_prefix="METAVAULT_",
        extra="ignore",
    )

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

