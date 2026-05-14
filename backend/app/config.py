from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./trading_agent.db"

    news_interval_min: int = 30
    market_interval_min: int = 15
    signal_interval_min: int = 60

    market_open_hhmm: str = "0915"
    market_close_hhmm: str = "1530"


settings = Settings()
