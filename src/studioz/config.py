import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gcp_project: str
    gcp_location: str = "us-central1"
    gemini_api_key: str = ""
    model_fast: str = "gemini-2.5-flash"
    model_pro: str = "gemini-2.5-pro"

    parallel_web_api_key: str = ""
    parallel_max_results: int = 3

    # Storage backend: "local" (disk) or "gcs" (Google Cloud Storage)
    # Auto-detected from K_SERVICE env var (Cloud Run) if not set explicitly.
    storage_backend: Literal["local", "gcs"] = "local"
    gcs_bucket: str = ""

    # Deployed frontend origin (for CORS)
    frontend_origin: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()

# Auto-detect Cloud Run environment if storage_backend not explicitly overridden
if not os.environ.get("STORAGE_BACKEND") and os.environ.get("K_SERVICE"):
    settings.storage_backend = "gcs"
