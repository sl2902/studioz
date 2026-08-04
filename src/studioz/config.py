from pydantic import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    gemini_api_key: str
    model_fast: str = "gemini-2.5-flash"
    model_pro: str = "gemini-2.5-pro"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()