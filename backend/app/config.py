from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM provider — any OpenAI-compatible endpoint.
    # Defaults target Google Gemini 2.5 Flash via AI Studio's OpenAI shim.
    # Swap base_url + model for Groq, DeepSeek, OpenAI, Ollama, etc.
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-2.5-flash"
    llm_top_n: int = 10  # max trade suggestions returned per LLM run
    llm_candidate_pool: int = 25  # top-by-raw-confidence sent to LLM for ranking

    database_url: str = "sqlite:///./trading_agent.db"

    news_interval_min: int = 30
    market_interval_min: int = 15
    signal_interval_min: int = 60

    market_open_hhmm: str = "0915"
    market_close_hhmm: str = "1530"


settings = Settings()
