from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://moneyflow:moneyflow@localhost:5432/moneyflow"
    telegram_bot_token: SecretStr = SecretStr("development-token")
    telegram_webhook_secret: SecretStr = SecretStr("development-secret")
    authorized_telegram_user_id: int = 1
    public_web_url: str = "http://localhost:5173"
    session_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
