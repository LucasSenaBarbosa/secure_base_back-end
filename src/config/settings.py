from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    supabase_url: HttpUrl
    supabase_secret_key: SecretStr
    supabase_timeout_seconds: float = Field(default=5, gt=0, le=30)
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expiry_seconds: int = Field(default=900, ge=300, le=86400)
    refresh_token_expiry_seconds: int = Field(default=2592000, ge=86400, le=2592000)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX must start with '/' and must not end with '/'.")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        else:
            origins = value
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "CORS_ORIGINS must contain absolute origins without paths or credentials."
                )
        return origins

    @model_validator(mode="after")
    def require_tls_in_hosted_environments(self) -> "Settings":
        if self.environment.lower() in {"production", "prod", "staging"}:
            if self.supabase_url.scheme != "https":
                raise ValueError("SUPABASE_URL must use HTTPS outside development.")
            if not self.cors_origins or any(
                urlsplit(origin).scheme != "https" for origin in self.cors_origins
            ):
                raise ValueError("CORS_ORIGINS must contain HTTPS origins outside development.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
