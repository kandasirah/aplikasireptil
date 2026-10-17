"""Konfigurasi terpusat REPTIL berbasis pydantic-settings (membaca .env)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = ""
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "aplikasireptil"
    database_user: str = "postgres"
    database_password: str = ""

    # Aplikasi
    app_env: str = "development"
    app_debug: bool = False
    app_name: str = "REPTIL"

    # Keamanan / JWT
    secret_key: str = "ubah-secret-ini-di-produksi"
    access_token_expire_minutes: int = 480  # 8 jam kerja

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """URL koneksi SQLAlchemy — fallback ke komponen terpisah bila DATABASE_URL kosong."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
