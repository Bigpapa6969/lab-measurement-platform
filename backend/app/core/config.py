"""
config.py — Application settings
==================================
All configuration is drawn from environment variables (prefixed LAB_) or a
.env file.  Pydantic-Settings handles type coercion and validation.

Usage anywhere in the app:
    from app.core.config import settings
    print(settings.default_load_resistance_ohms)
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LAB_",
        env_file=".env",
        extra="ignore",
    )

    # ---- Identity --------------------------------------------------------
    app_name: str = "Lab Measurement Platform"
    app_version: str = "0.1.0"
    debug: bool = False

    # ---- Electrical defaults ---------------------------------------------
    default_load_resistance_ohms: float = 50.0   # Standard RF / scope input

    # ---- Upload limits ---------------------------------------------------
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB

    # ---- CORS (frontend dev servers) -------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5173",   # Vite default
        "http://localhost:3000",   # CRA / alternate
    ]


settings = Settings()
