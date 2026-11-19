"""Настройки приложения.

Значения читаются из переменных окружения, а также из `.env` в корне проекта
(там лежат параметры подключения к PostgreSQL, которые использует docker-compose).
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Мониторинг инфраструктуры МГТС — API"
    api_prefix: str = "/api"
    debug: bool = True

    # --- PostgreSQL (ключи совпадают с корневым .env) ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "mtgsHack"
    db_echo: bool = False
    # Применять backend/sql/schema.sql при старте приложения.
    db_bootstrap: bool = True

    # --- Авторизация ---
    jwt_secret: str = "dev-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 720
    # Пока фронтенд не перешёл на реальный вход, защиту можно не включать.
    auth_required: bool = False

    # --- Файловое хранилище (MinIO / любой S3-совместимый сервис) ---
    # Внутри docker-сети эндпоинт — http://minio:9000, локально — http://localhost:9000.
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "mgts-objects"
    s3_region: str = "us-east-1"
    # Максимальный размер загружаемого фото объекта.
    max_photo_size_mb: int = 5

    # --- CORS ---
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    )

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_photo_size_bytes(self) -> int:
        return self.max_photo_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
