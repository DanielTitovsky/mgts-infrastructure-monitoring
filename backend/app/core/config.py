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

    # --- Файлы и CV-воркер ---
    # Где лежат загруженные фото. Пусто = <корень проекта>/uploads (локальный запуск).
    # В Docker задаётся через UPLOADS_DIR (общий том для backend и worker).
    uploads_dir: str = ""
    max_upload_mb: int = 10
    weights_path: str = " " # Путь к весам YOLO.
    cv_min_confidence: float = 0.40
    cv_high_confidence: float = 0.75
    cv_iou: float = 0.5
    cv_imgsz: int = 640
    worker_poll_interval: float = 3.0
    worker_max_attempts: int = 3
    worker_stale_minutes: int = 5

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
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir) if self.uploads_dir else PROJECT_ROOT / "uploads"

    @property
    def weights_file(self) -> Path:
        if self.weights_path:
            return Path(self.weights_path)
        return PROJECT_ROOT / "cv" / "ml" / "yolo-v" / "1-version.pt"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
