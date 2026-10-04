from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
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
    worker_stale_minutes: int = 15
    integration_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).parents[2] / ".env", Path.cwd() / ".env"),
        env_prefix="METAVAULT_",
        extra="ignore",
    )

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @model_validator(mode="after")
    def validate_deployment_security(self):
        if self.deployment_mode.lower() == "docker":
            if len(self.secret_key) < 32 or self.secret_key.lower() in {
                "dev-only-change-me",
                "change-this-before-production",
            }:
                raise ValueError("METAVAULT_SECRET_KEY must be a strong value of at least 32 characters")
            if len(self.admin_password) < 8 or self.admin_password == "Admin123!":
                raise ValueError("METAVAULT_ADMIN_PASSWORD must be a non-default value of at least 8 characters")
            if "*" in self.origins:
                raise ValueError("METAVAULT_CORS_ORIGINS must not contain wildcard CORS origins")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

