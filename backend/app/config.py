from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPPS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spps:spps@127.0.0.1:5432/spps"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_alg: str = "HS256"
    token_ttl_minutes: int = 480

    dev_auth: bool = True
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://127.0.0.1:8000/api/auth/callback"

    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
