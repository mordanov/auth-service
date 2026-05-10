from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = Field(..., description="PostgreSQL async URL, e.g. postgresql+asyncpg://...")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # JWT
    jwt_private_key: str = Field(..., description="RS256 private key PEM")
    jwt_public_key: str = Field(..., description="RS256 public key PEM")
    jwt_algorithm: str = "RS256"
    jwt_key_id: str = Field(default="auth-key-1", description="kid header value")
    access_token_ttl_minutes: int = Field(default=15)
    refresh_token_ttl_days: int = Field(default=30)

    # OAuth providers
    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")
    microsoft_client_id: str = Field(default="")
    microsoft_client_secret: str = Field(default="")
    microsoft_tenant_id: str = Field(default="common")

    # App
    app_base_url: str = Field(default="http://localhost:8000")
    allowed_origins: list[str] = Field(default=["http://localhost:3000"])

    # Seed admin (both must be set together, or neither)
    seed_admin_email: str | None = Field(default=None)
    seed_admin_password: str | None = Field(default=None)

    def model_post_init(self, __context: object) -> None:  # type: ignore[override]
        if bool(self.seed_admin_email) != bool(self.seed_admin_password):
            raise ValueError(
                "SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD must both be set or both be unset"
            )
        if self.seed_admin_password and len(self.seed_admin_password) < 12:
            raise ValueError("SEED_ADMIN_PASSWORD must be at least 12 characters")

    # Rate limiting
    rate_limit_login_per_minute: int = Field(default=10)
    rate_limit_refresh_per_minute: int = Field(default=30)


settings = Settings()
