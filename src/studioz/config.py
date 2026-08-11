from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gcp_project: str
    gcp_location: str = "us-central1"
    gemini_api_key: str = ""
    model_fast: str = "gemini-2.5-flash"
    model_pro: str = "gemini-2.5-pro"

    parallel_web_api_key: str = ""
    parallel_max_results: int = 3

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

settings = Settings()